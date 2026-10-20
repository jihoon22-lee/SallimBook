package io.github.jihoon22lee.sallimbook.auth

import java.io.Closeable
import java.io.InputStream
import java.io.OutputStream
import java.security.MessageDigest

/** Only the explicitly launched picker may cover the Activity, with no I/O in that phase. */
internal class NativeDocumentFlow(private val clock: () -> Long) {
    private enum class Phase { ACTIVE, PICKER, RETURNED, CANCELLED }
    private var phase = Phase.ACTIVE
    private var departedAt = 0L
    private var returnedAt = 0L
    fun beginPicker(): Boolean {
        if (phase != Phase.ACTIVE) return false
        phase = Phase.PICKER; departedAt = clock()
        return true
    }
    fun keepPicker(): Boolean {
        val now = clock()
        val valid = when (phase) {
            Phase.PICKER -> now >= departedAt && now - departedAt < 60_000
            Phase.RETURNED -> now >= returnedAt && now - returnedAt < 1000 && now >= departedAt && now - departedAt < 60_000
            else -> false
        }
        if (!valid && phase in setOf(Phase.PICKER, Phase.RETURNED)) cancel()
        return valid
    }
    fun pickerReturned(): Boolean {
        if (phase != Phase.PICKER || !keepPicker()) return false
        phase = Phase.RETURNED; returnedAt = clock()
        return true
    }
    fun resumePicker(): Boolean {
        if (phase != Phase.RETURNED || !keepPicker()) return false
        phase = Phase.ACTIVE
        return true
    }
    fun cancel() { phase = Phase.CANCELLED }
}

/** A single bounded native buffer, never a JSON value, Intent extra, or disk cache. */
internal class NativeDocumentBytes private constructor(private val bytes: ByteArray, val size: Int, val checksum: String) : Closeable {
    companion object {
        const val MAX_BYTES = 20 * 1024 * 1024
        const val TRANSFER_MILLIS = 180_000L
        fun read(input: InputStream, expectedSize: Long?, check: () -> Unit): NativeDocumentBytes {
            if (expectedSize != null && expectedSize !in 1..MAX_BYTES.toLong()) throw AuthFailure(AuthCode.INVALID_REQUEST)
            val buffer = ByteArray((expectedSize?.toInt() ?: MAX_BYTES) + 1)
            var count = 0
            try {
                while (true) {
                    check()
                    val read = input.read(buffer, count, minOf(8192, buffer.size - count))
                    if (read < 0) break
                    if (read == 0) throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
                    count += read
                    if (count == buffer.size || count > MAX_BYTES) throw AuthFailure(AuthCode.INVALID_REQUEST)
                }
                check()
                if (count == 0 || expectedSize != null && count.toLong() != expectedSize) throw AuthFailure(AuthCode.INVALID_REQUEST)
                val digest = MessageDigest.getInstance("SHA-256").apply { update(buffer, 0, count) }.digest()
                val checksum = digest.joinToString("") { "%02x".format(it.toInt() and 255) }
                digest.fill(0)
                return NativeDocumentBytes(buffer, count, checksum)
            } catch (failure: Throwable) { buffer.fill(0); throw failure }
        }
        /** Takes ownership of an already encoded buffer (no copy); [close] wipes it. */
        fun fromEncoded(bytes: ByteArray, size: Int): NativeDocumentBytes {
            if (size !in 1..MAX_BYTES || size > bytes.size) { bytes.fill(0); throw AuthFailure(AuthCode.INVALID_REQUEST) }
            val digest = MessageDigest.getInstance("SHA-256").apply { update(bytes, 0, size) }.digest()
            val checksum = digest.joinToString("") { "%02x".format(it.toInt() and 255) }
            digest.fill(0)
            return NativeDocumentBytes(bytes, size, checksum)
        }
    }
    @Volatile private var discarded = false
    fun <T> useBytes(action: (ByteArray, Int) -> T): T {
        if (discarded) throw AuthFailure(AuthCode.AUTH_CANCELLED)
        return action(bytes, size)
    }
    fun writeTo(output: OutputStream, check: () -> Unit) {
        var offset = 0
        while (offset < size) {
            check()
            if (discarded) throw AuthFailure(AuthCode.AUTH_CANCELLED)
            val length = minOf(8192, size - offset)
            output.write(bytes, offset, length)
            offset += length
        }
        check()
    }
    override fun close() { discarded = true; bytes.fill(0) }
    override fun toString() = "NativeDocumentBytes(redacted)"
}
