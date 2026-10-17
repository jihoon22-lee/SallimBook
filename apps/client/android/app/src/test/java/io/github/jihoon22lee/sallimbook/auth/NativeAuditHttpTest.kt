package io.github.jihoon22lee.sallimbook.auth

import okhttp3.Authenticator
import okhttp3.CookieJar
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.*
import org.junit.Test

class NativeAuditHttpTest {
    private val request=NativeAuditWire.prepare(emptyMap<String,Any>())
    private val correlation="00000000-0000-4000-8000-000000000001"
    private fun gate():ForegroundRequest {
        val policy=AppLockPolicy(); policy.resume(0,false); assertTrue(policy.unlock(policy.ticket(AppRequestKind.REAUTHENTICATE)))
        return ForegroundRequest().also { it.bindAppLock(policy,policy.ticket(AppRequestKind.PROTECTED)) { true } }
    }
    private fun bad(action:()->Unit) { try { action(); fail("Unsafe synthetic audit HTTP accepted") } catch(e:AuthFailure) { assertNull(e.message); assertNull(e.cause) } }
    private fun transport(body:ByteArray,status:Int=200,mime:String="application/json",inspect:(Request)->Unit={}):NativeAuditHttp = NativeAuditHttp("https://synthetic.invalid",
        vaultHttpClient().newBuilder().addInterceptor { chain -> inspect(chain.request()); Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(status).message("synthetic")
            .header("X-Request-ID",correlation).body(body.toResponseBody(mime.toMediaType())).build() }.build())
    @Test fun fixedNativeGetHasOnlyNativeBearerAndNoMutationHeadersOrBody() {
        var calls=0
        val http=transport("{\"items\":[],\"next_cursor\":null}".toByteArray()) { sent ->
            calls++; assertEquals("https://synthetic.invalid/api/v1/audit-events?limit=50",sent.url.toString()); assertEquals("GET",sent.method)
            assertEquals("Bearer synthetic-native-only",sent.header("Authorization")); assertEquals("1",sent.header("X-SallimBook-Native"))
            assertNull(sent.body); assertNull(sent.header("Cookie")); assertNull(sent.header("If-Match")); assertNull(sent.header("Idempotency-Key")); assertNull(sent.header("X-Step-Up-Token"))
        }
        val response=http.send(request,"synthetic-native-only",gate())
        assertEquals(1,calls); assertEquals(200,response.status); assertEquals(correlation,response.requestId)
        assertEquals(mapOf("items" to emptyList<Any>(),"next_cursor" to null),NativeAuditWire.response(request,response.status,response.body))
        val client=vaultHttpClient(); assertSame(CookieJar.NO_COOKIES,client.cookieJar); assertSame(Authenticator.NONE,client.authenticator)
        assertFalse(client.followRedirects); assertFalse(client.followSslRedirects); assertFalse(client.retryOnConnectionFailure); assertNull(client.cache); assertEquals(15000,client.callTimeoutMillis)
    }
    @Test fun errorStatusAndCorrelationSurviveButRawErrorTextIsNotBridged() {
        var calls=0
        val http=transport("{\"error\":{\"code\":\"AUDIT_METADATA_INVALID\",\"message\":\"synthetic private\"}}".toByteArray(),503) { calls++ }
        val response=http.send(request,"synthetic",gate()); assertEquals(1,calls)
        val safe=AuthPolicy.safeError(response.status,response.body,response.requestId)!!
        assertEquals("AUDIT_METADATA_INVALID",(safe["error"] as Map<*,*>)["code"]); assertFalse(safe.toString().contains("synthetic private"))
    }
    @Test fun mimeRedirectUtf8SizeAndNonStrictJsonAreRejected() {
        bad { transport("{}".toByteArray(),302).send(request,"synthetic",gate()) }
        bad { transport("{}".toByteArray(),mime="text/html").send(request,"synthetic",gate()) }
        bad { transport(byteArrayOf(0xc3.toByte(),0x28)).send(request,"synthetic",gate()) }
        bad { transport(ByteArray(1_048_577) { 32 }).send(request,"synthetic",gate()) }
        for(json in listOf("{\"items\":[],\"items\":[]}","{\"version\":1.0}","{} {}","{/*synthetic*/\"items\":[]}","[".repeat(14)+"0"+"]".repeat(14)))
            bad { transport(json.toByteArray()).send(request,"synthetic",gate()) }
    }
    @Test fun cancelledLockedOrLateGateAndUntrustedPathsNeverYieldMetadata() {
        var calls=0; val http=transport("{}".toByteArray()) { calls++ }; val cancelled=gate().also { it.cancel() }
        bad { http.send(request,"synthetic",cancelled) }; assertEquals(0,calls)
        bad { http.send(NativeAuditRequest("https://synthetic.invalid/api/v1/audit-events",50,emptyMap()),"synthetic",gate()) }; assertEquals(0,calls)
        bad { NativeAuditHttp("http://synthetic.invalid").send(request,"synthetic",gate()) }
        val late=gate(); bad { transport("{}".toByteArray()) { late.cancel() }.send(request,"synthetic",late) }
        val locked=AppLockPolicy(); val gate=ForegroundRequest().also { it.bindAppLock(locked,locked.ticket(AppRequestKind.PROTECTED)) { true } }
        bad { http.send(request,"synthetic",gate) }; assertEquals(0,calls)
    }
}
