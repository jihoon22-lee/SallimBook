package io.github.jihoon22lee.sallimbook.auth

import android.content.Context
import android.content.pm.ApplicationInfo
import android.os.SystemClock
import io.github.jihoon22lee.sallimbook.BuildConfig
import org.json.JSONObject
import java.time.OffsetDateTime
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
    private val store by lazy { RefreshStore(app, origin.orEmpty()) }
    private val http by lazy { NativeAuthHttp(origin ?: throw AuthFailure(AuthCode.AUTH_UNAVAILABLE)) }
    private var accessToken: String? = null
    private var accessExpiresAt = 0L

    private fun execute(gate: ForegroundRequest, callback: (AuthOutcome) -> Unit, action: () -> AuthOutcome) {
        executor.execute {
            val outcome = try {
                gate.check()
                action()
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
                requireAvailable()
                gate.check()
                clearLocal()
                payload = JSONObject().put("login_name", loginName).put("password", String(password))
                    .put("device_label", deviceLabel)
                password.fill('\u0000')
                val response = http.send("POST", "/api/v1/auth/native/login", gate, body = payload)
                if (response.status != 200) throw AuthFailure(AuthCode.AUTH_FAILED)
                acceptTokens(response.body, gate)
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
                    try { access(gate) } catch (_: AuthFailure) { null }
                } else null
                // A foreground logout intent still clears locally if the Activity pauses while queued.
                clearLocal()
                val revoked = if (token == null || !gate.isActive()) false else try {
                    http.send("POST", "/api/v1/auth/native/logout", gate, body = JSONObject(), accessToken = token).status == 204
                } catch (_: AuthFailure) { false }
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
}
