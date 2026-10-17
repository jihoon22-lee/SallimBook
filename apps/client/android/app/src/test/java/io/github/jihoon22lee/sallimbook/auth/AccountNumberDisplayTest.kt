package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class AccountNumberDisplayTest {
    @Test fun numberExpiresAtThirtySecondsAndNeverReopensAnExpiredBuffer() {
        val buffer = "SYNTHETIC123".toCharArray()
        val display = AccountNumberDisplay(buffer, 100)
        assertEquals("SYNTHETIC123", display.reveal(30_099, true, true, true))
        assertNull(display.reveal(30_100, true, true, true))
        assertTrue(buffer.all { it == '\u0000' })
        assertNull(display.reveal(101, true, true, true))
    }
    @Test fun focusPauseLockAndExplicitDestructionEraseTheNativeNumber() {
        for (state in listOf(Triple(false, true, true), Triple(true, false, true), Triple(true, true, false))) {
            val buffer = "SYNTHETIC123".toCharArray()
            val display = AccountNumberDisplay(buffer, 100)
            assertNull(display.reveal(101, state.first, state.second, state.third))
            assertTrue(buffer.all { it == '\u0000' })
            assertNull(display.reveal(102, true, true, true))
        }
        val number = NativeAccountNumber("SYNTHETIC123".toCharArray())
        assertEquals("NativeAccountNumber(redacted)", number.toString())
        number.discard()
        assertTrue(number.number.all { it == '\u0000' })
    }
}
