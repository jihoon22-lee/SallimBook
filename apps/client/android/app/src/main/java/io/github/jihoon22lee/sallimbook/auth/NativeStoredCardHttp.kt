package io.github.jihoon22lee.sallimbook.auth

import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import okhttp3.OkHttpClient
import okhttp3.Request

/** Dedicated native-only transport. The general metadata transport cannot call these endpoints. */
internal class NativeStoredCardHttp(private val origin: String, private val client: OkHttpClient = vaultHttpClient()) {
    fun send(action: String, cardId: String, version: Long?, details: NativeStoredCard?, accessToken: String, gate: ForegroundRequest): NativeHttpResponse {
        if (!NativeStoredCardPolicy.entry(mapOf("action" to action, "cardId" to cardId)) ||
            action != "view" && (version == null || version !in 1..9_007_199_254_740_991L) ||
            (action == "edit") != (details != null) || action == "view" && version != null) throw AuthFailure(AuthCode.INVALID_REQUEST)
        if (AuthPolicy.apiOrigin(origin) == null) throw AuthFailure(AuthCode.AUTH_UNAVAILABLE)
        val method = when(action) { "edit" -> "PUT"; "delete" -> "DELETE"; else -> "POST" }
        val path = "/api/v1/cards/$cardId/stored-details" + if (action == "view") "/reveal" else ""
        gate.checkHttp(method, path)
        val bytes = when(action) {
            "edit" -> {
                val d = details!!
                if (!NativeStoredCardPolicy.panValid(d.pan) || d.year !in 2000..2199 || d.month !in 1..12 ||
                    d.cvc != null && (d.cvc.size !in 3..4 || d.cvc.any { it !in '0'..'9' })) throw AuthFailure(AuthCode.INVALID_REQUEST)
                // Only the validated digit alphabet enters this native-only JSON body.
                "{\"pan\":\"${String(d.pan)}\",\"expiry_year\":${d.year},\"expiry_month\":${d.month},\"cvc\":${d.cvc?.let { "\"${String(it)}\"" } ?: "null"}}".toByteArray(Charsets.UTF_8)
            }
            "view" -> "{}".toByteArray()
            else -> null
        }
        try {
            val request = Request.Builder().url(origin + path)
                .method(method, bytes?.let { OneShotAuthBody(it) { gate.checkHttp(method, path) } })
                .header("Accept", "application/json").header("X-SallimBook-Native", "1")
                .header("Authorization", "Bearer $accessToken")
                .apply { version?.let { header("If-Match", "\"$it\"") } }.build()
            val call = client.newCall(request)
            gate.bindNetworkCancellation { call.cancel() }
            gate.checkHttp(method, path)
            return call.execute().use { response ->
                if (response.code in 300..399) throw AuthFailure(AuthCode.ACCESS_DENIED)
                if (response.code == 204) { gate.checkHttp(method, path); return@use NativeHttpResponse(204, null, null) }
                val type = response.body.contentType()
                if (type?.type != "application" || type.subtype != "json") throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
                val buffer = ByteArray(4096)
                val output = object : ByteArrayOutputStream() { fun wipe() { buf.fill(0); reset() } }
                var parsedBytes: ByteArray? = null
                try {
                    response.body.byteStream().use { stream ->
                        while (true) {
                            gate.checkHttp(method, path)
                            val count = stream.read(buffer); if (count < 0) break
                            if (output.size() + count > 16_384) throw AuthFailure(AuthCode.ACCESS_DENIED)
                            output.write(buffer, 0, count)
                        }
                    }
                    parsedBytes = output.toByteArray()
                    val text = Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(parsedBytes)).toString()
                    val body = NativeVaultJson.decode(text)
                    gate.checkHttp(method, path)
                    NativeHttpResponse(response.code, body, null)
                } finally { buffer.fill(0); parsedBytes?.fill(0); output.wipe() }
            }
        } catch (failure: AuthFailure) { throw failure }
        catch (_: Exception) { throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE) }
        finally { gate.releaseNetworkCancellation(); bytes?.fill(0) }
    }
}
