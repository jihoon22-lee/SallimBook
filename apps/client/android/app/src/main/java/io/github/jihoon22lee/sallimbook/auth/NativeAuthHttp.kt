package io.github.jihoon22lee.sallimbook.auth

import okhttp3.Authenticator
import okhttp3.CookieJar
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.Response
import okio.BufferedSink
import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean

internal class NativeHttpResponse(val status: Int, val body: Any?, val requestId: String?)

/** 503 Retry-After follow-ups must not resend a rotating credential, even with retries off. */
internal class OneShotAuthBody(private val bytes: ByteArray, private val beforeWrite: () -> Unit = {}) : RequestBody() {
    private val written = AtomicBoolean(false)
    override fun contentType() = "application/json; charset=utf-8".toMediaType()
    override fun contentLength() = bytes.size.toLong()
    override fun isOneShot() = true
    override fun writeTo(sink: BufferedSink) {
        if (!written.compareAndSet(false, true)) throw IOException("A native auth body cannot be replayed")
        beforeWrite()
        sink.write(bytes)
    }
}

/** A per-client policy, independent of Capacitor's process-global java.net cookie handler. */
internal fun accountHttpClient(): OkHttpClient = OkHttpClient.Builder()
        .cookieJar(CookieJar.NO_COOKIES)
        .followRedirects(false)
        .followSslRedirects(false)
        .retryOnConnectionFailure(false)
        .authenticator(Authenticator.NONE)
        .proxyAuthenticator(Authenticator.NONE)
        .cache(null)
        .callTimeout(15, TimeUnit.SECONDS)
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .writeTimeout(10, TimeUnit.SECONDS)
        .build()

/** Default HTTPS certificate/hostname checks, no redirects, no cookies, no logging/retry. */
internal class NativeAuthHttp(private val origin: String, private val client: OkHttpClient = accountHttpClient()) {
    companion object { const val REFRESH_PATH = "/api/v1/auth/native/refresh" }

    /**
     * The only refresh transport. [consume] runs right before the body reaches the sink, so a
     * failure before that point leaves the stored token intact. The exchange is not bound to
     * screen cancellation and the gate is not checked after the response, so a rotated token
     * that the server already issued is always handed back (callTimeout bounds the wait).
     */
    fun refresh(token: String, gate: ForegroundRequest, consume: () -> Unit): NativeHttpResponse {
        gate.checkHttp("POST", REFRESH_PATH)
        if (AuthPolicy.apiOrigin(origin) == null) throw AuthFailure(AuthCode.AUTH_UNAVAILABLE)
        if (!Regex("[A-Za-z0-9_-]{32,128}").matches(token)) throw AuthFailure(AuthCode.INVALID_REQUEST)
        // The token alphabet needs no JSON escaping.
        val requestBytes = "{\"refresh_token\":\"$token\"}".toByteArray(Charsets.UTF_8)
        try {
            val request = Request.Builder()
                .url(origin + REFRESH_PATH)
                .post(OneShotAuthBody(requestBytes) { gate.checkHttp("POST", REFRESH_PATH); consume() })
                .header("Accept", "application/json")
                .header("X-SallimBook-Native", "1")
                .build()
            return client.newCall(request).execute().use { response ->
                val requestId = requestId(response)
                if (response.code != 200) NativeHttpResponse(response.code, null, requestId)
                else NativeHttpResponse(200, readStrictJson(response, 262_144), requestId)
            }
        } catch (failure: AuthFailure) {
            throw failure
        } catch (_: Exception) {
            throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
        } finally {
            requestBytes.fill(0)
        }
    }

    fun send(
        method: String,
        path: String,
        gate: ForegroundRequest,
        body: JSONObject? = null,
        accessToken: String? = null,
        ifMatch: String? = null,
        stepUpToken: String? = null,
        nativeAccountNumber: Boolean = false,
        nativeInsurancePolicyNumber: Boolean = false,
        idempotencyKey: String? = null,
        nativeDocumentCreate: Boolean = false,
        nativeOnboarding: Boolean = false,
    ): NativeHttpResponse {
        gate.checkHttp(method, path)
        if (AuthPolicy.apiOrigin(origin) == null) {
            throw AuthFailure(AuthCode.AUTH_UNAVAILABLE)
        }
        val internalAuthPath = path in setOf(
            "/api/v1/auth/native/login", "/api/v1/auth/native/refresh",
            "/api/v1/auth/native/logout", "/api/v1/auth/invitations/accept",
            "/api/v1/household/invitations",
            "/api/v1/auth/native/passkeys/options", "/api/v1/auth/native/passkeys/verify",
            "/api/v1/auth/passkeys/register/options", "/api/v1/auth/passkeys/register/verify",
            "/api/v1/auth/step-up/options", "/api/v1/auth/step-up/verify",
            "/api/v1/auth/native/reauthenticate",
        ) && method == "POST" && ifMatch == null
        val onboarding = nativeOnboarding && !nativeAccountNumber && !nativeInsurancePolicyNumber && !nativeDocumentCreate &&
            NativeOnboardingPolicy.httpAllowed(method, path, body?.let { jsonValue(it) }, accessToken != null,
                ifMatch, stepUpToken, idempotencyKey)
        if (nativeOnboarding && !onboarding) throw AuthFailure(AuthCode.INVALID_REQUEST)
        val internalRevoke = method == "DELETE" && PasskeyPolicy.revokePath(path) &&
            PasskeyPolicy.target(path.substringAfterLast('/'), ifMatch) && body == null
        val metadata = FinancePolicy.metadataHttpAllowed(method, path, body?.let { jsonValue(it) }, ifMatch, idempotencyKey)
        val documentCreate = nativeDocumentCreate && !nativeAccountNumber && !nativeInsurancePolicyNumber && stepUpToken == null &&
            NativeDocumentPolicy.createHttpAllowed(method, path, body?.let { jsonValue(it) }, ifMatch, idempotencyKey)
        if (nativeDocumentCreate && !documentCreate) throw AuthFailure(AuthCode.INVALID_REQUEST)
        val numberFields = body?.keys()?.asSequence()?.toSet()
        val numberMutation = nativeAccountNumber && method == "PATCH" && FinancePolicy.numberPath(path, false) &&
            PasskeyPolicy.target(path.substringAfterLast('/'), ifMatch) && numberFields == setOf("account_number") &&
            (body?.opt("account_number") == JSONObject.NULL || (body?.opt("account_number") as? String)?.let {
                val characters = it.toCharArray()
                try { FinancePolicy.number(characters) } finally { characters.fill('\u0000') }
            } == true)
        val numberReveal = nativeAccountNumber && method == "POST" && FinancePolicy.numberPath(path, true) &&
            ifMatch == null && numberFields == emptySet<String>()
        val policyNumber = nativeInsurancePolicyNumber && !nativeAccountNumber && stepUpToken == null &&
            InsurancePolicy.numberHttpAllowed(method, path, body?.let { jsonValue(it) }, ifMatch)
        if (nativeInsurancePolicyNumber && !policyNumber || nativeAccountNumber && nativeInsurancePolicyNumber) throw AuthFailure(AuthCode.INVALID_REQUEST)
        if (!onboarding && !internalAuthPath && !internalRevoke && !metadata && !numberMutation && !numberReveal && !policyNumber && !documentCreate &&
            (body != null || !AuthPolicy.requestAllowed(method, path, ifMatch))) {
            throw AuthFailure(AuthCode.INVALID_REQUEST)
        }
        if (idempotencyKey != null && !metadata && !documentCreate) throw AuthFailure(AuthCode.INVALID_REQUEST)
        if (nativeAccountNumber && !numberMutation && !numberReveal) throw AuthFailure(AuthCode.INVALID_REQUEST)
        if (stepUpToken != null && !PasskeyPolicy.stepUpHeaderAllowed(method, path, ifMatch, stepUpToken)) {
            throw AuthFailure(AuthCode.INVALID_REQUEST)
        }
        var requestBytes: ByteArray? = null
        try {
            // OkHttp requires a RequestBody for POST. A zero-byte one-shot body implements
            // the no-payload connection-code endpoint without serializing an extra JSON value.
            requestBytes = if (onboarding && path == NativeOnboardingPolicy.CODE_PATH) byteArrayOf()
                else body?.toString()?.toByteArray(Charsets.UTF_8)
            val request = Request.Builder()
                .url(origin + path)
                .method(method, requestBytes?.let { OneShotAuthBody(it) { gate.checkHttp(method, path) } })
                .header("Accept", "application/json")
                .header("X-SallimBook-Native", "1")
                .apply {
                    if (accessToken != null) header("Authorization", "Bearer $accessToken")
                    if (ifMatch != null) header("If-Match", ifMatch)
                    if (idempotencyKey != null) header("Idempotency-Key", idempotencyKey)
                    if (stepUpToken != null) header("X-Step-Up-Token", stepUpToken)
                }.build()
            gate.checkHttp(method, path)
            val call = client.newCall(request)
            gate.bindNetworkCancellation { call.cancel() }
            return call.execute().use { response ->
                val status = response.code
                if (status in 300..399) throw AuthFailure(AuthCode.ACCESS_DENIED)
                // Up to 200 accounts may each include a bounded nested asset note.
                val parsed = if (status == 204) null else readJson(response, if (metadata) 3_145_728 else 262_144)
                gate.checkHttp(method, path)
                NativeHttpResponse(status, parsed, requestId(response))
            }
        } catch (failure: AuthFailure) {
            throw failure
        } catch (_: IOException) {
            throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
        } catch (_: Exception) {
            throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
        } finally {
            gate.releaseNetworkCancellation()
            requestBytes?.fill(0)
        }
    }

    private fun requestId(response: Response): String? = response.header("X-Request-ID")?.takeIf {
        Regex("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}").matches(it)
    }

    /** A bounded application/json body; anything else is NETWORK_UNAVAILABLE. */
    private fun readBody(response: Response, maximumBytes: Int): ByteArray {
        if (response.body.contentType()?.type != "application" ||
            response.body.contentType()?.subtype != "json") {
            throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
        }
        return response.body.byteStream().use { stream ->
            val output = ByteArrayOutputStream()
            val buffer = ByteArray(4096)
            while (true) {
                val count = stream.read(buffer)
                if (count < 0) break
                if (output.size() + count > maximumBytes) throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
                output.write(buffer, 0, count)
            }
            buffer.fill(0)
            output.toByteArray()
        }
    }

    private fun readJson(response: Response, maximumBytes: Int): Any? {
        val bytes = readBody(response, maximumBytes)
        try {
            val tokener = JSONTokener(bytes.toString(Charsets.UTF_8))
            val value = tokener.nextValue()
            if (tokener.nextClean() != 0.toChar()) throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
            return jsonValue(value)
        } finally { bytes.fill(0) }
    }

    /** The refresh response uses the strict Gson decoder: one value, unique names, integer-only numbers. */
    private fun readStrictJson(response: Response, maximumBytes: Int): Any? {
        val bytes = readBody(response, maximumBytes)
        try {
            return NativeVaultJson.decode(bytes.toString(Charsets.UTF_8))
        } catch (_: NativeVaultFailure) {
            throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
        } finally { bytes.fill(0) }
    }

    internal fun jsonValue(value: Any?, depth: Int = 0): Any? {
        if (depth > 16) throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
        return when (value) {
            null, JSONObject.NULL -> null
            is JSONObject -> value.keys().asSequence().associateWith { jsonValue(value.get(it), depth + 1) }
            is JSONArray -> (0 until value.length()).map { jsonValue(value.get(it), depth + 1) }
            is String, is Boolean, is Int, is Long, is Double -> value
            else -> throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
        }
    }
}
