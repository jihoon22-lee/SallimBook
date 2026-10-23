package io.github.jihoon22lee.sallimbook.auth

import java.time.Instant
import java.time.OffsetDateTime

/**
 * The invitation a 201 just created. A later API may add safe fields. Once the server has
 * answered 201 the invitation may exist, so an unreadable reply leaves the result unknown
 * instead of reading as a refusal.
 */
internal object NativeInvitationReply {
    private val fields = setOf("id", "token", "expires_at")
    private fun unknown(): Nothing = throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)

    /** With [now] (the passkey path), the code must also have time left to show. */
    fun read(body: Any?, now: Instant? = null): NativeInvitation {
        try {
            val row = NativeResponseShape.fields(body, fields, ::unknown)
            val id = row["id"] as? String ?: unknown()
            val expiry = row["expires_at"] as? String ?: unknown()
            if (!PasskeyPolicy.uuid.matches(id)) unknown()
            OffsetDateTime.parse(expiry)
            if (now != null && PasskeyPolicy.remaining(expiry, now, 30_000) == 0L) unknown()
            return NativeInvitation(PasskeyPolicy.encoded(row["token"], 32, 128).toCharArray(), expiry)
        } catch (_: Exception) { unknown() }
    }
}
