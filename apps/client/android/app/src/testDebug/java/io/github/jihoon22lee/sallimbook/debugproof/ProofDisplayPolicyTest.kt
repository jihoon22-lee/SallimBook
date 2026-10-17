package io.github.jihoon22lee.sallimbook.debugproof

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test

/** Policy event ordering only. No fake Activity, biometric result or Keystore success is asserted. */
class ProofDisplayPolicyTest {
    private var elapsed = 1_000L
    private val policy = ProofDisplayPolicy { elapsed }

    @Before fun presentForegroundWindow() {
        policy.updatePresentation(resumed = true, focused = true, unlocked = true)
    }

    private fun readyCipher(): Long {
        val request = policy.beginRequest()!!
        assertTrue(policy.authenticationSucceeded(request))
        assertTrue(policy.claimCipherForUse(request))
        return request
    }

    @Test fun encryptionCompletionDoesNotGrantDisplay() {
        val request = readyCipher()
        assertTrue(policy.finishEncryption(request))
        assertEquals(0L, policy.remainingDisplayMillis())
        assertFalse(policy.showAfterDecryption(request))
    }

    @Test fun separateRequestsAreRequiredForEncryptionAndDecryption() {
        val encrypt = readyCipher()
        assertTrue(policy.finishEncryption(encrypt))
        val decrypt = readyCipher()
        assertNotEquals(encrypt, decrypt)
        assertFalse(policy.showAfterDecryption(encrypt))
        assertTrue(policy.showAfterDecryption(decrypt))
    }

    @Test fun displayExpiresAtExactlyThirtyMonotonicSeconds() {
        assertTrue(policy.showAfterDecryption(readyCipher()))
        assertEquals(30_000L, policy.remainingDisplayMillis())
        elapsed += 29_999
        assertEquals(1L, policy.remainingDisplayMillis())
        elapsed += 1
        assertEquals(0L, policy.remainingDisplayMillis())
    }

    @Test fun repeatedChecksCannotExtendDisplayWindow() {
        assertTrue(policy.showAfterDecryption(readyCipher()))
        repeat(30) { elapsed += 1_000; policy.remainingDisplayMillis() }
        assertEquals(0L, policy.remainingDisplayMillis())
    }

    @Test fun pendingRequestsCannotBeReplacedByRepeatedTaps() {
        val request = policy.beginRequest()!!
        assertNull(policy.beginRequest())
        assertTrue(policy.isAuthenticating(request))
    }

    @Test fun visibilityRequiresAnExplicitLockBeforeAnotherRequest() {
        assertTrue(policy.showAfterDecryption(readyCipher()))
        assertNull(policy.beginRequest())
        policy.lock()
        assertTrue(policy.beginRequest() != null)
    }

    @Test fun lockRetainsThePromptSlotUntilItsCancellationCompletes() {
        val oldRequest = policy.beginRequest()!!
        assertEquals(oldRequest, policy.lock())
        assertNull(policy.lock())
        assertNull(policy.beginRequest())
        assertFalse(policy.canAcceptAction())
        assertTrue(policy.authenticationEnded(oldRequest))
        assertTrue(policy.canAcceptAction())
    }

    @Test fun lateCancelForRetiredRequestCannotEndTheNextRequest() {
        val oldRequest = policy.beginRequest()!!
        policy.lock()
        assertNull(policy.beginRequest())
        assertTrue(policy.authenticationEnded(oldRequest))
        val nextRequest = policy.beginRequest()!!
        assertFalse(policy.authenticationEnded(oldRequest))
        assertTrue(policy.isAuthenticating(nextRequest))
    }

    @Test fun successAfterCancellationOnlyReleasesTheSlotWithoutUsingOrDisplaying() {
        val request = policy.beginRequest()!!
        policy.lock()
        assertFalse(policy.authenticationSucceeded(request))
        assertFalse(policy.claimCipherForUse(request))
        assertFalse(policy.showAfterDecryption(request))
        assertEquals(0L, policy.remainingDisplayMillis())
        assertTrue(policy.canAcceptAction())
    }

    @Test fun focusLostBeforeSuccessPreventsCipherUseAndDisplay() {
        val request = policy.beginRequest()!!
        policy.updatePresentation(resumed = true, focused = false, unlocked = true)
        assertTrue(policy.authenticationSucceeded(request))
        assertFalse(policy.claimCipherForUse(request))
        assertFalse(policy.showAfterDecryption(request))
        assertEquals(0L, policy.remainingDisplayMillis())
    }

    @Test fun promptFocusCanSettleBeforeAnyCipherUseWithinTheBoundedWindow() {
        val request = policy.beginRequest()!!
        policy.updatePresentation(resumed = true, focused = false, unlocked = true)
        assertTrue(policy.authenticationSucceeded(request))
        elapsed += 100
        policy.updatePresentation(resumed = true, focused = true, unlocked = true)
        assertTrue(policy.claimCipherForUse(request))
        assertTrue(policy.showAfterDecryption(request))
    }

    @Test fun expiredFocusWaitCannotDecryptOnALaterFocusReturn() {
        val request = policy.beginRequest()!!
        policy.updatePresentation(resumed = true, focused = false, unlocked = true)
        assertTrue(policy.authenticationSucceeded(request))
        elapsed += ProofDisplayPolicy.MAX_FOCUS_SETTLE_MILLIS
        policy.updatePresentation(resumed = true, focused = true, unlocked = true)
        assertFalse(policy.claimCipherForUse(request))
        assertFalse(policy.showAfterDecryption(request))
        assertTrue(policy.canAcceptAction())
    }

    @Test fun focusLossBetweenCipherUseAndPresentationRejectsDisplay() {
        val request = readyCipher()
        policy.updatePresentation(resumed = true, focused = false, unlocked = true)
        assertFalse(policy.showAfterDecryption(request))
        assertEquals(0L, policy.remainingDisplayMillis())
    }

    @Test fun visibleTextCannotResumeAfterFocusLoss() {
        assertTrue(policy.showAfterDecryption(readyCipher()))
        policy.updatePresentation(resumed = true, focused = false, unlocked = true)
        assertEquals(0L, policy.remainingDisplayMillis())
        policy.updatePresentation(resumed = true, focused = true, unlocked = true)
        assertEquals(0L, policy.remainingDisplayMillis())
    }

    @Test fun pauseWhileWaitingForPromptFocusDiscardsTheAuthenticatedCipher() {
        val request = policy.beginRequest()!!
        assertTrue(policy.authenticationSucceeded(request))
        policy.updatePresentation(resumed = false, focused = false, unlocked = true)
        policy.updatePresentation(resumed = true, focused = true, unlocked = true)
        assertFalse(policy.claimCipherForUse(request))
        assertFalse(policy.showAfterDecryption(request))
    }

    @Test fun deviceLockCancelsPendingAuthenticationAndKeepsSlotOccupied() {
        val request = policy.beginRequest()!!
        assertEquals(request, policy.updatePresentation(resumed = true, focused = false, unlocked = false))
        policy.updatePresentation(resumed = true, focused = true, unlocked = true)
        assertNull(policy.beginRequest())
        assertFalse(policy.authenticationSucceeded(request))
        assertTrue(policy.canAcceptAction())
    }

    @Test fun recreatedPolicyStartsUnfocusedAndLocked() {
        val oldRequest = policy.beginRequest()!!
        val recreated = ProofDisplayPolicy { elapsed }
        assertNull(recreated.beginRequest())
        assertFalse(recreated.authenticationSucceeded(oldRequest))
        assertEquals(0L, recreated.remainingDisplayMillis())
    }

    @Test fun unexpectedMonotonicRegressionFailsClosed() {
        assertTrue(policy.showAfterDecryption(readyCipher()))
        elapsed -= 1
        assertEquals(0L, policy.remainingDisplayMillis())
        elapsed += 1
        assertEquals(0L, policy.remainingDisplayMillis())
    }
}
