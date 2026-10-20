package io.github.jihoon22lee.sallimbook.auth

import java.time.OffsetDateTime

/** The persisted refresh token, split so the ciphertext survives every failure before the body write. */
internal interface RefreshTokenStore {
    /** Decrypts without consuming; the ciphertext stays until [consume]. */
    fun readForRotation(): String?
    /** Deletes the ciphertext. Called only from the refresh body write. */
    fun consume()
    /** Stores a rotated token, or restores the same token after an answered non-401 failure. */
    fun save(refresh: String)
}

internal class NativeTokens private constructor(val access: String, val refresh: String, val expiresIn: Int) {
    companion object {
        fun parse(body: Any?): NativeTokens {
            val values = body as? Map<*, *> ?: throw AuthFailure(AuthCode.AUTH_FAILED)
            val access = values["access_token"] as? String ?: throw AuthFailure(AuthCode.AUTH_FAILED)
            val refresh = values["refresh_token"] as? String ?: throw AuthFailure(AuthCode.AUTH_FAILED)
            val expires = values["expires_in"] as? Int ?: throw AuthFailure(AuthCode.AUTH_FAILED)
            val refreshExpires = values["refresh_expires_at"] as? String ?: throw AuthFailure(AuthCode.AUTH_FAILED)
            if (values["token_type"] != "Bearer" || expires !in 1..600 ||
                !Regex("[A-Za-z0-9_-]{32,128}").matches(access) ||
                !Regex("[A-Za-z0-9_-]{32,128}").matches(refresh)) throw AuthFailure(AuthCode.AUTH_FAILED)
            try { OffsetDateTime.parse(refreshExpires) } catch (_: Exception) { throw AuthFailure(AuthCode.AUTH_FAILED) }
            return NativeTokens(access, refresh, expires)
        }
    }
    override fun toString() = "NativeTokens(redacted)"
}

/**
 * Decides one refresh attempt. Only an explicit server 401 ends the account session and wipes
 * the local vault ([rejected]). Once the old token has been written to the wire, an unclear
 * outcome cannot replay it, so the session ends without touching the vault ([abandoned]).
 * Answered non-401 failures restore the same token so the user can simply retry.
 */
internal class NativeRefreshRotation(
    private val store: RefreshTokenStore,
    private val exchange: (String, ForegroundRequest, () -> Unit) -> NativeHttpResponse,
    private val install: (NativeTokens) -> Unit,
    private val rejected: () -> Unit,
    private val abandoned: () -> Unit,
) {
    fun rotate(gate: ForegroundRequest) {
        val previous = store.readForRotation() ?: throw AuthFailure(AuthCode.SESSION_EXPIRED)
        var consumed = false
        val response = try {
            exchange(previous, gate) { store.consume(); consumed = true }
        } catch (failure: Exception) {
            if (consumed) {
                abandoned()
                throw AuthFailure(AuthCode.SESSION_EXPIRED)
            }
            throw failure as? AuthFailure ?: AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
        }
        when (response.status) {
            200 -> {
                val tokens = try { NativeTokens.parse(response.body) } catch (_: AuthFailure) {
                    abandoned()
                    throw AuthFailure(AuthCode.SESSION_EXPIRED)
                }
                // A usable in-memory session is published only after durable refresh encryption,
                // and even when the screen has gone away: the server already rotated the token.
                persist(tokens.refresh)
                install(tokens)
                gate.check()
            }
            401 -> {
                rejected()
                throw AuthFailure(AuthCode.SESSION_EXPIRED)
            }
            else -> {
                persist(previous)
                throw AuthFailure(if (response.status == 429) AuthCode.RATE_LIMITED else AuthCode.NETWORK_UNAVAILABLE)
            }
        }
    }

    private fun persist(refresh: String) {
        try {
            store.save(refresh)
        } catch (failure: Exception) {
            abandoned()
            throw failure as? AuthFailure ?: AuthFailure(AuthCode.KEY_INVALIDATED)
        }
    }
}
