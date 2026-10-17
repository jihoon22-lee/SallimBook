package io.github.jihoon22lee.sallimbook.auth

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
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

class NativeDocumentHttpTest {
    private val id = "00000000-0000-4000-8000-000000000001"
    private val raw = "synthetic attachment".toByteArray()
    private fun gate(): ForegroundRequest {
        val policy = AppLockPolicy()
        policy.resume(0, false); assertTrue(policy.unlock(policy.ticket(AppRequestKind.REAUTHENTICATE)))
        return ForegroundRequest().also { it.bindAppLock(policy, policy.ticket(AppRequestKind.PROTECTED)) { true } }
    }
    private fun info() = NativeDocumentBytes.read(ByteArrayInputStream(raw), raw.size.toLong()) {}.use {
        NativeDocumentInfo(id, "합성.pdf", "application/pdf", it.size, it.checksum)
    }
    private fun denied(action: () -> Unit) {
        try { action(); fail("Invalid synthetic file response accepted") }
        catch (failure: AuthFailure) { assertNull(failure.message) }
    }
    private fun transport(status: Int = 200, mime: String = "application/pdf", bytes: ByteArray = raw, inspect: (Request) -> Unit = {}): NativeDocumentHttp {
        val client = documentHttpClient().newBuilder().addInterceptor { chain ->
            inspect(chain.request())
            Response.Builder().request(chain.request()).protocol(Protocol.HTTP_1_1).code(status).message("synthetic")
                .body(bytes.toResponseBody(mime.toMediaType())).build()
        }.build()
        return NativeDocumentHttp("https://synthetic.invalid", client)
    }
    @Test fun binaryClientRetainsNoCookiesRedirectsCacheOrAutomaticRetry() {
        val client = documentHttpClient()
        assertSame(CookieJar.NO_COOKIES, client.cookieJar)
        assertSame(Authenticator.NONE, client.authenticator)
        assertSame(Authenticator.NONE, client.proxyAuthenticator)
        assertFalse(client.followRedirects); assertFalse(client.followSslRedirects); assertFalse(client.retryOnConnectionFailure)
        assertNull(client.cache); assertTrue(client.interceptors.isEmpty()); assertTrue(client.networkInterceptors.isEmpty())
        assertEquals(180_000, client.callTimeoutMillis); assertEquals(180_000, client.readTimeoutMillis)
    }
    @Test fun authenticatedDownloadChecksExactMetadataAndRetainsNativeBytesOnly() {
        var calls = 0
        val http = transport { request ->
            calls++
            assertEquals("GET", request.method)
            assertEquals("/api/v1/documents/$id/download", request.url.encodedPath)
            assertEquals("application/pdf", request.header("Accept"))
            assertEquals("1", request.header("X-SallimBook-Native"))
            assertNotNull(request.header("Authorization"))
            assertNull(request.body); assertNull(request.header("If-Match")); assertNull(request.header("Idempotency-Key"))
        }
        val result = http.download(info(), "synthetic-native-credential", gate())
        try {
            assertEquals(1, calls); assertEquals(200, result.response.status); assertNull(result.response.body)
            val output = ByteArrayOutputStream(); result.content!!.writeTo(output) {}
            assertArrayEquals(raw, output.toByteArray())
            assertFalse(result.toString().contains("synthetic"))
        } finally { result.content?.close() }
    }
    @Test fun wrongMimeSizeHashAndRedirectsNeverProduceAFile() {
        for (http in listOf(transport(mime = "text/html"), transport(bytes = byteArrayOf(1)),
            transport(bytes = ByteArray(raw.size) { 1 }), transport(status = 302))) denied { http.download(info(), "synthetic", gate()) }
    }
    @Test fun uploadSendsOriginalBytesOnceWithVersionAndIdempotency() {
        val content = NativeDocumentBytes.read(ByteArrayInputStream(raw), raw.size.toLong()) {}
        var calls = 0
        val http = transport(status = 302) { request ->
            calls++; assertEquals("PUT", request.method)
            assertEquals("/api/v1/documents/$id/content", request.url.encodedPath)
            assertEquals("\"1\"", request.header("If-Match")); assertEquals("synthetic:upload", request.header("Idempotency-Key"))
            assertEquals("application/json", request.header("Accept"))
            val body = request.body!!
            assertTrue(body.isOneShot()); assertEquals(raw.size.toLong(), body.contentLength())
            assertEquals("application/octet-stream", body.contentType().toString())
            val sink = Buffer(); body.writeTo(sink); assertArrayEquals(raw, sink.readByteArray())
            try { body.writeTo(Buffer()); fail("Request body replayed") } catch (_: java.io.IOException) { }
        }
        try { denied { http.upload(id, "\"1\"", "synthetic:upload", content, "synthetic", gate()) } }
        finally { content.close() }
        assertEquals(1, calls)
    }
    @Test fun cancelledGateStopsTransferBeforeAnyNetworkCall() {
        var calls = 0
        val http = transport { calls++ }
        val gate = gate().also { it.cancel() }
        denied { http.download(info(), "synthetic", gate) }
        assertEquals(0, calls)
    }
    @Test fun invalidIdentifiersAndHeadersFailBeforeBodyOrNetworkAccess() {
        var calls = 0
        val http = transport { calls++ }
        val content = NativeDocumentBytes.read(ByteArrayInputStream(raw), null) {}
        try {
            for ((target, version, key) in listOf(Triple("$id/../vault", "\"1\"", "synthetic"),
                Triple(id, "W/\"1\"", "synthetic"), Triple(id, "\"1\"", "bad key")))
                denied { http.upload(target, version, key, content, "synthetic", gate()) }
        } finally { content.close() }
        assertEquals(0, calls)
    }
}
