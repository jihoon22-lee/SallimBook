package io.github.jihoon22lee.sallimbook.auth

import java.net.SocketTimeoutException
import java.net.UnknownHostException
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import org.junit.Assert.*
import org.junit.Test

class NativeRefreshExchangeTest {
    private val token = "synthetic_refresh_old_000000000000000000001"
    private val rotated = """{"access_token":"synthetic_access_new_0000000000000000000001","refresh_token":"synthetic_refresh_new_000000000000000000001","token_type":"Bearer","expires_in":600,"refresh_expires_at":"2026-11-18T00:00:00Z"}"""
    private fun gate(): ForegroundRequest { // NativeVaultHttpTest.gate()와 같다
        val policy = AppLockPolicy(); policy.resume(0, false); assertTrue(policy.unlock(policy.ticket(AppRequestKind.REAUTHENTICATE)))
        return ForegroundRequest().also { it.bindAppLock(policy, policy.ticket(AppRequestKind.PROTECTED)) { true } }
    }
    private fun http(handler: (Interceptor.Chain) -> Response) =
        NativeAuthHttp("https://synthetic.invalid", accountHttpClient().newBuilder().addInterceptor { handler(it) }.build())
    private fun reply(chain: Interceptor.Chain, status: Int, body: String, mime: String = "application/json") = Response.Builder()
        .request(chain.request()).protocol(Protocol.HTTP_1_1).code(status).message("synthetic").body(body.toResponseBody(mime.toMediaType())).build()
    private fun sent(chain: Interceptor.Chain) = Buffer().also { chain.request().body!!.writeTo(it) }.readUtf8()
    private fun failure(action: () -> Unit): AuthCode = try { action(); fail("refresh exchange accepted"); error("unreachable") }
        catch (e: AuthFailure) { assertNull(e.message); e.code }

    @Test fun cancelledGateNeverSendsOrConsumes() {
        var calls = 0; var consumed = false; val gate = gate(); gate.cancel()
        assertEquals(AuthCode.AUTH_CANCELLED, failure { http { calls++; reply(it, 200, rotated) }.refresh(token, gate) { consumed = true } })
        assertEquals(0, calls); assertFalse(consumed)
    }
    @Test fun connectionFailureBeforeTheBodyKeepsTheTokenUnconsumed() {
        var consumed = false
        assertEquals(AuthCode.NETWORK_UNAVAILABLE, failure { http { throw UnknownHostException("synthetic") }.refresh(token, gate()) { consumed = true } })
        assertFalse(consumed)
    }
    @Test fun gateClosingBeforeTheBodyWriteStopsBeforeConsumption() {
        var consumed = false; val gate = gate()
        assertEquals(AuthCode.AUTH_CANCELLED, failure { http { gate.cancel(); sent(it); reply(it, 200, rotated) }.refresh(token, gate) { consumed = true } })
        assertFalse(consumed)
    }
    @Test fun bodyHandedToTransportAfterConsumptionIsAmbiguous() {
        var consumed = false; var body = ""
        assertEquals(AuthCode.NETWORK_UNAVAILABLE, failure { http { body = sent(it); throw SocketTimeoutException("synthetic") }.refresh(token, gate()) { consumed = true } })
        assertTrue(consumed); assertEquals("{\"refresh_token\":\"$token\"}", body)
    }
    @Test fun answeredFailuresReturnStatusWithoutTrustingTheBody() {
        for ((status, mime) in listOf(401 to "application/json", 429 to "application/json", 502 to "text/html", 503 to "text/html")) {
            var consumed = false
            val response = http { sent(it); reply(it, status, "<html>synthetic</html>", mime) }.refresh(token, gate()) { consumed = true }
            assertEquals(status, response.status); assertNull(response.body); assertTrue(consumed)
        }
    }
    @Test fun rotatedTokensSurviveGateCancellationAfterSending() {
        val gate = gate()
        val response = http { sent(it); gate.cancel(); reply(it, 200, rotated) }.refresh(token, gate) { }
        assertEquals(200, response.status)
        assertEquals("synthetic_refresh_new_000000000000000000001", (response.body as Map<*, *>)["refresh_token"])
    }
    @Test fun nonJsonSuccessIsAmbiguousRatherThanAnswered() {
        assertEquals(AuthCode.NETWORK_UNAVAILABLE, failure { http { sent(it); reply(it, 200, "ok", "text/plain") }.refresh(token, gate()) { } })
    }
}
