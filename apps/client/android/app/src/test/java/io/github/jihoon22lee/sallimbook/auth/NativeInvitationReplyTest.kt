package io.github.jihoon22lee.sallimbook.auth

import java.io.File
import java.time.Instant
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.fail
import org.junit.Test

class NativeInvitationReplyTest {
    private val now = Instant.parse("2026-01-01T00:00:00Z")
    // Canonical unpadded base64url of 32 bytes, as the server issues.
    private val token = "Sy".repeat(21) + "A"
    private fun reply(vararg extra: Pair<String, Any?>) = mapOf(
        "id" to "00000000-0000-4000-8000-000000000001", "token" to token,
        "expires_at" to "2026-01-08T00:00:00Z") + extra

    private fun unknown(action: () -> Unit) {
        try { action(); fail("Synthetic invitation accepted") } catch (failure: AuthFailure) {
            // The invitation may exist already, so the result is unknown rather than refused.
            assertEquals(AuthCode.NETWORK_UNAVAILABLE, failure.code)
        }
    }

    @Test fun anAddedSafeFieldStillShowsTheInvitation() {
        for (passkey in listOf(null, now)) {
            val invitation = NativeInvitationReply.read(reply("created_at" to "2026-01-01T00:00:00Z"), passkey)
            assertArrayEquals(token.toCharArray(), invitation.token)
            assertEquals("2026-01-08T00:00:00Z", invitation.expiresAt)
        }
    }

    @Test fun anUnreadableInvitationLeavesTheResultUnknown() {
        unknown { NativeInvitationReply.read(reply() - "token") }
        unknown { NativeInvitationReply.read(reply("access_token" to "synthetic")) }
        unknown { NativeInvitationReply.read(reply() + ("token" to "short")) }
        unknown { NativeInvitationReply.read(reply() + ("id" to "not-an-id")) }
        unknown { NativeInvitationReply.read(reply() + ("expires_at" to "tomorrow")) }
        unknown { NativeInvitationReply.read("not an object") }
        // The passkey path also needs time left to show the code.
        unknown { NativeInvitationReply.read(reply() + ("expires_at" to "2025-12-31T23:59:59Z"), now) }
    }

    @Test fun bothInvitationPathsReadTheReplyTheSameWay() {
        val session = File("src/main/java/io/github/jihoon22lee/sallimbook/auth/NativeAuthSession.kt").readText()
        assertEquals(2, Regex("NativeInvitationReply\\.read\\(").findAll(session).count())
        assertFalse(session.contains("setOf(\"id\", \"token\", \"expires_at\")"))
    }
}
