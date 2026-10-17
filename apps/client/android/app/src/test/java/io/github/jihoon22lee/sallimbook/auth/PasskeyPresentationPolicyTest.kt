package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class PasskeyPresentationPolicyTest {
    @Test fun providerMayOwnPresentationButVerificationNeedsResumedFocusedUnlockedActivity() {
        var now = 100L
        val policy = PasskeyPresentationPolicy({ now }, 10_000)
        assertTrue(policy.startProvider())
        assertTrue(policy.awaitingProvider())
        assertTrue(policy.mayWaitForPresentation())
        assertTrue(policy.providerReturned())
        assertFalse(policy.claimVerification(false, true, true))
        assertFalse(policy.claimVerification(true, false, true))
        assertFalse(policy.claimVerification(true, true, false))
        now += 999
        assertTrue(policy.claimVerification(true, true, true))
        assertFalse(policy.claimVerification(true, true, true))
        assertFalse(policy.mayWaitForPresentation())
    }

    @Test fun focusReturnHasAnExactOneSecondLimitAndDoesNotExtendChallengeExpiry() {
        for (expiry in listOf(1_100L, 1_000L)) {
            var now = 100L
            val policy = PasskeyPresentationPolicy({ now }, expiry)
            assertTrue(policy.startProvider())
            assertTrue(policy.providerReturned())
            now = expiry
            assertFalse(policy.canWait())
            assertFalse(policy.claimVerification(true, true, true))
        }
    }

    @Test fun cancellationAndExpiredProviderCallbacksCannotRestorePermissionToVerify() {
        var now = 100L
        val cancelled = PasskeyPresentationPolicy({ now }, 1_000)
        assertTrue(cancelled.startProvider())
        cancelled.cancel()
        assertFalse(cancelled.providerReturned())
        assertFalse(cancelled.claimVerification(true, true, true))
        val expired = PasskeyPresentationPolicy({ now }, 1_000)
        assertTrue(expired.startProvider())
        now = 1_000
        assertFalse(expired.providerReturned())
        assertFalse(expired.claimVerification(true, true, true))
    }

    @Test fun duplicateProviderResultsAndMonotonicClockRollbackFailClosed() {
        var now = 100L
        val policy = PasskeyPresentationPolicy({ now }, 1_000)
        assertTrue(policy.startProvider())
        assertTrue(policy.providerReturned())
        assertFalse(policy.providerReturned())
        assertFalse(policy.claimVerification(true, true, true))
        val rollback = PasskeyPresentationPolicy({ now }, 1_000)
        assertTrue(rollback.startProvider())
        assertTrue(rollback.providerReturned())
        now = 99
        assertFalse(rollback.claimVerification(true, true, true))
    }
}
