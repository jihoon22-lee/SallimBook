package io.github.jihoon22lee.sallimbook.auth

import android.content.Context
import android.content.pm.ApplicationInfo
import android.os.SystemClock
import io.github.jihoon22lee.sallimbook.BuildConfig
import org.json.JSONObject
import org.json.JSONTokener
import java.time.Instant
import java.time.OffsetDateTime
import java.util.Base64
import java.util.concurrent.Executors

/** This value is delivered exclusively to NativeAuthActivity, never an AuthOutcome or Intent. */
internal class NativeInvitation(val token: CharArray, val expiresAt: String) {
    fun discard() { token.fill('\u0000') }
    override fun toString() = "NativeInvitation(redacted)"
}

/** Account session only, not vault or biometric authentication.
 * One executor serializes login, refresh rotation, metadata access and logout per process.
 * Token strings stay here/native transport; outcomes contain only safe metadata/status.
 */
internal class NativeAuthSession private constructor(context: Context) {
    companion object {
        @Volatile private var instance: NativeAuthSession? = null

        fun get(context: Context): NativeAuthSession = instance ?: synchronized(this) {
            instance ?: NativeAuthSession(context.applicationContext).also { instance = it }
        }
    }

    private val app = context.applicationContext
    private val origin = AuthPolicy.apiOrigin(BuildConfig.SALLIMBOOK_API_ORIGIN)
    val available = origin != null && (app.applicationInfo.flags and ApplicationInfo.FLAG_ALLOW_BACKUP) == 0
    private val executor = Executors.newSingleThreadExecutor { task -> Thread(task, "sallimbook-account-auth") }
    private val appLock by lazy { AppLockController.get(app) }
    fun hasLocalSession(): Boolean = accessToken != null || available && store.hasRefresh()

    private fun authorize(gate: ForegroundRequest, kind: AppRequestKind = AppRequestKind.PROTECTED) {
        if (kind in setOf(AppRequestKind.LOGIN, AppRequestKind.INVITATION) && appLock.locked && hasLocalSession())
            throw AuthFailure(AuthCode.APP_LOCKED)
        appLock.bind(gate, kind)
    }

    private val store by lazy { RefreshStore(app, origin.orEmpty()) }
    private val http by lazy { NativeAuthHttp(origin ?: throw AuthFailure(AuthCode.AUTH_UNAVAILABLE)) }
    @Volatile private var accessToken: String? = null
    private var accessExpiresAt = 0L

    private fun execute(gate: ForegroundRequest, callback: (AuthOutcome) -> Unit, action: () -> AuthOutcome) {
        executor.execute {
            val outcome = try {
                authorize(gate)
                gate.check()
                action().also { gate.check() }
            } catch (failure: AuthFailure) {
                AuthOutcome.failure(failure.code)
            } catch (_: Exception) {
                AuthOutcome.failure(AuthCode.AUTH_UNAVAILABLE)
            }
            callback(outcome)
        }
    }

    private fun requireAvailable() {
        if (!available) throw AuthFailure(AuthCode.AUTH_UNAVAILABLE)
    }

    private fun clearLocal() {
        accessToken = null
        accessExpiresAt = 0L
        store.clear()
    }

    private fun acceptTokens(body: Any?, gate: ForegroundRequest) {
        val values = body as? Map<*, *> ?: throw AuthFailure(AuthCode.AUTH_FAILED)
        val access = values["access_token"] as? String ?: throw AuthFailure(AuthCode.AUTH_FAILED)
        val refresh = values["refresh_token"] as? String ?: throw AuthFailure(AuthCode.AUTH_FAILED)
        val expires = values["expires_in"] as? Int ?: throw AuthFailure(AuthCode.AUTH_FAILED)
        val refreshExpires = values["refresh_expires_at"] as? String ?: throw AuthFailure(AuthCode.AUTH_FAILED)
        if (values["token_type"] != "Bearer" || expires !in 1..600 ||
            !Regex("[A-Za-z0-9_-]{32,128}").matches(access) ||
            !Regex("[A-Za-z0-9_-]{32,128}").matches(refresh)) throw AuthFailure(AuthCode.AUTH_FAILED)
        try { OffsetDateTime.parse(refreshExpires) } catch (_: Exception) { throw AuthFailure(AuthCode.AUTH_FAILED) }
        gate.whileActive {
            // A usable in-memory session is published only after durable refresh encryption.
            store.save(refresh)
            accessToken = access
            accessExpiresAt = SystemClock.elapsedRealtime() + maxOf(1, expires - 5) * 1000L
        }
    }

    private fun access(gate: ForegroundRequest): String {
        requireAvailable()
        gate.check()
        accessToken?.let { if (SystemClock.elapsedRealtime() < accessExpiresAt) return it }
        accessToken = null
        accessExpiresAt = 0L
        val refresh = store.takeForRotation() ?: throw AuthFailure(AuthCode.SESSION_EXPIRED)
        val payload = JSONObject().put("refresh_token", refresh)
        try {
            // Exactly one attempt. The old persisted token was consumed before sending.
            val response = http.send("POST", "/api/v1/auth/native/refresh", gate, body = payload)
            if (response.status != 200) throw AuthFailure(AuthCode.SESSION_EXPIRED)
            acceptTokens(response.body, gate)
            return accessToken ?: throw AuthFailure(AuthCode.SESSION_EXPIRED)
        } catch (failure: Exception) {
            clearLocal()
            if (failure is AuthFailure) throw failure
            throw AuthFailure(AuthCode.SESSION_EXPIRED)
        } finally { payload.remove("refresh_token") }
    }

    fun getSession(gate: ForegroundRequest, callback: (AuthOutcome) -> Unit) = execute(gate, callback) {
        if (!available) return@execute AuthOutcome.success(mapOf("available" to false, "authenticated" to false))
        if (accessToken == null && !store.hasRefresh()) {
            return@execute AuthOutcome.success(mapOf("available" to true, "authenticated" to false))
        }
        val token = access(gate)
        val response = http.send("GET", "/api/v1/me", gate, accessToken = token)
        if (response.status == 401) {
            clearLocal()
            AuthOutcome.success(mapOf("available" to true, "authenticated" to false))
        } else if (response.status == 200) {
            AuthPolicy.metadataBody("GET", "/api/v1/me", response.status, response.body)
            AuthOutcome.success(mapOf("available" to true, "authenticated" to true))
        } else throw AuthFailure(AuthCode.ACCESS_DENIED)
    }

    fun login(
        loginName: String, password: CharArray, deviceLabel: String,
        gate: ForegroundRequest, callback: (AuthOutcome) -> Unit,
    ) {
        // Clear password arrays even when a queued operation has already been cancelled.
        executor.execute {
            var payload: JSONObject? = null
            val outcome = try {
                authorize(gate, AppRequestKind.LOGIN)
                requireAvailable()
                gate.check()
                payload = JSONObject().put("login_name", loginName).put("password", String(password))
                    .put("device_label", deviceLabel)
                password.fill('\u0000')
                val response = http.send("POST", "/api/v1/auth/native/login", gate, body = payload)
                if (response.status != 200) throw AuthFailure(AuthCode.AUTH_FAILED)
                acceptTokens(response.body, gate)
                appLock.finishServerAuthentication(gate)
                AuthOutcome.success(mapOf("status" to "authenticated"))
            } catch (failure: AuthFailure) {
                AuthOutcome.failure(failure.code)
            } catch (_: Exception) {
                AuthOutcome.failure(AuthCode.AUTH_UNAVAILABLE)
            } finally {
                payload?.remove("password")
                password.fill('\u0000')
            }
            callback(outcome)
        }
    }

    fun reauthenticate(
        password: CharArray, gate: ForegroundRequest, callback: (AuthOutcome) -> Unit,
    ) {
        executor.execute {
            var payload: JSONObject? = null
            val outcome = try {
                authorize(gate, AppRequestKind.REAUTHENTICATE)
                requireAvailable()
                gate.check()
                val token = access(gate)
                payload = JSONObject().put("password", String(password))
                password.fill('\u0000')
                val response = http.send("POST", "/api/v1/auth/native/reauthenticate", gate,
                    body = payload, accessToken = token)
                if (response.status == 401) {
                    clearLocal()
                    throw AuthFailure(AuthCode.SESSION_EXPIRED)
                }
                if (response.status != 200) throw AuthFailure(AuthCode.AUTH_FAILED)
                AuthPolicy.metadataBody("GET", "/api/v1/me", response.status, response.body)
                gate.check()
                appLock.finishServerAuthentication(gate)
                AuthOutcome.success(mapOf("status" to "authenticated"))
            } catch (failure: AuthFailure) {
                AuthOutcome.failure(failure.code)
            } catch (_: Exception) {
                AuthOutcome.failure(AuthCode.AUTH_UNAVAILABLE)
            } finally {
                payload?.remove("password")
                password.fill('\u0000')
            }
            callback(outcome)
        }
    }

    fun acceptInvitation(
        invitation: CharArray, password: CharArray, displayName: String,
        gate: ForegroundRequest, callback: (AuthOutcome) -> Unit,
    ) {
        executor.execute {
            var payload: JSONObject? = null
            val outcome = try {
                authorize(gate, AppRequestKind.INVITATION)
                requireAvailable()
                gate.check()
                payload = JSONObject().put("token", String(invitation)).put("password", String(password))
                    .put("display_name", displayName)
                password.fill('\u0000')
                invitation.fill('\u0000')
                val response = http.send("POST", "/api/v1/auth/invitations/accept", gate, body = payload)
                if (response.status != 201) throw AuthFailure(AuthCode.REGISTRATION_FAILED)
                // No member/token data is copied into the Activity result or the JS bridge.
                AuthOutcome.success(mapOf("status" to "accepted"))
            } catch (failure: AuthFailure) {
                AuthOutcome.failure(failure.code)
            } catch (_: Exception) {
                AuthOutcome.failure(AuthCode.AUTH_UNAVAILABLE)
            } finally {
                payload?.remove("password")
                payload?.remove("token")
                password.fill('\u0000')
                invitation.fill('\u0000')
            }
            callback(outcome)
        }
    }

    fun createInvitation(
        intendedLogin: String, gate: ForegroundRequest,
        callback: (AuthOutcome, NativeInvitation?) -> Unit,
    ) {
        executor.execute {
            var invitation: NativeInvitation? = null
            val outcome = try {
                authorize(gate, AppRequestKind.PROTECTED)
                requireAvailable()
                gate.check()
                val response = http.send("POST", "/api/v1/household/invitations", gate,
                    body = JSONObject().put("intended_login", intendedLogin), accessToken = access(gate))
                if (response.status == 401) { clearLocal(); throw AuthFailure(AuthCode.SESSION_EXPIRED) }
                val serverCode = ((response.body as? Map<*, *>)?.get("error") as? Map<*, *>)?.get("code")
                if (response.status == 403 && serverCode == "REAUTHENTICATION_REQUIRED") {
                    throw AuthFailure(AuthCode.SESSION_EXPIRED)
                }
                if (response.status != 201) throw AuthFailure(AuthCode.ACCESS_DENIED)
                val body = response.body as? Map<*, *> ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
                if (body.keys != setOf("id", "token", "expires_at")) throw AuthFailure(AuthCode.ACCESS_DENIED)
                val id = body["id"] as? String ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
                val token = body["token"] as? String ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
                val expiry = body["expires_at"] as? String ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
                if (!Regex("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}").matches(id) ||
                    !Regex("[A-Za-z0-9_-]{32,128}").matches(token)) throw AuthFailure(AuthCode.ACCESS_DENIED)
                try { OffsetDateTime.parse(expiry) } catch (_: Exception) { throw AuthFailure(AuthCode.ACCESS_DENIED) }
                gate.check()
                invitation = NativeInvitation(token.toCharArray(), expiry)
                AuthOutcome.success(mapOf("status" to "created"))
            } catch (failure: AuthFailure) {
                AuthOutcome.failure(failure.code)
            } catch (_: Exception) {
                AuthOutcome.failure(AuthCode.AUTH_UNAVAILABLE)
            }
            callback(outcome, invitation)
        }
    }

    fun logout(gate: ForegroundRequest, callback: (AuthOutcome) -> Unit) {
        executor.execute {
            val outcome = try {
                val token = if (available && gate.isActive()) {
                    try { authorize(gate, AppRequestKind.LOGOUT); access(gate) } catch (_: AuthFailure) { null }
                } else null
                // A foreground logout intent still clears locally if the Activity pauses while queued.
                clearLocal()
                val revoked = if (token == null || !gate.isActive()) false else try {
                    http.send("POST", "/api/v1/auth/native/logout", gate, body = JSONObject(), accessToken = token).status == 204
                } catch (_: AuthFailure) { false }
                appLock.lock()
                AuthOutcome.success(mapOf("status" to "signedOut", "serverRevoked" to revoked))
            } catch (failure: AuthFailure) {
                AuthOutcome.failure(failure.code)
            } catch (_: Exception) {
                AuthOutcome.failure(AuthCode.AUTH_UNAVAILABLE)
            }
            callback(outcome)
        }
    }

    fun request(
        method: String, path: String, ifMatch: String?,
        gate: ForegroundRequest, callback: (AuthOutcome) -> Unit,
    ) = execute(gate, callback) {
        if (!AuthPolicy.requestAllowed(method, path, ifMatch)) throw AuthFailure(AuthCode.INVALID_REQUEST)
        val response = http.send(method, path, gate, accessToken = access(gate), ifMatch = ifMatch)
        if (response.status == 401) clearLocal()
        val safeBody = if (response.status in 200..299) {
            AuthPolicy.metadataBody(method, path, response.status, response.body)
        } else {
            // Never forward raw server error messages, validation inputs, or unknown fields.
            AuthPolicy.safeError(response.status, response.body, response.requestId)
                ?: throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
        }
        AuthOutcome.success(mapOf("status" to response.status, "body" to safeBody))
    }

    fun finance(
        operation: FinanceOperation, arguments: JSONObject,
        gate: ForegroundRequest, callback: (AuthOutcome) -> Unit,
    ) = execute(gate, callback) {
        requireAvailable()
        val request = FinancePolicy.prepare(operation, http.jsonValue(arguments))
        val response = http.send(request.method, request.path, gate,
            body = request.body?.let { JSONObject(it) }, accessToken = access(gate), ifMatch = request.ifMatch, idempotencyKey = request.idempotencyKey)
        if (response.status == 401) clearLocal()
        val safe = if (response.status in 200..299) FinancePolicy.response(operation, request, response.status, response.body)
            else AuthPolicy.safeError(response.status, response.body, response.requestId)
                ?: throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
        AuthOutcome.success(mapOf("status" to response.status, "body" to safe))
    }

    private fun accountNumberFailure(response: NativeHttpResponse): Nothing {
        if (response.status == 401) { clearLocal(); throw AuthFailure(AuthCode.SESSION_EXPIRED) }
        val code = ((response.body as? Map<*, *>)?.get("error") as? Map<*, *>)?.get("code")
        throw AuthFailure(when {
            response.status == 403 && code == "REAUTHENTICATION_REQUIRED" -> AuthCode.REAUTHENTICATION_REQUIRED
            response.status == 409 && code == "VERSION_CONFLICT" -> AuthCode.VERSION_CONFLICT
            response.status == 503 -> AuthCode.AUTH_UNAVAILABLE
            else -> AuthCode.ACCESS_DENIED
        })
    }

    private fun accountNumberResponse(response: NativeHttpResponse, accountId: String): NativeAccountNumber {
        if (response.status != 200) accountNumberFailure(response)
        return NativeAccountNumber(FinancePolicy.readNumber(response.body, accountId))
    }

    fun editAccountNumber(
        accountId: String, ifMatch: String, number: CharArray?, gate: ForegroundRequest, callback: (AuthOutcome) -> Unit,
    ) {
        executor.execute {
            var payload: JSONObject? = null
            val outcome = try {
                authorize(gate, AppRequestKind.PROTECTED)
                requireAvailable(); gate.check()
                if (!PasskeyPolicy.target(accountId, ifMatch) || number != null && !FinancePolicy.number(number)) {
                    throw AuthFailure(AuthCode.INVALID_REQUEST)
                }
                payload = JSONObject().put("account_number", number?.let(::String) ?: JSONObject.NULL)
                number?.fill('\u0000')
                val response = http.send("PATCH", "/api/v1/accounts/$accountId", gate, body = payload,
                    accessToken = access(gate), ifMatch = ifMatch, nativeAccountNumber = true)
                if (response.status != 200) accountNumberFailure(response)
                val safe = try { FinancePolicy.account(response.body) } catch (_: Exception) { throw AuthFailure(AuthCode.ACCESS_DENIED) }
                if (safe["id"] != accountId) throw AuthFailure(AuthCode.ACCESS_DENIED)
                gate.check()
                AuthOutcome.success(mapOf("status" to if (number == null) "deleted" else "saved"))
            } catch (failure: AuthFailure) { AuthOutcome.failure(failure.code) }
            catch (_: Exception) { AuthOutcome.failure(AuthCode.AUTH_UNAVAILABLE) }
            finally { payload?.remove("account_number"); number?.fill('\u0000') }
            callback(outcome)
        }
    }

    fun revealAccountNumber(
        accountId: String, gate: ForegroundRequest, callback: (AuthOutcome, NativeAccountNumber?) -> Unit,
    ) {
        executor.execute {
            var number: NativeAccountNumber? = null
            val outcome = try {
                authorize(gate, AppRequestKind.PROTECTED)
                requireAvailable(); gate.check(); FinancePolicy.id(accountId)
                val response = http.send("POST", "/api/v1/accounts/$accountId/reveal", gate,
                    body = JSONObject(), accessToken = access(gate), nativeAccountNumber = true)
                number = accountNumberResponse(response, accountId)
                gate.check()
                AuthOutcome.success(mapOf("status" to "completed"))
            } catch (failure: AuthFailure) { number?.discard(); number = null; AuthOutcome.failure(failure.code) }
            catch (_: Exception) { number?.discard(); number = null; AuthOutcome.failure(AuthCode.AUTH_UNAVAILABLE) }
            callback(outcome, number)
        }
    }

    fun editInsurancePolicyNumber(
        policyId: String, ifMatch: String, number: CharArray?, gate: ForegroundRequest, callback: (AuthOutcome) -> Unit,
    ) {
        executor.execute {
            var payload: JSONObject? = null
            val outcome = try {
                authorize(gate, AppRequestKind.PROTECTED)
                requireAvailable(); gate.check()
                if (!PasskeyPolicy.target(policyId, ifMatch) || number != null && !FinancePolicy.number(number)) {
                    throw AuthFailure(AuthCode.INVALID_REQUEST)
                }
                payload = JSONObject().put("policy_number", number?.let(::String) ?: JSONObject.NULL)
                number?.fill('\u0000')
                val response = http.send("PATCH", "/api/v1/insurance/policies/$policyId", gate, body = payload,
                    accessToken = access(gate), ifMatch = ifMatch, nativeInsurancePolicyNumber = true)
                if (response.status != 200) accountNumberFailure(response)
                val safe = try { InsurancePolicy.policy(response.body) } catch (_: Exception) { throw AuthFailure(AuthCode.ACCESS_DENIED) }
                if (safe["id"] != policyId) throw AuthFailure(AuthCode.ACCESS_DENIED)
                gate.check()
                AuthOutcome.success(mapOf("status" to if (number == null) "deleted" else "saved"))
            } catch (failure: AuthFailure) { AuthOutcome.failure(failure.code) }
            catch (_: Exception) { AuthOutcome.failure(AuthCode.AUTH_UNAVAILABLE) }
            finally { payload?.remove("policy_number"); number?.fill('\u0000') }
            callback(outcome)
        }
    }

    fun revealInsurancePolicyNumber(
        policyId: String, gate: ForegroundRequest, callback: (AuthOutcome, NativePolicyNumber?) -> Unit,
    ) {
        executor.execute {
            var number: NativePolicyNumber? = null
            val outcome = try {
                authorize(gate, AppRequestKind.PROTECTED)
                requireAvailable(); gate.check(); FinancePolicy.id(policyId)
                val response = http.send("POST", "/api/v1/insurance/policies/$policyId/reveal", gate,
                    body = JSONObject(), accessToken = access(gate), nativeInsurancePolicyNumber = true)
                if (response.status != 200) accountNumberFailure(response)
                number = NativePolicyNumber(InsurancePolicy.readNumber(response.body, policyId))
                gate.check()
                AuthOutcome.success(mapOf("status" to "completed"))
            } catch (failure: AuthFailure) { number?.discard(); number = null; AuthOutcome.failure(failure.code) }
            catch (_: Exception) { number?.discard(); number = null; AuthOutcome.failure(AuthCode.AUTH_UNAVAILABLE) }
            callback(outcome, number)
        }
    }

    private fun passkeyFailure(response: NativeHttpResponse, unauthenticatedLogin: Boolean = false): Nothing {
        PasskeyPolicy.reject(response.status, response.body, unauthenticatedLogin, ::clearLocal)
    }

    fun beginPasskey(
        operation: PasskeyOperation, text: String, targetId: String?, ifMatch: String?,
        gate: ForegroundRequest, callback: (AuthOutcome, NativePasskeyCeremony?) -> Unit,
    ) {
        executor.execute {
            var ceremony: NativePasskeyCeremony? = null
            val outcome = try {
                authorize(gate, if (operation == PasskeyOperation.LOGIN) AppRequestKind.LOGIN else AppRequestKind.PROTECTED)
                requireAvailable()
                gate.check()
                val configuration = PasskeyConfiguration.read(app) ?: throw AuthFailure(AuthCode.PASSKEYS_DISABLED)
                var target = targetId
                val access = if (operation == PasskeyOperation.LOGIN) null else access(gate)
                if (operation == PasskeyOperation.DEVICE_REVOKE && !PasskeyPolicy.target(target, ifMatch)) {
                    throw AuthFailure(AuthCode.INVALID_REQUEST)
                }
                if (operation == PasskeyOperation.ACCOUNT_REVEAL && (target == null || !PasskeyPolicy.uuid.matches(target) || ifMatch != null)) {
                    throw AuthFailure(AuthCode.INVALID_REQUEST)
                }
                if (operation in setOf(PasskeyOperation.LOGIN, PasskeyOperation.INVITE) &&
                    !Regex("[A-Za-z][A-Za-z0-9_.-]{2,63}").matches(text)) throw AuthFailure(AuthCode.INVALID_REQUEST)
                if (operation == PasskeyOperation.REGISTER && (text.isBlank() || text.codePointCount(0, text.length) > 80)) {
                    throw AuthFailure(AuthCode.INVALID_REQUEST)
                }
                if (operation == PasskeyOperation.INVITE) {
                    val me = http.send("GET", "/api/v1/me", gate, accessToken = access)
                    if (me.status != 200) passkeyFailure(me)
                    val member = AuthPolicy.metadataBody("GET", "/api/v1/me", 200, me.body) as Map<*, *>
                    if (member["role"] != "owner") throw AuthFailure(AuthCode.ACCESS_DENIED)
                    target = member["household_id"] as String
                }
                val path = when (operation) {
                    PasskeyOperation.LOGIN -> "/api/v1/auth/native/passkeys/options"
                    PasskeyOperation.REGISTER -> "/api/v1/auth/passkeys/register/options"
                    else -> "/api/v1/auth/step-up/options"
                }
                val payload = when (operation) {
                    PasskeyOperation.LOGIN -> JSONObject().put("login_name", text).put("device_label", "Android")
                    PasskeyOperation.REGISTER -> JSONObject().put("label", text)
                    else -> JSONObject().put("purpose", when (operation) {
                        PasskeyOperation.INVITE -> "household.invite"
                        PasskeyOperation.ACCOUNT_REVEAL -> "account.reveal"
                        else -> "device.revoke"
                    })
                        .put("target_id", target)
                }
                val response = http.send("POST", path, gate, body = payload, accessToken = access)
                if (response.status != 200) passkeyFailure(response, operation == PasskeyOperation.LOGIN)
                val record = response.body as? Map<*, *> ?: throw AuthFailure(AuthCode.PASSKEY_FAILED)
                val keys = setOf("challenge_id", "public_key", "expires_at") +
                    if (operation == PasskeyOperation.LOGIN) setOf("device_binding") else emptySet()
                if (record.keys != keys) throw AuthFailure(AuthCode.PASSKEY_FAILED)
                val id = record["challenge_id"] as? String ?: throw AuthFailure(AuthCode.PASSKEY_FAILED)
                if (!PasskeyPolicy.uuid.matches(id)) throw AuthFailure(AuthCode.PASSKEY_FAILED)
                val options = PasskeyPolicy.options(record["public_key"], operation == PasskeyOperation.REGISTER, configuration.rpId)
                val expiry = record["expires_at"] as? String ?: throw AuthFailure(AuthCode.PASSKEY_FAILED)
                val remaining = PasskeyPolicy.remaining(expiry, Instant.now(), 300_000)
                if (remaining == 0L) throw AuthFailure(AuthCode.PASSKEY_FAILED)
                val binding = if (operation == PasskeyOperation.LOGIN) {
                    PasskeyPolicy.encoded(record["device_binding"], 32, 128).toCharArray()
                } else null
                gate.check()
                ceremony = NativePasskeyCeremony(operation, id, options["challenge"] as String,
                    JSONObject(options).toString().toCharArray(), binding, target, ifMatch,
                    if (operation == PasskeyOperation.INVITE) text else null,
                    SystemClock.elapsedRealtime() + remaining, configuration)
                AuthOutcome.success(mapOf("status" to "ready"))
            } catch (failure: AuthFailure) { AuthOutcome.failure(failure.code) }
            catch (_: Exception) { AuthOutcome.failure(AuthCode.PASSKEY_FAILED) }
            callback(outcome, ceremony)
        }
    }

    /** Verification and any scoped mutation are one native operation; no grant is returned. */
    fun finishPasskey(
        ceremony: NativePasskeyCeremony, credentialJson: CharArray, gate: ForegroundRequest,
        callback: (AuthOutcome, NativeInvitation?, NativeAccountNumber?) -> Unit,
    ) {
        executor.execute {
            var invitation: NativeInvitation? = null
            var accountNumber: NativeAccountNumber? = null
            var payload: JSONObject? = null
            var grant: CharArray? = null
            val outcome = try {
                authorize(gate, if (ceremony.operation == PasskeyOperation.LOGIN) AppRequestKind.LOGIN else AppRequestKind.PROTECTED)
                requireAvailable()
                gate.check()
                if (!ceremony.claim(SystemClock.elapsedRealtime()) || credentialJson.size !in 1..100_000) {
                    throw AuthFailure(AuthCode.PASSKEY_FAILED)
                }
                val configuration = PasskeyConfiguration.read(app) ?: throw AuthFailure(AuthCode.PASSKEYS_DISABLED)
                if (configuration.rpId != ceremony.configuration.rpId || configuration.androidOrigin != ceremony.configuration.androidOrigin) {
                    throw AuthFailure(AuthCode.PASSKEYS_DISABLED)
                }
                val tokener = JSONTokener(String(credentialJson))
                val json = tokener.nextValue() as? JSONObject ?: throw AuthFailure(AuthCode.PASSKEY_FAILED)
                if (tokener.nextClean() != 0.toChar()) throw AuthFailure(AuthCode.PASSKEY_FAILED)
                credentialJson.fill('\u0000')
                val registration = ceremony.operation == PasskeyOperation.REGISTER
                val credential = PasskeyPolicy.credential(http.jsonValue(json), registration)
                val responseData = credential["response"] as Map<*, *>
                val clientDataBytes = Base64.getUrlDecoder().decode(responseData["clientDataJSON"] as String)
                val clientData = try { http.jsonValue(JSONObject(clientDataBytes.toString(Charsets.UTF_8))) }
                    finally { clientDataBytes.fill(0) }
                if (!PasskeyPolicy.clientData(clientData, registration, ceremony.challenge, configuration.androidOrigin)) {
                    throw AuthFailure(AuthCode.PASSKEY_FAILED)
                }
                payload = JSONObject().put("challenge_id", ceremony.challengeId).put("credential", json)
                val operation = ceremony.operation
                val path = when (operation) {
                    PasskeyOperation.LOGIN -> "/api/v1/auth/native/passkeys/verify"
                    PasskeyOperation.REGISTER -> "/api/v1/auth/passkeys/register/verify"
                    else -> "/api/v1/auth/step-up/verify"
                }
                if (operation == PasskeyOperation.LOGIN) payload.put("device_binding", String(ceremony.binding
                    ?: throw AuthFailure(AuthCode.PASSKEY_FAILED)))
                val access = if (operation == PasskeyOperation.LOGIN) null else access(gate)
                val response = http.send("POST", path, gate, body = payload, accessToken = access)
                val expected = if (registration) 201 else 200
                if (response.status != expected) passkeyFailure(response, operation == PasskeyOperation.LOGIN)
                gate.check()
                when (operation) {
                    PasskeyOperation.LOGIN -> {
                        // A failed/cancelled replacement must not destroy the current session.
                        // acceptTokens publishes only inside the active gate after encrypted save.
                        acceptTokens(response.body, gate)
                        appLock.finishServerAuthentication(gate)
                        AuthOutcome.success(mapOf("status" to "authenticated"))
                    }
                    PasskeyOperation.REGISTER -> {
                        AuthPolicy.passkey(response.body)
                        AuthOutcome.success(mapOf("status" to "registered"))
                    }
                    else -> {
                        val purpose = when (operation) {
                            PasskeyOperation.INVITE -> "household.invite"
                            PasskeyOperation.ACCOUNT_REVEAL -> "account.reveal"
                            else -> "device.revoke"
                        }
                        grant = PasskeyPolicy.grant(response.body, purpose, ceremony.targetId, Instant.now()).toCharArray()
                        gate.check()
                        if (operation == PasskeyOperation.ACCOUNT_REVEAL) {
                            val accountId = ceremony.targetId ?: throw AuthFailure(AuthCode.INVALID_REQUEST)
                            val revealed = http.send("POST", "/api/v1/accounts/$accountId/reveal", gate,
                                body = JSONObject(), accessToken = access, stepUpToken = String(grant), nativeAccountNumber = true)
                            accountNumber = accountNumberResponse(revealed, accountId)
                            AuthOutcome.success(mapOf("status" to "completed"))
                        } else if (operation == PasskeyOperation.DEVICE_REVOKE) {
                            val removed = http.send("DELETE", "/api/v1/devices/${ceremony.targetId}", gate,
                                accessToken = access, ifMatch = ceremony.ifMatch, stepUpToken = String(grant))
                            if (removed.status != 204) passkeyFailure(removed)
                            AuthOutcome.success(mapOf("status" to "revoked"))
                        } else {
                            val created = http.send("POST", "/api/v1/household/invitations", gate,
                                body = JSONObject().put("intended_login", ceremony.intendedLogin),
                                accessToken = access, stepUpToken = String(grant))
                            if (created.status != 201) passkeyFailure(created)
                            val record = created.body as? Map<*, *> ?: throw AuthFailure(AuthCode.PASSKEY_FAILED)
                            if (record.keys != setOf("id", "token", "expires_at") ||
                                !PasskeyPolicy.uuid.matches(record["id"] as? String ?: "")) throw AuthFailure(AuthCode.PASSKEY_FAILED)
                            val token = PasskeyPolicy.encoded(record["token"], 32, 128)
                            val expiry = record["expires_at"] as? String ?: throw AuthFailure(AuthCode.PASSKEY_FAILED)
                            if (PasskeyPolicy.remaining(expiry, Instant.now(), 30_000) == 0L) throw AuthFailure(AuthCode.PASSKEY_FAILED)
                            invitation = NativeInvitation(token.toCharArray(), expiry)
                            AuthOutcome.success(mapOf("status" to "created"))
                        }
                    }
                }
            } catch (failure: AuthFailure) { AuthOutcome.failure(failure.code) }
            catch (_: Exception) { AuthOutcome.failure(AuthCode.PASSKEY_FAILED) }
            finally {
                payload?.remove("credential")
                payload?.remove("device_binding")
                credentialJson.fill('\u0000')
                grant?.fill('\u0000')
                ceremony.discard()
            }
            callback(outcome, invitation, accountNumber)
        }
    }

    fun revokePasskey(id: String, ifMatch: String, gate: ForegroundRequest, callback: (AuthOutcome) -> Unit) = execute(gate, callback) {
        if (!PasskeyPolicy.target(id, ifMatch)) throw AuthFailure(AuthCode.INVALID_REQUEST)
        val response = http.send("DELETE", "/api/v1/auth/passkeys/$id", gate, accessToken = access(gate), ifMatch = ifMatch)
        if (response.status != 204) passkeyFailure(response)
        AuthOutcome.success(mapOf("status" to "revoked"))
    }
}
