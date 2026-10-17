package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class CashflowPolicyTest {
    private val id = "00000000-0000-4000-8000-000000000001"
    private val valueId = "00000000-0000-4000-8000-000000000002"
    private val now = "2026-01-01T00:00:00Z"
    private val version = "\"1\""
    private fun bad(code: AuthCode = AuthCode.INVALID_REQUEST, action: () -> Unit) {
        try { action(); fail("Unsafe metadata crossed the native boundary") }
        catch (failure: AuthFailure) { assertEquals(code, failure.code); assertNull(failure.message) }
    }
    private fun request(op: FinanceOperation, args: Map<String, Any?> = emptyMap()) = FinancePolicy.prepare(op, mapOf("month" to "2026-01") + args)
    private fun valueInput() = mapOf("revision_id" to id, "value_id" to valueId, "input_amount_krw" to "99999999999999999999", "as_of_date" to "2026-01-31")
    private fun totals() = mapOf("assets_krw" to "99999999999999999999", "liabilities_krw" to "0", "net_assets_krw" to "99999999999999999999",
        "verified_count" to 1, "item_count" to 1, "missing_count" to 0, "carried_count" to 0, "provisional" to false)
    private fun value() = mapOf<String, Any?>("id" to valueId, "asset_id" to id, "name" to "합성 자산", "kind" to "asset", "category" to "financial",
        "ownership_kind" to "joint", "owner_member_id" to null, "household_share" to "0.5", "amount_basis" to "whole", "inclusion_status" to "included",
        "started_on" to "2026-01-01", "ended_on" to null, "source_asset_version" to 1, "input_amount_krw" to "99999999999999999999",
        "owned_amount_krw" to "50000000000000000000", "as_of_date" to "2026-01-31", "verification_state" to "verified", "origin" to "manual",
        "origin_revision_id" to null, "change_reason" to null, "version" to 1)
    private fun reference() = mapOf("month" to "2026-01", "revision_id" to id, "revision_no" to 1, "version" to 1)
    private fun history() = reference() + mapOf("state" to "draft", "previous_revision_id" to null, "reopened_reason" to null, "confirmed_at" to null, "created_at" to now)
    private fun month() = history() + mapOf("confirmed_by_member_id" to null, "totals" to totals(), "scope_stale" to false, "values" to listOf(value()), "next_cursor" to null)

    @Test fun eightMonthlyCommandsRoundTripOnlyTheirAllowedRoutesAndHeaders() {
        val requests = listOf(
            request(FinanceOperation.GET_ASSET_MONTH),
            request(FinanceOperation.GET_ASSET_MONTH_REVISION, mapOf("revisionNo" to 1, "query" to mapOf("limit" to 200, "cursor" to id))),
            request(FinanceOperation.LIST_ASSET_MONTH_REVISIONS, mapOf("query" to mapOf("cursor" to 3, "limit" to 1))),
            request(FinanceOperation.CREATE_ASSET_MONTH_DRAFT, mapOf("input" to emptyMap<String, Any>(), "idempotencyKey" to "synthetic.draft:1")),
            request(FinanceOperation.UPDATE_ASSET_MONTH_VALUE, mapOf("assetId" to id, "input" to valueInput(), "ifMatch" to version)),
            request(FinanceOperation.SYNCHRONIZE_ASSET_MONTH_SCOPE, mapOf("input" to mapOf("revision_id" to id), "ifMatch" to version)),
            request(FinanceOperation.CONFIRM_ASSET_MONTH, mapOf("input" to mapOf("revision_id" to id), "ifMatch" to version, "idempotencyKey" to "synthetic-confirm")),
            request(FinanceOperation.REOPEN_ASSET_MONTH, mapOf("input" to mapOf("revision_id" to id, "reason" to "합성 정정"), "ifMatch" to version, "idempotencyKey" to "synthetic-reopen")),
        )
        for (r in requests) {
            assertTrue(FinancePolicy.metadataHttpAllowed(r.method, r.path, r.body, r.ifMatch, r.idempotencyKey))
            assertFalse(AuthPolicy.requestAllowed(r.method, r.path, r.ifMatch))
            assertFalse(FinancePolicy.metadataHttpAllowed(r.method, r.path + "/reveal", r.body, r.ifMatch, r.idempotencyKey))
            assertFalse(FinancePolicy.metadataHttpAllowed(r.method, "https://synthetic.invalid" + r.path, r.body, r.ifMatch, r.idempotencyKey))
        }
        assertTrue(requests[1].path.endsWith("revisions/1?cursor=$id&limit=200"))
        assertTrue(requests[2].path.endsWith("revisions?cursor=3&limit=1"))
    }
    @Test fun monthAndRevisionAndQueriesRejectUnboundedOrAmbiguousValues() {
        for (m in listOf("0000-01", "2026-00", "2026-13", "2026-1", "2026-01/../accounts")) bad {
            FinancePolicy.prepare(FinanceOperation.GET_ASSET_MONTH, mapOf("month" to m))
        }
        for (revision in listOf(0, 1.0, "1", 9_007_199_254_740_992L)) bad {
            request(FinanceOperation.GET_ASSET_MONTH_REVISION, mapOf("revisionNo" to revision))
        }
        for (q in listOf(mapOf("cursor" to 1), mapOf("limit" to 201), mapOf("limit" to 1.0), mapOf("limit" to null), mapOf("url" to "synthetic"))) bad {
            request(FinanceOperation.GET_ASSET_MONTH, mapOf("query" to q))
        }
        assertEquals("/api/v1/asset-months/2026-01", request(FinanceOperation.GET_ASSET_MONTH, mapOf("query" to mapOf("cursor" to null))).path)
        for (suffix in listOf("?limit=01", "?limit=1&limit=2", "?cursor=", "#synthetic", "/revisions/01")) {
            assertFalse(FinancePolicy.metadataHttpAllowed("GET", "/api/v1/asset-months/2026-01$suffix", null, null))
        }
    }
    @Test fun mutationIdentityAndExplicitNullZeroAndUnchangedRemainDistinct() {
        val args = mapOf("assetId" to id, "ifMatch" to version)
        for (amount in listOf(null, "0", "99999999999999999999")) {
            val input = valueInput() + mapOf("input_amount_krw" to amount)
            assertEquals(input, request(FinanceOperation.UPDATE_ASSET_MONTH_VALUE, args + mapOf("input" to input)).body)
        }
        val unchanged = valueInput() - "input_amount_krw" + mapOf("unchanged" to true)
        assertEquals(unchanged, request(FinanceOperation.UPDATE_ASSET_MONTH_VALUE, args + mapOf("input" to unchanged)).body)
        for (input in listOf(valueInput() - "value_id", valueInput() - "revision_id", valueInput() - "input_amount_krw",
            valueInput() + mapOf("input_amount_krw" to 1), valueInput() + mapOf("input_amount_krw" to "01"),
            valueInput() + mapOf("input_amount_krw" to "-1"), valueInput() + mapOf("input_amount_krw" to "1e3"),
            valueInput() + mapOf("input_amount_krw" to "100000000000000000000"), valueInput() + mapOf("unchanged" to true),
            valueInput() - "as_of_date", valueInput() + mapOf("as_of_date" to "2026-02-30"))) bad {
            request(FinanceOperation.UPDATE_ASSET_MONTH_VALUE, args + mapOf("input" to input))
        }
    }
    @Test fun onlyRequiredMutationHeadersAndFixedOptionNamesAreAccepted() {
        val args = mapOf("input" to emptyMap<String, Any>(), "idempotencyKey" to "synthetic-key")
        for (key in listOf("", "x\r\nAuthorization:x", "a".repeat(129), "../secret", "합성")) bad {
            request(FinanceOperation.CREATE_ASSET_MONTH_DRAFT, args + mapOf("idempotencyKey" to key))
        }
        for (extra in listOf("headers", "url", "body", "accessToken", "ifMatch", "stepUpToken")) bad {
            request(FinanceOperation.CREATE_ASSET_MONTH_DRAFT, args + mapOf(extra to "synthetic"))
        }
        val r = request(FinanceOperation.CREATE_ASSET_MONTH_DRAFT, args)
        assertFalse(FinancePolicy.metadataHttpAllowed(r.method, r.path, r.body, null, null))
        assertFalse(FinancePolicy.metadataHttpAllowed(r.method, r.path, r.body, version, r.idempotencyKey))
        assertFalse(FinancePolicy.metadataHttpAllowed("GET", "/api/v1/assets", null, null, "synthetic"))
    }
    @Test fun monthlyResponseProjectionPreservesExactMoneyAndRequiresMatchingMonthAndRevision() {
        val r = request(FinanceOperation.GET_ASSET_MONTH)
        assertEquals(month(), FinancePolicy.response(FinanceOperation.GET_ASSET_MONTH, r, 200, month()))
        for (change in listOf(mapOf("month" to "2026-02"), mapOf("token" to "synthetic"), mapOf("totals" to totals() + mapOf("assets_krw" to 1.0)),
            mapOf("totals" to totals() + mapOf("account_number" to "synthetic")), mapOf("values" to listOf(value() + mapOf("ciphertext" to "synthetic"))),
            mapOf("values" to List(201) { value() }))) bad(AuthCode.ACCESS_DENIED) {
            FinancePolicy.response(FinanceOperation.GET_ASSET_MONTH, r, 200, month() + change)
        }
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.GET_ASSET_MONTH_REVISION,
            request(FinanceOperation.GET_ASSET_MONTH_REVISION, mapOf("revisionNo" to 2)), 200, month()) }
    }
    @Test fun valueReplyRequiresBothAssetAndRowIdentityToPreventAbaMixups() {
        val r = request(FinanceOperation.UPDATE_ASSET_MONTH_VALUE, mapOf("assetId" to id, "input" to valueInput(), "ifMatch" to version))
        val result = mapOf("value" to value(), "revision_version" to 2, "totals" to totals())
        assertEquals(result, FinancePolicy.response(FinanceOperation.UPDATE_ASSET_MONTH_VALUE, r, 200, result))
        for (change in listOf(mapOf("id" to id), mapOf("asset_id" to valueId), mapOf("input_amount_krw" to 0))) bad(AuthCode.ACCESS_DENIED) {
            FinancePolicy.response(FinanceOperation.UPDATE_ASSET_MONTH_VALUE, r, 200, result + mapOf("value" to value() + change))
        }
    }
    @Test fun historyAndMutationResponsesRejectWrongIdentityStatusAndNestedFields() {
        val historyRequest = request(FinanceOperation.LIST_ASSET_MONTH_REVISIONS)
        val response = mapOf("items" to listOf(history()), "next_cursor" to 2)
        assertEquals(response, FinancePolicy.response(FinanceOperation.LIST_ASSET_MONTH_REVISIONS, historyRequest, 200, response))
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.LIST_ASSET_MONTH_REVISIONS, historyRequest, 200,
            response + mapOf("items" to listOf(history() + mapOf("month" to "2026-02")))) }
        val confirm = request(FinanceOperation.CONFIRM_ASSET_MONTH, mapOf("input" to mapOf("revision_id" to id), "ifMatch" to version, "idempotencyKey" to "synthetic"))
        assertEquals(reference(), FinancePolicy.response(FinanceOperation.CONFIRM_ASSET_MONTH, confirm, 200, reference()))
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.CONFIRM_ASSET_MONTH, confirm, 200, reference() + mapOf("revision_id" to valueId)) }
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.CONFIRM_ASSET_MONTH, confirm, 201, reference()) }
    }
    @Test fun lockedAndRecoveryTicketsCannotReachMonthlyMetadata() {
        val policy = AppLockPolicy().also { it.resume(0, false) }
        for (kind in AppRequestKind.entries) {
            val ticket = policy.ticket(kind)
            for ((method, path) in listOf("GET" to "/api/v1/asset-months/2026-01", "POST" to "/api/v1/asset-months/2026-01/draft",
                "PATCH" to "/api/v1/asset-months/2026-01/values/$id")) assertFalse(policy.httpAllowed(ticket, method, path))
        }
    }
    @Test fun knownMonthlyErrorsPreserveCodeButNeverCopyServerMessagesOrDetails() {
        val safe = AuthPolicy.safeError(409, mapOf("error" to mapOf("code" to "VALUE_CONFLICT", "message" to "synthetic secret", "details" to mapOf("account_number" to "synthetic"))), id)!!
        val error = safe["error"] as Map<*, *>
        assertEquals("VALUE_CONFLICT", error["code"])
        assertFalse(safe.toString().contains("synthetic"))
    }
}
