package io.github.jihoon22lee.sallimbook.auth

import com.google.gson.Gson
import java.io.ByteArrayOutputStream
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response

internal fun exportHttpClient():OkHttpClient = documentHttpClient()

/** Fixed native POST only. The response remains native and is verified before any provider write. */
internal class NativeExportHttp(private val origin:String,private val client:OkHttpClient=exportHttpClient()) {
    fun create(selection:NativeExportSelection,token:String,gate:ForegroundRequest):NativeExportResponse {
        if(AuthPolicy.apiOrigin(origin)==null) throw AuthFailure(AuthCode.AUTH_UNAVAILABLE)
        val path=NativeExportPolicy.PATH
        val safe=NativeExportPolicy.selection(selection.body())
        gate.checkHttp("POST",path)
        val bytes=Gson().toJson(safe.body()).toByteArray(Charsets.UTF_8)
        try {
            val request=Request.Builder().url(origin+path).post(OneShotAuthBody(bytes) { gate.checkHttp("POST",path) })
                .header("Accept","application/zip").header("Accept-Encoding","identity")
                .header("Authorization","Bearer $token").header("X-SallimBook-Native","1")
                .header("Cache-Control","no-store").header("Pragma","no-cache").build()
            val call=client.newCall(request); gate.bindNetworkCancellation { call.cancel() }
            gate.checkHttp("POST",path)
            return call.execute().use { response ->
                gate.checkHttp("POST",path)
                if(response.code in 300..399) throw AuthFailure(AuthCode.ACCESS_DENIED)
                if(response.code!=200) return@use NativeExportResponse(code=error(response,gate))
                val id=single(response,"X-Export-ID")
                if(!PasskeyPolicy.uuid.matches(id) || single(response,"Content-Type")!="application/zip" ||
                    single(response,"Cache-Control")!="no-store" || single(response,"Pragma")!="no-cache" ||
                    single(response,"X-Content-Type-Options")!="nosniff" ||
                    single(response,"Content-Disposition")!="attachment; filename=\"sallimbook-$id.zip\"" ||
                    response.headers.values("Content-Encoding").let { it.isNotEmpty() && it!=listOf("identity") } || response.headers.values("Transfer-Encoding").isNotEmpty())
                    throw AuthFailure(AuthCode.ACCESS_DENIED)
                val length=single(response,"Content-Length")
                if(!Regex("[1-9][0-9]{0,8}").matches(length)) throw AuthFailure(AuthCode.ACCESS_DENIED)
                val size=length.toLong()
                if(size>NativeExportBytes.MAX_BYTES || response.body.contentLength().let { it!=-1L && it!=size }) throw AuthFailure(AuthCode.ACCESS_DENIED)
                val checksum=single(response,"X-Export-SHA256")
                var content:NativeExportBytes?=null
                try {
                    content=response.body.byteStream().use { stream -> NativeExportBytes.read(stream,size,checksum) { gate.checkHttp("POST",path) } }
                    gate.checkHttp("POST",path)
                    NativeExportResponse(archive=NativeExportArchive(id,content)).also { content=null }
                } finally { content?.close() }
            }
        } catch(failure:AuthFailure) { throw failure }
        catch(_:IOException) { throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE) }
        catch(_:Exception) { throw AuthFailure(AuthCode.ACCESS_DENIED) }
        finally { bytes.fill(0); gate.releaseNetworkCancellation() }
    }
    private fun single(response:Response,name:String)=response.headers.values(name).singleOrNull() ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
    private fun error(response:Response,gate:ForegroundRequest):String {
        if(response.code in 200..299) throw AuthFailure(AuthCode.ACCESS_DENIED)
        val mime=response.body.contentType()
        if(mime?.type!="application" || mime.subtype!="json") throw AuthFailure(AuthCode.ACCESS_DENIED)
        val buffer=ByteArray(4096)
        val output=object:ByteArrayOutputStream() { fun wipe() { buf.fill(0); reset() } }
        var bytes:ByteArray?=null
        try {
            response.body.byteStream().use { stream ->
                while(true) {
                    gate.checkHttp("POST",NativeExportPolicy.PATH)
                    val count=stream.read(buffer); if(count<0) break
                    if(count==0 || output.size()+count>16_384) throw AuthFailure(AuthCode.ACCESS_DENIED)
                    output.write(buffer,0,count)
                }
            }
            bytes=output.toByteArray()
            val text=Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT)
                .decode(ByteBuffer.wrap(bytes)).toString()
            val body=NativeVaultJson.decode(text)
            gate.checkHttp("POST",NativeExportPolicy.PATH)
            return NativeExportPolicy.error(response.code,body)
        } finally { buffer.fill(0); bytes?.fill(0); output.wipe() }
    }
}
