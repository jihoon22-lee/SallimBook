package io.github.jihoon22lee.sallimbook.auth

import java.io.ByteArrayOutputStream
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import okhttp3.OkHttpClient
import okhttp3.Request

/** Read-only fixed audit endpoint, with the existing strict no-follow-up native client policy. */
internal class NativeAuditHttp(private val origin:String,private val client:OkHttpClient=vaultHttpClient()) {
    fun send(query:NativeAuditRequest,accessToken:String,gate:ForegroundRequest):NativeHttpResponse {
        if(AuthPolicy.apiOrigin(origin)==null) throw AuthFailure(AuthCode.AUTH_UNAVAILABLE)
        if(!NativeAuditWire.httpAllowed("GET",query.path,null,null,null,null)) throw AuthFailure(AuthCode.INVALID_REQUEST)
        gate.checkHttp("GET",query.path)
        try {
            val request=Request.Builder().url(origin+query.path).get().header("Accept","application/json")
                .header("X-SallimBook-Native","1").header("X-SallimBook-People","1").header("Authorization","Bearer $accessToken").build()
            val call=client.newCall(request); gate.bindNetworkCancellation { call.cancel() }; gate.checkHttp("GET",query.path)
            return call.execute().use { response ->
                if(response.code in 300..399) throw AuthFailure(AuthCode.ACCESS_DENIED)
                val type=response.body.contentType()
                if(type?.type!="application" || type.subtype!="json") throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
                val buffer=ByteArray(4096)
                val output=object:ByteArrayOutputStream() { fun wipe() { buf.fill(0); reset() } }
                var bytes:ByteArray?=null
                try {
                    response.body.byteStream().use { stream ->
                        while(true) {
                            gate.checkHttp("GET",query.path)
                            val count=stream.read(buffer); if(count<0) break
                            if(output.size()+count>1_048_576) throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
                            output.write(buffer,0,count)
                        }
                    }
                    bytes=output.toByteArray()
                    val text=Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT)
                        .decode(ByteBuffer.wrap(bytes)).toString()
                    val value=NativeVaultJson.decode(text)
                    gate.checkHttp("GET",query.path)
                    val requestId=response.header("X-Request-ID")?.takeIf { Regex("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}").matches(it) }
                    NativeHttpResponse(response.code,value,requestId)
                } finally { buffer.fill(0); bytes?.fill(0); output.wipe() }
            }
        } catch(failure:AuthFailure) { throw failure }
        catch(_:IOException) { throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE) }
        catch(_:Exception) { throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE) }
        finally { gate.releaseNetworkCancellation() }
    }
}
