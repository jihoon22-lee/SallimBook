package io.github.jihoon22lee.sallimbook.auth

import java.io.ByteArrayInputStream
import java.io.ByteArrayOutputStream
import java.io.InputStream
import org.junit.Assert.*
import org.junit.Test

class NativeDocumentTransferTest {
    private fun denied(action: () -> Unit) {
        try { action(); fail("Invalid synthetic document accepted") }
        catch (failure: AuthFailure) { assertNull(failure.message) }
    }
    @Test fun pickerLifetimeIsBoundedAndRepeatedPauseCannotExtendIt() {
        var now = 0L
        val flow = NativeDocumentFlow { now }
        assertTrue(flow.beginPicker())
        now = 59_999
        assertTrue(flow.keepPicker())
        assertTrue(flow.keepPicker())
        now = 60_000
        assertFalse(flow.keepPicker())
        assertFalse(flow.pickerReturned())
    }
    @Test fun providerResultWaitsForForegroundAndCannotBeReused() {
        var now = 0L
        val flow = NativeDocumentFlow { now }
        flow.beginPicker(); now = 500
        assertTrue(flow.pickerReturned())
        assertTrue(flow.keepPicker())
        assertTrue(flow.resumePicker())
        assertFalse(flow.resumePicker())
        assertFalse(flow.keepPicker())
        assertFalse(flow.pickerReturned())
    }
    @Test fun lateFocusCancellationAndClockRollbackFailClosed() {
        var now = 500L
        val flow = NativeDocumentFlow { now }
        flow.beginPicker(); flow.pickerReturned(); now += 1000
        assertFalse(flow.resumePicker())
        val rollback = NativeDocumentFlow { now }
        rollback.beginPicker(); now--
        assertFalse(rollback.keepPicker())
        val cancelled = NativeDocumentFlow { now }
        cancelled.beginPicker(); cancelled.cancel()
        assertFalse(cancelled.pickerReturned()); assertFalse(cancelled.beginPicker())
    }
    @Test fun bytesAreBoundedHashedOnceAndWipedOnDiscard() {
        val raw = "synthetic document bytes".toByteArray()
        val content = NativeDocumentBytes.read(ByteArrayInputStream(raw), raw.size.toLong()) {}
        assertEquals(raw.size, content.size)
        assertEquals("cd0ae5ea7c937481dba1c94d53e3fc764d0c052760463b7eb24a73c88e2fe050", content.checksum)
        val output = ByteArrayOutputStream()
        content.writeTo(output) {}
        assertArrayEquals(raw, output.toByteArray())
        assertFalse(content.toString().contains("synthetic"))
        content.close(); content.close()
        denied { content.writeTo(ByteArrayOutputStream()) {} }
    }
    @Test fun sizeHintsCannotBypassActualLimitOrEmptyFileChecks() {
        denied { NativeDocumentBytes.read(ByteArrayInputStream(byteArrayOf()), null) {} }
        denied { NativeDocumentBytes.read(ByteArrayInputStream(byteArrayOf(1, 2)), 1) {} }
        denied { NativeDocumentBytes.read(ByteArrayInputStream(byteArrayOf(1)), 2) {} }
        denied { NativeDocumentBytes.read(ByteArrayInputStream(byteArrayOf(1)), 0) {} }
        denied { NativeDocumentBytes.read(ByteArrayInputStream(byteArrayOf(1)), 20_971_521) {} }
        val large = object : InputStream() {
            private var remaining = NativeDocumentBytes.MAX_BYTES + 1
            override fun read(): Int = if (remaining-- > 0) 1 else -1
            override fun read(buffer: ByteArray, offset: Int, count: Int): Int {
                if (remaining <= 0) return -1
                val n = minOf(remaining, count); buffer.fill(1, offset, offset + n); remaining -= n; return n
            }
        }
        denied { NativeDocumentBytes.read(large, null) {} }
    }
    @Test fun cancellationIsCheckedDuringReadAndBeforeEveryWrite() {
        var checks = 0
        denied { NativeDocumentBytes.read(ByteArrayInputStream(ByteArray(20_000) { 1 }), null) {
            if (++checks == 2) throw AuthFailure(AuthCode.AUTH_CANCELLED)
        } }
        val content = NativeDocumentBytes.read(ByteArrayInputStream(ByteArray(20_000) { 1 }), null) {}
        val output = ByteArrayOutputStream(); checks = 0
        try { denied { content.writeTo(output) { if (++checks == 2) throw AuthFailure(AuthCode.AUTH_CANCELLED) } } }
        finally { content.close() }
        assertTrue(output.size() < 20_000)
    }
    @Test fun aFileTooLargeForTheDevicesMemoryIsReportedInsteadOfCrashing() {
        for (size in listOf<Long?>(4, null)) {
            try {
                NativeDocumentBytes.read(ByteArrayInputStream(byteArrayOf(1, 2, 3, 4)), size, { throw OutOfMemoryError() }) {}
                fail("Synthetic allocation failure ignored")
            } catch (_: NativeDocumentTooLarge) {}
        }
        assertTrue(NativeDocumentPolicy.errorMessage(NativeDocumentBytes.TOO_LARGE_CODE).contains("파일이 너무 커요"))
        // Upload (picker read) and download (network read) both end with that message.
        val source = { name: String -> java.io.File("src/main/java/io/github/jihoon22lee/sallimbook/auth/$name").readText() }
        assertTrue(source("NativeDocumentActivity.kt").contains("catch (_: NativeDocumentTooLarge) { main.post { failure(AuthCode.INVALID_REQUEST, NativeDocumentBytes.TOO_LARGE_CODE) } }"))
        assertTrue(source("NativeDocumentHttp.kt").contains("catch (failure: NativeDocumentTooLarge) { throw failure }"))
        assertTrue(source("NativeAuthSession.kt").contains("\"error_code\" to NativeDocumentBytes.TOO_LARGE_CODE"))
    }
    @Test fun networkAndProviderCancellationOwnersCannotOverwriteEachOther() {
        val gate = ForegroundRequest(); val provider = Any(); val file = Any()
        var providerCalls = 0; var networkCalls = 0; var fileCalls = 0
        gate.bindCancellation(provider) { providerCalls++ }
        gate.bindCancellation(file) { fileCalls++ }
        gate.bindNetworkCancellation { networkCalls++ }
        gate.releaseNetworkCancellation()
        gate.bindNetworkCancellation { networkCalls++ }
        gate.releaseCancellation(file)
        gate.cancel(); gate.cancel()
        assertEquals(1, providerCalls); assertEquals(1, networkCalls); assertEquals(0, fileCalls)
        gate.bindCancellation(file) { fileCalls++ }
        assertEquals(1, fileCalls)
    }
    @Test fun oneBrokenCancellationHandlerDoesNotPreventOtherResourcesClosing() {
        val gate = ForegroundRequest(); var closed = false
        gate.bindCancellation(Any()) { throw IllegalStateException("synthetic") }
        gate.bindCancellation(Any()) { closed = true }
        gate.cancel()
        assertTrue(closed); assertFalse(gate.isActive())
    }
    @Test fun uploadReservesTokenLifetimeForTheWholeTransfer() {
        // The server re-checks the session after scanning; a token close to expiry is refreshed first.
        assertTrue(NativeDocumentBytes.REQUIRED_ACCESS_MILLIS > NativeDocumentBytes.TRANSFER_MILLIS)
        assertFalse(NativeAccessLifetime.usable(0, 180_000, NativeDocumentBytes.REQUIRED_ACCESS_MILLIS))
        assertTrue(NativeAccessLifetime.usable(0, 600_000, NativeDocumentBytes.REQUIRED_ACCESS_MILLIS))
        // A fresh 10-minute server lease covers the create deadline and the whole transfer.
        assertTrue(NativeAccessLifetime.usable(0, 600_000, NativeDocumentUploadLease.REQUIRED_MILLIS))
        val session = java.io.File("src/main/java/io/github/jihoon22lee/sallimbook/auth/NativeAuthSession.kt").readText()
        val flow = session.substringAfter("fun uploadDocument(").substringBefore("fun downloadDocument(")
        val leased = flow.substringAfter("NativeDocumentUploadLease.run({ access(gate, it) }) { token ->")
        assertNotEquals(flow, leased)
        assertFalse(flow.substringBefore("NativeDocumentUploadLease.run").contains("http.send"))
        assertTrue(leased, leased.contains("accessToken = token"))
        val upload = leased.substringAfter("documentHttp.upload(").substringBefore("if (uploaded.status")
        assertTrue(upload, upload.contains("content, token, gate)"))
    }
    @Test fun theUploadLeaseIsTakenBeforeTheCreateAndCoversBothCalls() {
        val requested = mutableListOf<Long>(); val sent = mutableListOf<String>()
        val result = NativeDocumentUploadLease.run({ requested.add(it); "synthetic-lease" }) { token -> sent.add(token); "created" }
        assertEquals("created", result); assertEquals(listOf("synthetic-lease"), sent)
        assertEquals(listOf(NativeDocumentUploadLease.REQUIRED_MILLIS), requested)
        assertTrue(NativeDocumentUploadLease.REQUIRED_MILLIS >= NativeDocumentBytes.REQUIRED_ACCESS_MILLIS + 15_000L)
    }
    @Test fun aFailedLeaseSendsNoCreate() {
        var sent = 0
        try {
            NativeDocumentUploadLease.run({ throw AuthFailure(AuthCode.AUTH_UNAVAILABLE) }) { sent++ }
            fail("Create sent without a lease")
        } catch (failure: AuthFailure) { assertEquals(AuthCode.AUTH_UNAVAILABLE, failure.code) }
        assertEquals(0, sent)
    }
}
