package io.github.jihoon22lee.sallimbook.auth

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class NativeSessionEndTest {
    @Test fun aSignedInScreenWhoseRequestEndedWithTheSessionCloses() {
        assertTrue(NativeSessionEnd.ended(current = true, ready = true, startedSignedIn = true, signedIn = false))
    }

    @Test fun otherLateResultsAreIgnoredAsBefore() {
        // A newer request, a screen in the background, a sign-in screen and an app lock with
        // the session kept all leave the screen as it is.
        assertFalse(NativeSessionEnd.ended(current = false, ready = true, startedSignedIn = true, signedIn = false))
        assertFalse(NativeSessionEnd.ended(current = true, ready = false, startedSignedIn = true, signedIn = false))
        assertFalse(NativeSessionEnd.ended(current = true, ready = true, startedSignedIn = false, signedIn = false))
        assertFalse(NativeSessionEnd.ended(current = true, ready = true, startedSignedIn = true, signedIn = true))
    }

    @Test fun everyCancelledRequestInTheSignedInScreensChecksForASessionEnd() {
        val root = File("src/main/java/io/github/jihoon22lee/sallimbook/auth")
        val expected = mapOf("NativeAuthActivity.kt" to 2, "NativeAccountNumberActivity.kt" to 3, "NativePasskeyActivity.kt" to 5)
        for ((name, count) in expected) {
            val source = File(root, name).readText()
            assertEquals(name, count, Regex("closeIfSignedOut\\(").findAll(source).count() - 1)
        }
    }
}
