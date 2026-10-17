package io.github.jihoon22lee.sallimbook.auth

import com.google.gson.GsonBuilder
import java.io.IOException
import java.net.InetAddress
import java.net.ServerSocket
import java.net.SocketTimeoutException
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread
import okhttp3.Authenticator
import okhttp3.CookieJar
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import org.junit.Assert.*
import org.junit.Test

class NativeVaultHttpTest {
    private val f=NativeVaultTestData
    private fun gate():ForegroundRequest {
        val policy=AppLockPolicy(); policy.resume(0,false); assertTrue(policy.unlock(policy.ticket(AppRequestKind.REAUTHENTICATE)))
        return ForegroundRequest().also { it.bindAppLock(policy,policy.ticket(AppRequestKind.PROTECTED)) { true } }
    }
    private fun bad(action:()->Unit) { try { action(); fail("Unsafe synthetic transport accepted") } catch(e:AuthFailure) { assertNull(e.message) } }
    private fun transport(body:ByteArray,status:Int=200,mime:String="application/json",inspect:(Request)->Unit={}):NativeVaultHttp = NativeVaultHttp("https://synthetic.invalid",
        vaultHttpClient().newBuilder().addInterceptor { chain -> inspect(chain.request()); Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(status).message("synthetic")
            .body(body.toResponseBody(mime.toMediaType())).build() }.build())
    @Test fun clientIsPrivateWithoutCookiesRedirectsCacheAuthenticationOrRetries() {
        val client=vaultHttpClient(); assertSame(CookieJar.NO_COOKIES,client.cookieJar); assertSame(Authenticator.NONE,client.authenticator); assertSame(Authenticator.NONE,client.proxyAuthenticator)
        assertFalse(client.followRedirects); assertFalse(client.followSslRedirects); assertFalse(client.retryOnConnectionFailure)
        assertNull(client.cache); assertTrue(client.interceptors.isEmpty()); assertTrue(client.networkInterceptors.isEmpty()); assertEquals(15000,client.callTimeoutMillis)
    }
    @Test fun actualGetAndMutationTransportUsesFixedPathsOpaqueBodyAndOneShotHeaders() {
        val status=f.snapshot().status
        val http=transport(GsonBuilder().serializeNulls().create().toJson(status).toByteArray()) { request ->
            assertEquals("https://synthetic.invalid/api/v1/vault/status",request.url.toString()); assertEquals("Bearer synthetic-token",request.header("Authorization")); assertEquals("1",request.header("X-SallimBook-Native")); assertNull(request.body)
        }
        val response=http.send(NativeVaultCommand(VaultOperation.STATUS),"synthetic-token",gate())
        assertEquals(status,response.body)
        val command=NativeVaultCommand(VaultOperation.CARD_WRITE,id=f.cardId,body=f.cardInput(),version=4,idempotencyKey="synthetic:card")
        val writer=transport("{\"id\":\"${f.resource}\",\"version\":5}".toByteArray()) { request ->
            assertEquals("PUT",request.method); assertEquals("\"4\"",request.header("If-Match")); assertEquals("synthetic:card",request.header("Idempotency-Key"))
            assertTrue(request.body!!.isOneShot()); val buffer=Buffer(); request.body!!.writeTo(buffer); val text=buffer.readUtf8()
            assertFalse(text.contains("4242424242424242")); assertFalse(text.contains("cvc")); assertFalse(text.contains("password"))
            val parsed=NativeVaultJson.decode(text) as Map<*,*>
            assertEquals(f.cardInput().keys,parsed.keys); assertEquals(7L,NativeVaultWire.version(parsed["key_version"]))
            try { request.body!!.writeTo(Buffer()); fail("Request replayed") } catch(_:IOException) { }
        }
        assertEquals(200,writer.send(command,"synthetic-token",gate()).status)
    }
    @Test fun redirectsMimeUtf8OversizedDuplicateAndNonIntegerJsonFailClosed() {
        val command=NativeVaultCommand(VaultOperation.STATUS)
        bad { transport("{}".toByteArray(),302).send(command,"synthetic-token",gate()) }
        bad { transport("{}".toByteArray(),mime="text/html").send(command,"synthetic-token",gate()) }
        bad { transport(byteArrayOf(0xc3.toByte(),0x28)).send(command,"synthetic-token",gate()) }
        bad { transport(ByteArray(1_048_577) { 32 }).send(command,"synthetic-token",gate()) }
        for(text in listOf("{\"version\":1,\"version\":2}","{\"version\":1.0}","{\"version\":NaN}","{} {}","{/*comment*/\"id\":1}","{\"id\":01}"))
            bad { transport(text.toByteArray()).send(command,"synthetic-token",gate()) }
    }
    @Test fun cancelledGateAndUntrustedOriginPreventAnyRequest() {
        var calls=0; val http=transport("{}".toByteArray()) { calls++ }; val gate=gate(); gate.cancel()
        bad { http.send(NativeVaultCommand(VaultOperation.STATUS),"synthetic-token",gate) }; assertEquals(0,calls)
        bad { NativeVaultHttp("http://synthetic.invalid").send(NativeVaultCommand(VaultOperation.STATUS),"synthetic-token",gate()) }
    }
    @Test fun jsonDepthContainerAndIntegerLimitsRejectHostileShapes() {
        for(text in listOf("[".repeat(14)+"0"+"]".repeat(14),"["+(1..2001).joinToString(",") { "0" }+"]",
            "{"+(1..65).joinToString(",") { "\"field$it\":0" }+"}","9223372036854775808")) {
            try { NativeVaultJson.decode(text); fail("Unbounded JSON accepted") } catch(_:Exception) { }
        }
        assertEquals(9_007_199_254_740_991L,NativeVaultJson.decode("9007199254740991"))
    }
    @Test fun retryAfterZeroCannotCauseSecondGetOnTheActualFollowUpEngine() {
        ServerSocket(0,2,InetAddress.getByName("127.0.0.1")).use { server ->
            server.soTimeout=1500; val count=AtomicInteger()
            val responder=thread(isDaemon=true) {
                try { repeat(2) { server.accept().use { socket ->
                    socket.soTimeout=1500; val reader=socket.getInputStream().bufferedReader()
                    while(true) { val line=reader.readLine() ?: break; if(line.isEmpty()) break }
                    count.incrementAndGet(); socket.getOutputStream().write("HTTP/1.1 503 Service Unavailable\r\nRetry-After: 0\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".toByteArray()); socket.getOutputStream().flush()
                } } } catch(_:SocketTimeoutException) { } catch(_:IOException) { }
            }
            try { vaultHttpClient().newCall(Request.Builder().url("http://127.0.0.1:${server.localPort}/synthetic").build()).execute().use { fail("Follow-up allowed") } }
            catch(_:IOException) { }
            responder.join(3000); assertFalse(responder.isAlive); assertEquals(1,count.get())
        }
    }
}
