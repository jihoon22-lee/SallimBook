package io.github.jihoon22lee.sallimbook.auth

import java.io.File
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class NativeInstallDeviceTest {
    private val id = "00000000-0000-4000-8000-000000000001"
    private val other = "00000000-0000-4000-8000-000000000002"
    private val key = "k".repeat(43)

    private class FakeStore(var stored: InstallClaim? = null, val transient: Boolean = false) : InstallClaimStore {
        var saves = 0
        var clears = 0
        override fun read(): InstallClaim? {
            if (transient) throw AuthFailure(AuthCode.AUTH_UNAVAILABLE)
            return stored
        }
        override fun save(claim: InstallClaim) { saves++; stored = claim }
        override fun clear() { clears++; stored = null }
    }

    @Test fun theFirstSignInAsksForADeviceKey() {
        assertEquals(emptyMap<String, String>(), NativeInstallDevice.claim(FakeStore()))
    }

    @Test fun aStoredClaimIsSentAsIs() {
        assertEquals(mapOf("device_id" to id, "key" to key), NativeInstallDevice.claim(FakeStore(InstallClaim(id, key))))
    }

    @Test fun aTransientReadFailureSendsNothingAndKeepsTheClaim() {
        val store = FakeStore(InstallClaim(id, key), transient = true)
        val sent = NativeInstallDevice.claim(store)
        assertNull(sent)
        NativeInstallDevice.accept(store, sent, mapOf("install" to mapOf("device_id" to other, "key" to key)))
        assertEquals(0, store.saves + store.clears)
    }

    @Test fun aNewRowsKeyReplacesTheStoredClaim() {
        val store = FakeStore(InstallClaim(id, key))
        val fresh = "f".repeat(43)
        NativeInstallDevice.accept(store, mapOf("device_id" to id, "key" to key),
            mapOf("install" to mapOf("device_id" to other, "key" to fresh)))
        assertEquals(other, store.stored!!.deviceId)
        assertEquals(fresh, store.stored!!.key)
    }

    @Test fun aReusedRowKeepsTheStoredClaim() {
        val store = FakeStore(InstallClaim(id, key))
        NativeInstallDevice.accept(store, mapOf("device_id" to id, "key" to key), mapOf("install" to mapOf("device_id" to id)))
        assertEquals(0, store.saves + store.clears)
    }

    @Test fun aDifferentRowWithoutAKeyClearsTheClaimItCanNoLongerProve() {
        val store = FakeStore(InstallClaim(id, key))
        NativeInstallDevice.accept(store, mapOf("device_id" to id, "key" to key), mapOf("install" to mapOf("device_id" to other)))
        assertNull(store.stored)
    }

    @Test fun anAnswerWithoutAnInstallOrWithMalformedValuesChangesNothing() {
        for (body in listOf<Any?>(
            mapOf("access_token" to "synthetic"),
            mapOf("install" to mapOf("device_id" to "not-a-uuid", "key" to key)),
            mapOf("install" to mapOf("device_id" to other, "key" to "short")),
            null,
        )) {
            val store = FakeStore(InstallClaim(id, key))
            NativeInstallDevice.accept(store, mapOf("device_id" to id, "key" to key), body)
            assertEquals(body.toString(), 0, store.saves + store.clears)
        }
    }

    @Test fun claimsNeverPrintTheirKey() {
        assertFalse(InstallClaim(id, key).toString().contains(key))
    }

    @Test fun signInSendsTheClaimAndSessionEndsLeaveItInPlace() {
        val session = File("src/main/java/io/github/jihoon22lee/sallimbook/auth/NativeAuthSession.kt").readText()
        // Password and passkey sign-in both present the claim and keep the answer.
        assertEquals(2, Regex("NativeInstallDevice\\.claim\\(").findAll(session).count())
        assertEquals(2, Regex("keepInstallDevice\\(").findAll(session).count() - 1)
        // Neither leaves the device key in its request body once the request is done.
        assertEquals(2, Regex("payload\\?\\.remove\\(\"install\"\\)").findAll(session).count())
        val drop = session.substringAfter("private fun dropSession(").substringBefore("\n    }")
        assertFalse(drop.contains("installDevices"))
        assertTrue(session.contains("InstallDeviceStore("))
    }
}
