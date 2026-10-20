package io.github.jihoon22lee.sallimbook.auth

import com.google.gson.GsonBuilder
import java.io.IOException
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.*
import org.junit.Test

class NativeVaultConnectionTest {
    private val f = NativeVaultTestData
    private val offer = "00000000-0000-4000-8000-000000000009"
    private val wrap = NativeVaultCommand(VaultOperation.SHARE_WRAP, id = offer)
    private val denied = 403 to """{"error":{"code":"VAULT_ACCESS_DENIED"}}"""
    private class Local : NativeVaultLocalState {
        var cleared = 0
        override fun clearAll() { cleared++ }
        override fun reconcile(scope: NativeVaultScope) = Unit
        override fun reconcileCard(binding: NativeVaultBinding) = Unit
        override fun clearCard(scope: NativeVaultScope, cardId: String) = Unit
    }
    private fun gate(): ForegroundRequest { // NativeVaultHttpTest.gate()와 같다
        val policy = AppLockPolicy(); policy.resume(0, false); assertTrue(policy.unlock(policy.ticket(AppRequestKind.REAUTHENTICATE)))
        return ForegroundRequest().also { it.bindAppLock(policy, policy.ticket(AppRequestKind.PROTECTED)) { true } }
    }
    private fun status(row: Map<String, Any?>) = 200 to GsonBuilder().serializeNulls().create().toJson(row)
    private fun connection(local: Local, paths: MutableList<String>, respond: (String) -> Pair<Int, String>): NativeVaultConnection {
        val client = vaultHttpClient().newBuilder().addInterceptor { chain ->
            val path = chain.request().url.encodedPath; paths += path
            val (code, body) = respond(path)
            Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(code).message("synthetic")
                .body(body.toResponseBody("application/json".toMediaType())).build()
        }.build()
        return NativeVaultConnection("io.github.synthetic", "https://synthetic.invalid", { "synthetic-token" },
            NativeAuthHttp("https://synthetic.invalid"), NativeVaultHttp("https://synthetic.invalid", client), gate(), local)
    }
    private fun failure(action: () -> Unit): String = try { action(); fail("denied vault call succeeded"); "" }
        catch (e: NativeVaultFailure) { e.code }

    @Test fun otherMembersOfferDenialKeepsLocalVaultWhileMembershipIsActive() {
        val local = Local(); val paths = mutableListOf<String>()
        val c = connection(local, paths) { if (it.endsWith("/wrapping")) denied else status(f.snapshot().status) }
        assertEquals("VAULT_ACCESS_DENIED", failure { c.call(wrap) })
        assertEquals(0, local.cleared)
        assertEquals(listOf("/api/v1/vault/shares/$offer/wrapping", "/api/v1/vault/status"), paths)
    }
    @Test fun denialWipesOnlyWhenFreshStatusShowsMembershipEnded() {
        for (row in listOf(f.snapshot().status + ("own_membership" to "revoked"), f.snapshot(initialized = false).status)) {
            val local = Local()
            val c = connection(local, mutableListOf()) { if (it.endsWith("/wrapping")) denied else status(row) }
            assertEquals("VAULT_ACCESS_DENIED", failure { c.call(wrap) })
            assertEquals(1, local.cleared)
        }
    }
    @Test fun unreachableStatusRecheckKeepsLocalVaultAndReportsTheOriginalDenial() {
        val local = Local()
        val c = connection(local, mutableListOf()) { if (it.endsWith("/wrapping")) denied else throw IOException("synthetic") }
        assertEquals("VAULT_ACCESS_DENIED", failure { c.call(wrap) })
        assertEquals(0, local.cleared)
    }
    @Test fun expiredSessionDuringRecheckStillWipes() {
        val local = Local()
        val c = connection(local, mutableListOf()) { if (it.endsWith("/wrapping")) denied else 401 to "{}" }
        assertEquals("SESSION_EXPIRED", failure { c.call(wrap) })
        assertEquals(1, local.cleared)
    }
    @Test fun sessionExpiryAndUninitializedVaultStillWipeWithoutRecheck() {
        for ((answer, code) in listOf((401 to "{}") to "SESSION_EXPIRED",
            (409 to """{"error":{"code":"VAULT_NOT_INITIALIZED"}}""") to "VAULT_NOT_INITIALIZED")) {
            val local = Local(); val paths = mutableListOf<String>()
            val c = connection(local, paths) { answer }
            assertEquals(code, failure { c.call(wrap) })
            assertEquals(1, local.cleared); assertEquals(1, paths.size)
        }
    }
}
