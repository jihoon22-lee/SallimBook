package io.github.jihoon22lee.sallimbook.auth

import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import org.junit.Assert.*
import org.junit.Test

class NativeStoredCardHttpTest {
    private val id = "00000000-0000-0000-0000-000000000001"
    private fun gate(): ForegroundRequest {
        val policy = AppLockPolicy(); policy.resume(0, false); policy.unlock(policy.ticket(AppRequestKind.REAUTHENTICATE))
        return ForegroundRequest().also { it.bindAppLock(policy, policy.ticket(AppRequestKind.PROTECTED)) { true } }
    }
    @Test fun dedicatedTransportUsesVersionAndOneShotBodyWithoutGenericBridge() {
        var requests = 0
        val http = NativeStoredCardHttp("https://synthetic.invalid", vaultHttpClient().newBuilder().addInterceptor { chain ->
            requests++
            val request = chain.request()
            assertEquals("/api/v1/cards/$id/stored-details", request.url.encodedPath)
            assertEquals("PUT", request.method); assertEquals("\"7\"", request.header("If-Match"))
            assertEquals("Bearer synthetic-token", request.header("Authorization"))
            assertTrue(request.body!!.isOneShot())
            val buffer = Buffer(); request.body!!.writeTo(buffer)
            val body = NativeVaultJson.decode(buffer.readUtf8()) as Map<*, *>
            assertEquals("4111111111111112", body["pan"]); assertEquals(2030, body["expiry_year"])
            assertEquals(12, body["expiry_month"]); assertNull(body["cvc"])
            Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(200).message("synthetic").body("{}".toResponseBody("application/json".toMediaType())).build()
        }.build())
        val details = NativeStoredCardPolicy.input("4111 1111 1111 1112".toCharArray(), "2030", "12", charArrayOf())
        assertEquals(200, http.send("edit", id, 7L, details, "synthetic-token", gate()).status)
        assertEquals(1, requests); details.discard()
        val cancelled = gate(); cancelled.cancel()
        try { http.send("view", id, null, null, "synthetic-token", cancelled); fail() } catch (_: AuthFailure) { }
        assertEquals(1, requests)
    }
    @Test fun deleteAccepts204AndRevealsRejectRedirectsAndOversizedReplies() {
        fun transport(status: Int, body: String) = NativeStoredCardHttp("https://synthetic.invalid", vaultHttpClient().newBuilder().addInterceptor { chain ->
            Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(status).message("synthetic").body(body.toResponseBody("application/json".toMediaType())).build()
        }.build())
        assertNull(transport(204, "").send("delete", id, 1, null, "synthetic-token", gate()).body)
        for ((status, body) in listOf(302 to "{}", 200 to " ".repeat(16_385), 200 to "{\"pan\":1,\"pan\":2}")) {
            try { transport(status, body).send("view", id, null, null, "synthetic-token", gate()); fail() } catch (_: AuthFailure) { }
        }
    }
}
