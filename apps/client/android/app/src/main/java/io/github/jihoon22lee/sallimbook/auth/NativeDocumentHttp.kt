package io.github.jihoon22lee.sallimbook.auth

import java.io.ByteArrayOutputStream
import java.io.IOException
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import okhttp3.Response
import okio.BufferedSink
import org.json.JSONArray
import org.json.JSONObject
import org.json.JSONTokener

internal fun documentHttpClient() = accountHttpClient().newBuilder()
    .callTimeout(NativeDocumentBytes.TRANSFER_MILLIS, TimeUnit.MILLISECONDS)
    .readTimeout(NativeDocumentBytes.TRANSFER_MILLIS, TimeUnit.MILLISECONDS)
    .writeTimeout(30, TimeUnit.SECONDS).build()

internal class NativeDocumentDownload(val response: NativeHttpResponse, val content: NativeDocumentBytes?) {
    override fun toString() = "NativeDocumentDownload(redacted)"
}

/** Separate binary transport; no URLs, headers, bytes, or file handles are accepted from JS. */
internal class NativeDocumentHttp(private val origin: String, private val client: OkHttpClient = documentHttpClient()) {
    private fun builder(path: String, gate: ForegroundRequest, method: String, token: String): Request.Builder {
        if (AuthPolicy.apiOrigin(origin) == null) throw AuthFailure(AuthCode.AUTH_UNAVAILABLE)
        gate.checkHttp(method, path)
        return Request.Builder().url(origin + path).header("X-SallimBook-Native", "1")
            .header("Authorization", "Bearer $token")
    }
    fun upload(documentId: String, ifMatch: String, idempotencyKey: String, content: NativeDocumentBytes,
        token: String, gate: ForegroundRequest): NativeHttpResponse {
        val path = NativeDocumentPolicy.binaryPath(documentId, true)
        val written = AtomicBoolean(false)
        val body = object : RequestBody() {
            override fun contentType() = "application/octet-stream".toMediaType()
            override fun contentLength() = content.size.toLong()
            override fun isOneShot() = true
            override fun writeTo(sink: BufferedSink) {
                if (!written.compareAndSet(false, true)) throw IOException("Document body cannot be replayed")
                content.writeTo(sink.outputStream()) { gate.checkHttp("PUT", path) }
            }
        }
        val request = builder(path, gate, "PUT", token).put(body).header("Accept", "application/json")
            .header("If-Match", NativeDocumentPolicy.tag(ifMatch))
            .header("Idempotency-Key", NativeDocumentPolicy.key(idempotencyKey)).build()
        return execute(request, gate) { response -> json(response, gate) }
    }
    fun download(info: NativeDocumentInfo, token: String, gate: ForegroundRequest): NativeDocumentDownload {
        val path = NativeDocumentPolicy.binaryPath(info.id, false)
        val request = builder(path, gate, "GET", token).get().header("Accept", info.mime).build()
        return execute(request, gate) { response ->
            if (response.code != 200) return@execute NativeDocumentDownload(json(response, gate), null)
            val type = response.body.contentType()
            if (type == null || "${type.type}/${type.subtype}" != info.mime ||
                response.body.contentLength().let { it != -1L && it != info.size.toLong() }) throw AuthFailure(AuthCode.ACCESS_DENIED)
            var content: NativeDocumentBytes? = null
            try {
                content = response.body.byteStream().use { stream -> NativeDocumentBytes.read(stream, info.size.toLong()) { gate.checkHttp("GET", path) } }
                if (content.checksum != info.checksum) throw AuthFailure(AuthCode.ACCESS_DENIED)
                gate.checkHttp("GET", path)
                NativeDocumentDownload(NativeHttpResponse(200, null, requestId(response)), content).also { content = null }
            } finally { content?.close() }
        }
    }
    private fun <T> execute(request: Request, gate: ForegroundRequest, consume: (Response) -> T): T {
        val call = client.newCall(request)
        gate.bindNetworkCancellation { call.cancel() }
        try {
            gate.check()
            return call.execute().use { response ->
                if (response.code in 300..399) throw AuthFailure(AuthCode.ACCESS_DENIED)
                gate.check()
                consume(response)
            }
        } catch (failure: AuthFailure) { throw failure }
        catch (_: Exception) { throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE) }
        finally { gate.releaseNetworkCancellation() }
    }
    private fun requestId(response: Response) = response.header("X-Request-ID")?.takeIf { PasskeyPolicy.uuid.matches(it) }
    private fun json(response: Response, gate: ForegroundRequest): NativeHttpResponse {
        val type = response.body.contentType()
        if (type?.type != "application" || type.subtype != "json") throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
        val buffer = ByteArray(4096)
        val output = ByteArrayOutputStream()
        var bytes: ByteArray? = null
        try {
            response.body.byteStream().use { stream ->
                while (true) {
                    gate.check()
                    val count = stream.read(buffer)
                    if (count < 0) break
                    if (count == 0 || output.size() + count > 262_144) throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
                    output.write(buffer, 0, count)
                }
            }
            bytes = output.toByteArray()
            val parser = JSONTokener(bytes.toString(Charsets.UTF_8))
            val result = jsonValue(parser.nextValue())
            if (parser.nextClean() != 0.toChar()) throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
            gate.check()
            return NativeHttpResponse(response.code, result, requestId(response))
        } finally { buffer.fill(0); bytes?.fill(0); output.reset() }
    }
    private fun jsonValue(value: Any?, depth: Int = 0): Any? {
        if (depth > 16) throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
        return when (value) {
            null, JSONObject.NULL -> null
            is JSONObject -> value.keys().asSequence().associateWith { jsonValue(value.get(it), depth + 1) }
            is JSONArray -> (0 until value.length()).map { jsonValue(value.get(it), depth + 1) }
            is String, is Boolean, is Int, is Long, is Double -> value
            else -> throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
        }
    }
}
