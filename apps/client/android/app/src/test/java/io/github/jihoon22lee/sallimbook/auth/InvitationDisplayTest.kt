package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class InvitationDisplayTest {
    @Test fun maximumThirtySecondsIncludesTimeWaitingToReveal() {
        val buffer = "synthetic".toCharArray()
        val display = InvitationDisplay(buffer, 100, 60_000)
        assertEquals(30_000, display.durationMillis)
        assertEquals("synthetic", display.reveal(30_099, true, true, true))
        assertNull(display.reveal(30_100, true, true, true))
        assertTrue(buffer.all { it == '\u0000' })
        assertNull(display.reveal(101, true, true, true))
    }

    @Test fun serverExpiryCanShortenButNeverExtendVisibility() {
        for (remaining in listOf(-1L, 0L, 50L)) {
            val display = InvitationDisplay("synthetic".toCharArray(), 100, remaining)
            assertEquals(remaining.coerceAtLeast(0), display.durationMillis)
            assertNull(display.reveal(100 + remaining.coerceAtLeast(0), true, true, true))
        }
    }

    @Test fun focusLossPauseAndScreenLockPermanentlyEraseBuffer() {
        for (state in listOf(Triple(false, true, true), Triple(true, false, true), Triple(true, true, false))) {
            val buffer = "synthetic".toCharArray()
            val display = InvitationDisplay(buffer, 100, 30_000)
            assertNull(display.reveal(101, state.first, state.second, state.third))
            assertTrue(buffer.all { it == '\u0000' })
            assertNull(display.reveal(102, true, true, true))
        }
    }

    @Test fun explicitDestructionAndClockRollbackFailClosed() {
        val buffer = "synthetic".toCharArray()
        val display = InvitationDisplay(buffer, 100, 30_000)
        display.discard()
        display.discard()
        assertTrue(buffer.all { it == '\u0000' })
        assertNull(display.reveal(101, true, true, true))
        assertNull(InvitationDisplay("synthetic".toCharArray(), 100, 30_000)
            .reveal(99, true, true, true))
        assertEquals("InvitationDisplay(redacted)", display.toString())
    }
}
