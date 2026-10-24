package io.github.jihoon22lee.sallimbook.auth

import java.io.Closeable
import java.io.InputStream
import java.io.OutputStream
import java.security.MessageDigest

/** Bounded native ownership only: no JSON, Intent, URI, disk cache or WebView representation. */
internal class NativeExportBytes private constructor(private val bytes:ByteArray,val size:Int) : Closeable {
    companion object {
        const val MAX_BYTES=64*1024*1024
        const val TRANSFER_MILLIS=180_000L
        fun read(input:InputStream,size:Long,checksum:String,allocate:(Int)->ByteArray={ ByteArray(it) },check:()->Unit):NativeExportBytes {
            if(size !in 4..MAX_BYTES.toLong() || !Regex("[0-9a-f]{64}").matches(checksum)) throw AuthFailure(AuthCode.ACCESS_DENIED)
            // The archive is held whole in memory; a device without room for it gets the size message.
            val bytes=try { allocate(size.toInt()+1) } catch(_:OutOfMemoryError) { throw NativeExportTooLarge() }
            var count=0
            try {
                while(true) {
                    check(); val n=input.read(bytes,count,minOf(8192,bytes.size-count))
                    if(n<0) break
                    if(n==0) throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
                    count+=n; if(count>size) throw AuthFailure(AuthCode.ACCESS_DENIED)
                }
                check()
                if(count.toLong()!=size || bytes[0]!=0x50.toByte() || bytes[1]!=0x4b.toByte() || bytes[2]!=3.toByte() || bytes[3]!=4.toByte())
                    throw AuthFailure(AuthCode.ACCESS_DENIED)
                val digest=MessageDigest.getInstance("SHA-256").apply { update(bytes,0,count) }.digest()
                val expected=checksum.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
                try { if(!MessageDigest.isEqual(expected,digest)) throw AuthFailure(AuthCode.ACCESS_DENIED) }
                finally { digest.fill(0); expected.fill(0) }
                check(); return NativeExportBytes(bytes,count)
            } catch(failure:Throwable) { bytes.fill(0); throw failure }
        }
    }
    @Volatile private var discarded=false
    fun writeTo(output:OutputStream,check:()->Unit) {
        var offset=0
        while(offset<size) {
            check(); if(discarded) throw AuthFailure(AuthCode.AUTH_CANCELLED)
            val count=minOf(8192,size-offset); output.write(bytes,offset,count); offset+=count
        }
        check(); if(discarded) throw AuthFailure(AuthCode.AUTH_CANCELLED)
    }
    override fun close() { discarded=true; bytes.fill(0) }
    override fun toString()="NativeExportBytes(redacted)"
}

internal class NativeExportTooLarge : Exception()

internal class NativeExportArchive(val id:String,val content:NativeExportBytes):Closeable {
    override fun close()=content.close()
    override fun toString()="NativeExportArchive(redacted)"
}
internal class NativeExportResponse(val code:String?=null,val archive:NativeExportArchive?=null) {
    override fun toString()="NativeExportResponse(redacted)"
}
