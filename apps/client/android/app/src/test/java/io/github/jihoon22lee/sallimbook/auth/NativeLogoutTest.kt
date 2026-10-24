package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class NativeLogoutTest {
    private val token = "synthetic_access_000000000000000000000000001"

    @Test fun logoutPostsBeforeClearingLocalState() {
        // Clearing locks the app and cancels every gate, so a POST after it would never be sent.
        val events = mutableListOf<String>()
        val revoked = NativeLogout.run(token, { "clear" !in events }, { events += "post:$it"; true }) { events += "clear" }
        assertTrue(revoked)
        assertEquals(listOf("post:$token", "clear"), events)
    }

    @Test fun aNetworkFailureStillClearsLocallyAndReportsUnconfirmed() {
        val events = mutableListOf<String>()
        val revoked = NativeLogout.run(token, { true }, { events += "post"; throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE) }) {
            events += "clear"
        }
        assertFalse(revoked)
        assertEquals(listOf("post", "clear"), events)
        val unexpected = mutableListOf<String>()
        assertFalse(NativeLogout.run(token, { true }, { throw IllegalStateException("synthetic") }) { unexpected += "clear" })
        assertEquals(listOf("clear"), unexpected)
    }

    @Test fun withoutATokenOrAnActiveScreenOnlyLocalStateIsCleared() {
        for ((lease, active) in listOf(null to true, token to false)) {
            val events = mutableListOf<String>()
            assertFalse(NativeLogout.run(lease, { active }, { events += "post"; true }) { events += "clear" })
            assertEquals(listOf("clear"), events)
        }
    }

    @Test fun anAnswerOtherThanRevokedIsUnconfirmed() {
        assertFalse(NativeLogout.run(token, { true }, { false }) {})
    }
}
