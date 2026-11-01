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
    private fun overview(month: String = "2026-03") = mapOf("month" to month, "holdings" to holdings(), "cards" to registered(),
        "appliances" to registered(5), "insurance" to insurance(), "plan" to plan())

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
