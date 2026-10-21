package io.github.jihoon22lee.sallimbook.auth

import android.graphics.Bitmap
import android.graphics.ImageDecoder
import android.os.Build
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer

/**
 * Camera JPEG normalization before upload: the framework decoder applies EXIF orientation,
 * the long edge is bounded and re-encoding drops metadata and vendor trailers. Must match
 * the web client's normalize.ts (pinned by a JVM test). Call only off the UI thread.
 */
internal object NativeDocumentImage {
    const val MAX_LONG_EDGE = 3072
    const val JPEG_QUALITY = 90

    fun targetSize(width: Int, height: Int): Pair<Int, Int> {
        val scale = minOf(1.0, MAX_LONG_EDGE.toDouble() / maxOf(width, height))
        return maxOf(1, Math.round(width * scale).toInt()) to maxOf(1, Math.round(height * scale).toInt())
    }

    private class WipeableOutput : ByteArrayOutputStream() {
        fun buffer(): ByteArray = buf
        fun wipe() { buf.fill(0); reset() }
    }

    /** Null when the bytes cannot be decoded or encoded; the caller then uploads the original. */
    fun normalizeJpeg(content: NativeDocumentBytes, check: () -> Unit): NativeDocumentBytes? {
        var bitmap: Bitmap? = null
        val output = WipeableOutput()
        try {
            check()
            val source = content.useBytes { bytes, size -> ImageDecoder.createSource(ByteBuffer.wrap(bytes, 0, size)) }
            val decoded = ImageDecoder.decodeBitmap(source) { decoder, info, _ ->
                decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
                val (width, height) = targetSize(info.size.width, info.size.height)
                decoder.setTargetSize(width, height)
            }
            bitmap = decoded
            // Ultra HDR photos decode with a gain map that compress() would write back as an
            // XMP/MPF secondary image; the upload keeps the SDR base image only.
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE && decoded.hasGainmap()) decoded.gainmap = null
            check()
            if (!decoded.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, output)) { output.wipe(); return null }
            decoded.recycle(); bitmap = null
            check()
            return NativeDocumentBytes.fromEncoded(output.buffer(), output.size())
        } catch (failure: AuthFailure) {
            output.wipe(); throw failure
        } catch (_: Exception) {
            output.wipe(); return null
        } catch (_: OutOfMemoryError) {
            // A large photo on a low-memory phone falls back to the original bytes, not a crash.
            output.wipe(); return null
        } finally {
            bitmap?.recycle()
        }
    }
}
