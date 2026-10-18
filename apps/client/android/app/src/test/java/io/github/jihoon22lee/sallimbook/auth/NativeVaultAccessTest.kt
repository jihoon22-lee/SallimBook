package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class NativeVaultAccessTest {
    @Test fun eachRequestAcquiresAFreshEnoughLeaseAfterSnapshotAndKdfDelay() {
        var now=59_000L; var expires=60_000L; var lease="synthetic-old"; var renewals=0
        val access=NativeVaultAccess(ForegroundRequest()) { required ->
            if(!NativeAccessLifetime.usable(now,expires,required)) { renewals++; lease="synthetic-$renewals"; expires=now+60_000 }
            lease
        }
        val observed=mutableListOf<String>()
        access.send { observed.add(it) } // Only 1s remains: renew before even the first identity call.
        now+=6_000; access.send { observed.add(it) }
        now+=40_000; access.send { observed.add(it) } // Snapshot/KDF spent the original lease.
        assertEquals(listOf("synthetic-1","synthetic-1","synthetic-2"),observed); assertEquals(2,renewals)
    }
    @Test fun leaseMustCoverWholeHttpDeadlineAndMargin() {
        assertFalse(NativeAccessLifetime.usable(100,100,0))
        assertFalse(NativeAccessLifetime.usable(100,20_100,NativeVaultAccess.REQUIRED_MILLIS))
        assertTrue(NativeAccessLifetime.usable(100,20_101,NativeVaultAccess.REQUIRED_MILLIS))
        assertFalse(NativeAccessLifetime.usable(100,90,0))
    }
    @Test fun unauthorizedMutationResponseIsReturnedOnceWithoutAutomaticReplay() {
        var acquisitions=0; var requests=0
        val access=NativeVaultAccess(ForegroundRequest()) { acquisitions++; "synthetic" }
        assertEquals(401,access.send { requests++; 401 })
        assertEquals(1,requests); assertEquals(1,acquisitions)
    }
    @Test fun cancellationBeforeOrDuringRefreshPreventsHttp() {
        var requests=0; var acquisitions=0
        val before=ForegroundRequest().also { it.cancel() }
        try { NativeVaultAccess(before) { acquisitions++; "synthetic" }.send { requests++ }; fail("Canceled request sent") }
        catch (_:AuthFailure) { }
        assertEquals(0,acquisitions)
        val during=ForegroundRequest()
        try { NativeVaultAccess(during) { acquisitions++; during.cancel(); "synthetic" }.send { requests++ }; fail("Canceled refresh sent") }
        catch (_:AuthFailure) { }
        assertEquals(1,acquisitions); assertEquals(0,requests)
    }
}
