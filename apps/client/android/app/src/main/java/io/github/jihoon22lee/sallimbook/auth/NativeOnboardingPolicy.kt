package io.github.jihoon22lee.sallimbook.auth

import java.time.OffsetDateTime

/** Native boundary projection of the setup/connect contract. No server admission authority. */
internal object NativeOnboardingPolicy {
    const val STATUS_PATH = "/api/v1/household/setup"
    const val SETUP_PATH = "/api/v1/auth/native/setup"
    const val CONNECT_PATH = "/api/v1/auth/native/connect"
    const val CODE_PATH = "/api/v1/household/connection-code"
    private val token = Regex("[A-Za-z0-9_-]{32,128}")

    private fun scalarLength(value: CharSequence): Int? {
        var count = 0; var index = 0
        while (index < value.length) {
            val next = value[index++]
            if (Character.isHighSurrogate(next)) {
                if (index >= value.length || !Character.isLowSurrogate(value[index++])) return null
            } else if (Character.isLowSurrogate(next)) return null
            count++
        }
        return count
    }
    fun name(value: String): Boolean = value == value.trim() && scalarLength(value)?.let { it in 1..80 } == true
    fun password(value: CharArray): Boolean = scalarLength(java.nio.CharBuffer.wrap(value))?.let { it in 15..128 } == true
    private fun password(value: String): Boolean = scalarLength(value)?.let { it in 15..128 } == true
    fun code(value: CharArray): Boolean = value.size == 8 && value.all { it in '0'..'9' }

    fun httpAllowed(method: String, path: String, body: Any?, authenticated: Boolean,
        ifMatch: String?, stepUp: String?, idempotency: String?): Boolean {
        if (ifMatch != null || stepUp != null || idempotency != null) return false
        if (method == "GET" && path == STATUS_PATH) return body == null && !authenticated
        if (method != "POST") return false
        if (path == CODE_PATH) return body == null && authenticated
        if (authenticated || path !in setOf(SETUP_PATH, CONNECT_PATH)) return false
        val values = body as? Map<*, *> ?: return false
        val fields = setOf("display_name", "password", "device_label") + if (path == CONNECT_PATH) setOf("code") else emptySet()
        if (values.keys != fields) return false
        val displayName = values["display_name"] as? String ?: return false
        val secret = values["password"] as? String ?: return false
        val label = values["device_label"] as? String ?: return false
        return name(displayName) && password(secret) && name(label) &&
            (path != CONNECT_PATH || (values["code"] as? String)?.let { it.length == 8 && it.all { char -> char in '0'..'9' } } == true)
    }
    fun setupStatus(status: Int, value: Any?): Map<String, Boolean> {
        if (status != 200) throw AuthFailure(error(status, value))
        val row = value as? Map<*, *> ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
        if (row.keys != setOf("available") || row["available"] !is Boolean) throw AuthFailure(AuthCode.ACCESS_DENIED)
        return mapOf("available" to row["available"] as Boolean)
    }
    /** Access is used only for native /me verification; the whole response stays native. */
    fun enrollmentAccess(status: Int, value: Any?): String {
        if (status != 201) throw AuthFailure(error(status, value))
        val row = value as? Map<*, *> ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
        if (row.keys != setOf("access_token", "refresh_token", "token_type", "expires_in", "refresh_expires_at") ||
            row["token_type"] != "Bearer" || row["expires_in"] !is Int || (row["expires_in"] as Int) !in 1..600)
            throw AuthFailure(AuthCode.ACCESS_DENIED)
        val access = row["access_token"] as? String ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
        val refresh = row["refresh_token"] as? String ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
        if (!token.matches(access) || !token.matches(refresh)) throw AuthFailure(AuthCode.ACCESS_DENIED)
        timestamp(row["refresh_expires_at"])
        return access
    }
    fun connectionCode(status: Int, value: Any?): NativeConnectionCode {
        if (status != 201) throw AuthFailure(error(status, value))
        val row = value as? Map<*, *> ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
        if (row.keys != setOf("code", "expires_at")) throw AuthFailure(AuthCode.ACCESS_DENIED)
        val code = row["code"] as? String ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
        if (code.length != 8 || code.any { it !in '0'..'9' }) throw AuthFailure(AuthCode.ACCESS_DENIED)
        val expiry = timestamp(row["expires_at"])
        return NativeConnectionCode(code.toCharArray(), expiry)
    }
    private fun timestamp(value: Any?): String {
        val text = value as? String ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
        if (text.length > 64) throw AuthFailure(AuthCode.ACCESS_DENIED)
        try { OffsetDateTime.parse(text) } catch (_: Exception) { throw AuthFailure(AuthCode.ACCESS_DENIED) }
        return text
    }
    fun error(status: Int, value: Any?): AuthCode {
        val code = ((value as? Map<*, *>)?.get("error") as? Map<*, *>)?.get("code")
        val known = mapOf(
            "SETUP_UNAVAILABLE" to (403 to AuthCode.SETUP_UNAVAILABLE),
            "SETUP_COMPLETE" to (409 to AuthCode.SETUP_COMPLETE),
            "INVALID_CONNECTION_CODE" to (400 to AuthCode.INVALID_CONNECTION_CODE),
            "REGISTRATION_CONFLICT" to (409 to AuthCode.REGISTRATION_CONFLICT),
            "HOUSEHOLD_FULL" to (409 to AuthCode.HOUSEHOLD_FULL),
            "LOGIN_UNAVAILABLE" to (409 to AuthCode.LOGIN_UNAVAILABLE),
            "RATE_LIMITED" to (429 to AuthCode.RATE_LIMITED),
            "VALIDATION_ERROR" to (422 to AuthCode.VALIDATION_ERROR),
            "REAUTHENTICATION_REQUIRED" to (403 to AuthCode.REAUTHENTICATION_REQUIRED),
        )
        return known[code]?.takeIf { it.first == status }?.second ?: when (status) {
            401 -> AuthCode.SESSION_EXPIRED
            403 -> AuthCode.ACCESS_DENIED
            else -> AuthCode.AUTH_UNAVAILABLE
        }
    }
}

/** Native display owner only. Never included in an AuthOutcome, Intent or bridge result. */
internal class NativeConnectionCode(val code: CharArray, val expiresAt: String) {
    fun discard() = code.fill('\u0000')
    override fun toString() = "NativeConnectionCode(redacted)"
}

/** Includes time spent waiting for the serialized account executor. Clock injected for tests. */
internal class NativeOnboardingAttempt(private val now: () -> Long) {
    private val started = now()
    fun check() {
        if (now() - started !in 0 until 60_000L) throw AuthFailure(AuthCode.AUTH_CANCELLED)
    }
    /** No pre-existing session is replaced. Roll back partial/new credentials if completion
     * loses its deadline or foreground generation; never unlock from a stale server result. */
    fun install(gate: ForegroundRequest, save: () -> Unit, unlock: () -> Unit, rollback: () -> Unit) = gate.whileActive {
        check()
        try {
            save()
            check()
            gate.check()
            unlock()
            gate.check()
            check()
        } catch (failure: Exception) {
            try { rollback() } catch (_: Exception) { throw AuthFailure(AuthCode.KEY_INVALIDATED) }
            throw failure
        }
    }
}
