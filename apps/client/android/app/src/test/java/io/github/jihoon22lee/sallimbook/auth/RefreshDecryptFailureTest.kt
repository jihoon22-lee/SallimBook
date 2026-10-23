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

    @Test fun theUnlockedDeviceRequirementFollowsTheVaultFromSdk35() {
        val source = java.io.File("src/main/java/io/github/jihoon22lee/sallimbook/auth/RefreshStore.kt").readText()
        assertTrue(source.contains(".apply { if (Build.VERSION.SDK_INT >= 35) setUnlockedDeviceRequired(true) }"))
        assertFalse(source.contains("            .setUnlockedDeviceRequired(true)"))
    }
}
