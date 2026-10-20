package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class NativeRefreshRotationTest {
    private val old = "synthetic_refresh_old_000000000000000000001"
    private val new = "synthetic_refresh_new_000000000000000000001"
    private val rotated = mapOf("access_token" to "synthetic_access_new_0000000000000000000001", "refresh_token" to new,
        "token_type" to "Bearer", "expires_in" to 600, "refresh_expires_at" to "2026-11-18T00:00:00Z")
    private open class Store(var stored: String?) : RefreshTokenStore {
        val saved = mutableListOf<String>(); var consumed = false
        override fun readForRotation() = stored
        override fun consume() { consumed = true; stored = null }
        override fun save(refresh: String) { saved += refresh; stored = refresh }
    }
    private val events = mutableListOf<String>()
    private fun gate(): ForegroundRequest { // NativeRefreshExchangeTest.gate()와 같다
        val policy = AppLockPolicy(); policy.resume(0, false); assertTrue(policy.unlock(policy.ticket(AppRequestKind.REAUTHENTICATE)))
        return ForegroundRequest().also { it.bindAppLock(policy, policy.ticket(AppRequestKind.PROTECTED)) { true } }
    }
    private fun rotation(store: RefreshTokenStore, exchange: (String, ForegroundRequest, () -> Unit) -> NativeHttpResponse) =
        NativeRefreshRotation(store, exchange, { events += "install:${it.expiresIn}" }, { events += "rejected" }) { events += "abandoned" }
    private fun answered(status: Int, body: Any? = null): (String, ForegroundRequest, () -> Unit) -> NativeHttpResponse =
        { _, _, consume -> consume(); NativeHttpResponse(status, body, null) }
    private fun code(action: () -> Unit): AuthCode = try { action(); fail("rotation succeeded"); error("unreachable") }
        catch (e: AuthFailure) { assertNull(e.message); e.code }

    @Test fun failureBeforeConsumptionKeepsTokenSessionAndVault() {
        for (thrown in listOf(AuthCode.NETWORK_UNAVAILABLE, AuthCode.AUTH_CANCELLED, AuthCode.APP_LOCKED)) {
            val store = Store(old); events.clear()
            assertEquals(thrown, code { rotation(store) { _, _, _ -> throw AuthFailure(thrown) }.rotate(gate()) })
            assertEquals(old, store.stored); assertFalse(store.consumed); assertTrue(store.saved.isEmpty()); assertTrue(events.isEmpty())
        }
    }
    @Test fun failureAfterConsumptionDropsSessionWithoutRestoringOrWipingVault() {
        val store = Store(old)
        assertEquals(AuthCode.SESSION_EXPIRED, code { rotation(store) { _, _, consume -> consume(); throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE) }.rotate(gate()) })
        assertNull(store.stored); assertTrue(store.saved.isEmpty()); assertEquals(listOf("abandoned"), events)
    }
    @Test fun onlyExplicit401EndsSessionAndWipesVault() {
        val store = Store(old)
        assertEquals(AuthCode.SESSION_EXPIRED, code { rotation(store, answered(401)).rotate(gate()) })
        assertTrue(store.saved.isEmpty()); assertEquals(listOf("rejected"), events)
    }
    @Test fun answeredServerFailuresRestoreTheSameTokenAndKeepVault() {
        for ((status, expected) in listOf(503 to AuthCode.NETWORK_UNAVAILABLE, 502 to AuthCode.NETWORK_UNAVAILABLE, 500 to AuthCode.NETWORK_UNAVAILABLE,
            403 to AuthCode.NETWORK_UNAVAILABLE, 302 to AuthCode.NETWORK_UNAVAILABLE, 429 to AuthCode.RATE_LIMITED)) {
            val store = Store(old); events.clear()
            assertEquals(expected, code { rotation(store, answered(status)).rotate(gate()) })
            assertEquals(listOf(old), store.saved); assertEquals(old, store.stored); assertTrue(events.isEmpty())
        }
    }
    @Test fun rotatedTokensArePersistedEvenWhenTheGateClosed() {
        val store = Store(old)
        assertEquals(AuthCode.AUTH_CANCELLED, code { rotation(store) { _, g, consume -> consume(); g.cancel(); NativeHttpResponse(200, rotated, null) }.rotate(gate()) })
        assertEquals(listOf(new), store.saved); assertEquals(listOf("install:600"), events)
    }
    @Test fun activeGateInstallsAndReturnsNormally() {
        val store = Store(old)
        rotation(store, answered(200, rotated)).rotate(gate())
        assertEquals(listOf(new), store.saved); assertEquals(listOf("install:600"), events)
    }
    @Test fun malformedSuccessIsAmbiguous() {
        for (body in listOf(null, rotated - "refresh_token", rotated + ("expires_in" to 601), rotated + ("token_type" to "bearer"),
            rotated + ("refresh_token" to "short"), rotated + ("refresh_expires_at" to "tomorrow"))) {
            val store = Store(old); events.clear()
            assertEquals(AuthCode.SESSION_EXPIRED, code { rotation(store, answered(200, body)).rotate(gate()) })
            assertTrue(store.saved.isEmpty()); assertEquals(listOf("abandoned"), events)
        }
    }
    @Test fun failedDurableSaveDropsSessionWithoutWipingVault() {
        for (status in listOf(200, 503)) {
            val store = object : Store(old) { override fun save(refresh: String) { throw AuthFailure(AuthCode.KEY_INVALIDATED) } }
            events.clear()
            assertEquals(AuthCode.KEY_INVALIDATED, code { rotation(store, answered(status, rotated)).rotate(gate()) })
            assertEquals(listOf("abandoned"), events)
        }
    }
    @Test fun missingStoredTokenExpiresWithoutNetwork() {
        var calls = 0
        assertEquals(AuthCode.SESSION_EXPIRED, code { rotation(Store(null)) { _, _, _ -> calls++; NativeHttpResponse(200, rotated, null) }.rotate(gate()) })
        assertEquals(0, calls); assertTrue(events.isEmpty())
    }
    @Test fun tokensNeverAppearInDiagnostics() {
        assertEquals("NativeTokens(redacted)", NativeTokens.parse(rotated).toString())
    }
}
