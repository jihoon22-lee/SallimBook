package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class PasskeyProviderLifecycleTest {
    private var now = 1_000L
    private fun provider(expiry: Long = 121_000L) = PasskeyPresentationPolicy({ now }, expiry).also { assertTrue(it.startProvider()) }

    @Test fun opaqueProviderMayPauseStopAndSaveWithoutDiscardingTheCurrentCeremony() {
        val policy = provider()
        repeat(3) { assertTrue(policy.keepPendingInBackground(true, true, true)); now += 10 }
        assertTrue(policy.awaitingProvider())
        assertTrue(policy.providerReturned())
        assertTrue(policy.claimVerification(true, true, true))
    }
    @Test fun foregroundLossStartsOneFixedSixtySecondDeadline() {
        val policy = provider()
        assertTrue(policy.keepPendingInBackground(true, true, true))
        assertEquals(60_000L, policy.remainingPresentationMillis())
        now = 60_999
        assertTrue(policy.keepPendingInBackground(true, true, true))
        assertEquals(1L, policy.remainingPresentationMillis())
        now = 61_000
        assertFalse(policy.keepPendingInBackground(true, true, true))
        assertFalse(policy.providerReturned())
    }
    @Test fun repeatedSaveAndStopCannotRefreshTheProviderDeadline() {
        val policy = provider()
        policy.keepPendingInBackground(true, true, true)
        for (time in listOf(20_000L, 40_000L, 60_000L)) {
            now = time
            assertTrue(policy.keepPendingInBackground(true, true, true))
            assertEquals(61_000L - now, policy.remainingPresentationMillis())
        }
        now = 61_001
        assertFalse(policy.providerWaitValid())
        assertFalse(policy.providerReturned())
    }
    @Test fun challengeExpiryWinsOverSixtySecondBackgroundAllowance() {
        val policy = provider(3_000)
        assertTrue(policy.keepPendingInBackground(true, true, true))
        assertEquals(2_000L, policy.remainingPresentationMillis())
        now = 3_000
        assertFalse(policy.providerReturned())
    }
    @Test fun aStoppedActivityWithoutExactProviderOwnershipCancels() {
        for ((owned, active, unlocked) in listOf(Triple(false, true, true), Triple(true, false, true), Triple(true, true, false))) {
            val policy = provider()
            assertFalse(policy.keepPendingInBackground(owned, active, unlocked))
            assertFalse(policy.providerReturned())
            assertFalse(policy.claimVerification(true, true, true))
        }
    }
    @Test fun callbacksAfterExplicitScreenOrAppLockCancellationCannotReviveTheCeremony() {
        val old = provider()
        old.keepPendingInBackground(true, true, true)
        old.cancel()
        assertFalse(old.keepPendingInBackground(true, true, true))
        assertFalse(old.providerReturned())
        assertFalse(old.claimVerification(true, true, true))
        val next = provider()
        assertTrue(next.providerReturned())
        assertTrue(next.claimVerification(true, true, true))
        assertFalse(old.providerReturned())
    }
    @Test fun stoppedProviderCallbackWaitsOnlyOneSecondForResumedFocusedUnlockedActivity() {
        val policy = provider()
        policy.keepPendingInBackground(true, true, true)
        now += 100
        assertTrue(policy.providerReturned())
        assertTrue(policy.keepPendingInBackground(false, true, true))
        assertFalse(policy.claimVerification(false, true, true))
        assertFalse(policy.claimVerification(true, false, true))
        assertFalse(policy.claimVerification(true, true, false))
        now += 999
        assertEquals(1L, policy.remainingPresentationMillis())
        assertTrue(policy.claimVerification(true, true, true))
        assertFalse(policy.claimVerification(true, true, true))
    }
    @Test fun responseWhileGenuinelyAwayIsDiscardedAtTheReturnDeadline() {
        val policy = provider()
        policy.keepPendingInBackground(true, true, true)
        assertTrue(policy.providerReturned())
        now += 1_000
        assertFalse(policy.keepPendingInBackground(false, true, true))
        assertFalse(policy.claimVerification(true, true, true))
    }
    @Test fun providerCannotKeepAnOptionsFetchOrServerVerificationAliveInBackground() {
        val fetched = PasskeyPresentationPolicy({ now }, 121_000)
        assertFalse(fetched.keepPendingInBackground(true, true, true))
        val verifying = provider()
        assertTrue(verifying.providerReturned())
        assertTrue(verifying.claimVerification(true, true, true))
        assertFalse(verifying.keepPendingInBackground(true, true, true))
    }
    @Test fun monotonicClockReversalFailsClosed() {
        val policy = provider()
        policy.keepPendingInBackground(true, true, true)
        now--
        assertFalse(policy.keepPendingInBackground(true, true, true))
        assertFalse(policy.providerReturned())
    }
    @Test fun onlyThePinnedNonexportedSameTaskTrampolineWithCurrentOwnershipIsPermitted() {
        val name = "androidx.credentials.playservices.controllers.identityauth.HiddenActivity"
        assertTrue(PasskeyProviderActivityPolicy.permits(name, false, true, true))
        assertFalse(PasskeyProviderActivityPolicy.permits(name, true, true, true))
        assertFalse(PasskeyProviderActivityPolicy.permits(name, false, false, true))
        assertFalse(PasskeyProviderActivityPolicy.permits(name, false, true, false))
        assertFalse(PasskeyProviderActivityPolicy.permits("synthetic.OtherActivity", false, true, true))
        assertFalse(PasskeyProviderActivityPolicy.permits("androidx.credentials.playservices.controllers.identitycredentials.IdentityCredentialApiHiddenActivity", false, true, true))
    }
    @Test fun trampolineAllowanceDoesNotUnlockOrAuthorizeProtectedRequests() {
        val policy = AppLockPolicy().also { it.resume(0, false) }
        val protected = policy.ticket(AppRequestKind.PROTECTED)
        assertTrue(PasskeyProviderActivityPolicy.permits("androidx.credentials.playservices.controllers.identityauth.HiddenActivity", false, true, true))
        assertTrue(policy.isLocked())
        assertFalse(policy.httpAllowed(protected, "GET", "/api/v1/accounts"))
        assertFalse(policy.httpAllowed(policy.ticket(AppRequestKind.LOGIN), "GET", "/api/v1/me"))
    }
}
