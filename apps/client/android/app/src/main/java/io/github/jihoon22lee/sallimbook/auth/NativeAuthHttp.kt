package io.github.jihoon22lee.sallimbook.auth

import okhttp3.Authenticator
import okhttp3.CookieJar
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
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
internal class OneShotAuthBody(private val bytes: ByteArray) : RequestBody() {
    private val written = AtomicBoolean(false)
    override fun contentType() = "application/json; charset=utf-8".toMediaType()
    override fun contentLength() = bytes.size.toLong()
    override fun isOneShot() = true
    override fun writeTo(sink: BufferedSink) {
        if (!written.compareAndSet(false, true)) throw IOException("A native auth body cannot be replayed")
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
internal class NativeAuthHttp(private val origin: String) {
    private val client = accountHttpClient()
    fun send(
        method: String,
        path: String,
        gate: ForegroundRequest,
        body: JSONObject? = null,
        accessToken: String? = null,
        ifMatch: String? = null,
    ): NativeHttpResponse {
        gate.check()
        if (AuthPolicy.apiOrigin(origin) == null) {
            throw AuthFailure(AuthCode.AUTH_UNAVAILABLE)
        }
        val internalAuthPath = path in setOf(
            "/api/v1/auth/native/login", "/api/v1/auth/native/refresh",
            "/api/v1/auth/native/logout", "/api/v1/auth/invitations/accept",
            "/api/v1/household/invitations",
            "/api/v1/auth/native/reauthenticate",
        ) && method == "POST" && ifMatch == null
        if (!internalAuthPath && (body != null || !AuthPolicy.requestAllowed(method, path, ifMatch))) {
            throw AuthFailure(AuthCode.INVALID_REQUEST)
        }
        var requestBytes: ByteArray? = null
        try {
            requestBytes = body?.toString()?.toByteArray(Charsets.UTF_8)
            val request = Request.Builder()
                .url(origin + path)
                .method(method, requestBytes?.let(::OneShotAuthBody))
                .header("Accept", "application/json")
                .header("X-SallimBook-Native", "1")
                .apply {
                    if (accessToken != null) header("Authorization", "Bearer $accessToken")
                    if (ifMatch != null) header("If-Match", ifMatch)
                }.build()
            gate.check()
            val call = client.newCall(request)
            gate.bindNetworkCancellation { call.cancel() }
            return call.execute().use { response ->
                val status = response.code
                if (status in 300..399) throw AuthFailure(AuthCode.ACCESS_DENIED)
                val parsed = if (status == 204) null else {
                    if (response.body.contentType()?.type != "application" ||
                        response.body.contentType()?.subtype != "json") {
                        throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
                    }
                    val bytes = response.body.byteStream().use { stream ->
                        val output = ByteArrayOutputStream()
                        val buffer = ByteArray(4096)
                        while (true) {
                            val count = stream.read(buffer)
                            if (count < 0) break
                            if (output.size() + count > 262_144) throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
                            output.write(buffer, 0, count)
                        }
                        buffer.fill(0)
                        output.toByteArray()
                    }
                    try {
                        val tokener = JSONTokener(bytes.toString(Charsets.UTF_8))
                        val value = tokener.nextValue()
                        if (tokener.nextClean() != 0.toChar()) throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
                        jsonValue(value)
                    } finally { bytes.fill(0) }
                }
                gate.check()
                val requestId = response.header("X-Request-ID")?.takeIf {
                    Regex("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}").matches(it)
                }
                NativeHttpResponse(status, parsed, requestId)
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

    private fun jsonValue(value: Any?, depth: Int = 0): Any? {
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
