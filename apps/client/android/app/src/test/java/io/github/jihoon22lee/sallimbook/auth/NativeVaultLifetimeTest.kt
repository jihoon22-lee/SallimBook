package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class NativeVaultLifetimeTest {
    private var clock = 100L
    private val life = NativeVaultLifetime { clock }
    private fun foreground() { life.presentation(true, true, true, true) }
    private fun decrypted(): Long {
        foreground(); val id = life.beginPrompt()!!
        assertTrue(life.promptSucceeded(id)); assertTrue(life.claimCipher(id))
        assertTrue(life.finishCipher(id, true)); return id
    }
    @Test fun freshScreenAndMissingPresentationCannotStartWorkOrPrompt() {
        assertNull(life.beginWork()); assertNull(life.beginPrompt()); assertEquals(0L, life.displayRemaining())
        for (state in listOf(listOf(false,true,true,true),listOf(true,false,true,true),listOf(true,true,false,true),listOf(true,true,true,false))) {
            life.presentation(state[0],state[1],state[2],state[3]); assertNull(life.beginWork()); assertNull(life.beginPrompt())
        }
        foreground(); assertNotNull(life.beginWork())
    }
    @Test fun promptSuccessAloneCannotDisplayAndSameRequestClaimsOnlyOnce() {
        foreground(); val id = life.beginPrompt()!!
        assertNull(life.beginPrompt()); assertNull(life.beginWork()); assertFalse(life.finishCipher(id, true))
        assertTrue(life.promptSucceeded(id)); assertEquals(0L, life.displayRemaining())
        assertTrue(life.claimCipher(id)); assertFalse(life.claimCipher(id)); assertFalse(life.promptSucceeded(id))
        assertTrue(life.finishCipher(id, true)); assertFalse(life.finishCipher(id, true)); assertEquals(30_000L, life.displayRemaining())
    }
    @Test fun promptFocusLossIsAllowedButCipherNeedsTimelyFocusReturn() {
        foreground(); val id = life.beginPrompt()!!
        assertNull(life.presentation(true,false,true,true)); assertTrue(life.promptSucceeded(id)); assertFalse(life.claimCipher(id))
        clock += 999; foreground(); assertTrue(life.claimCipher(id)); assertTrue(life.finishCipher(id,false)); assertEquals(0L,life.displayRemaining())
        val expired = life.beginPrompt()!!; life.presentation(true,false,true,true); assertTrue(life.promptSucceeded(expired))
        clock += 1000; foreground(); assertFalse(life.claimCipher(expired)); assertEquals(0L,life.focusRemaining(expired))
    }
    @Test fun pauseLockOrAppLockCancelsPromptAndBlocksNewOneUntilTerminalCallback() {
        for (state in listOf(listOf(false,true,true,true),listOf(true,true,false,true),listOf(true,true,true,false))) {
            foreground(); val id=life.beginPrompt()!!
            assertEquals(id,life.presentation(state[0],state[1],state[2],state[3])); assertNull(life.lock())
            foreground(); assertNull(life.beginPrompt()); assertNull(life.beginWork())
            assertFalse(life.promptEnded(id+1)); assertFalse(life.promptSucceeded(id)); assertTrue(life.canBegin())
        }
    }
    @Test fun cancelledWorkerAndOldPromptCannotCompleteANewerRequest() {
        foreground(); val old=life.beginWork()!!; life.lock(); val current=life.beginWork()!!
        assertFalse(life.workActive(old)); assertFalse(life.finishWork(old,true)); assertTrue(life.workActive(current))
        assertTrue(life.finishWork(current,false)); val prompt=life.beginPrompt()!!
        life.lock(); assertTrue(life.promptEnded(prompt)); val next=life.beginPrompt()!!
        assertFalse(life.promptSucceeded(prompt)); assertFalse(life.promptEnded(prompt)); assertTrue(life.promptSucceeded(next))
    }
    @Test fun workerLosesValidityImmediatelyOnFocusLossAndCannotDisplayLateResult() {
        foreground(); val id=life.beginWork()!!
        life.presentation(true,false,true,true); foreground()
        assertFalse(life.workActive(id)); assertFalse(life.finishWork(id,true)); assertEquals(0L,life.displayRemaining())
    }
    @Test fun timeoutDetectedByPredicateStillDispatchesCancellationExactlyOnce() {
        foreground(); val id=life.beginPrompt()!!; clock += 60_000
        assertFalse(life.canBegin()); assertEquals(id,life.expire()); assertNull(life.expire())
        assertNull(life.beginWork()); assertTrue(life.promptEnded(id)); assertTrue(life.canBegin())
    }
    @Test fun displayExpiresAtThirtySecondsAndRepeatedReadsCannotExtendIt() {
        decrypted(); clock += 29_999; assertEquals(1L,life.displayRemaining()); assertEquals(1L,life.displayRemaining())
        clock += 1; assertEquals(0L,life.displayRemaining()); foreground(); assertEquals(0L,life.displayRemaining())
    }
    @Test fun leavingScreenOrClockRollbackClearsDisplayAndCryptoClaim() {
        decrypted(); life.presentation(true,false,true,true); foreground(); assertEquals(0L,life.displayRemaining())
        decrypted(); clock -= 1; assertEquals(0L,life.displayRemaining())
        val id=life.beginPrompt()!!; assertTrue(life.promptSucceeded(id)); assertTrue(life.claimCipher(id))
        life.presentation(false,false,true,true); foreground(); assertFalse(life.finishCipher(id,true))
    }
    @Test fun requestTimeoutAndClockRollbackDiscardWorkerResults() {
        foreground(); val first=life.beginWork()!!; clock += 60_000
        assertFalse(life.workActive(first)); assertFalse(life.finishWork(first,true))
        val second=life.beginWork()!!; clock -= 1; assertFalse(life.workActive(second))
    }
    @Test fun crossingFocusDeadlineBetweenChecksCannotAuthorizeCipherOrLeaveNegativeTime() {
        var time=100L
        val policy=NativeVaultLifetime { time++ }
        policy.presentation(true,true,true,true); val id=policy.beginPrompt()!!; assertTrue(policy.promptSucceeded(id))
        time += 999; assertFalse(policy.claimCipher(id)); assertEquals(0L,policy.focusRemaining(id)); assertTrue(policy.canBegin())
    }
    @Test fun deadlineBetweenWorkerPredicateAndFinalConsumptionCannotDeliverASecret() {
        foreground(); val id=life.beginWork()!!; clock+=59_999; assertTrue(life.workActive(id))
        clock++; var deliveries=0
        assertFalse(life.consumeWork(id,true,{ true }) { deliveries++ })
        assertEquals(0,deliveries); assertEquals(0L,life.displayRemaining())
    }
    @Test fun finalPresentationFailureCannotConsumeAndSuccessfulConsumptionIsSingleUse() {
        foreground(); var deliveries=0; val canceled=life.beginWork()!!
        assertFalse(life.consumeWork(canceled,true,{ false }) { deliveries++ }); assertEquals(0,deliveries); assertEquals(0L,life.displayRemaining())
        val current=life.beginWork()!!
        assertTrue(life.consumeWork(current,true,{ true }) { deliveries++ })
        assertFalse(life.consumeWork(current,true,{ true }) { deliveries++ }); assertEquals(1,deliveries)
    }
    @Test fun cryptoThatCrossesRequestDeadlineCannotPassPrecommitCheck() {
        foreground(); val id = life.beginPrompt()!!
        clock += 59_998
        assertTrue(life.promptSucceeded(id)); assertTrue(life.claimCipher(id))
        // Actual doFinal/AtomicFile.write can block after the initial claim. Check the
        // request again at commit, without extending the original request's deadline.
        clock++
        assertTrue(life.cipherActive(id))
        clock++
        assertFalse(life.cipherActive(id))
        assertFalse(life.finishCipher(id, true))
        assertEquals(0L, life.displayRemaining())
    }
    @Test fun staleCryptoCannotCommitAfterANewRequestClaimsTheCipherSlot() {
        foreground(); val old = life.beginPrompt()!!
        assertTrue(life.promptSucceeded(old)); assertTrue(life.claimCipher(old))
        life.lock()
        val current = life.beginPrompt()!!
        assertTrue(life.promptSucceeded(current)); assertTrue(life.claimCipher(current))
        assertFalse(life.cipherActive(old))
        assertTrue(life.cipherActive(current))
        assertTrue(life.finishCipher(current, false))
        assertFalse(life.cipherActive(current))
    }
    @Test fun precommitCheckRejectsPresentationLossAndCannotAuthorizePromptSuccessAlone() {
        foreground(); val unclaimed = life.beginPrompt()!!
        assertTrue(life.promptSucceeded(unclaimed)); assertFalse(life.cipherActive(unclaimed))
        assertTrue(life.claimCipher(unclaimed)); assertTrue(life.cipherActive(unclaimed))
        life.presentation(true, false, true, true); foreground()
        assertFalse(life.cipherActive(unclaimed)); assertFalse(life.finishCipher(unclaimed, false))
    }
}
