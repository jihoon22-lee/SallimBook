package io.github.jihoon22lee.sallimbook.auth

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.InputStream
import java.io.OutputStream
import java.security.MessageDigest
import org.junit.Assert.*
import org.junit.Test

class NativeExportBytesTest {
    private val data=byteArrayOf(0x50,0x4b,3,4)+"synthetic export data".toByteArray()
    private fun checksum(bytes:ByteArray)=MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it.toInt() and 255) }
    private fun bad(action:()->Unit) { try { action(); fail("Invalid export bytes accepted") } catch(_:AuthFailure) { } }
    @Test fun onlyVerifiedExactBytesCanBeWrittenAndClosedOwnersCannotWriteAgain() {
        val content=NativeExportBytes.read(ByteArrayInputStream(data),data.size.toLong(),checksum(data)) { }
        val output=ByteArrayOutputStream(); content.writeTo(output) { }; assertArrayEquals(data,output.toByteArray())
        assertEquals(data.size,content.size); assertFalse(content.toString().contains("synthetic")); content.close()
        val rejected=ByteArrayOutputStream(); bad { content.writeTo(rejected) { } }; assertEquals(0,rejected.size())
    }
    @Test fun absentInvalidShortOversizedTrailingNonZipAndMismatchedHashFailBeforeOutput() {
        for(size in listOf(0L,3L,NativeExportBytes.MAX_BYTES.toLong()+1,data.size.toLong()-1,data.size.toLong()+1))
            bad { NativeExportBytes.read(ByteArrayInputStream(data),size,checksum(data)) { } }
        for(hash in listOf("","0".repeat(64),checksum(data).uppercase(),"../synthetic")) bad { NativeExportBytes.read(ByteArrayInputStream(data),data.size.toLong(),hash) { } }
        val html="<html>synthetic</html>".toByteArray(); bad { NativeExportBytes.read(ByteArrayInputStream(html),html.size.toLong(),checksum(html)) { } }
    }
    @Test fun canceledOrExpiredReadHasNoDeliverableArchiveAndWipesOwnedBuffer() {
        val gate=ForegroundRequest(); var owned:ByteArray?=null
        val stream=object:InputStream() {
            override fun read()=-1
            override fun read(b:ByteArray,off:Int,len:Int):Int { owned=b; data.copyInto(b,off); gate.cancel(); return data.size }
        }
        bad { NativeExportBytes.read(stream,data.size.toLong(),checksum(data),gate::check) }
        assertNotNull(owned); assertTrue(owned!!.all { it==0.toByte() })
    }
    @Test fun cancelBetweenProviderChunksStopsFurtherWritesAndLateSuccess() {
        val source=byteArrayOf(0x50,0x4b,3,4)+ByteArray(20_000) { 42 }
        val content=NativeExportBytes.read(ByteArrayInputStream(source),source.size.toLong(),checksum(source)) { }
        val gate=ForegroundRequest(); var count=0
        val output=object:OutputStream() {
            override fun write(b:Int) { error("Unexpected scalar write") }
            override fun write(b:ByteArray,off:Int,len:Int) { count+=len; gate.cancel() }
        }
        try { bad { content.writeTo(output,gate::check) }; assertEquals(8192,count) } finally { content.close() }
    }
    @Test fun zeroReadAndExactDeadlineDuringFinalDigestCheckDiscardBuffer() {
        val zero=object:InputStream() { override fun read()=0; override fun read(b:ByteArray,off:Int,len:Int)=0 }
        bad { NativeExportBytes.read(zero,data.size.toLong(),checksum(data)) { } }
        var checks=0
        bad { NativeExportBytes.read(ByteArrayInputStream(data),data.size.toLong(),checksum(data)) { if(++checks==4) throw AuthFailure(AuthCode.AUTH_CANCELLED) } }
        assertEquals(4,checks)
    }
}
