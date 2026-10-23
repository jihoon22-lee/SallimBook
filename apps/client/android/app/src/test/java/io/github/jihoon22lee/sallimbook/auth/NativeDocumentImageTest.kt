package io.github.jihoon22lee.sallimbook.auth

import java.security.MessageDigest
import org.junit.Assert.*
import org.junit.Test

class NativeDocumentImageTest {
    @Test fun targetSizeKeepsAspectAndBoundsTheLongEdge() {
        assertEquals(3072 to 2304, NativeDocumentImage.targetSize(4000, 3000))
        assertEquals(768 to 3072, NativeDocumentImage.targetSize(1000, 4000))
        assertEquals(1200 to 700, NativeDocumentImage.targetSize(1200, 700))
        assertEquals(3072 to 1, NativeDocumentImage.targetSize(16000, 1))
    }
    @Test fun encodedBytesAreChecksummedAndWipedOnClose() {
        val data = "SYNTHETIC JPEG BYTES".toByteArray()
        val expected = MessageDigest.getInstance("SHA-256").digest(data.copyOf()).joinToString("") { "%02x".format(it) }
        val content = NativeDocumentBytes.fromEncoded(data, data.size)
        assertEquals(data.size, content.size); assertEquals(expected, content.checksum)
        content.close()
        assertTrue(data.all { it == 0.toByte() })
        try { content.useBytes { _, _ -> Unit }; fail() } catch (f: AuthFailure) { assertEquals(AuthCode.AUTH_CANCELLED, f.code) }
        try { NativeDocumentBytes.fromEncoded(ByteArray(0), 0); fail() } catch (f: AuthFailure) { assertEquals(AuthCode.INVALID_REQUEST, f.code) }
    }
    @Test fun webAndAndroidShareTheLongEdgeAndQuality() {
        val web = java.io.File("../../src/features/documents/normalize.ts").readText()
        assertTrue(web.contains("MAX_LONG_EDGE = ${NativeDocumentImage.MAX_LONG_EDGE};"))
        assertTrue(web.contains("JPEG_QUALITY = 0.${NativeDocumentImage.JPEG_QUALITY / 10};"))
    }
    @Test fun outOfMemoryReturnsNullInsteadOfCrashing() {
        // ImageDecoder runs only on a device; pin that an OOM returns null (upload refused) instead of crashing.
        val source = java.io.File("src/main/java/io/github/jihoon22lee/sallimbook/auth/NativeDocumentImage.kt").readText()
        val handler = source.substringAfter("catch (_: OutOfMemoryError) {").substringBefore("}")
        assertTrue(handler, handler.contains("output.wipe(); return null"))
    }
    private fun bytes(text: String) = text.toByteArray().let { NativeDocumentBytes.fromEncoded(it, it.size) }
    private fun closed(content: NativeDocumentBytes) =
        try { content.useBytes { _, _ -> Unit }; false } catch (f: AuthFailure) { f.code == AuthCode.AUTH_CANCELLED }
    @Test fun aJpegThatCannotBeNormalizedYieldsNoUploadBytes() {
        val original = bytes("SYNTHETIC JPEG WITH LOCATION")
        assertNull(NativeDocumentImage.uploadContent("image/jpeg", original) { null })
        assertTrue(closed(original))
    }
    @Test fun aNormalizedJpegReplacesTheOriginal() {
        val original = bytes("SYNTHETIC JPEG WITH LOCATION")
        val copy = bytes("SYNTHETIC CLEAN COPY")
        assertSame(copy, NativeDocumentImage.uploadContent("image/jpeg", original) { copy })
        assertTrue(closed(original)); assertFalse(closed(copy))
        copy.close()
    }
    @Test fun pngAndPdfUploadUnchangedWithoutNormalizing() {
        for (mime in listOf("image/png", "application/pdf")) {
            val original = bytes("SYNTHETIC $mime")
            assertSame(original, NativeDocumentImage.uploadContent(mime, original) { fail("normalized $mime"); null })
            assertFalse(closed(original))
            original.close()
        }
    }
}
