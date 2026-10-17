package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class IncomePolicyTest {
    private val id = "00000000-0000-4000-8000-000000000001"
    private val other = "00000000-0000-4000-8000-000000000002"
    private val version = "\"1\""
    private fun bad(code: AuthCode = AuthCode.INVALID_REQUEST, action: () -> Unit) {
        try { action(); fail("Unsafe income metadata was accepted") }
        catch (failure: AuthFailure) { assertEquals(code, failure.code); assertNull(failure.message) }
    }
    private fun input() = mapOf<String, Any?>("kind" to "salary", "amount_krw" to "99999999999999999999", "period_month" to "2026-01",
        "date_precision" to "month", "occurred_on" to null, "member_id" to id, "account_id" to null, "note" to null)
    private fun cash() = input() + mapOf("id" to id, "household_id" to other, "flow" to "in", "reverses_id" to null, "state" to "active",
        "created_by_member_id" to id, "updated_by_member_id" to id, "created_at" to "2026-01-31T00:00:00Z", "updated_at" to "2026-01-31T00:00:00Z",
        "version" to 1, "action" to "create", "reason" to null, "conversion_id" to null, "editable" to true, "voidable" to true)
    private fun totals() = mapOf("salary_krw" to "99999999999999999999", "bonus_krw" to "0", "other_income_krw" to "0",
        "income_returns_krw" to "0", "insurance_receipts_krw" to "0", "insurance_returns_krw" to "0", "earned_net_krw" to "99999999999999999999",
        "insurance_net_krw" to "0", "net_inflow_krw" to "99999999999999999999", "record_count" to 1)
    private fun request(op: FinanceOperation, args: Map<String, Any?>) = FinancePolicy.prepare(op, args)
    private fun mutation(input: Map<String, Any?>) = mapOf("recordId" to id, "input" to input, "ifMatch" to version, "idempotencyKey" to "synthetic-income")
    private fun conversion() = mapOf("sources" to listOf(mapOf("id" to id, "version" to 1)), "replacements" to listOf(input()), "reason" to "합성 전환")

    @Test fun allTenIncomeCommandsHaveFixedPathsAndOnlyRequiredHeaders() {
        val requests = listOf(
            request(FinanceOperation.LIST_INCOME, mapOf("query" to mapOf("month" to "2026-01", "kind" to "insurance_receipt", "limit" to 200))),
            request(FinanceOperation.INCOME_SUMMARY, mapOf("query" to mapOf("month" to "2026-01"))),
            request(FinanceOperation.INCOME_DUPLICATE_CANDIDATES, mapOf("query" to mapOf("month" to "2026-01", "kind" to "salary", "member_id" to id, "date_precision" to "day"))),
            request(FinanceOperation.GET_INCOME, mapOf("recordId" to id)),
            request(FinanceOperation.INCOME_HISTORY, mapOf("recordId" to id, "query" to mapOf("cursor" to 4, "limit" to 200))),
            request(FinanceOperation.CREATE_INCOME, mapOf("input" to input(), "idempotencyKey" to "synthetic-income")),
            request(FinanceOperation.CORRECT_INCOME, mutation(mapOf("reason" to "합성 정정", "note" to null))),
            request(FinanceOperation.VOID_INCOME, mutation(mapOf("reason" to "합성 무효"))),
            request(FinanceOperation.RETURN_INCOME, mutation(input() - setOf("kind", "member_id") + mapOf("reason" to "합성 반환"))),
            request(FinanceOperation.CONVERT_INCOME_PRECISION, mapOf("input" to conversion(), "idempotencyKey" to "synthetic-convert")),
        )
        for (r in requests) {
            assertTrue(FinancePolicy.metadataHttpAllowed(r.method, r.path, r.body, r.ifMatch, r.idempotencyKey))
            assertFalse(AuthPolicy.requestAllowed(r.method, r.path, r.ifMatch))
            assertFalse(FinancePolicy.metadataHttpAllowed(r.method, r.path + "/secret", r.body, r.ifMatch, r.idempotencyKey))
            if (r.idempotencyKey != null) assertFalse(FinancePolicy.metadataHttpAllowed(r.method, r.path, r.body, r.ifMatch, null))
        }
        assertEquals("/api/v1/income?kind=insurance_receipt&limit=200&month=2026-01", requests[0].path)
        assertEquals("/api/v1/income/$id/history?cursor=4&limit=200", requests[4].path)
    }
    @Test fun incomeQueriesRejectMissingMonthAndGenericCashDomainFilters() {
        for (q in listOf(emptyMap(), mapOf("month" to null), mapOf("month" to "2026-01", "kind" to "medical_payment"),
            mapOf("month" to "2026-01", "cursor" to 1), mapOf("month" to "2026-01", "limit" to 201))) bad {
            request(FinanceOperation.LIST_INCOME, mapOf("query" to q))
        }
        bad { request(FinanceOperation.INCOME_SUMMARY, emptyMap()) }
        bad { request(FinanceOperation.INCOME_DUPLICATE_CANDIDATES, mapOf("query" to mapOf("month" to "2026-01", "kind" to "salary"))) }
        assertFalse(FinancePolicy.metadataHttpAllowed("GET", "/api/v1/income?month=2026-01&month=2026-02", null, null))
        assertFalse(FinancePolicy.metadataHttpAllowed("GET", "/api/v1/income/$id/history?cursor=01", null, null))
    }
    @Test fun createKeepsLargeDecimalStringsAndDatePrecisionWithoutNumericConversion() {
        val r = request(FinanceOperation.CREATE_INCOME, mapOf("input" to input(), "idempotencyKey" to "synthetic"))
        assertEquals(input(), r.body)
        for (change in listOf(mapOf("amount_krw" to 1), mapOf("amount_krw" to "0"), mapOf("amount_krw" to "-1"),
            mapOf("amount_krw" to "1.0"), mapOf("amount_krw" to "100000000000000000000"), mapOf("date_precision" to "day"),
            mapOf("occurred_on" to "2026-01-31"), mapOf("member_id" to null), mapOf("duplicate_acknowledged" to "true"),
            mapOf("kind" to "insurance_receipt"), mapOf("account_number" to null))) bad {
            request(FinanceOperation.CREATE_INCOME, mapOf("input" to input() + change, "idempotencyKey" to "synthetic"))
        }
    }
    @Test fun correctionRequiresReasonAndChangeWhileKeepingNullableFieldsExplicit() {
        val r = request(FinanceOperation.CORRECT_INCOME, mutation(mapOf("reason" to "합성 정정", "note" to null)))
        assertTrue(r.body!!.containsKey("note")); assertNull(r.body["note"])
        for (body in listOf(mapOf("reason" to "합성"), mapOf("reason" to "합성", "duplicate_acknowledged" to true),
            mapOf("reason" to " ", "note" to "합성"), mapOf("reason" to "합성", "member_id" to null),
            mapOf("reason" to "합성", "amount_krw" to null), mapOf("note" to null))) bad {
            request(FinanceOperation.CORRECT_INCOME, mutation(body))
        }
        for (tag in listOf("1", "W/\"1\"", "*", "\"0\"")) bad {
            request(FinanceOperation.CORRECT_INCOME, mutation(mapOf("reason" to "합성", "note" to null)) + mapOf("ifMatch" to tag))
        }
    }
    @Test fun returnsCannotChooseAnotherMemberOrChangeTheirKind() {
        val body = input() - setOf("kind", "member_id") + mapOf("reason" to "합성 반환")
        request(FinanceOperation.RETURN_INCOME, mutation(body + mapOf("member_id" to null)))
        bad { request(FinanceOperation.RETURN_INCOME, mutation(body + mapOf("member_id" to other))) }
        bad { request(FinanceOperation.RETURN_INCOME, mutation(body + mapOf("kind" to "income_return"))) }
    }
    @Test fun conversionBoundsSourcesAndReplacementsAndRequiresDistinctVersionedSources() {
        val args = mapOf("input" to conversion(), "idempotencyKey" to "synthetic")
        request(FinanceOperation.CONVERT_INCOME_PRECISION, args)
        for (change in listOf(mapOf("sources" to emptyList<Any>()), mapOf("replacements" to emptyList<Any>()),
            mapOf("replacements" to List(101) { input() }), mapOf("sources" to List(2) { mapOf("id" to id, "version" to 1) }),
            mapOf("sources" to listOf(mapOf("id" to id, "version" to 1.0))),
            mapOf("replacements" to listOf(input() + mapOf("duplicate_acknowledged" to true))))) bad {
            request(FinanceOperation.CONVERT_INCOME_PRECISION, args + mapOf("input" to conversion() + change))
        }
    }
    @Test fun cashProjectionRequiresTargetIdentityAndRejectsNestedSecrets() {
        val r = request(FinanceOperation.GET_INCOME, mapOf("recordId" to id))
        assertEquals(cash(), FinancePolicy.response(FinanceOperation.GET_INCOME, r, 200, cash()))
        for (change in listOf(mapOf("id" to other), mapOf("amount_krw" to 1.0), mapOf("account_number" to "synthetic"),
            mapOf("note" to mapOf("secret" to "synthetic")), mapOf("kind" to "medical_payment"), mapOf("date_precision" to "day"))) bad(AuthCode.ACCESS_DENIED) {
            FinancePolicy.response(FinanceOperation.GET_INCOME, r, 200, cash() + change)
        }
        val returned = cash() + mapOf("id" to other, "reverses_id" to id, "kind" to "income_return", "flow" to "out")
        val rr = request(FinanceOperation.RETURN_INCOME, mutation(input() - setOf("kind", "member_id") + mapOf("reason" to "합성")))
        assertEquals(returned, FinancePolicy.response(FinanceOperation.RETURN_INCOME, rr, 201, returned))
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.RETURN_INCOME, rr, 201, returned + mapOf("reverses_id" to other)) }
    }
    @Test fun historyAndSummaryRepliesAreBoundToRequestedRecordAndMonth() {
        val history = request(FinanceOperation.INCOME_HISTORY, mapOf("recordId" to id))
        val result = mapOf("items" to listOf(cash()), "next_cursor" to 2)
        assertEquals(result, FinancePolicy.response(FinanceOperation.INCOME_HISTORY, history, 200, result))
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.INCOME_HISTORY, history, 200, result + mapOf("items" to listOf(cash() + mapOf("id" to other)))) }
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.INCOME_HISTORY, history, 200, result + mapOf("items" to List(201) { cash() })) }
        val summary = request(FinanceOperation.INCOME_SUMMARY, mapOf("query" to mapOf("month" to "2026-01")))
        val body = mapOf("period_month" to "2026-01", "totals" to totals(), "members" to listOf(mapOf("member_id" to id, "totals" to totals())))
        assertEquals(body, FinancePolicy.response(FinanceOperation.INCOME_SUMMARY, summary, 200, body))
        for (change in listOf(mapOf("period_month" to "2026-02"), mapOf("totals" to totals() + mapOf("net_inflow_krw" to 1)),
            mapOf("members" to listOf(mapOf("member_id" to id, "totals" to totals() + mapOf("ciphertext" to "synthetic")))))) bad(AuthCode.ACCESS_DENIED) {
            FinancePolicy.response(FinanceOperation.INCOME_SUMMARY, summary, 200, body + change)
        }
    }
    @Test fun duplicateAndConversionResultsRemainBoundedPublicRecords() {
        val d = request(FinanceOperation.INCOME_DUPLICATE_CANDIDATES, mapOf("query" to mapOf("month" to "2026-01", "kind" to "salary", "member_id" to id, "date_precision" to "day")))
        val duplicates = mapOf("suspected" to true, "items" to listOf(cash()), "truncated" to false)
        assertEquals(duplicates, FinancePolicy.response(FinanceOperation.INCOME_DUPLICATE_CANDIDATES, d, 200, duplicates))
        val c = request(FinanceOperation.CONVERT_INCOME_PRECISION, mapOf("input" to conversion(), "idempotencyKey" to "synthetic"))
        val converted = mapOf("id" to other, "version" to 1, "reason" to "합성", "created_at" to "2026-01-31T00:00:00Z", "sources" to listOf(cash()), "replacements" to listOf(cash()))
        assertEquals(converted, FinancePolicy.response(FinanceOperation.CONVERT_INCOME_PRECISION, c, 201, converted))
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.CONVERT_INCOME_PRECISION, c, 201, converted + mapOf("sources" to List(101) { cash() })) }
    }
    @Test fun lockRecoveryNeverAuthorizesIncomeAndSafeErrorsKeepOnlyKnownCodes() {
        val policy = AppLockPolicy().also { it.resume(0, false) }
        for (kind in AppRequestKind.entries) {
            assertFalse(policy.httpAllowed(policy.ticket(kind), "GET", "/api/v1/income?month=2026-01"))
            assertFalse(policy.httpAllowed(policy.ticket(kind), "POST", "/api/v1/income"))
        }
        val error = AuthPolicy.safeError(409, mapOf("error" to mapOf("code" to "INCOME_DUPLICATE_SUSPECTED", "message" to "synthetic secret")), id)!!
        assertEquals("INCOME_DUPLICATE_SUSPECTED", (error["error"] as Map<*, *>)["code"])
        assertFalse(error.toString().contains("synthetic"))
    }
}
