package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test
import java.security.InvalidKeyException
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.spec.GCMParameterSpec

class NativeVaultKeyPreparationTest {
    @Test fun canceledOrFailedPromptKeepsExistingKeyAndBothKindsOfRecordReadable() {
        for (size in listOf(32, 3, 4)) {
            val key=KeyGenerator.getInstance("AES").apply { init(256) }.generateKey()
            val plaintext=ByteArray(size) { 52 }
            val old=Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE,key) }
            val record=old.doFinal(plaintext); val nonce=old.iv.clone()
            var creates=0
            repeat(2) {
                val prepared=NativeVaultKeyPreparation.encryption(existing={ key },create={ creates++; error("Existing key replaced") },
                    initialize={ selected -> assertSame(key,selected); Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE,selected) } })
                assertFalse(nonce.contentEquals(prepared.iv))
                val operation=NativeVaultKeyOperation(prepared,NativeVaultBinding(NativeVaultTestData.snapshot().scope!!),true,null)
                // Both cancellation and terminal prompt failure discard preparation without doFinal/commit.
                operation.discard(); assertTrue(operation.consumed.get())
                val reader=Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE,key,GCMParameterSpec(128,nonce)) }
                assertArrayEquals(plaintext,reader.doFinal(record))
            }
            assertEquals(0,creates)
        }
    }
    @Test fun transientExistingKeyReadOrCipherFailureNeverCreatesReplacement() {
        var creates=0
        for (readFails in listOf(true,false)) {
            try {
                NativeVaultKeyPreparation.encryption(existing={ if(readFails) throw InvalidKeyException("synthetic transient read"); "existing" },
                    create={ creates++; "replacement" },initialize={ throw InvalidKeyException("synthetic transient cipher") })
                fail("Transient failure accepted")
            } catch (_:InvalidKeyException) { }
        }
        assertEquals(0,creates)
    }
    @Test fun absentKeyIsCreatedOnceAndInitializedWithoutAnExistingRecord() {
        var creates=0
        val selected=NativeVaultKeyPreparation.encryption(existing={ null as String? },create={ creates++; "new" },initialize={ it })
        assertEquals("new",selected); assertEquals(1,creates)
    }
    @Test fun resetRequiresSeparateConfirmationBeforeEvenCheckingInvalidation() {
        var probed=false; var removed=false
        try { NativeVaultKeyPreparation.clearInvalidated(false,{ probed=true; true },{ removed=true }); fail("Unconfirmed reset") }
        catch (_:NativeVaultFailure) { }
        assertFalse(probed); assertFalse(removed)
    }
    @Test fun healthyOrTransientlyUnavailableKeyCannotBeReset() {
        var removed=false
        try { NativeVaultKeyPreparation.clearInvalidated(true,{ false },{ removed=true }); fail("Healthy reset") }
        catch (_:NativeVaultFailure) { }
        try { NativeVaultKeyPreparation.clearInvalidated(true,{ throw InvalidKeyException("synthetic transient") },{ removed=true }); fail("Transient reset") }
        catch (_:InvalidKeyException) { }
        assertFalse(removed)
    }
    @Test fun positivelyIdentifiedPermanentInvalidationCanBeExplicitlyReset() {
        var removals=0
        NativeVaultKeyPreparation.clearInvalidated(true,{ true },{ removals++ })
        assertEquals(1,removals)
    }
}
