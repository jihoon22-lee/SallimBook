package io.github.jihoon22lee.sallimbook.auth

import java.io.IOException
import java.security.KeyStoreException
import java.security.ProviderException
import javax.crypto.AEADBadTagException
import javax.crypto.IllegalBlockSizeException
import org.junit.Assert.*
import org.junit.Test

class RefreshDecryptFailureTest {
    @Test fun aTransientExceptionKeepsTheStoredToken() {
        // A locked keystore or a vendor glitch after face unlock must not log the user out for good.
        for (failure in listOf(ProviderException("synthetic"), KeyStoreException("synthetic"),
            IllegalBlockSizeException("synthetic"), IOException("synthetic"), IllegalStateException("synthetic"))) {
            assertFalse(failure.javaClass.simpleName, RefreshDecryptFailure.permanent(failure))
        }
    }

    @Test fun aPermanentInvalidationClearsIt() {
        assertTrue(RefreshDecryptFailure.permanent(AEADBadTagException("synthetic")))
        assertTrue(RefreshDecryptFailure.permanent(AuthFailure(AuthCode.KEY_INVALIDATED)))
        // KeyPermanentlyInvalidatedException is an Android stub on the JVM; pin the check in source.
        val source = java.io.File("src/main/java/io/github/jihoon22lee/sallimbook/auth/RefreshStore.kt").readText()
        assertTrue(source.contains("failure is KeyPermanentlyInvalidatedException"))
    }

    @Test fun readForRotationClearsOnlyOnAPermanentFailure() {
        val source = java.io.File("src/main/java/io/github/jihoon22lee/sallimbook/auth/RefreshStore.kt").readText()
        val read = source.substringAfter("override fun readForRotation()").substringBefore("override fun consume()")
        val handler = read.substringAfter("} catch (failure: Exception) {").substringBefore("} finally {")
        assertTrue(handler, handler.contains("if (!RefreshDecryptFailure.permanent(failure)) throw AuthFailure(AuthCode.AUTH_UNAVAILABLE)"))
        assertTrue(handler, handler.indexOf("permanent(failure)") < handler.indexOf("clear()"))
    }

    @Test fun anEnvelopeNamesTheKeyThatSealedIt() {
        // Keys made before 0.1.7 require an unlocked device on every SDK; their envelopes stay
        // readable until the next save moves the token to the current key.
        assertEquals(RefreshEnvelope.LEGACY, RefreshEnvelope.keyVersion(1))
        assertEquals(RefreshEnvelope.CURRENT, RefreshEnvelope.keyVersion(2))
        assertNull(RefreshEnvelope.keyVersion(0))
        assertNull(RefreshEnvelope.keyVersion(3))
    }

    @Test fun savingMovesAnOldInstallToTheCurrentKey() {
        val source = java.io.File("src/main/java/io/github/jihoon22lee/sallimbook/auth/RefreshStore.kt").readText()
        assertTrue(source.contains("app.packageName + \".auth.refresh.v2\""))
        val save = source.substringAfter("override fun save(").substringBefore("override fun readForRotation()")
        assertTrue(save.contains(".put(RefreshEnvelope.CURRENT)"))
        // The old key goes only once the envelope under the current key is committed.
        val committed = save.indexOf("file.finishWrite(output)")
        assertTrue(committed >= 0 && committed < save.indexOf("keyStore.deleteEntry(legacyAlias)"))
        val read = source.substringAfter("override fun readForRotation()").substringBefore("override fun consume()")
        assertTrue(read.contains("key(create = false, RefreshEnvelope.keyVersion(envelope[0]) ?: throw AuthFailure(AuthCode.KEY_INVALIDATED))"))
        val clear = source.substringAfter("fun clear()")
        assertTrue(clear.contains("gone(alias)") && clear.contains("gone(legacyAlias)"))
    }

    @Test fun theUnlockedDeviceRequirementFollowsTheVaultFromSdk35() {
        val source = java.io.File("src/main/java/io/github/jihoon22lee/sallimbook/auth/RefreshStore.kt").readText()
        assertTrue(source.contains(".apply { if (Build.VERSION.SDK_INT >= 35) setUnlockedDeviceRequired(true) }"))
        assertFalse(source.contains("            .setUnlockedDeviceRequired(true)"))
    }
}
