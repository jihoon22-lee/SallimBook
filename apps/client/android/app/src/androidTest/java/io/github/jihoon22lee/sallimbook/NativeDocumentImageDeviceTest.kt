package io.github.jihoon22lee.sallimbook

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.jihoon22lee.sallimbook.auth.NativeDocumentBytes
import io.github.jihoon22lee.sallimbook.auth.NativeDocumentImage
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** The framework ImageDecoder path only exists on a device: orientation, metadata and trailers.
 * Synthetic in-memory images only; no files, network, credentials or Activity.
 */
@RunWith(AndroidJUnit4::class)
class NativeDocumentImageDeviceTest {
    private fun source(width: Int, height: Int, leftDark: Boolean): ByteArray {
        val bitmap = Bitmap.createBitmap(width, height, Bitmap.Config.ARGB_8888)
        Canvas(bitmap).apply {
            drawColor(Color.WHITE)
            if (leftDark) drawRect(0f, 0f, width / 2f, height.toFloat(), Paint().apply { color = Color.BLACK })
            drawText("SYNTHETIC RECEIPT", width * 0.55f, height / 2f, Paint().apply { color = Color.GRAY; textSize = height / 12f })
        }
        return ByteArrayOutputStream().also { bitmap.compress(Bitmap.CompressFormat.JPEG, 92, it); bitmap.recycle() }.toByteArray()
    }
    private fun segment(marker: Int, payload: ByteArray): ByteArray =
        ByteBuffer.allocate(4 + payload.size).putShort((0xff00 or marker).toShort()).putShort((payload.size + 2).toShort()).put(payload).array()
    private fun withSegments(jpeg: ByteArray, segments: List<ByteArray>, trailer: ByteArray = ByteArray(0)) =
        jpeg.copyOfRange(0, 2) + segments.fold(ByteArray(0)) { all, next -> all + next } + jpeg.copyOfRange(2, jpeg.size) + trailer
    private fun exifOrientation(value: Int): ByteArray {
        val tiff = ByteBuffer.allocate(26).put("MM".toByteArray()).putShort(42).putInt(8).putShort(1)
            .putShort(0x0112).putShort(3).putInt(1).putShort(value.toShort()).putShort(0).putInt(0).array()
        return segment(0xe1, "Exif\u0000\u0000".toByteArray(Charsets.ISO_8859_1) + tiff)
    }
    private fun xmp() = segment(0xe1, "http://ns.adobe.com/xap/1.0/\u0000<x:xmpmeta xmlns:x=\"adobe:ns:meta/\"/>".toByteArray(Charsets.ISO_8859_1))
    private fun mpf() = segment(0xe2, "MPF\u0000MM\u0000*\u0000\u0000\u0000\u0008".toByteArray(Charsets.ISO_8859_1))
    private fun seftTrailer() = ("\u0000\u0000\u0000\u0018ftypmp42\u0000\u0000\u0000\u0000mp42isom" +
        "SEFHsynthetic camera trailer onlySEFT").toByteArray(Charsets.ISO_8859_1)
    /** Markers as "e0:JFIF" style strings and the byte count after EOI. */
    private fun segments(jpeg: ByteArray): Pair<List<String>, Int> {
        val markers = mutableListOf<String>()
        var position = 2
        while (position < jpeg.size) {
            assertEquals(0xff, jpeg[position].toInt() and 0xff)
            while (jpeg[position].toInt() and 0xff == 0xff) position++
            val marker = jpeg[position++].toInt() and 0xff
            if (marker == 0xd9) return markers to (jpeg.size - position)
            val length = ((jpeg[position].toInt() and 0xff) shl 8) or (jpeg[position + 1].toInt() and 0xff)
            val payload = jpeg.copyOfRange(position + 2, minOf(position + length, position + 34))
            val prefix = if (marker in 0xe0..0xef) String(payload, Charsets.ISO_8859_1).takeWhile { it.code in 0x20..0x7e } else ""
            markers += "%x:%s".format(marker, prefix)
            position += length
            if (marker == 0xda) {
                while (position + 1 < jpeg.size) {
                    val next = jpeg[position + 1].toInt() and 0xff
                    if (jpeg[position].toInt() and 0xff != 0xff) position++
                    else if (next == 0x00 || next in 0xd0..0xd7) position += 2
                    else if (next == 0xff) position++
                    else break
                }
            }
        }
        fail("synthetic jpeg without EOI"); return markers to -1
    }
    private fun meanRed(bitmap: Bitmap, top: Boolean): Double {
        val quarter = bitmap.height / 4
        val start = if (top) 0 else bitmap.height - quarter
        var total = 0L
        for (y in start until start + quarter step 8) for (x in 0 until bitmap.width step 8) total += Color.red(bitmap.getPixel(x, y))
        return total.toDouble() / (((quarter + 7) / 8) * ((bitmap.width + 7) / 8))
    }

    @Test fun cameraJpegLosesMetadataAndTrailerAndAppliesOrientation() {
        val input = withSegments(source(4000, 1000, leftDark = true), listOf(exifOrientation(6), xmp(), mpf()), seftTrailer())
        val output = NativeDocumentImage.normalizeJpeg(NativeDocumentBytes.fromEncoded(input, input.size)) {}!!
        output.useBytes { bytes, size ->
            val (markers, trailing) = segments(bytes.copyOf(size))
            assertEquals(0, trailing)
            assertTrue(markers.toString(), markers.all { it in setOf("e0:JFIF", "e2:ICC_PROFILE", "ee:Adobe", "db:", "c0:", "c2:", "c4:", "dd:", "da:") })
            val bitmap = BitmapFactory.decodeByteArray(bytes, 0, size)
            assertEquals(768, bitmap.width); assertEquals(3072, bitmap.height)
            assertTrue(meanRed(bitmap, top = true) < 64); assertTrue(meanRed(bitmap, top = false) > 192)
            bitmap.recycle()
        }
    }
    @Test fun normalizationIsDeterministic() {
        val input = withSegments(source(1600, 1200, leftDark = false), listOf(exifOrientation(1)), seftTrailer())
        val first = NativeDocumentImage.normalizeJpeg(NativeDocumentBytes.fromEncoded(input.copyOf(), input.size)) {}!!
        val second = NativeDocumentImage.normalizeJpeg(NativeDocumentBytes.fromEncoded(input.copyOf(), input.size)) {}!!
        assertEquals(first.checksum, second.checksum)
    }
    @Test fun undecodableBytesReturnNull() {
        val data = "SYNTHETIC DOCUMENT FIXTURE ONLY".toByteArray()
        assertNull(NativeDocumentImage.normalizeJpeg(NativeDocumentBytes.fromEncoded(data, data.size)) {})
    }
}
