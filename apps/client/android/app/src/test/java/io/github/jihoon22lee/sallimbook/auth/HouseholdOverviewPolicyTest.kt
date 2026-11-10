package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class HouseholdOverviewPolicyTest {
    private val op = FinanceOperation.HOUSEHOLD_OVERVIEW
    private val id = "00000000-0000-4000-8000-000000000001"
    private val other = "00000000-0000-4000-8000-000000000002"
    private val account = "00000000-0000-4000-8000-000000000003"
    private fun bad(code: AuthCode = AuthCode.INVALID_REQUEST, action: () -> Unit) {
        try { action(); fail("Invalid household status accepted") }
        catch (failure: AuthFailure) { assertEquals(code, failure.code); assertNull(failure.message) }
    }
    private fun request(month: Any? = "2026-03") = FinancePolicy.prepare(op, mapOf("query" to mapOf("month" to month)))
    private fun holding(asset: String = id, amount: String? = "301700000", basis: String? = "2026-03", included: Boolean = true,
        stale: Boolean = false, accountId: String? = null) = mapOf<String, Any?>("asset_id" to asset, "account_id" to accountId,
        "name" to "합성 자산", "kind" to "asset", "category" to "financial", "group" to if (accountId == null) "financial" else "accounts",
        "included" to included, "owned_amount_krw" to amount, "basis_month" to basis, "as_of_date" to basis?.let { "$it-28" }, "stale" to stale)
    private fun holdings(items: List<Map<String, Any?>> = listOf(holding(), holding(other, null, null)), known: Int = 1, missing: Int = 1) =
        mapOf<String, Any?>("assets_krw" to "301700000", "liabilities_krw" to "100000000", "net_assets_krw" to "-99999999999999999999",
            "item_count" to known + missing, "known_count" to known, "missing_count" to missing, "stale_count" to 0, "current_count" to known,
            "oldest_basis_month" to "2025-06", "groups" to listOf(mapOf("group" to "financial", "count" to 2, "known_count" to 1,
                "assets_krw" to "301700000", "liabilities_krw" to "0")), "items" to items)
    private fun registered(count: Int = 2) = mapOf("count" to count, "items" to List(minOf(count, 4)) { mapOf("id" to id, "name" to "합성 기기") })
    private fun insurance() = mapOf("active_policy_count" to 1, "open_case_count" to 1, "claims_in_progress_count" to 2,
        "documents_required_count" to 1, "policies" to listOf(mapOf("id" to id, "name" to "합성 보험사 · 합성 보험상품")))
    private fun plan() = mapOf<String, Any?>("as_of" to "2026-03-15", "expected_income_known_krw" to "5000000", "expected_income_count" to 2,
        "expected_income_unknown_count" to 1, "spending_known_krw" to "2500000", "loan_known_krw" to "1055000", "transfer_known_krw" to "300000",
        "planned_unknown_count" to 1, "unconverted_count" to 0, "excluded_known_krw" to "0",
        "margin_before_transfers_krw" to "1445000", "margin_after_transfers_krw" to "-1145000")
    private fun investment(gain: String = "1490000", percent: String? = "14.9") = mapOf<String, Any?>("asset_id" to id, "account_id" to account,
        "name" to "합성 증권 계좌", "account_type" to "brokerage", "value_krw" to "11490000", "basis_month" to "2026-03",
        "contributed_krw" to "10000000", "contributed_as_of" to "2026-02-28", "gain_krw" to gain, "return_percent" to percent)
    private fun investments(items: List<Map<String, Any?>> = listOf(investment())) = mapOf<String, Any?>("count" to items.size,
        "value_krw" to "11490000", "contributed_krw" to "10000000", "gain_krw" to "1490000", "return_percent" to "14.9",
        "missing_contribution_count" to 1, "items" to items)
    private fun overview(month: String = "2026-03") = mapOf("month" to month, "holdings" to holdings(), "investments" to investments(),
        "cards" to registered(), "appliances" to registered(5), "insurance" to insurance(), "plan" to plan())
    private val trendsOp = FinanceOperation.HOUSEHOLD_TRENDS
    private val summaryOp = FinanceOperation.INSURANCE_SUMMARY
    private fun trendsRequest(to: Any? = "2026-03", months: Any? = 2) =
        FinancePolicy.prepare(trendsOp, mapOf("query" to mapOf("to" to to, "months" to months)))
    private fun netPoint(month: String, net: String? = "201700000") = mapOf<String, Any?>("month" to month,
        "assets_krw" to net?.let { "301700000" }, "liabilities_krw" to net?.let { "100000000" }, "net_assets_krw" to net,
        "item_count" to 5, "known_count" to if (net == null) 0 else 4, "entered_count" to if (net == null) 0 else 1, "confirmed" to false)
    private fun planPoint(month: String, margin: String? = "-1145000") = mapOf<String, Any?>("month" to month, "as_of" to "$month-15",
        "income_known_krw" to if (margin == null) "0" else "5000000", "income_count" to if (margin == null) 0 else 2,
        "income_unknown_count" to if (margin == null) 0 else 1, "spending_known_krw" to "2500000", "loan_known_krw" to "1055000",
        "transfer_known_krw" to "300000", "planned_unknown_count" to 1, "margin_before_transfers_krw" to margin?.let { "1445000" },
        "margin_after_transfers_krw" to margin, "actual_income_krw" to "0")
    private fun trends() = mapOf<String, Any?>("to_month" to "2026-03", "months" to 2,
        "net_assets" to listOf(netPoint("2026-02", null), netPoint("2026-03")),
        "plan" to listOf(planPoint("2026-02", null), planPoint("2026-03")))
    private fun policyMoney(policy: String = id, before: String? = "1000000", months: Int = 3) = mapOf<String, Any?>("policy_id" to policy,
        "insurer" to "합성 보험사", "product_name" to "합성 실손", "status" to "active", "monthly_premium_krw" to "100000",
        "paid_before_krw" to before, "paid_through" to before?.let { "2025-12-31" }, "paid_estimated_krw" to if (months == 0) "0" else "300000",
        "estimated_from_month" to if (months == 0) null else "2026-01", "estimated_months" to months, "unknown_months" to 0,
        "paid_total_krw" to if (before == null && months == 0) null else "1300000", "received_krw" to "350000",
        "recovery_percent" to if (before == null && months == 0) null else "26.9")
    private fun summary(policies: List<Map<String, Any?>> = listOf(policyMoney(), policyMoney(other, null, 0))) = mapOf<String, Any?>(
        "as_of" to "2026-03-15", "policy_count" to policies.size, "paid_unknown_count" to 1, "monthly_premium_krw" to "100000",
        "paid_total_krw" to "1300000", "received_krw" to "450000", "matched_received_krw" to "350000",
        "unassigned_received_krw" to "100000", "recovery_percent" to "26.9",
        "policies" to policies)

    @Test fun onlyTheNamedMonthReachesTheReadOnlyRoute() {
        val r = request()
        assertEquals("GET", r.method)
        assertEquals("/api/v1/household-overview?month=2026-03", r.path)
        assertTrue(FinancePolicy.metadataHttpAllowed(r.method, r.path, null, null))
        assertFalse(AuthPolicy.requestAllowed(r.method, r.path, null))
        assertFalse(FinancePolicy.metadataHttpAllowed("POST", r.path, null, null))
        assertFalse(FinancePolicy.metadataHttpAllowed("GET", r.path, emptyMap<String, Any>(), null))
        assertFalse(FinancePolicy.metadataHttpAllowed("GET", r.path, null, "\"1\""))
        assertFalse(FinancePolicy.metadataHttpAllowed("GET", r.path, null, null, "synthetic"))
        for (path in listOf("/api/v1/household-overview", "/api/v1/household-overview?month=2026-13", "/api/v1/household-overview?month=0000-01",
            "/api/v1/household-overview?month=2026-03&month=2026-04", "/api/v1/household-overview?month=2026%2D03",
            "/api/v1/household-overview?month=2026-03#synthetic", "/api/v1/household-overview/2026-03"))
            assertFalse(path, FinancePolicy.metadataHttpAllowed("GET", path, null, null))
        for (month in listOf("2026-13", "0000-01", "2026-3", 202603, null, "2026-03&limit=1")) bad { request(month) }
        for (args in listOf(emptyMap<String, Any?>(), mapOf("query" to emptyMap<String, Any?>()),
            mapOf("query" to mapOf("month" to "2026-03", "household_id" to id)), mapOf("query" to mapOf("month" to "2026-03"), "path" to "/api/v1/assets"),
            mapOf("query" to mapOf("month" to "2026-03"), "idempotencyKey" to "synthetic"))) bad { FinancePolicy.prepare(op, args) }
    }

    @Test fun statusKeepsUnsavedSignedAndLatestKnownAmountsExactly() {
        val response = overview()
        assertEquals(response, FinancePolicy.response(op, request(), 200, response))
        assertEquals(response, FinancePolicy.response(op, request(), 200, withAddedFields(response)))
        val empty = overview() + mapOf("holdings" to holdings(listOf(holding(amount = null, basis = null)), 0, 1) +
            mapOf("assets_krw" to "0", "liabilities_krw" to "0", "net_assets_krw" to "0", "oldest_basis_month" to null,
                "groups" to listOf(mapOf("group" to "financial", "count" to 1, "known_count" to 0, "assets_krw" to "0", "liabilities_krw" to "0"))),
            "cards" to registered(0))
        assertEquals(empty, FinancePolicy.response(op, request(), 200, empty))
        // An account's asset is one listed row; an excluded item is listed but never counted.
        val accounts = overview() + mapOf("holdings" to holdings(listOf(holding(accountId = account), holding(other, included = false)), 1, 0) +
            mapOf("groups" to listOf(mapOf("group" to "accounts", "count" to 1, "known_count" to 1, "assets_krw" to "301700000", "liabilities_krw" to "0"))))
        assertEquals(accounts, FinancePolicy.response(op, request(), 200, accounts))
    }

    @Test fun inconsistentCountsMonthsAndAmountsAreWithheld() {
        val changes = listOf(
            mapOf("month" to "2026-04"),
            mapOf("holdings" to holdings() + mapOf("assets_krw" to 301700000)),
            mapOf("holdings" to holdings() + mapOf("assets_krw" to "-1")),
            mapOf("holdings" to holdings() + mapOf("net_assets_krw" to "1.5")),
            mapOf("holdings" to holdings() + mapOf("net_assets_krw" to "-0")),
            mapOf("holdings" to holdings() + mapOf("known_count" to 2)),
            mapOf("holdings" to holdings() + mapOf("stale_count" to 2)),
            mapOf("holdings" to holdings(listOf(holding(), holding()))),
            mapOf("holdings" to holdings(listOf(holding(), holding(other, null, "2026-03")))),
            mapOf("holdings" to holdings(listOf(holding(), holding(other, null, null, stale = true)))),
            mapOf("holdings" to holdings(listOf(holding(), holding(other, null, null) + mapOf("group" to "accounts")))),
            mapOf("holdings" to holdings(listOf(holding(), holding(other, null, null) + mapOf("category" to "card")))),
            mapOf("holdings" to holdings() + mapOf("groups" to List(2) { mapOf("group" to "financial", "count" to 1, "known_count" to 1,
                "assets_krw" to "0", "liabilities_krw" to "0") })),
            mapOf("cards" to mapOf("count" to 1, "items" to List(2) { mapOf("id" to id, "name" to "합성 카드") })),
            mapOf("cards" to mapOf("count" to 9, "items" to List(5) { mapOf("id" to id, "name" to "합성 카드") })),
            mapOf("appliances" to mapOf("count" to 1, "items" to listOf(mapOf("id" to id, "name" to " ")))),
            mapOf("insurance" to insurance() + mapOf("documents_required_count" to 3)),
            mapOf("insurance" to insurance() + mapOf("active_policy_count" to 0)),
            mapOf("plan" to plan() + mapOf("expected_income_unknown_count" to 3)),
            mapOf("plan" to plan() + mapOf("margin_after_transfers_krw" to 1145000)),
            mapOf("plan" to plan() + mapOf("as_of" to "2026-02-30")),
        )
        for (change in changes) bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(op, request(), 200, overview() + change) }
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(op, request(), 201, overview()) }
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(op, request("2026-04"), 200, overview()) }
    }

    @Test fun investmentsKeepSignedGainsAndRejectInconsistentRows() {
        val loss = overview() + mapOf("investments" to investments(listOf(investment("-1000000", "-16.7"))))
        assertEquals(loss, FinancePolicy.response(op, request(), 200, loss))
        val none = overview() + mapOf("investments" to investments(emptyList()) + mapOf("return_percent" to null))
        assertEquals(none, FinancePolicy.response(op, request(), 200, none))
        for (change in listOf(
            investments() + mapOf("count" to 2),
            investments(listOf(investment(), investment())),
            investments(listOf(investment() + mapOf("account_type" to "checking"))),
            investments(listOf(investment() + mapOf("return_percent" to "14.95"))),
            investments(listOf(investment() + mapOf("return_percent" to 14.9))),
            investments(listOf(investment() + mapOf("contributed_krw" to null))),
            investments() + mapOf("gain_krw" to "1,490,000"),
        )) bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(op, request(), 200, overview() + mapOf("investments" to change)) }
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(op, request(), 200, overview() - "investments") }
    }

    @Test fun trendsReachOnlyTheBoundedReadOnlyRouteAndKeepEmptyMonthsEmpty() {
        val r = trendsRequest()
        assertEquals("GET", r.method)
        assertEquals("/api/v1/household-trends?to=2026-03&months=2", r.path)
        assertTrue(FinancePolicy.metadataHttpAllowed(r.method, r.path, null, null))
        assertFalse(FinancePolicy.metadataHttpAllowed("POST", r.path, null, null))
        assertFalse(FinancePolicy.metadataHttpAllowed("GET", r.path, null, null, "synthetic"))
        for (path in listOf("/api/v1/household-trends", "/api/v1/household-trends?to=2026-03", "/api/v1/household-trends?to=2026-13&months=2",
            "/api/v1/household-trends?to=2026-03&months=0", "/api/v1/household-trends?to=2026-03&months=37",
            "/api/v1/household-trends?months=2&to=2026-03", "/api/v1/household-trends?to=2026-03&months=2&household_id=$id"))
            assertFalse(path, FinancePolicy.metadataHttpAllowed("GET", path, null, null))
        for ((to, months) in listOf<Pair<Any?, Any?>>("2026-13" to 2, "2026-03" to 0, "2026-03" to 37, "2026-03" to "2", "2026-03" to 2.5, null to 2))
            bad { trendsRequest(to, months) }
        bad { FinancePolicy.prepare(trendsOp, mapOf("query" to mapOf("to" to "2026-03"))) }
        val response = trends()
        assertEquals(response, FinancePolicy.response(trendsOp, r, 200, response))
        assertEquals(response, FinancePolicy.response(trendsOp, r, 200, withAddedFields(response)))
        for (change in listOf(
            mapOf("to_month" to "2026-04"),
            mapOf("months" to 3),
            mapOf("net_assets" to listOf(netPoint("2026-03"))),
            mapOf("net_assets" to listOf(netPoint("2026-01", null), netPoint("2026-03"))),
            mapOf("net_assets" to listOf(netPoint("2026-02", null) + mapOf("net_assets_krw" to "0"), netPoint("2026-03"))),
            mapOf("net_assets" to listOf(netPoint("2026-02", null), netPoint("2026-03") + mapOf("net_assets_krw" to null))),
            mapOf("net_assets" to listOf(netPoint("2026-02", null), netPoint("2026-03") + mapOf("entered_count" to 5))),
            mapOf("plan" to listOf(planPoint("2026-02", null), planPoint("2026-04"))),
            mapOf("plan" to listOf(planPoint("2026-02", null) + mapOf("margin_after_transfers_krw" to "0"), planPoint("2026-03"))),
            mapOf("plan" to listOf(planPoint("2026-02", null), planPoint("2026-03") + mapOf("margin_before_transfers_krw" to null))),
            mapOf("plan" to listOf(planPoint("2026-02", null), planPoint("2026-03") + mapOf("actual_income_krw" to 0))),
            mapOf("plan" to listOf(planPoint("2026-02", null), planPoint("2026-03") + mapOf("token" to "synthetic"))),
        )) bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(trendsOp, r, 200, trends() + change) }
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(trendsOp, trendsRequest("2026-03", 1), 200, trends()) }
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(trendsOp, r, 201, trends()) }
    }

    @Test fun insuranceSummaryTakesNoArgumentsAndKeepsUnknownPremiumsUnknown() {
        val r = FinancePolicy.prepare(summaryOp, emptyMap<String, Any?>())
        assertEquals("GET", r.method)
        assertEquals("/api/v1/insurance/summary", r.path)
        assertTrue(FinancePolicy.metadataHttpAllowed(r.method, r.path, null, null))
        assertFalse(FinancePolicy.metadataHttpAllowed("POST", r.path, null, null))
        assertFalse(FinancePolicy.metadataHttpAllowed("GET", r.path + "?household_id=$id", null, null))
        bad { FinancePolicy.prepare(summaryOp, mapOf("query" to mapOf("month" to "2026-03"))) }
        val response = summary()
        assertEquals(response, FinancePolicy.response(summaryOp, r, 200, response))
        assertEquals(response, FinancePolicy.response(summaryOp, r, 200, withAddedFields(response)))
        for (change in listOf(
            mapOf("policy_count" to 3),
            mapOf("paid_unknown_count" to 3),
            mapOf("recovery_percent" to "26.95"),
            mapOf("matched_received_krw" to null),
            mapOf("received_krw" to 450000),
            mapOf("policies" to listOf(policyMoney(), policyMoney())),
            mapOf("policies" to listOf(policyMoney() + mapOf("paid_through" to null), policyMoney(other, null, 0))),
            mapOf("policies" to listOf(policyMoney() + mapOf("paid_total_krw" to null), policyMoney(other, null, 0))),
            mapOf("policies" to listOf(policyMoney(), policyMoney(other, null, 0) + mapOf("recovery_percent" to "0.0"))),
            mapOf("policies" to listOf(policyMoney(), policyMoney(other, null, 0) + mapOf("estimated_from_month" to "2026-01"))),
            mapOf("policies" to listOf(policyMoney() + mapOf("policy_number" to "synthetic"), policyMoney(other, null, 0))),
        )) bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(summaryOp, r, 200, summary() + change) }
    }

    @Test fun addedFieldsNamedLikeSecretsNeverReachTheBridge() {
        for (change in listOf(mapOf("token" to "synthetic"),
            mapOf("holdings" to holdings(listOf(holding() + mapOf("account_number" to "synthetic"), holding(other, null, null)))),
            mapOf("cards" to mapOf("count" to 1, "items" to listOf(mapOf("id" to id, "name" to "합성 카드", "cvc" to "synthetic")))),
            mapOf("insurance" to insurance() + mapOf("policy_number" to "synthetic")),
            mapOf("plan" to plan() + mapOf("ciphertext" to "synthetic")))) bad(AuthCode.ACCESS_DENIED) {
            FinancePolicy.response(op, request(), 200, overview() + change)
        }
    }
}
