package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class InsurancePolicyTest {
    private val id = "00000000-0000-4000-8000-000000000003"
    private val child = "00000000-0000-4000-8000-000000000002"
    private val other = "00000000-0000-4000-8000-000000000001"
    private val day = "2026-01-31"
    private val now = "2026-01-31T00:00:00Z"
    private val tag = "\"7\""
    private val audit get() = mapOf("id" to id, "household_id" to other, "created_by_member_id" to other, "updated_by_member_id" to other, "created_at" to now, "updated_at" to now, "version" to 7)
    private fun policyInput() = mapOf<String, Any?>("insurer" to "합성 보험사", "product_name" to "합성 계약", "policyholder_member_id" to null, "insured_member_id" to other,
        "beneficiary_note" to null, "contract_start" to null, "contract_end" to null, "coverage_start" to day, "coverage_end" to null,
        "payment_start" to null, "payment_end" to null, "status" to "active", "valuation_asset_id" to null, "note" to null)
    private fun policy() = policyInput() + audit + mapOf("has_number" to true, "masked_number" to "**** C123")
    private fun coverage() = mapOf<String, Any?>("name" to "합성 보장", "benefit_type" to "fixed", "insured_amount_krw" to null, "coverage_start" to null, "coverage_end" to null, "note" to null, "active" to true)
    private fun caseInput() = mapOf<String, Any?>("title" to "합성 사건", "patient_member_id" to other, "diagnosis_note" to null, "diagnosis_code" to null, "start_on" to day, "end_on" to null, "treatment_state" to "ongoing", "financial_state" to "settled")
    private fun node() = mapOf<String, Any?>("parent_id" to null, "kind" to "pharmacy", "label" to "합성 약국", "provider_name" to null, "start_on" to null, "end_on" to null, "sort_order" to 0, "note" to null)
    private fun request(op: FinanceOperation, args: Map<String, Any?>) = FinancePolicy.prepare(op, args)
    private fun input(value: Map<String, Any?>) = mapOf("input" to value)
    private fun bad(code: AuthCode = AuthCode.INVALID_REQUEST, action: () -> Unit) {
        try { action(); fail("Unsafe insurance data accepted") } catch (e: AuthFailure) { assertEquals(code, e.code); assertNull(e.message) }
    }
    private fun response(op: FinanceOperation, args: Map<String, Any?>, value: Any?, status: Int = 200): Any? = FinancePolicy.response(op, request(op, args), status, value)

    @Test fun twentyNamedOperationsRetainOnlyFixedRoutesAndStrongVersions() {
        val p = mapOf("policyId" to id); val c = mapOf("caseId" to id)
        val commands = listOf(
            FinanceOperation.LIST_INSURANCE_POLICIES to mapOf("query" to mapOf("status" to "active", "limit" to 200)),
            FinanceOperation.CREATE_INSURANCE_POLICY to input(policyInput()), FinanceOperation.GET_INSURANCE_POLICY to p,
            FinanceOperation.UPDATE_INSURANCE_POLICY to (p + input(mapOf("note" to null)) + mapOf("ifMatch" to tag)),
            FinanceOperation.LIST_INSURANCE_COVERAGES to (p + mapOf("query" to mapOf("active" to false))),
            FinanceOperation.CREATE_INSURANCE_COVERAGE to (p + input(coverage())),
            FinanceOperation.UPDATE_INSURANCE_COVERAGE to (p + mapOf("coverageId" to child, "ifMatch" to tag) + input(mapOf("active" to false))),
            FinanceOperation.LIST_POLICY_PREMIUM_LINKS to p, FinanceOperation.CREATE_POLICY_PREMIUM_LINK to (p + input(mapOf("rule_id" to child))),
            FinanceOperation.UPDATE_POLICY_PREMIUM_LINK to (p + mapOf("linkId" to child, "ifMatch" to tag) + input(mapOf("active" to false))),
            FinanceOperation.LIST_INSURANCE_CASES to emptyMap(), FinanceOperation.CREATE_INSURANCE_CASE to input(caseInput()),
            FinanceOperation.GET_INSURANCE_CASE to c, FinanceOperation.UPDATE_INSURANCE_CASE to (c + mapOf("ifMatch" to tag) + input(mapOf("reason" to "합성 변경", "title" to "합성 변경 사건"))),
            FinanceOperation.INSURANCE_CASE_HISTORY to (c + mapOf("query" to mapOf("cursor" to 8))),
            FinanceOperation.LIST_MEDICAL_NODES to c, FinanceOperation.CREATE_MEDICAL_NODE to (c + input(node())),
            FinanceOperation.GET_MEDICAL_NODE to (c + mapOf("nodeId" to child)),
            FinanceOperation.UPDATE_MEDICAL_NODE to (c + mapOf("nodeId" to child, "ifMatch" to tag) + input(mapOf("parent_id" to other))),
            FinanceOperation.DELETE_MEDICAL_NODE to (c + mapOf("nodeId" to child, "ifMatch" to tag)))
        assertEquals(20, commands.size)
        for ((op, args) in commands) {
            val r = request(op, args)
            assertTrue(op.name, FinancePolicy.metadataHttpAllowed(r.method, r.path, r.body, r.ifMatch))
            assertFalse(FinancePolicy.metadataHttpAllowed(r.method, r.path, r.body, r.ifMatch, "key"))
            assertFalse(AuthPolicy.requestAllowed(r.method, r.path, r.ifMatch))
            bad { request(op, args + mapOf("url" to "/api/v1/insurance/policies/$id/reveal")) }
            if (r.ifMatch != null) for (version in listOf("7", "W/\"7\"", "\"0\"", "*")) bad { request(op, args + mapOf("ifMatch" to version)) }
        }
    }
    @Test fun metadataRejectsNumberFieldsIncludingNullAndUnknownEncryptedFields() {
        for (field in listOf("policy_number", "account_number", "number_nonce", "policy_number_ciphertext", "cvc")) {
            bad { request(FinanceOperation.CREATE_INSURANCE_POLICY, input(policyInput() + mapOf(field to null))) }
            bad { request(FinanceOperation.UPDATE_INSURANCE_POLICY, mapOf("policyId" to id, "ifMatch" to tag) + input(mapOf(field to null))) }
            bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.GET_INSURANCE_POLICY, mapOf("policyId" to id), policy() + mapOf(field to null)) }
        }
        assertFalse(FinancePolicy.metadataHttpAllowed("POST", "/api/v1/insurance/policies/$id/reveal", emptyMap<String, Any?>(), null))
    }
    @Test fun policiesValidateCalendarPeriodsRequiredFieldsAndMasks() {
        for (change in listOf(mapOf("coverage_start" to "2026-02-30"), mapOf("coverage_start" to "0000-01-01"), mapOf("coverage_start" to null), mapOf("contract_start" to day, "contract_end" to "2026-01-01"), mapOf("status" to "closed"))) {
            bad { request(FinanceOperation.CREATE_INSURANCE_POLICY, input(policyInput() + change)) }
        }
        assertEquals(policy(), response(FinanceOperation.GET_INSURANCE_POLICY, mapOf("policyId" to id), policy()))
        for (change in listOf(mapOf("masked_number" to "SYNTHETIC123"), mapOf("has_number" to false), mapOf("id" to child))) bad(AuthCode.ACCESS_DENIED) {
            response(FinanceOperation.GET_INSURANCE_POLICY, mapOf("policyId" to id), policy() + change)
        }
    }
    @Test fun coverageMoneyPreservesNullZeroAndTwentyDigitStringsAndRejectsFloats() {
        for (amount in listOf(null, "0", "99999999999999999999")) {
            val body = coverage() + mapOf("insured_amount_krw" to amount)
            assertEquals(amount, request(FinanceOperation.CREATE_INSURANCE_COVERAGE, mapOf("policyId" to id) + input(body)).body!!["insured_amount_krw"])
            response(FinanceOperation.UPDATE_INSURANCE_COVERAGE, mapOf("policyId" to id, "coverageId" to child, "ifMatch" to tag) + input(mapOf("active" to true)), body + audit + mapOf("id" to child, "policy_id" to id))
        }
        for (amount in listOf(0, 0.0, "1.0", "01", "-1", "100000000000000000000")) bad {
            request(FinanceOperation.CREATE_INSURANCE_COVERAGE, mapOf("policyId" to id) + input(coverage() + mapOf("insured_amount_krw" to amount)))
        }
    }
    @Test fun caseListExcludesDiagnosisWhileDetailsAndHistoryAcceptBoundedSyntheticNotes() {
        val detail = caseInput() + audit + mapOf("diagnosis_note" to "합성 메모", "diagnosis_code" to "SYNTHETIC")
        response(FinanceOperation.GET_INSURANCE_CASE, mapOf("caseId" to id), detail)
        val list = mapOf("items" to listOf(detail - setOf("diagnosis_note", "diagnosis_code") + mapOf("net_burden_krw" to "0")), "next_cursor" to null)
        response(FinanceOperation.LIST_INSURANCE_CASES, emptyMap(), list)
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.LIST_INSURANCE_CASES, emptyMap(), mapOf("items" to listOf(detail), "next_cursor" to null)) }
        bad { request(FinanceOperation.UPDATE_INSURANCE_CASE, mapOf("caseId" to id, "ifMatch" to tag) + input(mapOf("reason" to "합성 사유"))) }
        bad { request(FinanceOperation.CREATE_INSURANCE_CASE, input(caseInput() + mapOf("diagnosis_note" to "x".repeat(2001)))) }
    }
    @Test fun caseListCarriesSignedNetBurden() {
        val item = caseInput() - setOf("diagnosis_note", "diagnosis_code") + audit
        fun list(row: Map<String, Any?>) = mapOf("items" to listOf(row), "next_cursor" to null)
        response(FinanceOperation.LIST_INSURANCE_CASES, emptyMap(), list(item + mapOf("net_burden_krw" to "-200")))
        // Response violations are refused as ACCESS_DENIED, like the diagnosis fields above.
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.LIST_INSURANCE_CASES, emptyMap(), list(item)) }
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.LIST_INSURANCE_CASES, emptyMap(), list(item + mapOf("net_burden_krw" to "1.5"))) }
    }
    @Test fun treatmentAndFinancialStatesRemainIndependentAndTreatmentDatesCoherent() {
        request(FinanceOperation.CREATE_INSURANCE_CASE, input(caseInput()))
        request(FinanceOperation.CREATE_INSURANCE_CASE, input(caseInput() + mapOf("treatment_state" to "ended", "end_on" to day, "financial_state" to "open")))
        for (change in listOf(mapOf("treatment_state" to "ended"), mapOf("end_on" to day), mapOf("treatment_state" to "ended", "end_on" to "2026-01-01"))) bad {
            request(FinanceOperation.CREATE_INSURANCE_CASE, input(caseInput() + change))
        }
    }
    @Test fun historyUsesDescendingPositiveVersionsAndMatchesCaseAndCursor() {
        val revision = caseInput() + mapOf("case_id" to id, "version" to 7, "changed_by_member_id" to other, "changed_at" to now, "reason" to null)
        val args = mapOf("caseId" to id, "query" to mapOf("cursor" to 8, "limit" to 1))
        val page = mapOf("items" to listOf(revision), "next_cursor" to 7)
        response(FinanceOperation.INSURANCE_CASE_HISTORY, args, page)
        for (change in listOf(mapOf("case_id" to other), mapOf("version" to 8), mapOf("version" to 0))) bad(AuthCode.ACCESS_DENIED) {
            response(FinanceOperation.INSURANCE_CASE_HISTORY, args, mapOf("items" to listOf(revision + change), "next_cursor" to null))
        }
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.INSURANCE_CASE_HISTORY, args, page + mapOf("next_cursor" to 6)) }
    }
    @Test fun medicalNodesValidateParentTargetSortAndDeletionBodyWithoutInventingAmounts() {
        val args = mapOf("caseId" to id, "nodeId" to child)
        response(FinanceOperation.GET_MEDICAL_NODE, args, node() + audit + mapOf("id" to child, "case_id" to id))
        for (change in listOf(mapOf("parent_id" to child), mapOf("sort_order" to 0.5), mapOf("sort_order" to true), mapOf("sort_order" to 1000001), mapOf("amount_krw" to "0"))) bad {
            request(FinanceOperation.UPDATE_MEDICAL_NODE, args + mapOf("ifMatch" to tag) + input(change))
        }
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.GET_MEDICAL_NODE, args, node() + audit + mapOf("id" to child, "case_id" to other)) }
        assertNull(response(FinanceOperation.DELETE_MEDICAL_NODE, args + mapOf("ifMatch" to tag), null, 204))
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.DELETE_MEDICAL_NODE, args + mapOf("ifMatch" to tag), emptyMap<String, Any?>(), 204) }
    }
    @Test fun nodePagesPreserveServerTreeAndSiblingOrderWithOpaqueUuidCursor() {
        val parent = node() + audit + mapOf("id" to other, "case_id" to id, "kind" to "group", "sort_order" to 0)
        val leaf = node() + audit + mapOf("id" to child, "case_id" to id, "parent_id" to other, "sort_order" to 1)
        val args = mapOf("caseId" to id)
        val page = mapOf("items" to listOf(parent, leaf), "next_cursor" to child)
        assertEquals(page, response(FinanceOperation.LIST_MEDICAL_NODES, args, page))
        response(FinanceOperation.LIST_MEDICAL_NODES, args + mapOf("query" to mapOf("cursor" to other)), mapOf("items" to listOf(leaf), "next_cursor" to null))
        for (rows in listOf(listOf(parent, parent), listOf(leaf, leaf))) bad(AuthCode.ACCESS_DENIED) {
            response(FinanceOperation.LIST_MEDICAL_NODES, args, mapOf("items" to rows, "next_cursor" to null))
        }
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.LIST_MEDICAL_NODES, args, page + mapOf("next_cursor" to other)) }
    }
    @Test fun metadataPagesKeepServerOrderButValidateLimitsDuplicatesAndNextCursor() {
        val op = FinanceOperation.LIST_INSURANCE_POLICIES
        val items = listOf(policy(), policy() + mapOf("id" to child))
        response(op, emptyMap(), mapOf("items" to items, "next_cursor" to child))
        response(op, emptyMap(), mapOf("items" to items.reversed(), "next_cursor" to id))
        bad(AuthCode.ACCESS_DENIED) { response(op, emptyMap(), mapOf("items" to listOf(policy(), policy()), "next_cursor" to null)) }
        bad(AuthCode.ACCESS_DENIED) { response(op, mapOf("query" to mapOf("cursor" to id)), mapOf("items" to items.reversed(), "next_cursor" to null)) }
        bad(AuthCode.ACCESS_DENIED) { response(op, mapOf("query" to mapOf("limit" to 1)), mapOf("items" to items, "next_cursor" to null)) }
        bad(AuthCode.ACCESS_DENIED) { response(op, emptyMap(), mapOf("items" to items, "next_cursor" to other)) }
        for (limit in listOf(0, 201, 1.5, "1")) bad { request(op, mapOf("query" to mapOf("limit" to limit))) }
    }
    @Test fun queriesAreCanonicalAndBoundedAndRejectArbitraryRoutes() {
        val base = "/api/v1/insurance/policies/$id/coverages"
        assertTrue(InsurancePolicy.httpAllowed("GET", "$base?active=false&limit=200", null, null))
        for (suffix in listOf("?active=1", "?limit=01", "?active=true&active=false", "?limit=201", "?url=secret", "?cursor=$id%2f", "/reveal", "#x")) assertFalse(InsurancePolicy.httpAllowed("GET", base + suffix, null, null))
        assertFalse(InsurancePolicy.httpAllowed("GET", "https://synthetic.invalid$base", null, null))
    }
    @Test fun nativeNumberRequestsHaveDedicatedPathsExactFieldsAndNoMetadataOrAccountCrossover() {
        val path = "/api/v1/insurance/policies/$id"
        assertTrue(InsurancePolicy.numberHttpAllowed("PATCH", path, mapOf("policy_number" to "SYNTHETIC123"), tag))
        assertTrue(InsurancePolicy.numberHttpAllowed("PATCH", path, mapOf("policy_number" to null), tag))
        assertTrue(InsurancePolicy.numberHttpAllowed("POST", "$path/reveal", emptyMap<String, Any?>(), null))
        for (body in listOf(mapOf("policy_number" to 123), mapOf("account_number" to null), mapOf("policy_number" to null, "note" to "synthetic"))) assertFalse(InsurancePolicy.numberHttpAllowed("PATCH", path, body, tag))
        assertFalse(InsurancePolicy.numberHttpAllowed("PATCH", "/api/v1/accounts/$id", mapOf("policy_number" to null), tag))
        assertFalse(InsurancePolicy.numberHttpAllowed("PATCH", "$path?x=1", mapOf("policy_number" to null), tag))
        assertFalse(InsurancePolicy.numberHttpAllowed("POST", "$path/reveal", emptyMap<String, Any?>(), tag))
        assertFalse(FinancePolicy.metadataHttpAllowed("PATCH", path, mapOf("policy_number" to null), tag))
    }
    @Test fun revealedNumberIsNativeOnlyBoundToTargetAndExactlyThirtySeconds() {
        val row = mapOf("id" to id, "policy_number" to "SYNTHETIC123", "display_for_seconds" to 30)
        val number = NativePolicyNumber(InsurancePolicy.readNumber(row, id))
        assertEquals("NativePolicyNumber(redacted)", number.toString())
        val display = AccountNumberDisplay(number.number.copyOf(), 100)
        number.discard(); assertTrue(number.number.all { it == '\u0000' })
        assertEquals("SYNTHETIC123", display.reveal(30099, true, true, true))
        assertNull(display.reveal(30100, true, true, true))
        for (change in listOf(mapOf("id" to child), mapOf("display_for_seconds" to 31), mapOf("token" to "synthetic"), mapOf("policy_number" to "123"))) bad(AuthCode.ACCESS_DENIED) { InsurancePolicy.readNumber(row + change, id) }
    }
    @Test fun premiumLinksReuseFixedRuleProjectionAndBindRuleHouseholdAndPolicy() {
        val version = mapOf<String, Any?>("id" to child, "effective_from" to "2026-01-01", "effective_until" to null, "reason" to null, "created_at" to now,
            "title" to "합성 보험료", "category" to "합성 분류", "amount_mode" to "fixed", "expected_amount_krw" to "0", "economic_type" to "expense",
            "loan_asset_id" to null, "account_id" to null, "card_id" to null, "currency_reference" to null, "foreign_amount_reference" to null, "note" to null,
            "anchor_date" to day, "frequency" to "monthly", "interval_count" to 1)
        val rule = mapOf("id" to child, "household_id" to other, "version" to 7, "ended_on" to null, "end_reason" to null, "versions" to listOf(version))
        val link = audit + mapOf("id" to child, "policy_id" to id, "rule_id" to child, "active" to true, "ended_at" to null, "rule" to rule)
        val args = mapOf("policyId" to id) + input(mapOf("rule_id" to child))
        response(FinanceOperation.CREATE_POLICY_PREMIUM_LINK, args, link, 201)
        for (badRule in listOf(rule + mapOf("id" to other), rule + mapOf("household_id" to id), rule + mapOf("versions" to listOf(version + mapOf("policy_number" to null))))) bad(AuthCode.ACCESS_DENIED) {
            response(FinanceOperation.CREATE_POLICY_PREMIUM_LINK, args, link + mapOf("rule" to badRule), 201)
        }
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.CREATE_POLICY_PREMIUM_LINK, args, link + mapOf("active" to false), 201) }
    }
    @Test fun knownInsuranceErrorsProjectOnlySafeCodeAndMessage() {
        for ((code, status) in listOf("MEDICAL_NODE_CYCLE" to 422, "MEDICAL_NODE_IN_USE" to 409, "PREMIUM_RULE_ALREADY_LINKED" to 409, "POLICY_NUMBER_UNAVAILABLE" to 503, "INSURANCE_ASSET_REQUIRED" to 422)) {
            val safe = AuthPolicy.safeError(status, mapOf("error" to mapOf("code" to code, "message" to "synthetic sensitive text", "policy_number" to "SYNTHETIC123")), id)!!
            assertEquals(code, (safe["error"] as Map<*, *>)["code"])
            assertFalse(safe.toString().contains("SYNTHETIC123")); assertFalse(safe.toString().contains("synthetic sensitive text"))
        }
    }
}
