package io.github.jihoon22lee.sallimbook

import android.content.Intent
import android.hardware.biometrics.BiometricManager
import android.os.SystemClock
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import io.github.jihoon22lee.sallimbook.auth.NativeVaultAcceptanceGate
import io.github.jihoon22lee.sallimbook.auth.NativeVaultBinding
import io.github.jihoon22lee.sallimbook.auth.NativeVaultFailure
import io.github.jihoon22lee.sallimbook.auth.NativeVaultStore
import io.github.jihoon22lee.sallimbook.debugproof.CvcAcceptanceActivity
import io.github.jihoon22lee.sallimbook.debugproof.CvcAcceptanceFixtures
import java.io.File
import java.security.KeyStore
import org.junit.Assert.*
import org.junit.Assume.assumeFalse
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith

/** Device-only negative/gate tests. Successful biometric prompts and AtomicFile replacement
 * must still be exercised by a person in CvcAcceptanceActivity; APK assembly is not execution.
 * All mutable artifacts use synthetic namespaces. No network, account, bridge or real secret.
 */
@RunWith(AndroidJUnit4::class)
class NativeVaultCvcAcceptanceTest {
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext
    private val binding get() = CvcAcceptanceFixtures.binding(context)
    private fun rejected(action: () -> Unit) {
        try { action(); fail("Expected closed CVC gate") }
        catch (failure: NativeVaultFailure) { assertEquals("CVC_GATE_CLOSED", failure.code) }
    }
    @Test fun normalStoreCannotActivateLocalCvc() {
        assertFalse(NativeVaultStore.LOCAL_CVC_ACCEPTANCE_VERIFIED)
        rejected { NativeVaultStore.get(context).prepareEncryption(binding) }
        rejected { NativeVaultStore.get(context).prepareDecryption(binding) }
    }
    @Test fun syntheticStoreStartsClosedWithoutActivityOwner() {
        val store = NativeVaultStore(context, CvcAcceptanceFixtures.NAMESPACE)
        rejected { store.prepareEncryption(binding) }
        rejected { store.prepareDecryption(binding) }
    }
    private fun findButton(view: View, label: String): Button? {
        if (view is Button && view.text == label) return view
        if (view is ViewGroup) for (index in 0 until view.childCount) {
            findButton(view.getChildAt(index), label)?.let { return it }
        }
        return null
    }
    private fun withOwner(action: (CvcAcceptanceActivity) -> Unit) {
        val activity = instrumentation.startActivitySync(Intent(context, CvcAcceptanceActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) as CvcAcceptanceActivity
        try {
            val deadline = SystemClock.elapsedRealtime() + 4_000L
            var presented = false
            while (!presented && SystemClock.elapsedRealtime() < deadline) {
                instrumentation.runOnMainSync { presented = activity.syntheticOwnerPresented() }
                if (!presented) SystemClock.sleep(50)
            }
            assertTrue("Requires an unlocked foreground test device", presented)
            instrumentation.runOnMainSync {
                val button = findButton(activity.window.decorView, "합성 세션 시작")
                assertNotNull(button)
                button!!.performClick()
                assertTrue(NativeVaultAcceptanceGate.active(activity))
                action(activity)
            }
        } finally {
            instrumentation.runOnMainSync { activity.finish() }
            instrumentation.waitForIdleSync()
        }
    }
    @Test fun activeOwnerAllowsOnlyExactSyntheticBindingAndNamespace() = withOwner {
        assertTrue(NativeVaultAcceptanceGate.allows(context, binding, CvcAcceptanceFixtures.NAMESPACE))
        assertFalse(NativeVaultAcceptanceGate.allows(context, binding, "vault.v1"))
        val otherCard = NativeVaultBinding(binding.scope, "20000000-0000-4000-8000-000000000005", binding.envelopeId, binding.revision)
        assertFalse(NativeVaultAcceptanceGate.allows(context, otherCard, CvcAcceptanceFixtures.NAMESPACE))
        rejected { NativeVaultStore.get(context).prepareEncryption(binding) }
    }
    @Test fun endingOwnerImmediatelyClosesSyntheticGate() = withOwner { activity ->
        NativeVaultAcceptanceGate.end(activity)
        rejected { NativeVaultStore(context, CvcAcceptanceFixtures.NAMESPACE).prepareEncryption(binding) }
        assertFalse(NativeVaultAcceptanceGate.armSyntheticCvcWriteFailure(activity))
    }
    @Test fun ownerFlagCannotUseKeystoreCipherWithoutActualBiometricAuthorization() {
        assumeTrue(context.getSystemService(BiometricManager::class.java)
            .canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_STRONG) == BiometricManager.BIOMETRIC_SUCCESS)
        val store = NativeVaultStore(context, CvcAcceptanceFixtures.NAMESPACE)
        // Preserve any earlier manually created acceptance record. Explicit reset is required
        // before this negative test; never erase a pre-existing proof to make a test pass.
        assumeFalse(store.exists(binding))
        val aliases = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }.aliases().toList()
        assumeFalse(aliases.any { it.startsWith(context.packageName + "." + CvcAcceptanceFixtures.NAMESPACE + ".") })
        withOwner {
            val operation = store.prepareEncryption(binding)
            val value = CvcAcceptanceFixtures.value(false)
            try {
                try { store.finish(operation, operation.cipher, value); fail("Unauthenticated Cipher must not write") }
                catch (_: NativeVaultFailure) { /* Android Keystore rejects doFinal without prompt authorization. */ }
                assertFalse(store.exists(binding))
            } finally { value.fill(0); operation.discard(); store.clearAll() }
        }
    }
    @Test fun clearingOneSyntheticNamespacePreservesAnother() {
        val names = listOf("instrumentation-cvc-isolation-a", "instrumentation-cvc-isolation-b")
        val stores = names.map { NativeVaultStore(context, it) }
        val files = names.map { File(context.noBackupFilesDir, "sallimbook-$it/synthetic.bin") }
        try {
            files.forEach { it.parentFile!!.mkdirs(); it.writeBytes(byteArrayOf(1, 2, 3)) }
            stores[0].clearAll()
            assertFalse(files[0].exists())
            assertArrayEquals(byteArrayOf(1, 2, 3), files[1].readBytes())
        } finally { stores.forEach { it.clearAll() }; files.forEach { it.parentFile!!.delete() } }
    }
    @Test fun namespaceCannotEscapeNoBackupDirectory() {
        for (name in listOf("../vault.v1", "", "/vault.v1", "vault/v1")) {
            try { NativeVaultStore(context, name); fail("Invalid namespace") }
            catch (failure: NativeVaultFailure) { assertEquals("ACCESS_DENIED", failure.code) }
        }
    }
}
