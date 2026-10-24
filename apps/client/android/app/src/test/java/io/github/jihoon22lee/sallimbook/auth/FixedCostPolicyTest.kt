package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test
import java.time.YearMonth

class FixedCostPolicyTest {
    private val ruleId = "00000000-0000-4000-8000-000000000001"
    private val obligationId = "00000000-0000-4000-8000-000000000002"
    private val paymentId = "00000000-0000-4000-8000-000000000003"
    private val cashId = "00000000-0000-4000-8000-000000000004"
    private val memberId = "00000000-0000-4000-8000-000000000005"
    private val now = "2026-01-31T00:00:00Z"
    private val tag = "\"7\""
    private fun bad(code: AuthCode = AuthCode.INVALID_REQUEST, action: () -> Unit) {
        try { action(); fail("Unsafe fixed-cost metadata accepted") }
        catch (failure: AuthFailure) { assertEquals(code, failure.code); assertNull(failure.message) }
    }
    private fun request(op: FinanceOperation, args: Map<String, Any?>) = FinancePolicy.prepare(op, args)
    private fun terms() = mapOf<String, Any?>("title" to "합성 정기납부", "category" to "합성 분류", "amount_mode" to "fixed", "expected_amount_krw" to "33000",
        "economic_type" to "expense", "loan_asset_id" to null, "account_id" to null, "card_id" to null, "currency_reference" to null,
        "foreign_amount_reference" to null, "note" to null, "anchor_date" to "2026-01-31", "frequency" to "monthly", "interval_count" to 1)
    private fun create() = terms() + mapOf("effective_from" to "2026-01-01")
    private fun change() = terms() + mapOf("effective_from" to "2026-02-01", "reason" to "합성 적용 변경")
    private fun write(input: Map<String, Any?>) = mapOf("input" to input, "idempotencyKey" to "synthetic.stable:fixed-1")
    private fun mutation(name: String, id: String, input: Map<String, Any?>) = write(input) + mapOf(name to id, "ifMatch" to tag)
    private fun version() = terms() + mapOf("id" to ruleId, "effective_from" to "2026-01-01", "effective_until" to null, "reason" to null, "created_at" to now)
    private fun rule() = mapOf("id" to ruleId, "household_id" to memberId, "version" to 8, "ended_on" to null, "end_reason" to null, "versions" to listOf(version()))
    private fun obligation() = terms() - setOf("anchor_date", "frequency", "interval_count") + mapOf("id" to obligationId, "household_id" to memberId, "rule_id" to ruleId,
        "rule_version_id" to ruleId, "version" to 8, "nominal_date" to "2026-01-31", "scheduled_date" to "2026-01-31", "schedule_state" to "active",
        "manual_override" to false, "skipped" to false, "manually_completed" to false, "status" to "paid", "actual_amount_krw" to "35000",
        "difference_krw" to "2000", "consumption_krw" to "35000", "principal_krw" to "0", "asset_transfer_krw" to "0", "created_at" to now, "updated_at" to now)
    private fun history() = mapOf("id" to obligationId, "version" to 8, "rule_version_id" to ruleId, "expected_amount_krw" to "33000", "nominal_date" to "2026-01-31",
        "scheduled_date" to "2026-01-31", "schedule_state" to "active", "manual_override" to false, "skipped" to false, "manually_completed" to false,
        "action" to "settle", "reason" to null, "updated_at" to now)
    private fun cash(amount: String = "35000", void: Boolean = false) = mapOf<String, Any?>("id" to cashId, "household_id" to memberId, "kind" to "fixed_payment", "flow" to "out",
        "amount_krw" to amount, "period_month" to "2026-01", "occurred_on" to "2026-01-31", "date_precision" to "day", "member_id" to null, "account_id" to null,
        "card_id" to null, "reverses_id" to null, "state" to if (void) "void" else "active", "note" to null, "created_by_member_id" to memberId, "updated_by_member_id" to memberId,
        "created_at" to now, "updated_at" to now, "version" to if (void) 2 else 1, "action" to if (void) "void" else "create", "reason" to if (void) "합성 취소" else null,
        "conversion_id" to null, "editable" to false, "voidable" to false)
    private fun settlement() = mapOf("id" to paymentId, "obligation_id" to obligationId, "economic_type" to "expense", "principal_krw" to "0",
        "consumption_krw" to "35000", "asset_transfer_krw" to "0", "cash" to cash())
    private fun payment() = mapOf("amount_krw" to "35000", "occurred_on" to "2026-01-31")
    private fun deletion() = mapOf<String, Any?>("ruleId" to ruleId, "ifMatch" to tag, "idempotencyKey" to "synthetic.stable:fixed-delete")

    @Test fun allNineteenNamedCommandsReachOnlyTheirFixedRoutesAndHeaders() {
        val commands = listOf(
            FinanceOperation.LIST_RECURRING_RULES to emptyMap<String, Any?>(),
            FinanceOperation.CREATE_RECURRING_RULE to write(create()),
            FinanceOperation.GET_RECURRING_RULE to mapOf("ruleId" to ruleId),
            FinanceOperation.CHANGE_RECURRING_RULE to mutation("ruleId", ruleId, change()),
            FinanceOperation.END_RECURRING_RULE to mutation("ruleId", ruleId, mapOf("effective_on" to "2026-02-01", "reason" to "합성 종료")),
            FinanceOperation.DELETE_RECURRING_RULE to deletion(),
            FinanceOperation.GENERATE_OBLIGATIONS to write(mapOf("start_date" to "2026-01-01", "end_date" to "2026-12-31", "rule_id" to ruleId)),
            FinanceOperation.LIST_OBLIGATIONS to mapOf("query" to mapOf("month" to "2026-01", "cursor" to obligationId, "limit" to 200)),
            FinanceOperation.FIXED_COST_SUMMARY to mapOf("query" to mapOf("month" to "2026-01")),
            FinanceOperation.GET_OBLIGATION to mapOf("obligationId" to obligationId),
            FinanceOperation.OBLIGATION_HISTORY to mapOf("obligationId" to obligationId, "query" to mapOf("cursor" to 4, "limit" to 200)),
            FinanceOperation.RESCHEDULE_OBLIGATION to mutation("obligationId", obligationId, mapOf("scheduled_date" to "2026-01-30", "reason" to "합성 이동")),
            FinanceOperation.SKIP_OBLIGATION to mutation("obligationId", obligationId, mapOf("reason" to "합성 건너뜀")),
            FinanceOperation.UNSKIP_OBLIGATION to mutation("obligationId", obligationId, mapOf("reason" to "합성 복원")),
            FinanceOperation.COMPLETE_OBLIGATION to mutation("obligationId", obligationId, mapOf("reason" to "합성 완료")),
            FinanceOperation.REOPEN_OBLIGATION to mutation("obligationId", obligationId, mapOf("reason" to "합성 재개")),
            FinanceOperation.SETTLE_OBLIGATION to mutation("obligationId", obligationId, payment()),
            FinanceOperation.LIST_OBLIGATION_SETTLEMENTS to mapOf("obligationId" to obligationId, "query" to mapOf("cursor" to paymentId)),
            FinanceOperation.VOID_FIXED_SETTLEMENT to mutation("settlementId", paymentId, mapOf("reason" to "합성 납부 취소")),
        )
        assertEquals(19, commands.size)
        for ((op, args) in commands) {
            val r = request(op, args)
            assertTrue("Fixed route denied: $op", FinancePolicy.metadataHttpAllowed(r.method, r.path, r.body, r.ifMatch, r.idempotencyKey))
            assertFalse(AuthPolicy.requestAllowed(r.method, r.path, r.ifMatch))
            assertFalse(FinancePolicy.metadataHttpAllowed(r.method, r.path + "/reveal", r.body, r.ifMatch, r.idempotencyKey))
            if (r.idempotencyKey != null) assertFalse(FinancePolicy.metadataHttpAllowed(r.method, r.path, r.body, r.ifMatch, null))
        }
    }
    @Test fun everyMutationRequiresItsExactKeyAndVersionAndRejectsArbitraryTransportFields() {
        for (key in listOf("", "x\r\nAuthorization:x", "a".repeat(129), "../synthetic")) bad {
            request(FinanceOperation.CREATE_RECURRING_RULE, write(create()) + mapOf("idempotencyKey" to key))
        }
        for (version in listOf("7", "W/\"7\"", "*", "\"0\"")) bad {
            request(FinanceOperation.CHANGE_RECURRING_RULE, mutation("ruleId", ruleId, change()) + mapOf("ifMatch" to version))
        }
        for (field in listOf("url", "path", "method", "body", "headers", "stepUpToken", "accessToken")) bad {
            request(FinanceOperation.SETTLE_OBLIGATION, mutation("obligationId", obligationId, payment()) + mapOf(field to "synthetic"))
        }
        bad { request(FinanceOperation.END_RECURRING_RULE, mutation("ruleId", ruleId, mapOf("effective_on" to "2026-02-01", "reason" to "합성")) - "ifMatch") }
        bad { request(FinanceOperation.GENERATE_OBLIGATIONS, write(mapOf("start_date" to "2026-01-01", "end_date" to "2026-01-31")) - "idempotencyKey") }
    }
    @Test fun ruleDeleteSendsNoBodyNeedsVersionAndKeyAndAcceptsOnlyAnEmpty204() {
        val r = request(FinanceOperation.DELETE_RECURRING_RULE, deletion())
        assertEquals(listOf("DELETE", "/api/v1/recurring-rules/$ruleId", null, tag, "synthetic.stable:fixed-delete"),
            listOf(r.method, r.path, r.body, r.ifMatch, r.idempotencyKey))
        assertTrue(FinancePolicy.metadataHttpAllowed("DELETE", r.path, null, tag, "synthetic.stable:fixed-delete"))
        assertFalse(FinancePolicy.metadataHttpAllowed("DELETE", r.path, emptyMap<String, Any?>(), tag, "synthetic.stable:fixed-delete"))
        assertFalse(FinancePolicy.metadataHttpAllowed("DELETE", r.path, null, null, "synthetic.stable:fixed-delete"))
        assertFalse(FinancePolicy.metadataHttpAllowed("DELETE", r.path, null, tag, null))
        assertFalse(FinancePolicy.metadataHttpAllowed("DELETE", "/api/v1/obligations/$obligationId", null, tag, "synthetic.stable:fixed-delete"))
        for (missing in listOf("ruleId", "ifMatch", "idempotencyKey")) bad { request(FinanceOperation.DELETE_RECURRING_RULE, deletion() - missing) }
        bad { request(FinanceOperation.DELETE_RECURRING_RULE, deletion() + mapOf("input" to emptyMap<String, Any?>())) }
        assertNull(FinancePolicy.response(FinanceOperation.DELETE_RECURRING_RULE, r, 204, null))
        bad(AuthCode.NETWORK_UNAVAILABLE) { FinancePolicy.reply(FinanceOperation.DELETE_RECURRING_RULE, r, 200, null) }
        bad(AuthCode.NETWORK_UNAVAILABLE) { FinancePolicy.reply(FinanceOperation.DELETE_RECURRING_RULE, r, 204, mapOf("id" to ruleId)) }
        val refused = AuthPolicy.safeError(409, mapOf("error" to mapOf("code" to "RULE_IN_USE", "message" to "synthetic secret")), ruleId)!!
        assertEquals("RULE_IN_USE", (refused["error"] as Map<*, *>)["code"])
        assertEquals("보험료로 연결됐거나 납부 기록·확정된 월이 있는 규칙은 종료만 할 수 있어요.", (refused["error"] as Map<*, *>)["message"])
    }
    @Test fun initialRuleEndRequiresBothDateAndReasonAndFullTermsChangeIsSeparate() {
        val ended = create() + mapOf("effective_until" to "2026-02-01", "end_reason" to "합성 초기 종료")
        assertEquals(ended, request(FinanceOperation.CREATE_RECURRING_RULE, write(ended)).body)
        for (change in listOf(mapOf("effective_until" to "2026-02-01"), mapOf("end_reason" to "합성"),
            mapOf("effective_until" to "2026-01-01", "end_reason" to "합성"), mapOf("effective_until" to "2025-12-31", "end_reason" to "합성"))) bad {
            request(FinanceOperation.CREATE_RECURRING_RULE, write(create() + change))
        }
        bad { request(FinanceOperation.CHANGE_RECURRING_RULE, mutation("ruleId", ruleId, mapOf("effective_from" to "2026-02-01", "reason" to "합성", "title" to "합성 변경"))) }
        bad { request(FinanceOperation.CHANGE_RECURRING_RULE, mutation("ruleId", ruleId, change() + mapOf("effective_until" to "2027-01-01"))) }
        assertEquals(change(), request(FinanceOperation.CHANGE_RECURRING_RULE, mutation("ruleId", ruleId, change())).body)
    }
    @Test fun expectedNullZeroAndLargeMoneyStayDistinctAndForeignAmountsRemainReferenceStrings() {
        for (amount in listOf(null, "0", "99999999999999999999")) {
            val body = create() + mapOf("amount_mode" to "variable", "expected_amount_krw" to amount)
            assertEquals(body, request(FinanceOperation.CREATE_RECURRING_RULE, write(body)).body)
        }
        val foreign = create() + mapOf("currency_reference" to "USD", "foreign_amount_reference" to "12345678901234567890.12345678")
        assertEquals(foreign, request(FinanceOperation.CREATE_RECURRING_RULE, write(foreign)).body)
        for (change in listOf(mapOf("expected_amount_krw" to null), mapOf("expected_amount_krw" to 0), mapOf("expected_amount_krw" to "1.0"),
            mapOf("currency_reference" to "USD"), mapOf("foreign_amount_reference" to "1.25"),
            mapOf("currency_reference" to "usd", "foreign_amount_reference" to "1"), mapOf("currency_reference" to "USD", "foreign_amount_reference" to 1.25),
            mapOf("currency_reference" to "USD", "foreign_amount_reference" to "1.123456789"))) bad {
            request(FinanceOperation.CREATE_RECURRING_RULE, write(create() + change))
        }
    }
    @Test fun scheduleAndPaymentLinksHaveTypedBoundsWithoutInventingRecurrenceOrBalances() {
        for (frequency in listOf("monthly", "annual", "days")) request(FinanceOperation.CREATE_RECURRING_RULE, write(create() + mapOf("frequency" to frequency, "interval_count" to 3650)))
        for (change in listOf(mapOf("interval_count" to 0), mapOf("interval_count" to 3651), mapOf("interval_count" to 1.0), mapOf("frequency" to "weekly"),
            mapOf("anchor_date" to "2026-02-30"), mapOf("loan_asset_id" to ruleId), mapOf("account_id" to ruleId, "card_id" to paymentId),
            mapOf("balance_krw" to "100"), mapOf("cvc" to "synthetic"), mapOf("card_number" to "synthetic"))) bad {
            request(FinanceOperation.CREATE_RECURRING_RULE, write(create() + change))
        }
        request(FinanceOperation.CREATE_RECURRING_RULE, write(create() + mapOf("economic_type" to "loan", "loan_asset_id" to ruleId)))
    }
    @Test fun variablePaymentCanBeConfirmedWhileItsExpectedAmountAndDifferenceStayUnknown() {
        val op = FinanceOperation.GET_OBLIGATION
        val r = request(op, mapOf("obligationId" to obligationId))
        val paid = obligation() + mapOf("amount_mode" to "variable", "expected_amount_krw" to null, "difference_krw" to null)
        assertEquals(paid, FinancePolicy.response(op, r, 200, paid))
        val voided = paid + mapOf("status" to "unpaid", "actual_amount_krw" to "0", "consumption_krw" to "0")
        assertEquals(voided, FinancePolicy.response(op, r, 200, voided))
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(op, r, 200, paid + mapOf("difference_krw" to "0")) }
    }
    @Test fun generationIsBoundedToAnInclusive366DayWindowAnd2000ImmutableReferences() {
        val args = write(mapOf("start_date" to "2024-01-01", "end_date" to "2024-12-31"))
        val r = request(FinanceOperation.GENERATE_OBLIGATIONS, args)
        for (body in listOf(mapOf("start_date" to "2024-01-01", "end_date" to "2025-01-01"), mapOf("start_date" to "2026-02-01", "end_date" to "2026-01-31"))) bad {
            request(FinanceOperation.GENERATE_OBLIGATIONS, write(body))
        }
        val result = mapOf("id" to paymentId, "version" to 1, "items" to listOf(mapOf("id" to obligationId, "version" to 1)))
        assertEquals(result, FinancePolicy.response(FinanceOperation.GENERATE_OBLIGATIONS, r, 201, result))
        assertEquals(result, FinancePolicy.response(FinanceOperation.GENERATE_OBLIGATIONS, r, 201, withAddedFields(result)))
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.GENERATE_OBLIGATIONS, r, 201, result + mapOf("items" to List(2001) { mapOf("id" to obligationId, "version" to 1) })) }
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.GENERATE_OBLIGATIONS, r, 201, result + mapOf("version" to 2)) }
    }
    @Test fun actualPaymentMustBePositiveAndT09LoanComponentsRemainExactStrings() {
        val loan = mapOf("amount_krw" to "1000000", "principal_krw" to "700000", "interest_krw" to "300000", "occurred_on" to "2026-01-31", "card_id" to paymentId)
        assertEquals(loan, request(FinanceOperation.SETTLE_OBLIGATION, mutation("obligationId", obligationId, loan)).body)
        for (change in listOf(mapOf("amount_krw" to "0"), mapOf("amount_krw" to 35000), mapOf("amount_krw" to "-1"), mapOf("principal_krw" to 0),
            mapOf("interest_krw" to "0.5"), mapOf("account_id" to ruleId, "card_id" to paymentId), mapOf("occurred_on" to "2026-01"))) bad {
            request(FinanceOperation.SETTLE_OBLIGATION, mutation("obligationId", obligationId, payment() + change))
        }
    }
    @Test fun mutationReferenceDoesNotLeakLatestMetadataAndKeepsTheImmutableVersion() {
        val r = request(FinanceOperation.CHANGE_RECURRING_RULE, mutation("ruleId", ruleId, change()))
        val reference = mapOf("id" to ruleId, "version" to 8)
        assertEquals(reference, FinancePolicy.response(FinanceOperation.CHANGE_RECURRING_RULE, r, 200, reference))
        assertEquals(reference, FinancePolicy.response(FinanceOperation.CHANGE_RECURRING_RULE, r, 200, withAddedFields(reference)))
        assertEquals(reference, FinancePolicy.response(FinanceOperation.CHANGE_RECURRING_RULE, r, 200, reference))
        assertEquals(reference, FinancePolicy.response(FinanceOperation.CHANGE_RECURRING_RULE, r, 200, withAddedFields(reference)))
        for (change in listOf(mapOf("id" to paymentId), mapOf("version" to 8.0), mapOf("version" to 0), mapOf("token" to "synthetic"))) bad(AuthCode.ACCESS_DENIED) {
            FinancePolicy.response(FinanceOperation.CHANGE_RECURRING_RULE, r, 200, reference + change)
        }
        // Latest rule metadata added to the receipt is dropped instead of crossing the bridge.
        assertEquals(reference, FinancePolicy.response(FinanceOperation.CHANGE_RECURRING_RULE, r, 200, reference + mapOf("rule" to rule())))
    }
    @Test fun historicalRuleVersionsAreNotMistakenForTheOuter200ItemPage() {
        val start = YearMonth.parse("2026-01")
        val versions = (0..200).map { n -> version() + mapOf("id" to "00000000-0000-4000-8000-${(n + 1).toString().padStart(12, '0')}",
            "effective_from" to start.plusMonths(n.toLong()).atDay(1).toString(), "effective_until" to start.plusMonths(n.toLong() + 1).atDay(1).toString()) }
        val row = rule() + mapOf("versions" to versions)
        val r = request(FinanceOperation.GET_RECURRING_RULE, mapOf("ruleId" to ruleId))
        assertEquals(row, FinancePolicy.response(FinanceOperation.GET_RECURRING_RULE, r, 200, row))
        assertEquals(row, FinancePolicy.response(FinanceOperation.GET_RECURRING_RULE, r, 200, withAddedFields(row)))
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.GET_RECURRING_RULE, r, 200, row + mapOf("id" to obligationId)) }
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.GET_RECURRING_RULE, r, 200, row + mapOf("versions" to listOf(version() + mapOf("ciphertext" to "synthetic")))) }
        val list = request(FinanceOperation.LIST_RECURRING_RULES, emptyMap())
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.LIST_RECURRING_RULES, list, 200, mapOf("items" to List(201) { rule() }, "next_cursor" to null)) }
    }
    @Test fun obligationProjectionKeepsT11ExpectedAndActualSeparateAndBindsMonthAndHistoryIdentity() {
        val r = request(FinanceOperation.GET_OBLIGATION, mapOf("obligationId" to obligationId))
        assertEquals(obligation(), FinancePolicy.response(FinanceOperation.GET_OBLIGATION, r, 200, obligation()))
        assertEquals(obligation(), FinancePolicy.response(FinanceOperation.GET_OBLIGATION, r, 200, withAddedFields(obligation())))
        for (expected in listOf(null, "0")) {
            val row = obligation() + mapOf("amount_mode" to "variable", "expected_amount_krw" to expected, "actual_amount_krw" to "0",
                "difference_krw" to if (expected == null) null else "0", "consumption_krw" to "0", "status" to "unpaid")
            assertEquals(row, FinancePolicy.response(FinanceOperation.GET_OBLIGATION, r, 200, row))
            assertEquals(row, FinancePolicy.response(FinanceOperation.GET_OBLIGATION, r, 200, withAddedFields(row)))
        }
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.GET_OBLIGATION, r, 200, obligation() + mapOf("difference_krw" to null)) }
        val list = request(FinanceOperation.LIST_OBLIGATIONS, mapOf("query" to mapOf("month" to "2026-02")))
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.LIST_OBLIGATIONS, list, 200, mapOf("items" to listOf(obligation()), "next_cursor" to null)) }
        val h = request(FinanceOperation.OBLIGATION_HISTORY, mapOf("obligationId" to obligationId))
        assertEquals(mapOf("items" to listOf(history()), "next_cursor" to 7), FinancePolicy.response(FinanceOperation.OBLIGATION_HISTORY, h, 200, mapOf("items" to listOf(history()), "next_cursor" to 7)))
        assertEquals(mapOf("items" to listOf(history()), "next_cursor" to 7), FinancePolicy.response(FinanceOperation.OBLIGATION_HISTORY, h, 200, withAddedFields(mapOf("items" to listOf(history()), "next_cursor" to 7))))
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.OBLIGATION_HISTORY, h, 200, mapOf("items" to listOf(history() + mapOf("id" to ruleId)), "next_cursor" to null)) }
    }
    @Test fun settlementProjectionChecksT09LoanAndExpenseAndAssetTransferWithoutFloatRounding() {
        val r = request(FinanceOperation.SETTLE_OBLIGATION, mutation("obligationId", obligationId, payment()))
        assertEquals(settlement(), FinancePolicy.response(FinanceOperation.SETTLE_OBLIGATION, r, 201, settlement()))
        assertEquals(settlement(), FinancePolicy.response(FinanceOperation.SETTLE_OBLIGATION, r, 201, withAddedFields(settlement())))
        val loan = settlement() + mapOf("economic_type" to "loan", "principal_krw" to "700000", "consumption_krw" to "300000", "cash" to cash("1000000"))
        assertEquals(loan, FinancePolicy.response(FinanceOperation.SETTLE_OBLIGATION, r, 201, loan))
        assertEquals(loan, FinancePolicy.response(FinanceOperation.SETTLE_OBLIGATION, r, 201, withAddedFields(loan)))
        val transfer = settlement() + mapOf("economic_type" to "asset_transfer", "consumption_krw" to "0", "asset_transfer_krw" to "99999999999999999999", "cash" to cash("99999999999999999999"))
        assertEquals(transfer, FinancePolicy.response(FinanceOperation.SETTLE_OBLIGATION, r, 201, transfer))
        assertEquals(transfer, FinancePolicy.response(FinanceOperation.SETTLE_OBLIGATION, r, 201, withAddedFields(transfer)))
        for (change in listOf(mapOf("consumption_krw" to "35001"), mapOf("obligation_id" to ruleId), mapOf("principal_krw" to "1"),
            mapOf("cash" to cash() + mapOf("amount_krw" to 35000)), mapOf("cash" to cash() + mapOf("kind" to "salary")),
            mapOf("cash" to cash() + mapOf("card_id" to paymentId, "account_id" to ruleId)), mapOf("cash" to cash() + mapOf("cvc" to "synthetic")))) bad(AuthCode.ACCESS_DENIED) {
            FinancePolicy.response(FinanceOperation.SETTLE_OBLIGATION, r, 201, settlement() + change)
        }
    }
    @Test fun voidUsesSettlementIdentityAndImmutableCashRevisionRatherThanObligationVersion() {
        val r = request(FinanceOperation.VOID_FIXED_SETTLEMENT, mutation("settlementId", paymentId, mapOf("reason" to "합성 취소")))
        val result = settlement() + mapOf("cash" to cash(void = true))
        assertEquals(result, FinancePolicy.response(FinanceOperation.VOID_FIXED_SETTLEMENT, r, 200, result))
        assertEquals(result, FinancePolicy.response(FinanceOperation.VOID_FIXED_SETTLEMENT, r, 200, withAddedFields(result)))
        for (change in listOf(mapOf("id" to cashId), mapOf("cash" to cash()), mapOf("cash" to cash(void = true) + mapOf("version" to 2.0)),
            mapOf("cash" to cash(void = true) + mapOf("date_precision" to "month", "occurred_on" to null)),
            mapOf("cash" to cash(void = true) + mapOf("period_month" to "2026-02")))) bad(AuthCode.ACCESS_DENIED) {
            FinancePolicy.response(FinanceOperation.VOID_FIXED_SETTLEMENT, r, 200, result + change)
        }
        val list = request(FinanceOperation.LIST_OBLIGATION_SETTLEMENTS, mapOf("obligationId" to obligationId))
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.LIST_OBLIGATION_SETTLEMENTS, list, 200,
            mapOf("items" to listOf(settlement() + mapOf("obligation_id" to ruleId)), "next_cursor" to null)) }
    }
    @Test fun summariesKeepKnownExpectedUnknownCountsAndActualComponentsSeparate() {
        val r = request(FinanceOperation.FIXED_COST_SUMMARY, mapOf("query" to mapOf("month" to "2026-01")))
        val row = mapOf("expected_known_krw" to "33000", "unknown_expected_count" to 1, "actual_amount_krw" to "35000",
            "consumption_krw" to "35000", "principal_krw" to "0", "asset_transfer_krw" to "0", "obligation_count" to 2)
        assertEquals(row, FinancePolicy.response(FinanceOperation.FIXED_COST_SUMMARY, r, 200, row))
        assertEquals(row, FinancePolicy.response(FinanceOperation.FIXED_COST_SUMMARY, r, 200, withAddedFields(row)))
        for (change in listOf(mapOf("actual_amount_krw" to 35000), mapOf("expected_known_krw" to null), mapOf("unknown_expected_count" to -1), mapOf("pan" to "synthetic"))) bad(AuthCode.ACCESS_DENIED) {
            FinancePolicy.response(FinanceOperation.FIXED_COST_SUMMARY, r, 200, row + change)
        }
    }
    @Test fun queryTypingDoesNotAllowUnknownFiltersOrNumericCursorsOnUuidPages() {
        for (q in listOf(emptyMap(), mapOf("month" to "2026-13"), mapOf("month" to "2026-01", "limit" to 201), mapOf("month" to "2026-01", "cursor" to 1),
            mapOf("month" to "2026-01", "card_id" to paymentId))) bad { request(FinanceOperation.LIST_OBLIGATIONS, mapOf("query" to q)) }
        bad { request(FinanceOperation.OBLIGATION_HISTORY, mapOf("obligationId" to obligationId, "query" to mapOf("cursor" to ruleId))) }
        for (path in listOf("/api/v1/obligations?limit=01&month=2026-01", "/api/v1/obligations?month=2026-01&month=2026-02",
            "/api/v1/obligations/$obligationId/history?cursor=01", "/api/v1/recurring-rules?limit=1#synthetic"))
            assertFalse(FinancePolicy.metadataHttpAllowed("GET", path, null, null))
    }
    @Test fun lockedRecoveryCannotReadOrWriteFixedCostsAndSafeErrorsNeverCopyRawDetails() {
        val lock = AppLockPolicy().also { it.resume(0, false) }
        for (kind in AppRequestKind.entries) {
            assertFalse(lock.httpAllowed(lock.ticket(kind), "GET", "/api/v1/recurring-rules"))
            assertFalse(lock.httpAllowed(lock.ticket(kind), "POST", "/api/v1/obligations/$obligationId/settlements"))
        }
        val safe = AuthPolicy.safeError(422, mapOf("error" to mapOf("code" to "INVALID_PAYMENT_SPLIT", "message" to "synthetic secret")), ruleId)!!
        assertEquals("INVALID_PAYMENT_SPLIT", (safe["error"] as Map<*, *>)["code"])
        assertFalse(safe.toString().contains("synthetic"))
    }

    @Test fun overdueReadNeedsNoMonthAndRejectsTodayOrResolvedRowsAndUnexpectedFilters() {
        val op=FinanceOperation.LIST_OVERDUE_OBLIGATIONS
        val prepared=request(op,mapOf("query" to mapOf("limit" to 2)))
        assertEquals("/api/v1/obligations/overdue?limit=2",prepared.path)
        assertTrue(FinancePolicy.metadataHttpAllowed("GET",prepared.path,null,null,null))
        bad { request(op,mapOf("query" to mapOf("month" to "2026-01"))) }
        val unpaid=obligation()+mapOf("status" to "unpaid","actual_amount_krw" to "0","difference_krw" to "-33000","consumption_krw" to "0")
        val value=mapOf("as_of" to "2026-02-01","items" to listOf(unpaid),"next_cursor" to null)
        assertEquals(value,FinancePolicy.response(op,prepared,200,value))
        for(patch in listOf(mapOf("status" to "paid"),mapOf("scheduled_date" to "2026-02-01"),mapOf("scheduled_date" to "2026-02-02"),mapOf("skipped" to true),mapOf("manually_completed" to true),mapOf("schedule_state" to "superseded")))
            bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(op,prepared,200,value+mapOf("items" to listOf(unpaid+patch))) }
    }
}
