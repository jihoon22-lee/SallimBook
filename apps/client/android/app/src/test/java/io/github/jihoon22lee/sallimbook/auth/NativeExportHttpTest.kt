package io.github.jihoon22lee.sallimbook.auth

import java.io.ByteArrayOutputStream
import java.io.IOException
import java.security.MessageDigest
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

class NativeExportHttpTest {
    private val id="00000000-0000-4000-8000-000000000001"
    private val data=byteArrayOf(0x50,0x4b,3,4)+"synthetic export".toByteArray()
    private val hash=MessageDigest.getInstance("SHA-256").digest(data).joinToString("") { "%02x".format(it.toInt() and 255) }
    private val selection=NativeExportPolicy.selection(mapOf("formats" to listOf("json"),"document_ids" to listOf(id)))
    private fun gate():ForegroundRequest {
        val policy=AppLockPolicy(); policy.resume(0,false); assertTrue(policy.unlock(policy.ticket(AppRequestKind.REAUTHENTICATE)))
        return ForegroundRequest().also { it.bindAppLock(policy,policy.ticket(AppRequestKind.PROTECTED)) { true } }
    }
    private fun bad(action:()->Unit) { try { action(); fail("Unsafe export transport accepted") } catch(e:AuthFailure) { assertNull(e.message) } }
    private fun transport(body:ByteArray=data,status:Int=200,change:(Response.Builder)->Unit={},inspect:(Request)->Unit={},
        allocate:(Int)->ByteArray={ ByteArray(it) }):NativeExportHttp {
        return NativeExportHttp("https://synthetic.invalid",allocate=allocate,client=exportHttpClient().newBuilder().addInterceptor { chain ->
            inspect(chain.request())
            Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(status).message("synthetic")
                .header("Content-Type",if(status==200) "application/zip" else "application/json")
                .header("Content-Length",body.size.toString()).header("Cache-Control","no-store").header("Pragma","no-cache")
                .header("X-Content-Type-Options","nosniff").header("X-Export-ID",id).header("X-Export-SHA256",hash)
                .header("Content-Disposition","attachment; filename=\"sallimbook-$id.zip\"")
                .body(body.toResponseBody((if(status==200) "application/zip" else "application/json").toMediaType())).apply(change).build()
        }.build())
    }
    @Test fun anArchiveTooLargeForTheDeviceMemoryIsReportedAsTooLargeInsteadOfCrashing() {
        val response=transport(allocate={ throw OutOfMemoryError() }).create(selection,"synthetic-token",gate())
        assertEquals("EXPORT_TOO_LARGE",response.code); assertNull(response.archive)
    }
    @Test fun clientHasBoundedPrivateTransportWithoutCookiesCacheRedirectsRetriesOrAuthenticationFallback() {
        val client=exportHttpClient()
        assertEquals(180_000,client.callTimeoutMillis); assertEquals(180_000,client.readTimeoutMillis); assertEquals(30_000,client.writeTimeoutMillis)
        assertSame(CookieJar.NO_COOKIES,client.cookieJar); assertSame(Authenticator.NONE,client.authenticator); assertSame(Authenticator.NONE,client.proxyAuthenticator)
        assertFalse(client.followRedirects); assertFalse(client.followSslRedirects); assertFalse(client.retryOnConnectionFailure)
        assertNull(client.cache); assertTrue(client.interceptors.isEmpty()); assertTrue(client.networkInterceptors.isEmpty())
    }
    @Test fun exactPostHasOnlySelectionBodyAndVerifiedNativeArchive() {
        var calls=0
        val http=transport(inspect={ request ->
            calls++; assertEquals("POST",request.method); assertEquals("https://synthetic.invalid/api/v1/exports",request.url.toString())
            assertEquals("Bearer synthetic-token",request.header("Authorization")); assertEquals("1",request.header("X-SallimBook-Native"))
            assertEquals("application/zip",request.header("Accept")); assertEquals("identity",request.header("Accept-Encoding")); assertEquals("no-store",request.header("Cache-Control"))
            assertNull(request.header("Idempotency-Key")); assertNull(request.header("X-Step-Up-Token")); assertNull(request.header("Cookie"))
            assertTrue(request.body!!.isOneShot()); val output=Buffer(); request.body!!.writeTo(output)
            assertEquals(selection.body(),NativeVaultJson.decode(output.readUtf8()))
            try { request.body!!.writeTo(Buffer()); fail("POST body replayed") } catch(_:IOException) { }
        })
        val response=http.create(selection,"synthetic-token",gate()); assertNull(response.code); assertEquals(id,response.archive!!.id)
        try { val output=ByteArrayOutputStream(); response.archive.content.writeTo(output) { }; assertArrayEquals(data,output.toByteArray()) }
        finally { response.archive.close() }
        assertEquals(1,calls); assertFalse(response.toString().contains(id))
    }
    @Test fun missingDuplicateOrInconsistentRequiredHeadersFailClosed() {
        for(header in listOf("Content-Type","Content-Length","Cache-Control","Pragma","X-Content-Type-Options","X-Export-ID","X-Export-SHA256","Content-Disposition")) {
            bad { transport(change={ it.removeHeader(header) }).create(selection,"synthetic-token",gate()) }
            bad { transport(change={ it.addHeader(header,"synthetic-duplicate") }).create(selection,"synthetic-token",gate()) }
        }
        for((header,value) in mapOf("Content-Type" to "text/html","Content-Length" to "67108865","Cache-Control" to "public",
            "X-Export-ID" to "../synthetic","X-Export-SHA256" to "0".repeat(64),"Content-Disposition" to "attachment; filename=\"../../synthetic.zip\"",
            "Content-Encoding" to "gzip","Transfer-Encoding" to "chunked"))
            bad { transport(change={ it.header(header,value) }).create(selection,"synthetic-token",gate()) }
        bad { transport(change={ it.addHeader("Content-Encoding","identity").addHeader("Content-Encoding","identity") }).create(selection,"synthetic-token",gate()) }
    }
    @Test fun redirectsNonZipTruncatedAndExtraBodiesNeverReturnAnArchive() {
        for(status in listOf(201,204,301,302,307,308)) bad { transport(status=status).create(selection,"synthetic-token",gate()) }
        bad { transport(data.copyOf(data.size-1),change={ it.header("Content-Length",data.size.toString()) }).create(selection,"synthetic-token",gate()) }
        bad { transport(data+byteArrayOf(42),change={ it.header("Content-Length",data.size.toString()) }).create(selection,"synthetic-token",gate()) }
        bad { transport("synthetic nonzip".toByteArray()).create(selection,"synthetic-token",gate()) }
    }
    @Test fun errorsAreBoundedStrictSafeCodesAndNeverTriggerAPostRetry() {
        for((code,status) in NativeExportPolicy.errors) {
            var calls=0
            val body="{\"error\":{\"code\":\"$code\",\"message\":\"synthetic private detail\"}}".toByteArray()
            val response=transport(body,status,inspect={ calls++ }).create(selection,"synthetic-token",gate())
            assertEquals(code,response.code); assertNull(response.archive); assertEquals(1,calls)
        }
        for(body in listOf(ByteArray(16_385) { 32 },"{\"error\":{},\"error\":{}}".toByteArray(),byteArrayOf(0xc3.toByte(),0x28)))
            bad { transport(body,503).create(selection,"synthetic-token",gate()) }
    }
    @Test fun cancelledStaleRequestsAndUntrustedOriginNeverExposeBytes() {
        var calls=0; val canceled=gate().also { it.cancel() }
        bad { transport(inspect={ calls++ }).create(selection,"synthetic-token",canceled) }; assertEquals(0,calls)
        val late=gate(); bad { transport(inspect={ late.cancel() }).create(selection,"synthetic-token",late) }
        bad { NativeExportHttp("http://synthetic.invalid").create(selection,"synthetic-token",gate()) }
        bad { NativeExportHttp("https://synthetic.invalid/alternate").create(selection,"synthetic-token",gate()) }
    }
}
