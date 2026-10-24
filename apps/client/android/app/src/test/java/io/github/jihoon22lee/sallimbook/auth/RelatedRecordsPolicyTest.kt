package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class RelatedRecordsPolicyTest {
    private val id = "00000000-0000-4000-8000-000000000001"
    private val other = "00000000-0000-4000-8000-000000000002"
    private fun rejected(code: AuthCode = AuthCode.INVALID_REQUEST, action: () -> Unit) {
        try { action(); fail("Invalid reference accepted") } catch (error: AuthFailure) { assertEquals(code, error.code) }
    }
    @Test fun readOnlyReferencesRejectArbitraryPathsBodiesAndForeignResponseIdentity() {
        for ((op, name) in listOf(FinanceOperation.GET_INCOME_INSURANCE_SOURCE to "recordId", FinanceOperation.GET_RECURRING_RULE_INSURANCE_LINK to "ruleId")) {
            val request = FinancePolicy.prepare(op, mapOf(name to id))
            assertTrue(FinancePolicy.metadataHttpAllowed("GET", request.path, null, null))
            assertFalse(FinancePolicy.metadataHttpAllowed("POST", request.path, null, null))
            assertFalse(FinancePolicy.metadataHttpAllowed("GET", request.path, mapOf("x" to "y"), null))
            assertFalse(FinancePolicy.metadataHttpAllowed("GET", request.path + "?url=synthetic", null, null))
            assertFalse(FinancePolicy.metadataHttpAllowed("GET", "https://synthetic.invalid" + request.path, null, null))
            rejected { FinancePolicy.prepare(op, mapOf(name to "$id/../reveal")) }
            rejected { FinancePolicy.prepare(op, mapOf(name to id, "url" to "synthetic")) }
        }
    }
    @Test fun incomeKeepsMultipleCaseAllocationsAndReturnTargetWithoutConvertingMoney() {
        val op = FinanceOperation.GET_INCOME_INSURANCE_SOURCE
        val request = FinancePolicy.prepare(op, mapOf("recordId" to id))
        val allocation = mapOf("id" to id, "case_id" to other, "case_title" to "합성 사건", "amount_krw" to "99999999999999999999")
        val row = mapOf("record_id" to id, "payout_id" to other, "return_id" to id, "original_allocation_id" to id, "allocations" to listOf(allocation, allocation + mapOf("id" to other, "case_id" to id)))
        assertEquals(row, FinancePolicy.response(op, request, 200, row))
        rejected(AuthCode.ACCESS_DENIED) { FinancePolicy.response(op, request, 200, row + mapOf("record_id" to other)) }
        rejected(AuthCode.ACCESS_DENIED) { FinancePolicy.response(op, request, 200, row + mapOf("original_allocation_id" to null)) }
        rejected(AuthCode.ACCESS_DENIED) { FinancePolicy.response(op, request, 200, row + mapOf("allocations" to listOf(allocation + mapOf("amount_krw" to 10)))) }
        rejected(AuthCode.ACCESS_DENIED) { FinancePolicy.response(op, request, 201, row) }
    }
    @Test fun endedInsuranceLinksRemainVisibleAndNamesAreBounded() {
        val op = FinanceOperation.GET_RECURRING_RULE_INSURANCE_LINK
        val request = FinancePolicy.prepare(op, mapOf("ruleId" to id))
        val link = mapOf("id" to id, "policy_id" to other, "product_name" to "합성 계약", "insurer" to "합성 보험사", "policy_status" to "ended", "active" to false, "ended_at" to "2026-01-01T00:00:00Z")
        val row = mapOf("rule_id" to id, "link" to link)
        assertEquals(row, FinancePolicy.response(op, request, 200, row))
        assertEquals(mapOf("rule_id" to id, "link" to null), FinancePolicy.response(op, request, 200, mapOf("rule_id" to id, "link" to null)))
        rejected(AuthCode.ACCESS_DENIED) { FinancePolicy.response(op, request, 200, row + mapOf("rule_id" to other)) }
        rejected(AuthCode.ACCESS_DENIED) { FinancePolicy.response(op, request, 200, row + mapOf("link" to link + mapOf("product_name" to "x".repeat(121)))) }
    }
}
