package io.github.jihoon22lee.sallimbook.auth

import java.util.Base64
import org.junit.Assert.*
import org.junit.Test

class NativeAuditWireTest {
    private val f=NativeVaultTestData
    private val instant="2026-10-18T03:04:05Z"
    private val upper="00000000-0000-4000-8000-000000000099"
    private fun row(id:String=f.resource,time:String=instant)=mapOf("id" to id,"actor_member_id" to f.member,"entity_type" to "asset","entity_id" to f.cardId,
        "action" to "update","request_id" to "synthetic-audit-1","before_version" to 1,"after_version" to 2,"occurred_at" to time,"changed_fields" to listOf("name"))
    private fun page(vararg rows:Map<String,Any?>,cursor:String?=null)=mapOf("items" to rows.toList(),"next_cursor" to cursor)
    private fun cursor(time:String=instant,id:String=f.resource)=Base64.getUrlEncoder().withoutPadding()
        .encodeToString("[\"$time\",\"$id\",\"${"a".repeat(64)}\"]".toByteArray())
    private fun request(query:Map<String,Any?> = emptyMap())=NativeAuditWire.prepare(mapOf("query" to query))
    private fun bad(code:AuthCode=AuthCode.INVALID_REQUEST,action:()->Unit) {
        try { action(); fail("Unsafe synthetic audit accepted") } catch(e:AuthFailure) { assertEquals(code,e.code); assertNull(e.message); assertNull(e.cause) }
    }
    @Test fun allFiltersHaveCanonicalFixedPathWithExplicitTimezoneEncodingAndNullOmission() {
        assertEquals("/api/v1/audit-events?limit=50",NativeAuditWire.prepare(emptyMap<String,Any>()).path)
        val query=mapOf("limit" to 200,"cursor" to cursor(),"entity_type" to "asset","entity_id" to f.cardId,"actor_member_id" to f.member,
            "action" to "update","since" to "2026-10-18T00:00:00+09:00","until" to "2026-10-19T00:00:00Z")
        val built=request(query); assertEquals(query,built.query); assertTrue(built.path.contains("%2B09%3A00")); assertEquals(200,built.limit)
        assertTrue(NativeAuditWire.httpAllowed("GET",built.path,null,null,null,null))
        assertEquals("/api/v1/audit-events?limit=50",request(mapOf("cursor" to null,"since" to null)).path)
        assertFalse(AuthPolicy.requestAllowed("GET",built.path,null))
        assertFalse(FinancePolicy.metadataHttpAllowed("GET",built.path,null,null,null))
    }
    @Test fun extraFieldsPrivateValuesHostsHeadersAndInvalidFiltersAreRejectedBeforeTransport() {
        for(field in listOf("url","path","headers","household_id","safe_diff","password","token","body","ifMatch")) {
            bad { NativeAuditWire.prepare(mapOf(field to "synthetic")) }; bad { request(mapOf(field to "synthetic")) }
        }
        for(value in listOf(null,emptyList<Any>(),"synthetic")) bad { NativeAuditWire.prepare(mapOf("query" to value)) }
        for(value in listOf(null,0,201,1.0,"50",true)) bad { request(mapOf("limit" to value)) }
        for(query in listOf(mapOf("entity_type" to "unknown"),mapOf("action" to "secret"),mapOf("entity_id" to "../synthetic"),
            mapOf("actor_member_id" to "https://synthetic.invalid"),mapOf("since" to "2026-10-18"),mapOf("since" to "2026-02-30T00:00:00Z"),
            mapOf("until" to "2026-10-18T00:00:00"),mapOf("since" to instant,"until" to instant))) bad { request(query) }
    }
    @Test fun cursorMustBeCanonicalBoundedMetadataAndHttpCannotSmuggleAlternateInputs() {
        for(value in listOf("",cursor()+"=","a".repeat(1025),"https://synthetic.invalid",Base64.getUrlEncoder().withoutPadding().encodeToString("[\"secret\"]".toByteArray()),
            cursor(time="2026-10-18T12:04:05+09:00"),cursor(id="../synthetic"))) bad { request(mapOf("cursor" to value)) }
        val path=request().path
        for(candidate in listOf("https://synthetic.invalid$path",path+"&limit=50",path+"&password=synthetic",path+"#synthetic",path.replace("50","050"),"/api/v1/audit-events",path.replace("limit","%6cimit")))
            assertFalse(NativeAuditWire.httpAllowed("GET",candidate,null,null,null,null))
        assertFalse(NativeAuditWire.httpAllowed("POST",path,null,null,null,null)); assertFalse(NativeAuditWire.httpAllowed("GET",path,emptyMap<String,Any>(),null,null,null))
        assertFalse(NativeAuditWire.httpAllowed("GET",path,null,"\"1\"",null,null)); assertFalse(NativeAuditWire.httpAllowed("GET",path,null,null,"synthetic",null))
        assertFalse(NativeAuditWire.httpAllowed("GET",path,null,null,null,"synthetic"))
    }
    @Test fun safeMetadataAndHistoricalActorsAreRetainedWithoutRawValues() {
        val historical=row()+mapOf("actor_member_id" to f.partner,"request_id" to null,"before_version" to null)
        val result=NativeAuditWire.response(request(),200,page(historical))
        assertEquals(page(historical+mapOf("after_version" to 2L)),result)
        // Names of sensitive columns are metadata, never their stored values.
        val fields=listOf("account_number","password_hash","wrapped_hvk")
        assertEquals(fields,((NativeAuditWire.response(request(),200,page(row()+mapOf("changed_fields" to fields)))["items"] as List<*>)[0] as Map<*,*>)["changed_fields"])
        assertEquals(43,NativeAuditWire.entityTypes.size); assertEquals(22,NativeAuditWire.actions.size); assertTrue(NativeAuditWire.knownFields.containsAll(setOf("annual_fee_krw", "is_family_card", "gross_krw", "net_cash_krw", "stock_grant_value_krw")))
    }
    @Test fun securityEventTypesAreAcceptedAndCounted() {
        assertEquals(43, NativeAuditWire.entityTypes.size); assertEquals(22, NativeAuditWire.actions.size)
        assertTrue(NativeAuditWire.entityTypes.contains("user"))
        assertTrue(NativeAuditWire.entityTypes.containsAll(setOf("registered_device", "passkey", "invitation")))
        assertTrue(NativeAuditWire.actions.containsAll(setOf("login", "revoke", "accept")))
        val login=row()+mapOf("entity_type" to "registered_device","action" to "login","changed_fields" to emptyList<String>())
        val parsed=(NativeAuditWire.response(request(),200,page(login))["items"] as List<*>)[0] as Map<*,*>
        assertEquals("registered_device" to "login",parsed["entity_type"] to parsed["action"])
    }
    @Test fun everyResponseFieldIsRequiredAndAnyRawDiffOrUnknownChangedFieldFailsClosed() {
        for(field in row().keys) bad(AuthCode.ACCESS_DENIED) { NativeAuditWire.response(request(),200,page(row()-field)) }
        for(field in listOf("safe_diff","before","after","pan","ciphertext","password","household_id")) {
            bad(AuthCode.ACCESS_DENIED) { NativeAuditWire.response(request(),200,page(row()+mapOf(field to "synthetic"))) }
            bad(AuthCode.ACCESS_DENIED) { NativeAuditWire.response(request(),200,page(row())+mapOf(field to "synthetic")) }
        }
        for(fields in listOf(listOf("synthetic_private_value"),listOf("name","name"),listOf("name","alias"),List(65) { "name" },listOf(1),listOf(mapOf("name" to "synthetic"))))
            bad(AuthCode.ACCESS_DENIED) { NativeAuditWire.response(request(),200,page(row()+mapOf("changed_fields" to fields))) }
        bad(AuthCode.ACCESS_DENIED) { NativeAuditWire.response(request(),204,page()) }
    }
    @Test fun scalarBoundsEnumsAndUtcTimestampsRejectMalformedMetadata() {
        for(changes in listOf(mapOf("id" to "synthetic"),mapOf("actor_member_id" to null),mapOf("entity_type" to "unknown"),mapOf("action" to "unknown"),
            mapOf("request_id" to "synthetic\nprivate"),mapOf("request_id" to "a".repeat(129)),mapOf("before_version" to 0),mapOf("after_version" to 1.0),
            mapOf("after_version" to 9_007_199_254_740_992L),mapOf("occurred_at" to "2026-10-18T12:04:05+09:00"),mapOf("occurred_at" to "2026-02-30T00:00:00Z")))
            bad(AuthCode.ACCESS_DENIED) { NativeAuditWire.response(request(),200,page(row()+changes)) }
    }
    @Test fun pageOrderingUniquenessLimitAndCursorMustMatchTheLastReturnedRow() {
        val req=request(mapOf("limit" to 1)); NativeAuditWire.response(req,200,page(row(),cursor=cursor()))
        bad(AuthCode.ACCESS_DENIED) { NativeAuditWire.response(req,200,page(row(),row(upper))) }
        bad(AuthCode.ACCESS_DENIED) { NativeAuditWire.response(request(),200,page(row(),row())) }
        bad(AuthCode.ACCESS_DENIED) { NativeAuditWire.response(request(),200,page(row(),row(upper))) }
        NativeAuditWire.response(request(),200,page(row(upper),row()))
        bad(AuthCode.ACCESS_DENIED) { NativeAuditWire.response(req,200,page(cursor=cursor())) }
        bad(AuthCode.ACCESS_DENIED) { NativeAuditWire.response(req,200,page(row(),cursor=cursor(id=upper))) }
        bad(AuthCode.ACCESS_DENIED) { NativeAuditWire.response(request(),200,page(row(),cursor=cursor())) }
        bad(AuthCode.ACCESS_DENIED) { NativeAuditWire.response(request(mapOf("cursor" to cursor())),200,page(row())) }
        NativeAuditWire.response(request(mapOf("cursor" to cursor(id=upper))),200,page(row()))
    }
    @Test fun responseMustRespectEveryRequestedFilterAndHalfOpenTimeWindow() {
        val filters=mapOf("entity_type" to "asset","entity_id" to f.cardId,"actor_member_id" to f.member,"action" to "update",
            "since" to instant,"until" to "2026-10-18T03:04:06Z")
        NativeAuditWire.response(request(filters),200,page(row()))
        for(changes in listOf(mapOf("entity_type" to "card"),mapOf("entity_id" to f.partner),mapOf("actor_member_id" to f.partner),mapOf("action" to "create"),
            mapOf("occurred_at" to "2026-10-18T03:04:04Z"),mapOf("occurred_at" to "2026-10-18T03:04:06Z")))
            bad(AuthCode.ACCESS_DENIED) { NativeAuditWire.response(request(filters),200,page(row()+changes)) }
    }
    @Test fun identityProjectionNeverUsesJsScopeOrAcceptsPrivateExtraFields() {
        assertEquals(listOf(f.household,f.member,f.user),NativeAuditWire.identity(f.snapshot().me))
        bad(AuthCode.ACCESS_DENIED) { NativeAuditWire.identity(f.snapshot().me+mapOf("token" to "synthetic")) }
        assertNotEquals(NativeAuditWire.identity(f.snapshot().me),NativeAuditWire.identity(f.snapshot().me+mapOf("household_id" to f.partner)))
    }
    @Test fun knownAuditErrorsKeepStatusMatchedCodesAndDiscardRawServerDetails() {
        for((code,status) in listOf("INVALID_CURSOR" to 400,"INVALID_AUDIT_FILTER" to 422,"AUDIT_METADATA_INVALID" to 503)) {
            val raw=mapOf("error" to mapOf("code" to code,"message" to "synthetic private","fields" to listOf("synthetic private")))
            val safe=AuthPolicy.safeError(status,raw,f.resource)!!
            assertEquals(code,(safe["error"] as Map<*,*>)["code"]); assertFalse(safe.toString().contains("synthetic private"))
            assertEquals("INTERNAL_ERROR",(AuthPolicy.safeError(500,raw,f.resource)!!["error"] as Map<*,*>)["code"])
        }
    }

    @Test fun activityUsesFixedReadRouteAndProjectsOnlyPublicNamesAndKnownLocalLinks() {
        val request=NativeAuditWire.prepare(mapOf("activity" to true,"query" to mapOf("limit" to 2,"actor_member_id" to f.member)))
        assertTrue(request.path.startsWith("/api/v1/activity-events?"))
        assertTrue(NativeAuditWire.httpAllowed("GET",request.path,null,null,null,null))
        val named=row()+mapOf("target_name" to "합성 공동 기록","target_path" to "/assets/${f.cardId}")
        assertEquals("합성 공동 기록",((NativeAuditWire.response(request,200,page(named))["items"] as List<*>)[0] as Map<*,*>)["target_name"])
        NativeAuditWire.response(request,200,page(named+mapOf("target_name" to null,"target_path" to null)))
        for(path in listOf("https://synthetic.invalid", "//synthetic.invalid", "/assets/../vault", "/assets/${f.cardId}?token=synthetic", "/vault", "/settings/auth"))
            bad(AuthCode.ACCESS_DENIED) { NativeAuditWire.response(request,200,page(named+mapOf("target_path" to path))) }
        bad(AuthCode.ACCESS_DENIED) { NativeAuditWire.response(request,200,page(named+mapOf("target_name" to null))) }
        bad(AuthCode.ACCESS_DENIED) { NativeAuditWire.response(request,200,page(named+mapOf("safe_diff" to emptyMap<String,Any>()))) }
        bad(AuthCode.ACCESS_DENIED) { NativeAuditWire.response(request,200,page(named+mapOf("entity_type" to "vault"))) }
        bad(AuthCode.ACCESS_DENIED) { NativeAuditWire.response(request,200,page(named+mapOf("action" to "reveal"))) }
        bad { NativeAuditWire.prepare(mapOf("activity" to "true")) }
        assertFalse(NativeAuditWire.httpAllowed("GET",request.path+"&activity=true",null,null,null,null))
        assertFalse(NativeAuditWire.httpAllowed("POST",request.path,null,null,null,null))
    }
}
