package io.github.jihoon22lee.sallimbook.auth

import java.net.URI
import java.math.BigInteger
import java.time.LocalDate
import java.time.OffsetDateTime

private typealias EventField = (Any?) -> Unit

/** Explicit projection of the generated insurance event contract; no URL or schema comes from JS. */
internal object InsuranceEventPolicy {
    private fun invalid(): Nothing = throw AuthFailure(AuthCode.INVALID_REQUEST)
    private fun obj(value: Any?): Map<String, Any?> {
        val row = value as? Map<*, *> ?: invalid()
        if (row.size > 48 || row.keys.any { it !is String }) invalid()
        return row.entries.associate { it.key as String to it.value }
    }
    private fun number(value: Any?, minimum: Long = 1, maximum: Long = 9_007_199_254_740_991L) {
        val number = when (value) { is Int -> value.toLong(); is Long -> value; else -> invalid() }
        if (number !in minimum..maximum) invalid()
    }
    private val id: EventField = { FinancePolicy.id(it); Unit }
    private val bool: EventField = { if (it !is Boolean) invalid() }
    private val date: EventField = {
        if (it !is String || !Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}").matches(it) || it.startsWith("0000")) invalid()
        try { LocalDate.parse(it) } catch (_: Exception) { invalid() }
    }
    private val timestamp: EventField = {
        if (it !is String || it.length > 40) invalid()
        try { OffsetDateTime.parse(it) } catch (_: Exception) { invalid() }
    }
    private fun choice(vararg values: String): EventField = { if (it !is String || it !in values) invalid() }
    private fun nullable(rule: EventField): EventField = { if (it != null) rule(it) }
    private fun shape(value: Any?, fields: Map<String, EventField>, required: Set<String> = fields.keys): Map<String, Any?> {
        val row = obj(value)
        if (!fields.keys.containsAll(row.keys) || !row.keys.containsAll(required)) invalid()
        row.forEach { (name, item) -> fields.getValue(name)(item) }
        return row
    }
    private fun tag(value: Any?): String {
        if (value !is String || !Regex("\"[1-9][0-9]{0,18}\"").matches(value)) invalid()
        return value
    }
    private fun integer(minimum: Long, maximum: Long): EventField = { number(it, minimum, maximum) }
    private val nil: EventField = { if (it != null) invalid() }
    private fun text(maximum: Int, minimum: Int): EventField = {
        if (it !is String || it.codePointCount(0, it.length) > maximum || it.trim().length < minimum) invalid()
    }
    private fun pattern(value: String): EventField = { if (it !is String || !Regex(value).matches(it)) invalid() }
    private fun array(rule: EventField, minimum: Int, maximum: Int): EventField = {
        if (it !is List<*> || it.size !in minimum..maximum) invalid()
        it.forEach(rule)
    }
    private fun key(value: Any?): String {
        if (value !is String || !Regex("[A-Za-z0-9._:-]{1,128}").matches(value)) invalid()
        return value
    }
    private data class Route(val method: String, val path: String, val input: String, val output: String, val query: Map<String, EventField>, val version: Boolean, val idem: Boolean, val status: Int)
    private val routes = mapOf(
        FinanceOperation.MEDICAL_NODE_SUMMARY to Route("GET", "/api/v1/insurance/cases/{caseId}/nodes/{nodeId}/summary", "", "NodeSummaryResponse", mapOf(), false, false, 200),
        FinanceOperation.INSURANCE_CASE_SUMMARY to Route("GET", "/api/v1/insurance/cases/{caseId}/summary", "", "CaseSummaryResponse", mapOf(), false, false, 200),
        FinanceOperation.LIST_INSURANCE_CLAIMS to Route("GET", "/api/v1/insurance/claims", "", "ClaimListResponse", mapOf("case_id" to nullable(id), "policy_id" to nullable(id), "claim_state" to nullable({ v -> validate("ClaimState", v); Unit }), "cursor" to nullable(id), "limit" to integer(1L, 200L)), false, false, 200),
        FinanceOperation.CREATE_INSURANCE_CLAIM to Route("POST", "/api/v1/insurance/claims", "ClaimCreate", "ClaimResponse", mapOf(), false, false, 201),
        FinanceOperation.GET_INSURANCE_CLAIM to Route("GET", "/api/v1/insurance/claims/{claimId}", "", "ClaimResponse", mapOf(), false, false, 200),
        FinanceOperation.UPDATE_INSURANCE_CLAIM to Route("PATCH", "/api/v1/insurance/claims/{claimId}", "ClaimPatch", "ClaimResponse", mapOf(), true, false, 200),
        FinanceOperation.INSURANCE_CLAIM_HISTORY to Route("GET", "/api/v1/insurance/claims/{claimId}/history", "", "ClaimHistoryResponse", mapOf("cursor" to nullable(integer(1L, 9007199254740991L)), "limit" to integer(1L, 200L)), false, false, 200),
        FinanceOperation.LIST_MEDICAL_EXPENSES to Route("GET", "/api/v1/insurance/medical-expenses", "", "ExpenseListResponse", mapOf("case_id" to nullable(id), "node_id" to nullable(id), "state" to nullable(choice("active", "void")), "cursor" to nullable(id), "limit" to integer(1L, 200L)), false, false, 200),
        FinanceOperation.CREATE_MEDICAL_EXPENSE to Route("POST", "/api/v1/insurance/medical-expenses", "ExpenseCreate", "EventReference", mapOf(), false, true, 201),
        FinanceOperation.GET_MEDICAL_EXPENSE to Route("GET", "/api/v1/insurance/medical-expenses/{resourceId}", "", "ExpenseResponse", mapOf(), false, false, 200),
        FinanceOperation.CORRECT_MEDICAL_EXPENSE to Route("POST", "/api/v1/insurance/medical-expenses/{resourceId}/correct", "ExpenseCorrection", "EventReference", mapOf(), true, true, 201),
        FinanceOperation.MEDICAL_EXPENSE_HISTORY to Route("GET", "/api/v1/insurance/medical-expenses/{resourceId}/history", "", "EventCashHistoryResponse", mapOf("cursor" to nullable(integer(1L, 9007199254740991L)), "limit" to integer(1L, 200L)), false, false, 200),
        FinanceOperation.LIST_MEDICAL_REFUNDS to Route("GET", "/api/v1/insurance/medical-expenses/{resourceId}/refunds", "", "RefundListResponse", mapOf("cursor" to nullable(id), "limit" to integer(1L, 200L)), false, false, 200),
        FinanceOperation.CREATE_MEDICAL_REFUND to Route("POST", "/api/v1/insurance/medical-expenses/{resourceId}/refunds", "RefundCreate", "EventReference", mapOf(), true, true, 201),
        FinanceOperation.VOID_MEDICAL_EXPENSE to Route("POST", "/api/v1/insurance/medical-expenses/{resourceId}/void", "EventReason", "EventReference", mapOf(), true, true, 200),
        FinanceOperation.GET_MEDICAL_REFUND to Route("GET", "/api/v1/insurance/medical-refunds/{resourceId}", "", "RefundResponse", mapOf(), false, false, 200),
        FinanceOperation.CORRECT_MEDICAL_REFUND to Route("POST", "/api/v1/insurance/medical-refunds/{resourceId}/correct", "RefundCreate", "EventReference", mapOf(), true, true, 201),
        FinanceOperation.MEDICAL_REFUND_HISTORY to Route("GET", "/api/v1/insurance/medical-refunds/{resourceId}/history", "", "EventCashHistoryResponse", mapOf("cursor" to nullable(integer(1L, 9007199254740991L)), "limit" to integer(1L, 200L)), false, false, 200),
        FinanceOperation.VOID_MEDICAL_REFUND to Route("POST", "/api/v1/insurance/medical-refunds/{resourceId}/void", "EventReason", "EventReference", mapOf(), true, true, 200),
        FinanceOperation.GET_PAYOUT_ALLOCATION to Route("GET", "/api/v1/insurance/payout-allocations/{allocationId}", "", "AllocationResponse", mapOf(), false, false, 200),
        FinanceOperation.LINK_PAYOUT_ALLOCATION to Route("PATCH", "/api/v1/insurance/payout-allocations/{allocationId}", "AllocationLinkPatch", "EventReference", mapOf(), true, true, 200),
        FinanceOperation.PAYOUT_ALLOCATION_HISTORY to Route("GET", "/api/v1/insurance/payout-allocations/{allocationId}/history", "", "AllocationHistoryResponse", mapOf("cursor" to nullable(integer(1L, 9007199254740991L)), "limit" to integer(1L, 200L)), false, false, 200),
        FinanceOperation.LIST_INSURANCE_PAYOUTS to Route("GET", "/api/v1/insurance/payouts", "", "PayoutListResponse", mapOf("case_id" to nullable(id), "policy_id" to nullable(id), "claim_id" to nullable(id), "state" to nullable(choice("active", "void")), "cursor" to nullable(id), "limit" to integer(1L, 200L)), false, false, 200),
        FinanceOperation.CREATE_INSURANCE_PAYOUT to Route("POST", "/api/v1/insurance/payouts", "PayoutCreate", "EventReference", mapOf(), false, true, 201),
        FinanceOperation.GET_INSURANCE_PAYOUT to Route("GET", "/api/v1/insurance/payouts/{resourceId}", "", "PayoutResponse", mapOf(), false, false, 200),
        FinanceOperation.CORRECT_INSURANCE_PAYOUT to Route("POST", "/api/v1/insurance/payouts/{resourceId}/correct", "PayoutCorrection", "EventReference", mapOf(), true, true, 201),
        FinanceOperation.INSURANCE_PAYOUT_HISTORY to Route("GET", "/api/v1/insurance/payouts/{resourceId}/history", "", "EventCashHistoryResponse", mapOf("cursor" to nullable(integer(1L, 9007199254740991L)), "limit" to integer(1L, 200L)), false, false, 200),
        FinanceOperation.LIST_INSURANCE_RETURNS to Route("GET", "/api/v1/insurance/payouts/{resourceId}/returns", "", "ReturnListResponse", mapOf("cursor" to nullable(id), "limit" to integer(1L, 200L)), false, false, 200),
        FinanceOperation.CREATE_INSURANCE_RETURN to Route("POST", "/api/v1/insurance/payouts/{resourceId}/returns", "ReturnCreate", "EventReference", mapOf(), true, true, 201),
        FinanceOperation.VOID_INSURANCE_PAYOUT to Route("POST", "/api/v1/insurance/payouts/{resourceId}/void", "EventReason", "EventReference", mapOf(), true, true, 200),
        FinanceOperation.GET_INSURANCE_RETURN to Route("GET", "/api/v1/insurance/returns/{resourceId}", "", "ReturnResponse", mapOf(), false, false, 200),
        FinanceOperation.CORRECT_INSURANCE_RETURN to Route("POST", "/api/v1/insurance/returns/{resourceId}/correct", "ReturnCreate", "EventReference", mapOf(), true, true, 201),
        FinanceOperation.INSURANCE_RETURN_HISTORY to Route("GET", "/api/v1/insurance/returns/{resourceId}/history", "", "EventCashHistoryResponse", mapOf("cursor" to nullable(integer(1L, 9007199254740991L)), "limit" to integer(1L, 200L)), false, false, 200),
        FinanceOperation.VOID_INSURANCE_RETURN to Route("POST", "/api/v1/insurance/returns/{resourceId}/void", "EventReason", "EventReference", mapOf(), true, true, 200),
    )
    fun supports(operation: FinanceOperation) = operation in routes
    private fun validate(schema: String, value: Any?): Map<String, Any?> {
        val row = when (schema) {
            "AllocationHistoryResponse" -> shape(value, mapOf(
            "items" to array({ v -> validate("AllocationRevisionResponse", v); Unit }, 0, 200),
            "next_cursor" to nullable(integer(1L, 9007199254740991L))
        ))
            "AllocationInput" -> shape(value, mapOf(
            "amount_krw" to pattern("^(0|[1-9][0-9]{0,19})\$"),
            "benefit_type" to { v -> validate("BenefitType", v); Unit },
            "case_id" to id,
            "claim_id" to nullable(id),
            "policy_id" to nullable(id)
        ), setOf("case_id", "benefit_type", "amount_krw"))
            "AllocationLinkPatch" -> shape(value, mapOf(
            "claim_id" to nullable(id),
            "policy_id" to nullable(id),
            "reason" to text(500, 1)
        ), setOf("reason"))
            "AllocationResponse" -> shape(value, mapOf(
            "amount_krw" to pattern("^(0|[1-9][0-9]{0,19})\$"),
            "benefit_type" to { v -> validate("BenefitType", v); Unit },
            "case_id" to id,
            "claim_id" to nullable(id),
            "created_at" to timestamp,
            "created_by_member_id" to id,
            "household_id" to id,
            "id" to id,
            "payout_id" to id,
            "policy_id" to nullable(id),
            "updated_at" to timestamp,
            "updated_by_member_id" to id,
            "version" to integer(1L, 9007199254740991L)
        ))
            "AllocationRevisionResponse" -> shape(value, mapOf(
            "allocation_id" to id,
            "amount_krw" to pattern("^(0|[1-9][0-9]{0,19})\$"),
            "benefit_type" to { v -> validate("BenefitType", v); Unit },
            "case_id" to id,
            "changed_at" to timestamp,
            "changed_by_member_id" to id,
            "claim_id" to nullable(id),
            "payout_id" to id,
            "policy_id" to nullable(id),
            "reason" to nullable(text(2000, 0)),
            "version" to integer(1L, 9007199254740991L)
        ))
            "BenefitSummary" -> shape(value, mapOf(
            "benefit_type" to { v -> validate("BenefitType", v); Unit },
            "net_received_krw" to pattern("^(0|[1-9][0-9]{0,19})\$"),
            "received_krw" to pattern("^(0|[1-9][0-9]{0,19})\$"),
            "returned_krw" to pattern("^(0|[1-9][0-9]{0,19})\$")
        ), setOf("benefit_type", "received_krw", "returned_krw", "net_received_krw"))
            "BenefitType" -> run { choice("reimbursement", "fixed", "other")(value); emptyMap() }
            "CaseSummaryResponse" -> shape(value, mapOf(
            "benefits" to array({ v -> validate("BenefitSummary", v); Unit }, 0, 200),
            "case_id" to id,
            "insurance_received_krw" to pattern("^(0|[1-9][0-9]{0,19})\$"),
            "insurance_returned_krw" to pattern("^(0|[1-9][0-9]{0,19})\$"),
            "medical_paid_krw" to pattern("^(0|[1-9][0-9]{0,19})\$"),
            "medical_refunded_krw" to pattern("^(0|[1-9][0-9]{0,19})\$"),
            "net_burden_krw" to pattern("^(0|-?[1-9][0-9]{0,19})\$"),
            "net_medical_krw" to pattern("^(0|[1-9][0-9]{0,19})\$"),
            "net_received_krw" to pattern("^(0|[1-9][0-9]{0,19})\$")
        ))
            "CashKind" -> run { choice("salary", "bonus", "other_income", "income_return", "insurance_receipt", "insurance_return", "medical_payment", "medical_refund", "fixed_payment")(value); emptyMap() }
            "CashResponse" -> shape(value, mapOf(
            "account_id" to nullable(id),
            "action" to choice("create", "correct", "void", "convert_source", "convert_result"),
            "amount_krw" to pattern("^(0|[1-9][0-9]{0,19})\$"),
            "card_id" to nullable(id),
            "conversion_id" to nullable(id),
            "created_at" to timestamp,
            "created_by_member_id" to id,
            "date_precision" to { v -> validate("Precision", v); Unit },
            "editable" to bool,
            "flow" to choice("in", "out"),
            "household_id" to id,
            "id" to id,
            "kind" to { v -> validate("CashKind", v); Unit },
            "member_id" to nullable(id),
            "note" to nullable(text(2000, 0)),
            "occurred_on" to nullable(date),
            "period_month" to pattern("^[0-9]{4}-(0[1-9]|1[0-2])\$"),
            "reason" to nullable(text(2000, 0)),
            "reverses_id" to nullable(id),
            "state" to choice("active", "void"),
            "updated_at" to timestamp,
            "updated_by_member_id" to id,
            "version" to integer(1L, 9007199254740991L),
            "voidable" to bool
        ))
            "ClaimCreate" -> shape(value, mapOf(
            "case_id" to id,
            "claim_reference" to nullable(text(120, 1)),
            "claim_state" to { v -> validate("ClaimState", v); Unit },
            "decided_krw" to nullable(pattern("^(0|[1-9][0-9]{0,19})\$")),
            "decision_note" to nullable(text(2000, 0)),
            "expense_ids" to array(id, 0, 200),
            "policy_id" to id,
            "requested_krw" to nullable(pattern("^(0|[1-9][0-9]{0,19})\$")),
            "submitted_on" to nullable(date)
        ), setOf("case_id", "policy_id"))
            "ClaimHistoryResponse" -> shape(value, mapOf(
            "items" to array({ v -> validate("ClaimRevisionResponse", v); Unit }, 0, 200),
            "next_cursor" to nullable(integer(1L, 9007199254740991L))
        ))
            "ClaimListItem" -> shape(value, mapOf(
            "case_id" to id,
            "claim_reference" to nullable(text(120, 1)),
            "claim_state" to { v -> validate("ClaimState", v); Unit },
            "created_at" to timestamp,
            "created_by_member_id" to id,
            "decided_krw" to nullable(pattern("^(0|[1-9][0-9]{0,19})\$")),
            "decision_note" to nullable(text(2000, 0)),
            "expense_count" to integer(0L, 9007199254740991L),
            "household_id" to id,
            "id" to id,
            "policy_id" to id,
            "requested_krw" to nullable(pattern("^(0|[1-9][0-9]{0,19})\$")),
            "submitted_on" to nullable(date),
            "updated_at" to timestamp,
            "updated_by_member_id" to id,
            "version" to integer(1L, 9007199254740991L)
        ))
            "ClaimListResponse" -> shape(value, mapOf(
            "items" to array({ v -> validate("ClaimListItem", v); Unit }, 0, 200),
            "next_cursor" to nullable(id)
        ))
            "ClaimPatch" -> shape(value, mapOf(
            "claim_reference" to nullable(text(120, 1)),
            "claim_state" to { v -> validate("ClaimState", v); Unit },
            "decided_krw" to nullable(pattern("^(0|[1-9][0-9]{0,19})\$")),
            "decision_note" to nullable(text(2000, 0)),
            "expense_ids" to array(id, 0, 200),
            "reason" to text(500, 1),
            "requested_krw" to nullable(pattern("^(0|[1-9][0-9]{0,19})\$")),
            "submitted_on" to nullable(date)
        ), setOf("reason"))
            "ClaimResponse" -> shape(value, mapOf(
            "case_id" to id,
            "claim_reference" to nullable(text(120, 1)),
            "claim_state" to { v -> validate("ClaimState", v); Unit },
            "created_at" to timestamp,
            "created_by_member_id" to id,
            "decided_krw" to nullable(pattern("^(0|[1-9][0-9]{0,19})\$")),
            "decision_note" to nullable(text(2000, 0)),
            "expense_count" to integer(0L, 9007199254740991L),
            "expense_ids" to array(id, 0, 200),
            "household_id" to id,
            "id" to id,
            "policy_id" to id,
            "requested_krw" to nullable(pattern("^(0|[1-9][0-9]{0,19})\$")),
            "submitted_on" to nullable(date),
            "updated_at" to timestamp,
            "updated_by_member_id" to id,
            "version" to integer(1L, 9007199254740991L)
        ))
            "ClaimRevisionResponse" -> shape(value, mapOf(
            "case_id" to id,
            "changed_at" to timestamp,
            "changed_by_member_id" to id,
            "claim_id" to id,
            "claim_reference" to nullable(text(120, 1)),
            "claim_state" to { v -> validate("ClaimState", v); Unit },
            "decided_krw" to nullable(pattern("^(0|[1-9][0-9]{0,19})\$")),
            "decision_note" to nullable(text(2000, 0)),
            "expense_ids" to array(id, 0, 200),
            "policy_id" to id,
            "reason" to nullable(text(2000, 0)),
            "requested_krw" to nullable(pattern("^(0|[1-9][0-9]{0,19})\$")),
            "submitted_on" to nullable(date),
            "version" to integer(1L, 9007199254740991L)
        ))
            "ClaimState" -> run { choice("draft", "submitted", "documents_required", "reviewing", "decided", "closed", "withdrawn")(value); emptyMap() }
            "EventCashHistoryResponse" -> shape(value, mapOf(
            "items" to array({ v -> validate("CashResponse", v); Unit }, 0, 200),
            "next_cursor" to nullable(integer(1L, 9007199254740991L))
        ))
            "EventReason" -> shape(value, mapOf(
            "reason" to text(500, 1)
        ), setOf("reason"))
            "EventReference" -> shape(value, mapOf(
            "id" to id,
            "version" to integer(1L, 9007199254740991L)
        ), setOf("id", "version"))
            "ExpenseCorrection" -> shape(value, mapOf(
            "account_id" to nullable(id),
            "amount_krw" to pattern("^(0|[1-9][0-9]{0,19})\$"),
            "card_id" to nullable(id),
            "case_id" to id,
            "gross_medical_krw" to nullable(pattern("^(0|[1-9][0-9]{0,19})\$")),
            "lines" to array({ v -> validate("ExpenseLineInput", v); Unit }, 0, 200),
            "node_id" to id,
            "note" to nullable(text(2000, 0)),
            "occurred_on" to date,
            "provider_name" to nullable(text(120, 1)),
            "public_coverage_krw" to nullable(pattern("^(0|[1-9][0-9]{0,19})\$")),
            "reason" to text(500, 1),
            "receipt_reference" to nullable(text(120, 1))
        ), setOf("reason", "amount_krw", "occurred_on", "case_id", "node_id"))
            "ExpenseCreate" -> shape(value, mapOf(
            "account_id" to nullable(id),
            "amount_krw" to pattern("^(0|[1-9][0-9]{0,19})\$"),
            "card_id" to nullable(id),
            "case_id" to id,
            "gross_medical_krw" to nullable(pattern("^(0|[1-9][0-9]{0,19})\$")),
            "lines" to array({ v -> validate("ExpenseLineInput", v); Unit }, 0, 200),
            "node_id" to id,
            "note" to nullable(text(2000, 0)),
            "occurred_on" to date,
            "provider_name" to nullable(text(120, 1)),
            "public_coverage_krw" to nullable(pattern("^(0|[1-9][0-9]{0,19})\$")),
            "receipt_reference" to nullable(text(120, 1))
        ), setOf("amount_krw", "occurred_on", "case_id", "node_id"))
            "ExpenseLineInput" -> shape(value, mapOf(
            "amount_krw" to pattern("^(0|[1-9][0-9]{0,19})\$"),
            "detail_type" to text(40, 1),
            "label" to text(120, 1)
        ), setOf("label", "amount_krw"))
            "ExpenseLineResponse" -> shape(value, mapOf(
            "amount_krw" to pattern("^(0|[1-9][0-9]{0,19})\$"),
            "detail_type" to text(40, 1),
            "id" to id,
            "label" to text(120, 1)
        ))
            "ExpenseListItem" -> shape(value, mapOf(
            "case_id" to id,
            "cash" to { v -> validate("CashResponse", v); Unit },
            "correction_of_id" to nullable(id),
            "correction_reason" to nullable(text(2000, 0)),
            "created_at" to timestamp,
            "created_by_member_id" to id,
            "gross_medical_krw" to nullable(pattern("^(0|[1-9][0-9]{0,19})\$")),
            "household_id" to id,
            "id" to id,
            "line_count" to integer(0L, 9007199254740991L),
            "node_id" to id,
            "provider_name" to nullable(text(2000, 0)),
            "public_coverage_krw" to nullable(pattern("^(0|[1-9][0-9]{0,19})\$")),
            "receipt_reference" to nullable(text(2000, 0)),
            "updated_at" to timestamp,
            "updated_by_member_id" to id,
            "version" to integer(1L, 9007199254740991L)
        ))
            "ExpenseListResponse" -> shape(value, mapOf(
            "items" to array({ v -> validate("ExpenseListItem", v); Unit }, 0, 200),
            "next_cursor" to nullable(id)
        ))
            "ExpenseResponse" -> shape(value, mapOf(
            "case_id" to id,
            "cash" to { v -> validate("CashResponse", v); Unit },
            "correction_of_id" to nullable(id),
            "correction_reason" to nullable(text(2000, 0)),
            "created_at" to timestamp,
            "created_by_member_id" to id,
            "gross_medical_krw" to nullable(pattern("^(0|[1-9][0-9]{0,19})\$")),
            "household_id" to id,
            "id" to id,
            "line_count" to integer(0L, 9007199254740991L),
            "lines" to array({ v -> validate("ExpenseLineResponse", v); Unit }, 0, 200),
            "node_id" to id,
            "provider_name" to nullable(text(2000, 0)),
            "public_coverage_krw" to nullable(pattern("^(0|[1-9][0-9]{0,19})\$")),
            "receipt_reference" to nullable(text(2000, 0)),
            "updated_at" to timestamp,
            "updated_by_member_id" to id,
            "version" to integer(1L, 9007199254740991L)
        ))
            "NodeSummaryResponse" -> shape(value, mapOf(
            "case_id" to id,
            "medical_paid_krw" to pattern("^(0|[1-9][0-9]{0,19})\$"),
            "medical_refunded_krw" to pattern("^(0|[1-9][0-9]{0,19})\$"),
            "net_medical_krw" to pattern("^(0|[1-9][0-9]{0,19})\$"),
            "node_id" to id,
            "subtree_node_count" to integer(1L, 9007199254740991L)
        ))
            "PayoutCorrection" -> shape(value, mapOf(
            "account_id" to nullable(id),
            "allocations" to array({ v -> validate("AllocationInput", v); Unit }, 1, 200),
            "amount_krw" to pattern("^(0|[1-9][0-9]{0,19})\$"),
            "card_id" to nil,
            "insurer_note" to nullable(text(1000, 0)),
            "note" to nullable(text(2000, 0)),
            "occurred_on" to date,
            "reason" to text(500, 1)
        ), setOf("reason", "amount_krw", "occurred_on", "allocations"))
            "PayoutCreate" -> shape(value, mapOf(
            "account_id" to nullable(id),
            "allocations" to array({ v -> validate("AllocationInput", v); Unit }, 1, 200),
            "amount_krw" to pattern("^(0|[1-9][0-9]{0,19})\$"),
            "card_id" to nil,
            "insurer_note" to nullable(text(1000, 0)),
            "note" to nullable(text(2000, 0)),
            "occurred_on" to date
        ), setOf("amount_krw", "occurred_on", "allocations"))
            "PayoutListItem" -> shape(value, mapOf(
            "allocation_count" to integer(1L, 9007199254740991L),
            "cash" to { v -> validate("CashResponse", v); Unit },
            "correction_of_id" to nullable(id),
            "correction_reason" to nullable(text(2000, 0)),
            "created_at" to timestamp,
            "created_by_member_id" to id,
            "household_id" to id,
            "id" to id,
            "insurer_note" to nullable(text(2000, 0)),
            "updated_at" to timestamp,
            "updated_by_member_id" to id,
            "version" to integer(1L, 9007199254740991L)
        ))
            "PayoutListResponse" -> shape(value, mapOf(
            "items" to array({ v -> validate("PayoutListItem", v); Unit }, 0, 200),
            "next_cursor" to nullable(id)
        ))
            "PayoutResponse" -> shape(value, mapOf(
            "allocation_count" to integer(1L, 9007199254740991L),
            "allocations" to array({ v -> validate("AllocationResponse", v); Unit }, 0, 200),
            "cash" to { v -> validate("CashResponse", v); Unit },
            "correction_of_id" to nullable(id),
            "correction_reason" to nullable(text(2000, 0)),
            "created_at" to timestamp,
            "created_by_member_id" to id,
            "household_id" to id,
            "id" to id,
            "insurer_note" to nullable(text(2000, 0)),
            "updated_at" to timestamp,
            "updated_by_member_id" to id,
            "version" to integer(1L, 9007199254740991L)
        ))
            "Precision" -> run { choice("day", "month")(value); emptyMap() }
            "RefundCreate" -> shape(value, mapOf(
            "account_id" to nullable(id),
            "amount_krw" to pattern("^(0|[1-9][0-9]{0,19})\$"),
            "card_id" to nullable(id),
            "note" to nullable(text(2000, 0)),
            "occurred_on" to date,
            "reason" to text(500, 1)
        ), setOf("reason", "amount_krw", "occurred_on"))
            "RefundListResponse" -> shape(value, mapOf(
            "items" to array({ v -> validate("RefundResponse", v); Unit }, 0, 200),
            "next_cursor" to nullable(id)
        ))
            "RefundResponse" -> shape(value, mapOf(
            "cash" to { v -> validate("CashResponse", v); Unit },
            "correction_of_id" to nullable(id),
            "created_at" to timestamp,
            "created_by_member_id" to id,
            "expense_id" to id,
            "household_id" to id,
            "id" to id,
            "reason" to text(2000, 0),
            "updated_at" to timestamp,
            "updated_by_member_id" to id,
            "version" to integer(1L, 9007199254740991L)
        ))
            "ReturnCreate" -> shape(value, mapOf(
            "account_id" to nullable(id),
            "amount_krw" to pattern("^(0|[1-9][0-9]{0,19})\$"),
            "card_id" to nil,
            "note" to nullable(text(2000, 0)),
            "occurred_on" to date,
            "original_allocation_id" to id,
            "reason" to text(500, 1)
        ), setOf("reason", "amount_krw", "occurred_on", "original_allocation_id"))
            "ReturnListResponse" -> shape(value, mapOf(
            "items" to array({ v -> validate("ReturnResponse", v); Unit }, 0, 200),
            "next_cursor" to nullable(id)
        ))
            "ReturnResponse" -> shape(value, mapOf(
            "cash" to { v -> validate("CashResponse", v); Unit },
            "correction_of_id" to nullable(id),
            "created_at" to timestamp,
            "created_by_member_id" to id,
            "household_id" to id,
            "id" to id,
            "original_allocation_id" to id,
            "payout_id" to id,
            "reason" to text(2000, 0),
            "updated_at" to timestamp,
            "updated_by_member_id" to id,
            "version" to integer(1L, 9007199254740991L)
        ))
            else -> invalid()
        }
        invariants(schema, row)
        return row
    }
    private fun money(value: Any?): BigInteger = (value as? String ?: invalid()).toBigInteger()
    private fun sum(rows: List<*>, field: String) = rows.fold(BigInteger.ZERO) { acc, value -> acc + money(obj(value)[field]) }
    private fun unique(values: List<*>) { if (values.toSet().size != values.size) invalid() }
    private fun invariants(schema: String, row: Map<String, Any?>) {
        if (schema in setOf("ExpenseCreate", "ExpenseCorrection", "RefundCreate", "PayoutCreate", "PayoutCorrection", "ReturnCreate")) {
            if (row["amount_krw"] == "0" || row["account_id"] != null && row["card_id"] != null) invalid()
            val details = (row["lines"] ?: row["allocations"]) as? List<*>
            if (!details.isNullOrEmpty() && sum(details, "amount_krw") != money(row["amount_krw"])) invalid()
        }
        if (schema in setOf("AllocationInput", "AllocationResponse", "AllocationRevisionResponse")) {
            if (row["amount_krw"] == "0" || row["claim_id"] != null && row["policy_id"] == null) invalid()
        }
        if (schema in setOf("ClaimPatch", "AllocationLinkPatch") && (row.keys - "reason").isEmpty()) invalid()
        (row["expense_ids"] as? List<*>)?.let(::unique)
        if (schema == "CashResponse") {
            if (row["editable"] != false || row["voidable"] != false || row["date_precision"] != "day" || row["occurred_on"] == null ||
                row["period_month"] != (row["occurred_on"] as String).take(7) || row["amount_krw"] == "0" || row["member_id"] != null ||
                row["account_id"] != null && row["card_id"] != null || row["conversion_id"] != null) invalid()
            val expected = when (row["kind"]) { "medical_payment", "insurance_return" -> "out"; "medical_refund", "insurance_receipt" -> "in"; else -> invalid() }
            if (row["flow"] != expected || row["action"] != if (row["state"] == "void") "void" else "create") invalid()
            if ((row["kind"] in setOf("medical_refund", "insurance_return")) != (row["reverses_id"] != null)) invalid()
            if (row["kind"] in setOf("insurance_receipt", "insurance_return") && row["card_id"] != null) invalid()
        }
        if (row["cash"] != null) {
            val cash = obj(row["cash"])
            val kind = when { schema.startsWith("Expense") -> "medical_payment"; schema.startsWith("Refund") -> "medical_refund"; schema.startsWith("Payout") -> "insurance_receipt"; schema.startsWith("Return") -> "insurance_return"; else -> invalid() }
            if (cash["household_id"] != row["household_id"] || cash["kind"] != kind || row["id"] == cash["id"]) invalid()
            if (row["correction_of_id"] == row["id"]) invalid()
            if ("correction_reason" in row && (row["correction_of_id"] == null) != (row["correction_reason"] == null)) invalid()
            (row["lines"] as? List<*>)?.let { lines ->
                if (lines.size.toLong() != (row["line_count"] as Number).toLong()) invalid()
                unique(lines.map { obj(it)["id"] })
                if (lines.isNotEmpty() && sum(lines, "amount_krw") != money(cash["amount_krw"])) invalid()
            }
            (row["allocations"] as? List<*>)?.let { allocations ->
                if (allocations.size.toLong() != (row["allocation_count"] as Number).toLong() || sum(allocations, "amount_krw") != money(cash["amount_krw"])) invalid()
                unique(allocations.map { obj(it)["id"] })
                allocations.forEach { val a = obj(it); if (a["household_id"] != row["household_id"] || a["payout_id"] != row["id"]) invalid() }
            }
        }
        if (schema == "ClaimResponse" && (row["expense_ids"] as List<*>).size.toLong() != (row["expense_count"] as Number).toLong()) invalid()
        if (schema == "BenefitSummary") {
            if (money(row["received_krw"]) - money(row["returned_krw"]) != money(row["net_received_krw"])) invalid()
        }
        if (schema in setOf("CaseSummaryResponse", "NodeSummaryResponse")) {
            if (money(row["medical_paid_krw"]) - money(row["medical_refunded_krw"]) != money(row["net_medical_krw"])) invalid()
        }
        if (schema == "CaseSummaryResponse") {
            val benefits = row["benefits"] as List<*>
            if (benefits.map { obj(it)["benefit_type"] }.toSet() != setOf("reimbursement", "fixed", "other") || benefits.size != 3) invalid()
            if (sum(benefits, "received_krw") != money(row["insurance_received_krw"]) || sum(benefits, "returned_krw") != money(row["insurance_returned_krw"]) ||
                sum(benefits, "net_received_krw") != money(row["net_received_krw"]) || money(row["net_medical_krw"]) - money(row["net_received_krw"]) != money(row["net_burden_krw"])) invalid()
        }
    }
    private fun query(route: Route, value: Any?): Map<String, Any?> = if (value == null) emptyMap() else shape(value, route.query, emptySet()).filterValues { it != null }
    fun prepare(operation: FinanceOperation, value: Any?): FinanceRequest {
        val route = routes[operation] ?: invalid()
        val args = obj(value)
        val ids = Regex("\\{([^}]+)\\}").findAll(route.path).map { it.groupValues[1] }.toSet()
        val required = ids + (if (route.input.isNotEmpty()) setOf("input") else emptySet()) +
            (if (route.version) setOf("ifMatch") else emptySet()) + (if (route.idem) setOf("idempotencyKey") else emptySet())
        if (!args.keys.containsAll(required) || !(required + if (route.query.isNotEmpty()) setOf("query") else emptySet()).containsAll(args.keys)) invalid()
        var path = route.path
        ids.forEach { path = path.replace("{$it}", FinancePolicy.id(args[it]).lowercase()) }
        val values = query(route, args["query"])
        if (values.isNotEmpty()) path += "?" + values.toSortedMap().entries.joinToString("&") { "${it.key}=${if (it.value is String) (it.value as String).lowercase() else it.value}" }
        return FinanceRequest(route.method, path, if (route.input.isEmpty()) null else validate(route.input, args["input"]),
            if (route.version) tag(args["ifMatch"]) else null, if (route.idem) key(args["idempotencyKey"]) else null)
    }
    private fun queryValues(route: Route, uri: URI): Map<String, Any?> {
        val values = mutableMapOf<String, Any?>()
        uri.rawQuery?.let { raw ->
            if (raw.isEmpty() || route.query.isEmpty()) invalid()
            raw.split('&').forEach { part ->
                val pair = part.split('=', limit = 2)
                if (pair.size != 2 || pair[0] in values) invalid()
                values[pair[0]] = if (pair[0] == "limit" || pair[0] == "cursor" && route.output.endsWith("HistoryResponse")) pair[1].toLongOrNull() ?: invalid() else pair[1]
            }
        }
        return query(route, values)
    }
    fun httpAllowed(method: String, path: String, body: Any?, ifMatch: String?, idempotencyKey: String?): Boolean = try {
        val uri = URI(path)
        if (path.length > 2048 || uri.isAbsolute || uri.rawAuthority != null || uri.rawFragment != null || '%' in path || '\\' in path || path.any { it.isWhitespace() || it.code < 32 }) invalid()
        val parts = uri.rawPath.split('/')
        val entry = routes.entries.firstOrNull { (_, route) ->
            val pattern = route.path.split('/')
            route.method == method && pattern.size == parts.size && pattern.indices.all { pattern[it].startsWith('{') || pattern[it] == parts[it] }
        } ?: invalid()
        val route = entry.value
        val args = mutableMapOf<String, Any?>()
        route.path.split('/').forEachIndexed { n, p -> if (p.startsWith('{')) args[p.removeSurrounding("{", "}")] = parts[n] }
        if (route.input.isNotEmpty()) args["input"] = body else if (body != null) invalid()
        if (route.version) args["ifMatch"] = ifMatch else if (ifMatch != null) invalid()
        if (route.idem) args["idempotencyKey"] = idempotencyKey else if (idempotencyKey != null) invalid()
        if (uri.rawQuery != null) args["query"] = queryValues(route, uri)
        val request = prepare(entry.key, args)
        request.path == path && request.body == body && request.ifMatch == ifMatch && request.idempotencyKey == idempotencyKey
    } catch (_: Exception) { false }
    fun response(operation: FinanceOperation, request: FinanceRequest, status: Int, value: Any?): Any? {
        try {
            val route = routes[operation] ?: invalid()
            if (status != route.status) invalid()
            val row = validate(route.output, value)
            val uri = URI(request.path)
            val parts = uri.path.split('/')
            val target = mutableMapOf<String, String>()
            route.path.split('/').forEachIndexed { n, p -> if (p.startsWith('{')) target[p.removeSurrounding("{", "}")] = parts[n] }
            val q = queryValues(route, uri)
            fun bound(record: Map<String, Any?>) {
                for ((arg, field) in mapOf("caseId" to "case_id", "nodeId" to "node_id", "claimId" to "claim_id", "allocationId" to "allocation_id")) {
                    target[arg]?.let { expected ->
                        val name = if (route.output in setOf("ClaimResponse", "AllocationResponse", "EventReference") && arg in setOf("claimId", "allocationId")) "id" else field
                        if (record[name] != expected) invalid()
                    }
                }
                if (route.output == "RefundListResponse" && record["expense_id"] != target["resourceId"]) invalid()
                if (route.output == "ReturnListResponse" && record["payout_id"] != target["resourceId"]) invalid()
                for (filter in listOf("case_id", "node_id", "policy_id", "claim_state")) {
                    if (q[filter] != null && filter in record && record[filter] != q[filter]) invalid()
                }
                if (q["state"] != null && obj(record["cash"])["state"] != q["state"]) invalid()
            }
            if (route.output == "EventReference") {
                // A retry receipt retains the mutation's version. It is not the latest domain state.
                if (request.path.endsWith("/void") && row["id"] != target["resourceId"]) invalid()
                if (operation == FinanceOperation.LINK_PAYOUT_ALLOCATION && row["id"] != target["allocationId"]) invalid()
                return row
            }
            if (row["items"] != null) {
                val items = (row["items"] as List<*>).map(::obj)
                if (items.size > ((q["limit"] as? Number)?.toInt() ?: 200)) invalid()
                val history = route.output.endsWith("HistoryResponse")
                val field = if (history) "version" else "id"
                val keys = items.map { it[field] ?: invalid() }
                unique(keys)
                if (history) {
                    var previous = (q["cursor"] as? Number)?.toLong() ?: Long.MAX_VALUE
                    for (item in items) { val version = (item["version"] as Number).toLong(); if (version >= previous) invalid(); previous = version }
                } else {
                    var previous = q["cursor"] as? String
                    for (item in items) { val id = item["id"] as String; if (previous != null && id >= previous!!) invalid(); previous = id }
                }
                if (row["next_cursor"] != null && (keys.isEmpty() || row["next_cursor"].toString() != keys.last().toString())) invalid()
                if (items.mapNotNull { it["household_id"] }.toSet().size > 1) invalid()
                items.forEach(::bound)
                val stable = when (route.output) {
                    "ClaimHistoryResponse" -> setOf("case_id", "policy_id")
                    "AllocationHistoryResponse" -> setOf("payout_id", "case_id", "benefit_type", "amount_krw")
                    else -> emptySet()
                }
                if (stable.isNotEmpty() && items.map { it.filterKeys { key -> key in stable } }.toSet().size > 1) invalid()
                if (route.output == "EventCashHistoryResponse") {
                    if (items.map { it["id"] }.toSet().size > 1) invalid()
                    val kind = when (parts[4]) { "medical-expenses" -> "medical_payment"; "medical-refunds" -> "medical_refund"; "payouts" -> "insurance_receipt"; "returns" -> "insurance_return"; else -> invalid() }
                    if (items.any { it["kind"] != kind }) invalid()
                    val mutable = setOf("version", "state", "action", "reason", "updated_at", "updated_by_member_id")
                    if (items.map { it - mutable }.toSet().size > 1) invalid()
                }
            } else {
                bound(row)
                if (target["resourceId"] != null && row["id"] != target["resourceId"]) invalid()
                if (operation == FinanceOperation.CREATE_INSURANCE_CLAIM && (!row["case_id"].toString().equals(request.body?.get("case_id").toString(), true) || !row["policy_id"].toString().equals(request.body?.get("policy_id").toString(), true))) invalid()
            }
            return row
        } catch (_: Exception) { throw AuthFailure(AuthCode.ACCESS_DENIED) }
    }
}
