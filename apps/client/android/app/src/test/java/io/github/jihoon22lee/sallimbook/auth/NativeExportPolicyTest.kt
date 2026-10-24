package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class NativeExportPolicyTest {
    private val id="00000000-0000-4000-8000-000000000001"
    private fun bad(action:()->Unit) { try { action(); fail("Unsafe export selection accepted") } catch(_:AuthFailure) { } }
    @Test fun defaultsAndExactSelectionsAreCopiedBeforeNativeWork() {
        assertEquals(mapOf("formats" to listOf("json","csv"),"document_ids" to emptyList<String>()),NativeExportPolicy.arguments(mapOf("input" to emptyMap<String,Any>())).body())
        val formats=mutableListOf("csv"); val docs=mutableListOf(id)
        val selected=NativeExportPolicy.arguments(mapOf("input" to mapOf("formats" to formats,"document_ids" to docs)))
        formats.clear(); docs.clear(); assertEquals(listOf("csv"),selected.formats); assertEquals(listOf(id),selected.documents)
        assertEquals("/api/v1/exports",NativeExportPolicy.PATH); assertFalse(selected.toString().contains(id))
    }
    @Test fun extraFieldsAndNonCollectionsNeverReachTheTransport() {
        for(field in listOf("household_id","url","headers","password","token","bytes","path","uri","cvc","ciphertext")) {
            bad { NativeExportPolicy.arguments(mapOf("input" to emptyMap<String,Any>(),field to "synthetic")) }
            bad { NativeExportPolicy.selection(mapOf(field to "synthetic")) }
        }
        for(value in listOf(null,"json",listOf("json"),1)) bad { NativeExportPolicy.arguments(value) }
        bad { NativeExportPolicy.arguments(mapOf("formats" to listOf("json"))) }
        bad { NativeExportPolicy.selection(mapOf("formats" to null)) }; bad { NativeExportPolicy.selection(mapOf("document_ids" to id)) }
    }
    @Test fun formatAndDocumentLimitsRejectDuplicatesAndPathValues() {
        for(formats in listOf(emptyList(),listOf("json","json"),listOf("json","csv","json"),listOf("zip"),listOf("JSON"),listOf(1)))
            bad { NativeExportPolicy.selection(mapOf("formats" to formats)) }
        for(docs in listOf(listOf(id,id),listOf("../synthetic"),listOf("content://synthetic/1"),List(11) { "00000000-0000-4000-8000-${it.toString().padStart(12,'0')}" }))
            bad { NativeExportPolicy.selection(mapOf("document_ids" to docs)) }
        assertEquals(10,NativeExportPolicy.selection(mapOf("document_ids" to List(10) { "00000000-0000-4000-8000-${it.toString().padStart(12,'0')}" })).documents.size)
    }
    @Test fun readableOnlyScopeIsCopiedAndBoundedWithoutPathsOrSecrets() {
        val domains=mutableListOf("insurance", "homecare")
        val scope=mutableMapOf<String,Any?>("domains" to domains, "from_date" to "2024-02-29", "through_date" to "2024-03-01", "annual_year" to 2024L)
        val selected=NativeExportPolicy.selection(mapOf("formats" to emptyList<String>(), "readable" to scope))
        domains.clear(); scope.clear()
        assertEquals(listOf("insurance", "homecare"), selected.readable!!.domains)
        assertEquals(2024, selected.readable!!.year)
        assertEquals("2024-02-29", (selected.body()["readable"] as Map<*,*>)["from_date"])
        for(invalid in listOf(
            mapOf("domains" to emptyList<String>()), mapOf("domains" to listOf("vault")),
            mapOf("domains" to listOf("insurance","insurance")),
            mapOf("domains" to listOf("income"), "annual_year" to 2024),
            mapOf("domains" to listOf("insurance"), "annual_year" to 1.5),
            mapOf("domains" to listOf("insurance"), "annual_year" to 10000),
            mapOf("domains" to listOf("insurance"), "from_date" to "2025-02-29"),
            mapOf("domains" to listOf("insurance"), "from_date" to "0000-01-01"),
            mapOf("domains" to listOf("insurance"), "from_date" to "2025-03-01", "through_date" to "2025-02-28"),
            mapOf("domains" to listOf("insurance"), "household_id" to id),
            mapOf("domains" to listOf("insurance"), "url" to "https://synthetic.invalid/"),
        )) bad { NativeExportPolicy.selection(mapOf("readable" to invalid)) }
    }
    @Test fun serverErrorsAreStatusBoundAndNeverExposeRawDetails() {
        for((code,status) in NativeExportPolicy.errors) {
            val body=mapOf("error" to mapOf("code" to code,"message" to "synthetic private detail","details" to mapOf("uri" to "content://synthetic/private")))
            assertEquals(code,NativeExportPolicy.error(status,body)); assertEquals("ACCESS_DENIED",NativeExportPolicy.error(500,body))
            assertFalse(NativeExportPolicy.message(code).contains("synthetic"))
        }
        assertEquals("SESSION_EXPIRED",NativeExportPolicy.error(401,null)); assertEquals("RATE_LIMITED",NativeExportPolicy.error(429,null))
        assertEquals("ACCESS_DENIED",NativeExportPolicy.error(503,mapOf("error" to mapOf("code" to "UNKNOWN_RAW_DETAIL"))))
    }
    @Test fun independentAuthenticationPickerTransferAndWriteDeadlinesAreStrict() {
        var now=0L; val flow=NativeExportFlow { now }
        flow.beginAuthentication(); now+=59_999; flow.beginPicker(); now+=59_999; flow.beginTransfer()
        now+=179_999; flow.beginWrite(); now+=179_999; flow.finish()
        bad { flow.finish() }; bad { flow.beginAuthentication() }
        for(phase in listOf(NativeExportFlow.Phase.AUTH,NativeExportFlow.Phase.PICKER,NativeExportFlow.Phase.TRANSFER,NativeExportFlow.Phase.WRITE)) {
            now=0; val candidate=NativeExportFlow { now }; candidate.beginAuthentication()
            if(phase!=NativeExportFlow.Phase.AUTH) candidate.beginPicker()
            if(phase in setOf(NativeExportFlow.Phase.TRANSFER,NativeExportFlow.Phase.WRITE)) candidate.beginTransfer()
            if(phase==NativeExportFlow.Phase.WRITE) candidate.beginWrite()
            now=phase.millis; bad { candidate.check(phase) }
        }
    }
    @Test fun cancelRollbackAndOutOfOrderOperationsCannotAuthorizeAWriteOrLateSuccess() {
        var now=100L; val flow=NativeExportFlow { now }; bad { flow.beginWrite() }
        flow.beginAuthentication(); now--; bad { flow.check(NativeExportFlow.Phase.AUTH) }; now=100
        flow.beginPicker(); bad { flow.beginWrite() }; flow.close()
        bad { flow.beginTransfer() }; bad { flow.finish() }; bad { flow.beginAuthentication() }
    }
}
