package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class NativeOnboardingAttemptTest {
    private var clock = 0L
    private val attempt = NativeOnboardingAttempt { clock }
    private val lock = AppLockPolicy().also { it.resume(0, false) }
    private fun gate() = ForegroundRequest().also { it.bindAppLock(lock, lock.ticket(AppRequestKind.ONBOARDING)) { true } }
    private fun rejected(code: AuthCode = AuthCode.AUTH_CANCELLED, action: () -> Unit) {
        try { action(); fail("Stale onboarding completion accepted") } catch (failure: AuthFailure) { assertEquals(code, failure.code) }
    }
    @Test fun queueWaitCountsTowardTheExactSixtySecondDeadline() {
        clock = 59_999; attempt.check(); clock++
        rejected { attempt.check() }
    }
    @Test fun monotonicClockRollbackRejectsCompletion() { clock = -1; rejected { attempt.check() } }
    @Test fun cancelledBeforeInstallationCannotPersistOrUnlock() {
        val gate = gate(); gate.cancel()
        rejected { attempt.install(gate, { fail("saved") }, { fail("unlocked") }, { fail("unneeded rollback") }) }
        assertTrue(lock.locked)
    }
    @Test fun generationChangedAfterEarlierCheckCannotInstall() {
        val gate = gate(); gate.check(); lock.lock()
        rejected(AuthCode.APP_LOCKED) { attempt.install(gate, { fail("saved") }, { fail("unlocked") }, { fail("unneeded rollback") }) }
    }
    @Test fun durableSaveCrossingDeadlineRollsBackBeforeUnlock() {
        val gate = gate(); var persisted = false; var unlocked = false
        clock = 59_999
        rejected { attempt.install(gate, { persisted = true; clock++ }, { unlocked = true }, { persisted = false }) }
        assertFalse(persisted); assertFalse(unlocked); assertTrue(lock.locked)
    }
    @Test fun cancellationDuringSaveRollsBackAndCannotUnlock() {
        val gate = gate(); var persisted = false
        rejected { attempt.install(gate, { persisted = true; gate.cancel() }, { fail("unlocked") }, { persisted = false }) }
        assertFalse(persisted)
    }
    @Test fun failedDurableSaveCannotPublishAndStillCleansPartialState() {
        var rolledBack = false
        rejected(AuthCode.KEY_INVALIDATED) { attempt.install(gate(), { throw AuthFailure(AuthCode.KEY_INVALIDATED) },
            { fail("unlocked") }, { rolledBack = true }) }
        assertTrue(rolledBack)
    }
    @Test fun failedFinalUnlockRollsBackNewCredentials() {
        var persisted = false
        rejected(AuthCode.APP_LOCKED) { attempt.install(gate(), { persisted = true },
            { throw AuthFailure(AuthCode.APP_LOCKED) }, { persisted = false }) }
        assertFalse(persisted)
    }
    @Test fun deadlineCrossingDuringFinalUnlockRevokesTheNewLocalState() {
        val gate = gate(); var persisted = false; clock = 59_999
        rejected { attempt.install(gate, { persisted = true }, {
            assertTrue(lock.unlockAfterServerProof(gate) { true }); clock++
        }, { persisted = false; lock.lock() }) }
        assertFalse(persisted); assertTrue(lock.locked)
    }
    @Test fun lockGenerationChangingDuringUnlockRevokesTheNewLocalState() {
        val gate = gate(); var persisted = false
        rejected(AuthCode.APP_LOCKED) { attempt.install(gate, { persisted = true }, {
            assertTrue(lock.unlockAfterServerProof(gate) { true }); lock.lock()
        }, { persisted = false }) }
        assertFalse(persisted); assertTrue(lock.locked)
    }
    @Test fun onlyValidatedLiveCompletionPublishesAUsableSession() {
        val gate = gate(); var persisted = false
        attempt.install(gate, { persisted = true }, {
            assertTrue(persisted); assertTrue(lock.unlockAfterServerProof(gate) { true })
        }, { fail("unneeded rollback") })
        assertTrue(persisted); assertFalse(lock.locked)
    }
    @Test fun cleanupFailureCannotBeReportedAsSuccessfulOrOrdinaryCancellation() {
        rejected(AuthCode.KEY_INVALIDATED) { attempt.install(gate(), { clock = 60_000 },
            { fail("unlocked") }, { throw IllegalStateException() }) }
    }
}
