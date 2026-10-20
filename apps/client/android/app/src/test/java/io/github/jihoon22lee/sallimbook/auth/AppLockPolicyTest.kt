package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class AppLockPolicyTest {
    private fun unlocked(): AppLockPolicy = AppLockPolicy().also {
        it.resume(0, false)
        assertTrue(it.unlock(it.ticket(AppRequestKind.REAUTHENTICATE)))
    }
    private fun denied(action: () -> Unit) {
        try { action(); fail("A locked request was accepted") }
        catch (failure: AuthFailure) { assertEquals(AuthCode.APP_LOCKED, failure.code) }
    }
    @Test fun coldStartAndNewProcessNeverRestoreUnlockedState() {
        val old = unlocked()
        val restarted = AppLockPolicy().also { it.resume(10, false) }
        assertFalse(old.isLocked()); assertTrue(restarted.isLocked())
        assertFalse(restarted.allowed(restarted.ticket(AppRequestKind.PROTECTED)))
    }
    @Test fun backgroundBoundaryIsExactlySixtySeconds() {
        for (duration in listOf(59_999L, 60_000L, 60_001L)) {
            val policy = unlocked()
            policy.pause(); policy.background(100)
            policy.resume(100 + duration, false)
            assertEquals(duration >= 60_000L, policy.isLocked())
        }
    }
    @Test fun wallClockIsNotUsedAndInvalidMonotonicOrderFailsClosed() {
        val policy = unlocked()
        policy.pause(); policy.background(100); policy.resume(99, false)
        assertTrue(policy.isLocked())
    }
    @Test fun InternalActivityPauseWithoutExternalStopDoesNotStartBackgroundTimeout() {
        val policy = unlocked()
        policy.pause(); policy.resume(100_000, false)
        assertFalse(policy.isLocked())
    }
    @Test fun deviceLockAndManualLockInvalidateEveryOldAttempt() {
        for (screenLock in listOf(false, true)) {
            val policy = unlocked()
            val old = policy.ticket(AppRequestKind.REAUTHENTICATE)
            if (screenLock) policy.resume(1, true) else policy.lock()
            assertFalse(policy.unlock(old)); assertTrue(policy.isLocked())
        }
    }
    @Test fun elapsedBackgroundTimerLocksBeforeActivityReturns() {
        val policy = unlocked()
        policy.pause(); policy.background(20)
        assertFalse(policy.expire(60_019)); assertTrue(policy.expire(60_020))
        assertTrue(policy.isLocked())
    }
    @Test fun backgroundCannotConsumeServerOrOsAuthentication() {
        val policy = AppLockPolicy().also { it.resume(0, false) }
        val ticket = policy.ticket(AppRequestKind.REAUTHENTICATE)
        policy.pause()
        assertFalse(policy.unlock(ticket))
        assertFalse(policy.allowed(ticket))
    }
    @Test fun recoveryGrantsCannotFetchMetadataOrRevealNumbers() {
        val policy = AppLockPolicy().also { it.resume(0, false) }
        for (kind in AppRequestKind.entries) {
            val ticket = policy.ticket(kind)
            assertEquals(kind == AppRequestKind.ONBOARDING, policy.httpAllowed(ticket, "GET", "/api/v1/me"))
            assertFalse(policy.httpAllowed(ticket, "GET", "/api/v1/assets"))
            assertFalse(policy.httpAllowed(ticket, "POST", "/api/v1/accounts/00000000-0000-4000-8000-000000000001/reveal"))
        }
        assertTrue(policy.httpAllowed(policy.ticket(AppRequestKind.REAUTHENTICATE), "POST", "/api/v1/auth/native/refresh"))
        assertTrue(policy.httpAllowed(policy.ticket(AppRequestKind.REAUTHENTICATE), "POST", "/api/v1/auth/native/reauthenticate"))
        assertFalse(policy.httpAllowed(policy.ticket(AppRequestKind.REAUTHENTICATE), "POST", "/api/v1/auth/native/login"))
        assertTrue(policy.httpAllowed(policy.ticket(AppRequestKind.LOGIN), "POST", "/api/v1/auth/native/login"))
        assertFalse(policy.httpAllowed(policy.ticket(AppRequestKind.LOGIN), "POST", "/api/v1/auth/native/refresh"))
    }
    @Test fun invitationLogoutAndProtectedTicketsNeverUnlock() {
        val policy = AppLockPolicy().also { it.resume(0, false) }
        for (kind in listOf(AppRequestKind.INVITATION, AppRequestKind.LOGOUT, AppRequestKind.PROTECTED, AppRequestKind.SETUP_STATUS))
            assertFalse(policy.unlock(policy.ticket(kind)))
    }
    @Test fun queuedRequestKeepsCreationGenerationAcrossLockAndUnlock() {
        val policy = unlocked()
        val gate = ForegroundRequest()
        gate.captureAppLock(policy, policy.ticket(AppRequestKind.PROTECTED)) { true }
        policy.lock(); policy.unlock(policy.ticket(AppRequestKind.REAUTHENTICATE))
        denied { gate.bindAppLock(policy, policy.ticket(AppRequestKind.PROTECTED)) { true } }
        denied { gate.check() }
    }
    @Test fun boundRequestCannotChangeItsRecoveryScope() {
        val policy = AppLockPolicy().also { it.resume(0, false) }
        val gate = ForegroundRequest()
        gate.bindAppLock(policy, policy.ticket(AppRequestKind.INVITATION)) { true }
        gate.checkHttp("POST", "/api/v1/auth/invitations/accept")
        denied { gate.bindAppLock(policy, policy.ticket(AppRequestKind.REAUTHENTICATE)) { true } }
        denied { gate.checkHttp("GET", "/api/v1/accounts") }
    }
    @Test fun transportRejectsUnboundAndDeviceLockedRequests() {
        denied { ForegroundRequest().checkHttp("GET", "/api/v1/me") }
        val policy = unlocked(); val gate = ForegroundRequest()
        gate.bindAppLock(policy, policy.ticket(AppRequestKind.PROTECTED)) { false }
        denied { gate.checkHttp("GET", "/api/v1/me") }
    }
    @Test fun replyPublicationRechecksGenerationEvenAfterAnEarlierSuccessfulCheck() {
        val policy = unlocked(); val gate = ForegroundRequest()
        gate.bindAppLock(policy, policy.ticket(AppRequestKind.PROTECTED)) { true }
        gate.checkHttp("GET", "/api/v1/accounts")
        policy.lock(); policy.unlock(policy.ticket(AppRequestKind.REAUTHENTICATE))
        denied { gate.whileActive { fail("Stale callback published metadata") } }
    }
    @Test fun cancelledServerProofCannotUnlockAfterAQuickPauseAndResume() {
        val policy = AppLockPolicy().also { it.resume(0, false) }
        val gate = ForegroundRequest()
        gate.bindAppLock(policy, policy.ticket(AppRequestKind.REAUTHENTICATE)) { true }
        gate.check() // HTTP succeeded; cancellation wins before final proof consumption.
        policy.pause(); gate.cancel(); policy.resume(10, false)
        try {
            policy.unlockAfterServerProof(gate) { true }
            fail("A cancelled server authentication unlocked the screen")
        } catch (failure: AuthFailure) { assertEquals(AuthCode.AUTH_CANCELLED, failure.code) }
        assertTrue(policy.isLocked())
    }
    @Test fun setupAvailabilityTicketCannotEnrollAuthenticateRefreshOrUnlock() {
        val policy = AppLockPolicy().also { it.resume(0, false) }; val ticket = policy.ticket(AppRequestKind.SETUP_STATUS)
        assertTrue(policy.httpAllowed(ticket, "GET", NativeOnboardingPolicy.STATUS_PATH))
        for (path in listOf(NativeOnboardingPolicy.SETUP_PATH, NativeOnboardingPolicy.CONNECT_PATH,
            NativeOnboardingPolicy.CODE_PATH, "/api/v1/auth/native/login", "/api/v1/auth/native/refresh"))
            assertFalse(policy.httpAllowed(ticket, "POST", path))
        assertFalse(policy.unlock(ticket))
    }
    @Test fun onboardingTicketCanOnlyEnrollAndVerifyItsNewMeBeforeRealServerUnlock() {
        val policy = AppLockPolicy().also { it.resume(0, false) }; val ticket = policy.ticket(AppRequestKind.ONBOARDING)
        assertTrue(policy.httpAllowed(ticket, "POST", NativeOnboardingPolicy.SETUP_PATH))
        assertTrue(policy.httpAllowed(ticket, "POST", NativeOnboardingPolicy.CONNECT_PATH))
        assertTrue(policy.httpAllowed(ticket, "GET", "/api/v1/me"))
        for (path in listOf(NativeOnboardingPolicy.CODE_PATH, "/api/v1/auth/native/refresh", "/api/v1/auth/native/login"))
            assertFalse(policy.httpAllowed(ticket, "POST", path))
        assertFalse(policy.httpAllowed(ticket, "GET", "/api/v1/household/members"))
        policy.pause(); assertFalse(policy.unlock(ticket))
    }

    @Test fun onlyUnlockedProtectedRequestsCanChangeThePasswordOrSignOutOthers() {
        val policy = AppLockPolicy().also { it.resume(0, false) }
        for (kind in AppRequestKind.entries.filter { it != AppRequestKind.PROTECTED }) {
            for (path in listOf("/api/v1/auth/password", "/api/v1/devices/revoke-others")) {
                assertFalse(policy.httpAllowed(policy.ticket(kind), "POST", path))
            }
        }
    }
}
