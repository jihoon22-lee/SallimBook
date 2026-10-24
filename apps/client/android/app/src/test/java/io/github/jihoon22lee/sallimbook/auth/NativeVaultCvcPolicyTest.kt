package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class NativeVaultCvcPolicyTest {
    @Test fun onlyOrdinaryNamespaceIsAvailableWithoutSyntheticOwner() {
        assertTrue(NativeVaultCvcPolicy.available("vault.v1"))
        for (name in listOf("", "vault.v2", "VAULT.v1", "vault.v1.", "cvc-acceptance-v1"))
            assertFalse(NativeVaultCvcPolicy.available(name))
    }
    @Test fun consentIsRequiredAndRejectedInputIsWiped() {
        val chars=charArrayOf('1','2','3')
        try { NativeVaultCvcPolicy.input(false,chars); fail("Consent required") }
        catch (failure:NativeVaultFailure) { assertEquals("CVC_CONSENT_REQUIRED",failure.code) }
        assertTrue(chars.all { it=='\u0000' })
    }
    @Test fun onlyThreeOrFourAsciiDigitsAreAcceptedAndInputsAreWiped() {
        for (size in 3..4) {
            val chars=CharArray(size) { '1' }; val bytes=NativeVaultCvcPolicy.input(true,chars)
            try { assertEquals(size,bytes.size); assertTrue(bytes.all { it==49.toByte() }); assertTrue(chars.all { it=='\u0000' }) }
            finally { bytes.fill(0) }
        }
        for (value in listOf("", "12", "12345", "1 3", "１２３", "1a3", "12\n")) {
            val chars=value.toCharArray()
            try { NativeVaultCvcPolicy.input(true,chars); fail("Invalid format") }
            catch (failure:NativeVaultFailure) { assertEquals("INVALID_FORMAT",failure.code) }
            assertTrue(chars.all { it=='\u0000' })
        }
    }
}
