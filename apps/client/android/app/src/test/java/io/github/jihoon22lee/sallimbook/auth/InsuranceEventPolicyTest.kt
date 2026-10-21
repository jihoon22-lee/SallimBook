package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class InsuranceEventPolicyTest {
    private val id = "00000000-0000-4000-8000-000000000009"
    private val child = "00000000-0000-4000-8000-000000000008"
    private val other = "00000000-0000-4000-8000-000000000007"
    private val household = "00000000-0000-4000-8000-000000000006"
    private val day = "2026-01-31"
    private val now = "2026-01-31T00:00:00Z"
    private val tag = "\"7\""
    private val payment get() = mapOf<String, Any?>("amount_krw" to "100", "occurred_on" to day)
    private val expenseInput get() = payment + mapOf("case_id" to other, "node_id" to child)
    private val allocationInput get() = mapOf<String, Any?>("case_id" to other, "policy_id" to null, "claim_id" to null, "benefit_type" to "fixed", "amount_krw" to "100")
    private val payoutInput get() = payment + mapOf("allocations" to listOf(allocationInput))
    private val claimInput get() = mapOf<String, Any?>("case_id" to other, "policy_id" to child, "expense_ids" to listOf(id))
    private val reason get() = mapOf<String, Any?>("reason" to "합성 정정 사유")
    private val audit get() = mapOf<String, Any?>("id" to id, "household_id" to household, "created_by_member_id" to household, "updated_by_member_id" to household, "created_at" to now, "updated_at" to now, "version" to 7)
    private fun cash(kind: String = "medical_payment") = audit + mapOf("id" to child, "version" to 1, "kind" to kind, "flow" to if (kind in setOf("medical_payment", "insurance_return")) "out" else "in",
        "amount_krw" to "100", "period_month" to "2026-01", "occurred_on" to day, "date_precision" to "day", "member_id" to null,
        "account_id" to null, "card_id" to null, "reverses_id" to if (kind in setOf("medical_refund", "insurance_return")) other else null,
        "state" to "active", "note" to null, "action" to "create", "reason" to null, "conversion_id" to null, "editable" to false, "voidable" to false)
    private fun expense() = audit + mapOf("case_id" to other, "node_id" to child, "provider_name" to null, "receipt_reference" to null, "gross_medical_krw" to null, "public_coverage_krw" to "0",
        "correction_of_id" to null, "correction_reason" to null, "cash" to cash(), "line_count" to 0, "lines" to emptyList<Any>())
    private fun allocation() = allocationInput + audit + mapOf("id" to child, "payout_id" to id)
    private fun payout() = audit + mapOf("insurer_note" to null, "correction_of_id" to null, "correction_reason" to null, "cash" to cash("insurance_receipt"), "allocation_count" to 1, "allocations" to listOf(allocation()))
    private fun refund() = audit + mapOf("expense_id" to other, "correction_of_id" to null, "reason" to "합성 환불", "cash" to cash("medical_refund"))
    private fun returned() = audit + mapOf("payout_id" to other, "original_allocation_id" to child, "correction_of_id" to null, "reason" to "합성 반환", "cash" to cash("insurance_return"))
    private fun claim() = audit + claimInput + mapOf("claim_reference" to null, "submitted_on" to null, "requested_krw" to null, "decided_krw" to "0", "claim_state" to "draft", "decision_note" to null, "expense_count" to 1, "received_krw" to "600", "returned_krw" to "50", "net_received_krw" to "550")
    private val claimMoney = setOf("received_krw", "returned_krw", "net_received_krw")
    private fun claimRevision() = (claim() - audit.keys - "expense_count" - claimMoney) + mapOf("claim_id" to id, "version" to 7, "changed_by_member_id" to household, "changed_at" to now, "reason" to null)
    private fun allocationRevision() = allocationInput + mapOf("allocation_id" to child, "payout_id" to id, "version" to 7, "changed_by_member_id" to household, "changed_at" to now, "reason" to null)
    private fun page(vararg items: Any?) = mapOf("items" to items.toList(), "next_cursor" to null)
    private fun summary() = mapOf<String, Any?>("case_id" to other, "medical_paid_krw" to "100", "medical_refunded_krw" to "0", "net_medical_krw" to "100", "insurance_received_krw" to "150", "insurance_returned_krw" to "0", "net_received_krw" to "150", "net_burden_krw" to "-50",
        "benefits" to listOf("reimbursement", "fixed", "other").map { mapOf("benefit_type" to it, "received_krw" to if (it == "fixed") "150" else "0", "returned_krw" to "0", "net_received_krw" to if (it == "fixed") "150" else "0") })
    private fun bad(code: AuthCode = AuthCode.INVALID_REQUEST, action: () -> Unit) {
        try { action(); fail("Unsafe insurance event accepted") } catch (e: AuthFailure) { assertEquals(code, e.code); assertNull(e.message) }
    }
    private fun request(op: FinanceOperation, args: Map<String, Any?>) = FinancePolicy.prepare(op, args)
    private fun response(op: FinanceOperation, args: Map<String, Any?>, value: Any?, status: Int = 200) = FinancePolicy.response(op, request(op, args), status, value)
    private fun create(input: Map<String, Any?>) = mapOf("input" to input, "idempotencyKey" to "synthetic:1")
    private fun change(input: Map<String, Any?>, resource: String = id) = create(input) + mapOf("resourceId" to resource, "ifMatch" to tag)

    @Test fun allThirtyFourOperationsHaveFixedRoutesAndExactHeaderRequirements() {
        val commands = commands()
        assertEquals(34, commands.size)
        for ((op, args) in commands) {
            val r = request(op, args)
            assertTrue(op.name, FinancePolicy.metadataHttpAllowed(r.method, r.path, r.body, r.ifMatch, r.idempotencyKey))
            assertFalse(AuthPolicy.requestAllowed(r.method, r.path, r.ifMatch))
            bad { request(op, args + mapOf("url" to "/api/v1/insurance/policies/$id/reveal")) }
            bad { request(op, args + mapOf("headers" to emptyMap<String, String>())) }
            if (r.idempotencyKey != null) bad { request(op, args - "idempotencyKey") } else bad { request(op, args + mapOf("idempotencyKey" to "unexpected")) }
            if (r.ifMatch != null) {
                bad { request(op, args - "ifMatch") }
                for (v in listOf("7", "W/\"7\"", "*", "\"0\"")) bad { request(op, args + mapOf("ifMatch" to v)) }
            } else bad { request(op, args + mapOf("ifMatch" to tag)) }
        }
    }
    private fun commands(): List<Pair<FinanceOperation, Map<String, Any?>>> = listOf(
        FinanceOperation.MEDICAL_NODE_SUMMARY to mapOf("caseId" to other, "nodeId" to child),
        FinanceOperation.INSURANCE_CASE_SUMMARY to mapOf("caseId" to other),
        FinanceOperation.LIST_INSURANCE_CLAIMS to emptyMap(), FinanceOperation.CREATE_INSURANCE_CLAIM to mapOf("input" to claimInput),
        FinanceOperation.GET_INSURANCE_CLAIM to mapOf("claimId" to id), FinanceOperation.UPDATE_INSURANCE_CLAIM to mapOf("claimId" to id, "input" to reason + mapOf("expense_ids" to emptyList<String>()), "ifMatch" to tag),
        FinanceOperation.INSURANCE_CLAIM_HISTORY to mapOf("claimId" to id),
        FinanceOperation.LIST_MEDICAL_EXPENSES to emptyMap(), FinanceOperation.CREATE_MEDICAL_EXPENSE to create(expenseInput), FinanceOperation.GET_MEDICAL_EXPENSE to mapOf("resourceId" to id),
        FinanceOperation.CORRECT_MEDICAL_EXPENSE to change(expenseInput + reason), FinanceOperation.MEDICAL_EXPENSE_HISTORY to mapOf("resourceId" to id),
        FinanceOperation.LIST_MEDICAL_REFUNDS to mapOf("resourceId" to other), FinanceOperation.CREATE_MEDICAL_REFUND to change(payment + reason), FinanceOperation.VOID_MEDICAL_EXPENSE to change(reason),
        FinanceOperation.GET_MEDICAL_REFUND to mapOf("resourceId" to id), FinanceOperation.CORRECT_MEDICAL_REFUND to change(payment + reason), FinanceOperation.MEDICAL_REFUND_HISTORY to mapOf("resourceId" to id), FinanceOperation.VOID_MEDICAL_REFUND to change(reason),
        FinanceOperation.GET_PAYOUT_ALLOCATION to mapOf("allocationId" to child), FinanceOperation.LINK_PAYOUT_ALLOCATION to mapOf("allocationId" to child, "input" to reason + mapOf("claim_id" to null), "ifMatch" to tag, "idempotencyKey" to "synthetic:1"), FinanceOperation.PAYOUT_ALLOCATION_HISTORY to mapOf("allocationId" to child),
        FinanceOperation.LIST_INSURANCE_PAYOUTS to emptyMap(), FinanceOperation.CREATE_INSURANCE_PAYOUT to create(payoutInput), FinanceOperation.GET_INSURANCE_PAYOUT to mapOf("resourceId" to id), FinanceOperation.CORRECT_INSURANCE_PAYOUT to change(payoutInput + reason), FinanceOperation.INSURANCE_PAYOUT_HISTORY to mapOf("resourceId" to id),
        FinanceOperation.LIST_INSURANCE_RETURNS to mapOf("resourceId" to other), FinanceOperation.CREATE_INSURANCE_RETURN to change(payment + reason + mapOf("original_allocation_id" to child)), FinanceOperation.VOID_INSURANCE_PAYOUT to change(reason),
        FinanceOperation.GET_INSURANCE_RETURN to mapOf("resourceId" to id), FinanceOperation.CORRECT_INSURANCE_RETURN to change(payment + reason + mapOf("original_allocation_id" to child)), FinanceOperation.INSURANCE_RETURN_HISTORY to mapOf("resourceId" to id), FinanceOperation.VOID_INSURANCE_RETURN to change(reason))

    @Test fun allThirtyFourResponsesRespectActualGeneratedShapes() {
        for ((op, args) in commands()) {
            val body: Any = when (op) {
                FinanceOperation.MEDICAL_NODE_SUMMARY -> mapOf("case_id" to other, "node_id" to child, "subtree_node_count" to 2, "medical_paid_krw" to "100", "medical_refunded_krw" to "0", "net_medical_krw" to "100")
                FinanceOperation.INSURANCE_CASE_SUMMARY -> summary()
                FinanceOperation.LIST_INSURANCE_CLAIMS -> page(claim() - "expense_ids" - claimMoney)
                FinanceOperation.CREATE_INSURANCE_CLAIM, FinanceOperation.GET_INSURANCE_CLAIM, FinanceOperation.UPDATE_INSURANCE_CLAIM -> claim()
                FinanceOperation.INSURANCE_CLAIM_HISTORY -> page(claimRevision())
                FinanceOperation.LIST_MEDICAL_EXPENSES -> page(expense() - "lines")
                FinanceOperation.GET_MEDICAL_EXPENSE -> expense()
                FinanceOperation.MEDICAL_EXPENSE_HISTORY -> page(cash())
                FinanceOperation.LIST_MEDICAL_REFUNDS -> page(refund())
                FinanceOperation.GET_MEDICAL_REFUND -> refund()
                FinanceOperation.MEDICAL_REFUND_HISTORY -> page(cash("medical_refund"))
                FinanceOperation.GET_PAYOUT_ALLOCATION -> allocation()
                FinanceOperation.PAYOUT_ALLOCATION_HISTORY -> page(allocationRevision())
                FinanceOperation.LIST_INSURANCE_PAYOUTS -> page(payout() - "allocations")
                FinanceOperation.GET_INSURANCE_PAYOUT -> payout()
                FinanceOperation.INSURANCE_PAYOUT_HISTORY -> page(cash("insurance_receipt"))
                FinanceOperation.LIST_INSURANCE_RETURNS -> page(returned())
                FinanceOperation.GET_INSURANCE_RETURN -> returned()
                FinanceOperation.INSURANCE_RETURN_HISTORY -> page(cash("insurance_return"))
                FinanceOperation.LINK_PAYOUT_ALLOCATION -> mapOf("id" to child, "version" to 8)
                else -> mapOf("id" to if (op.name.startsWith("VOID")) id else child, "version" to 1)
            }
            val status = if (op.name.startsWith("CREATE") || op.name.startsWith("CORRECT")) 201 else 200
            assertEquals(op.name, body, response(op, args, body, status))
            assertEquals(op.name, body, response(op, args, withAddedFields(body), status))
            bad(AuthCode.ACCESS_DENIED) { response(op, args, body, 202) }
        }
    }
    @Test fun inputsRejectSecretsUnknownFieldsFloatsInvalidDatesAndDoublePaymentMethods() {
        val op = FinanceOperation.CREATE_MEDICAL_EXPENSE
        for (field in listOf("policy_number", "account_number", "cvc", "token", "cash", "household_id")) bad { request(op, create(expenseInput + mapOf(field to null))) }
        for (amount in listOf(100, 100.0, "0", "01", "-1", "1.0", "100000000000000000000")) bad { request(op, create(expenseInput + mapOf("amount_krw" to amount))) }
        for (date in listOf("2026-02-30", "0000-01-01", "2026-1-31")) bad { request(op, create(expenseInput + mapOf("occurred_on" to date))) }
        bad { request(op, create(expenseInput + mapOf("account_id" to id, "card_id" to child))) }
        for (op2 in listOf(FinanceOperation.CREATE_INSURANCE_PAYOUT, FinanceOperation.CORRECT_INSURANCE_PAYOUT)) {
            val args = if (op2.name.startsWith("CORRECT")) change(payoutInput + reason + mapOf("card_id" to child)) else create(payoutInput + mapOf("card_id" to child))
            bad { request(op2, args) }
        }
    }
    @Test fun exactSumsUseBigIntegersAndReceiptLinesAreOptional() {
        val amount = "99999999999999999999"
        request(FinanceOperation.CREATE_MEDICAL_EXPENSE, create(expenseInput + mapOf("amount_krw" to amount, "lines" to listOf(mapOf("label" to "합성 상세", "amount_krw" to amount)))))
        request(FinanceOperation.CREATE_INSURANCE_PAYOUT, create(payoutInput + mapOf("amount_krw" to amount, "allocations" to listOf(allocationInput + mapOf("amount_krw" to amount)))))
        bad { request(FinanceOperation.CREATE_MEDICAL_EXPENSE, create(expenseInput + mapOf("lines" to listOf(mapOf("label" to "합성", "amount_krw" to "99"))))) }
        bad { request(FinanceOperation.CREATE_INSURANCE_PAYOUT, create(payoutInput + mapOf("allocations" to listOf(allocationInput + mapOf("amount_krw" to "99"))))) }
        bad { request(FinanceOperation.CREATE_INSURANCE_PAYOUT, create(payoutInput + mapOf("allocations" to emptyList<String>()))) }
    }
    @Test fun claimAndAllocationEditsRequireActualChangedFieldsAndUniqueExpenseIds() {
        bad { request(FinanceOperation.CREATE_INSURANCE_CLAIM, mapOf("input" to claimInput + mapOf("expense_ids" to listOf(id, id)))) }
        for (input in listOf(reason, reason + mapOf("expense_ids" to null), reason + mapOf("claim_state" to null))) bad {
            request(FinanceOperation.UPDATE_INSURANCE_CLAIM, mapOf("claimId" to id, "input" to input, "ifMatch" to tag))
        }
        bad { request(FinanceOperation.LINK_PAYOUT_ALLOCATION, mapOf("allocationId" to id, "input" to reason, "ifMatch" to tag, "idempotencyKey" to "synthetic")) }
        bad { request(FinanceOperation.CREATE_INSURANCE_PAYOUT, create(payoutInput + mapOf("allocations" to listOf(allocationInput + mapOf("claim_id" to id))))) }
    }
    @Test fun nestedCashIsReadOnlyKindBoundAndHouseholdBoundWithoutEquatingVersions() {
        val op = FinanceOperation.GET_MEDICAL_EXPENSE; val args = mapOf("resourceId" to id)
        assertEquals(expense(), response(op, args, expense()))
        assertEquals(expense(), response(op, args, withAddedFields(expense())))
        for (change in listOf(mapOf("editable" to true), mapOf("voidable" to true), mapOf("kind" to "salary"), mapOf("flow" to "in"), mapOf("household_id" to other), mapOf("date_precision" to "month"), mapOf("period_month" to "2026-02"), mapOf("account_number" to null))) bad(AuthCode.ACCESS_DENIED) {
            response(op, args, expense() + mapOf("cash" to cash() + change))
        }
        bad(AuthCode.ACCESS_DENIED) { response(op, args, expense() + mapOf("id" to other)) }
        bad(AuthCode.ACCESS_DENIED) { response(op, args, expense() + mapOf("policy_number" to null)) }
    }
    @Test fun detailChildrenBindPayoutHouseholdAndAmountsAndCounts() {
        val op = FinanceOperation.GET_INSURANCE_PAYOUT; val args = mapOf("resourceId" to id)
        for (change in listOf(mapOf("payout_id" to other), mapOf("household_id" to other), mapOf("amount_krw" to "99"))) bad(AuthCode.ACCESS_DENIED) {
            response(op, args, payout() + mapOf("allocations" to listOf(allocation() + change)))
        }
        bad(AuthCode.ACCESS_DENIED) { response(op, args, payout() + mapOf("allocation_count" to 2)) }
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.GET_MEDICAL_EXPENSE, args, expense() + mapOf("line_count" to 1)) }
    }
    @Test fun correctionReceiptsMayUseNewIdAndRetainEarlierVersionWhileVoidAndLinkBindTarget() {
        response(FinanceOperation.CORRECT_MEDICAL_EXPENSE, change(expenseInput + reason), mapOf("id" to child, "version" to 1), 201)
        response(FinanceOperation.CREATE_MEDICAL_REFUND, change(payment + reason), mapOf("id" to child, "version" to 1), 201)
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.VOID_MEDICAL_EXPENSE, change(reason), mapOf("id" to child, "version" to 8)) }
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.VOID_MEDICAL_EXPENSE, change(reason), mapOf("id" to id, "version" to 8, "cash" to cash())) }
    }
    @Test fun historiesBindDomainIdsButCashHistoryKeepsItsOwnStableIdAndVersion() {
        val op = FinanceOperation.MEDICAL_EXPENSE_HISTORY; val args = mapOf("resourceId" to id, "query" to mapOf("cursor" to 3, "limit" to 2))
        val void = cash() + mapOf("state" to "void", "action" to "void", "version" to 2)
        response(op, args, page(void, cash()) + mapOf("next_cursor" to 1))
        for (items in listOf(listOf(cash(), void), listOf(void, void), listOf(void, cash() + mapOf("id" to other)), listOf(void, cash() + mapOf("household_id" to other)))) bad(AuthCode.ACCESS_DENIED) { response(op, args, mapOf("items" to items, "next_cursor" to null)) }
        bad(AuthCode.ACCESS_DENIED) { response(op, args, page(void, cash()) + mapOf("next_cursor" to 2)) }
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.INSURANCE_CLAIM_HISTORY, mapOf("claimId" to id), page(claimRevision() + mapOf("claim_id" to child))) }
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.PAYOUT_ALLOCATION_HISTORY, mapOf("allocationId" to child), page(allocationRevision() + mapOf("allocation_id" to id))) }
    }
    @Test fun listsEnforceParentFiltersCursorLimitAndNoDetailedChildArrays() {
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.LIST_MEDICAL_REFUNDS, mapOf("resourceId" to id), page(refund())) }
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.LIST_INSURANCE_RETURNS, mapOf("resourceId" to id), page(returned())) }
        val op = FinanceOperation.LIST_MEDICAL_EXPENSES; val item = expense() - "lines"
        // A detailed child array in a list item is dropped; list items never carry receipt lines.
        assertEquals(page(item), response(op, emptyMap(), page(expense())))
        bad(AuthCode.ACCESS_DENIED) { response(op, mapOf("query" to mapOf("case_id" to child)), page(item)) }
        bad(AuthCode.ACCESS_DENIED) { response(op, mapOf("query" to mapOf("state" to "void")), page(item)) }
        bad(AuthCode.ACCESS_DENIED) { response(op, mapOf("query" to mapOf("cursor" to id)), page(item)) }
        bad(AuthCode.ACCESS_DENIED) { response(op, mapOf("query" to mapOf("limit" to 1)), page(item, item + mapOf("id" to other))) }
    }
    @Test fun summariesKeepNegativeBurdenAndRejectArbitraryNodeInsuranceAttribution() {
        val op = FinanceOperation.INSURANCE_CASE_SUMMARY; val args = mapOf("caseId" to other)
        response(op, args, summary())
        for (change in listOf(mapOf("case_id" to id), mapOf("net_burden_krw" to "50"), mapOf("benefits" to emptyList<Any>()))) bad(AuthCode.ACCESS_DENIED) { response(op, args, summary() + change) }
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.MEDICAL_NODE_SUMMARY, mapOf("caseId" to other, "nodeId" to child), summary() + mapOf("node_id" to child)) }
    }
    @Test fun lowLevelAllowlistRejectsMalformedUrlsQueriesAndHeaderCrossover() {
        val path = "/api/v1/insurance/medical-expenses"
        for (suffix in listOf("?limit=01", "?limit=201", "?limit=1&limit=2", "?url=x", "?cursor=$id%2f", "#fragment", "/$id/reveal")) assertFalse(FinancePolicy.metadataHttpAllowed("GET", path + suffix, null, null))
        assertFalse(FinancePolicy.metadataHttpAllowed("GET", "https://synthetic.invalid$path", null, null))
        assertFalse(FinancePolicy.metadataHttpAllowed("POST", path, expenseInput, tag, "synthetic"))
        assertFalse(FinancePolicy.metadataHttpAllowed("GET", "$path/$id/history?cursor=01", null, null))
        assertFalse(FinancePolicy.metadataHttpAllowed("POST", path, expenseInput, null, "bad key"))
    }
    @Test fun claimListAcceptsExpenseFilter() {
        request(FinanceOperation.LIST_INSURANCE_CLAIMS, mapOf("query" to mapOf("expense_id" to id)))
        bad { request(FinanceOperation.LIST_INSURANCE_CLAIMS, mapOf("query" to mapOf("expense_id" to "not-a-uuid"))) }
    }
    @Test fun claimMoneyMustBeExactDifference() {
        response(FinanceOperation.GET_INSURANCE_CLAIM, mapOf("claimId" to id), claim())
        assertEquals(claim(), response(FinanceOperation.GET_INSURANCE_CLAIM, mapOf("claimId" to id), withAddedFields(claim())))
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.GET_INSURANCE_CLAIM, mapOf("claimId" to id), claim() + mapOf("net_received_krw" to "551")) }
    }
    @Test fun responseDefaultsAndImmutableHistoryFieldsCannotBeOmittedOrChanged() {
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.GET_INSURANCE_CLAIM, mapOf("claimId" to id), claim() - "claim_state") }
        val previous = cash() + mapOf("version" to 2, "state" to "void", "action" to "void")
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.MEDICAL_EXPENSE_HISTORY, mapOf("resourceId" to id), page(previous, cash() + mapOf("amount_krw" to "99"))) }
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.INSURANCE_CLAIM_HISTORY, mapOf("claimId" to id), page(claimRevision(), claimRevision() + mapOf("version" to 6, "policy_id" to other))) }
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.PAYOUT_ALLOCATION_HISTORY, mapOf("allocationId" to child), page(allocationRevision(), allocationRevision() + mapOf("version" to 6, "amount_krw" to "99"))) }
    }
    @Test fun eventErrorsPreserveOnlyKnownCodesAndLocallyDefinedMessages() {
        for ((code, status) in listOf("MEDICAL_EXPENSE_IN_CLAIM" to 409, "MEDICAL_EXPENSE_HAS_REFUNDS" to 409, "PRESCRIPTION_HAS_NO_PAYMENT" to 422, "RETURN_EXCEEDS_ALLOCATION" to 409, "INVALID_SUBMISSION_DATE" to 422)) {
            val unsafe = mapOf("error" to mapOf("code" to code, "message" to "SYNTHETIC PRIVATE DETAIL", "details" to mapOf("policy_number" to "SYNTHETIC")))
            val safe = AuthPolicy.safeError(status, unsafe, id)
            assertNotNull(safe)
            assertFalse(safe.toString().contains("SYNTHETIC"))
            assertFalse(safe.toString().contains("policy_number"))
            assertEquals("INTERNAL_ERROR", (AuthPolicy.safeError(500, unsafe, id)!!["error"] as Map<*, *>)["code"])
        }
    }
    @Test fun listsKeepServerOrderButRejectRepeatedCursor() {
        val op = FinanceOperation.LIST_MEDICAL_EXPENSES; val item = expense() - "lines"
        response(op, mapOf("query" to mapOf("cursor" to child)), page(item))
        bad(AuthCode.ACCESS_DENIED) { response(op, mapOf("query" to mapOf("cursor" to id)), page(item)) }
    }
}
