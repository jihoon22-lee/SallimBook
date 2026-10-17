package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test
import java.time.YearMonth

class ComparisonPolicyTest {
    private val id = "00000000-0000-4000-8000-000000000001"
    private val other = "00000000-0000-4000-8000-000000000002"
    private fun bad(code: AuthCode = AuthCode.INVALID_REQUEST, action: () -> Unit) {
        try { action(); fail("Invalid historical metadata accepted") }
        catch (failure: AuthFailure) { assertEquals(code, failure.code); assertNull(failure.message) }
    }
    private fun request(op: FinanceOperation = FinanceOperation.GET_ASSET_COMPARISON, query: Map<String, Any?> = mapOf("to" to "2026-01")) =
        FinancePolicy.prepare(op, mapOf("query" to query))
    private fun filters() = mapOf<String, Any?>("asset_id" to null, "kind" to null, "category" to null, "ownership_kind" to null, "owner_member_id" to null)
    private fun dates() = mapOf("non_month_end_asset_ids" to emptyList<String>(), "missing_date_asset_ids" to emptyList<String>(), "mixed_dates" to false)
    private fun totals(amount: String? = "10", provisional: Boolean = false) = mapOf("assets_krw" to amount, "liabilities_krw" to "0", "net_assets_krw" to amount,
        "verified_count" to if (provisional) 0 else 1, "item_count" to 1, "missing_count" to if (amount == null) 1 else 0,
        "carried_count" to if (provisional && amount != null) 1 else 0, "provisional" to provisional)
    private fun ref(month: String) = mapOf("month" to month, "revision_id" to other, "revision_no" to 2, "version" to 3)
    private fun period(month: String, state: String = "confirmed") = mapOf("month" to month, "state" to state, "revision" to if (state == "missing") null else ref(month),
        "confirmed_at" to if (state == "confirmed") "2026-01-31T00:00:00Z" else null, "totals" to if (state == "missing") null else totals(), "dates" to dates())
    private fun value(month: String) = mapOf<String, Any?>("id" to other, "asset_id" to id, "name" to "합성 과거 자산", "kind" to "asset", "category" to "financial",
        "ownership_kind" to "joint", "owner_member_id" to null, "household_share" to "0.5", "amount_basis" to "whole", "inclusion_status" to "included",
        "started_on" to "2025-01-01", "ended_on" to null, "source_asset_version" to 1, "input_amount_krw" to "20", "owned_amount_krw" to "10",
        "as_of_date" to YearMonth.parse(month).atEndOfMonth().toString(), "verification_state" to "verified", "origin" to "manual", "origin_revision_id" to null,
        "change_reason" to null, "version" to 3)
    private fun item() = mapOf("asset_id" to id, "before" to value("2025-12"), "after" to value("2026-01"), "before_in_scope" to true,
        "after_in_scope" to true, "membership" to "common", "share_changed" to false, "same_scope" to true, "scope_reason" to null,
        "amount_delta_krw" to "0", "net_assets_effect_krw" to "0")
    private fun comparison() = mapOf("from_month" to "2025-12", "to_month" to "2026-01", "filters" to filters(), "state" to "available",
        "previous" to period("2025-12"), "current" to period("2026-01"), "total_delta_krw" to "0", "common_scope_delta_krw" to "0",
        "change_percent" to "0.00", "change_percent_unavailable_reason" to null, "scope_changed" to false, "added_asset_ids" to emptyList<String>(),
        "removed_asset_ids" to emptyList<String>(), "changed_share_asset_ids" to emptyList<String>(), "item_count" to 1, "items" to listOf(item()), "next_cursor" to null)
    private fun point(month: String, state: String = "confirmed", valueState: String = "verified", amount: String? = "0") = mapOf("month" to month, "state" to state,
        "revision" to if (state == "missing") null else ref(month), "totals" to if (state == "missing") null else totals(amount, valueState == "unconfirmed"),
        "value_state" to valueState, "observed_amount_krw" to amount, "confirmed_amount_krw" to if (valueState == "verified") amount else null,
        "included_in_total" to null, "as_of_date" to null, "dates" to dates())
    private fun trend(from: String = "2026-01", to: String = from, points: List<Map<String, Any?>> = listOf(point(from))) =
        mapOf("from_month" to from, "to_month" to to, "filters" to filters(), "series_kind" to "household_net_assets", "points" to points)

    @Test fun comparisonAndTrendQueriesReachOnlyCanonicalNamedGetRoutes() {
        val compare = request(query = mapOf("to" to "2026-01", "from" to "2025-01", "limit" to 200, "kind" to "asset", "cursor" to id))
        assertEquals("/api/v1/asset-comparison?cursor=$id&from=2025-01&kind=asset&limit=200&to=2026-01", compare.path)
        val series = request(FinanceOperation.GET_ASSET_TRENDS, mapOf("from" to "2016-02", "to" to "2026-01", "asset_id" to id))
        for (r in listOf(compare, series)) {
            assertTrue(FinancePolicy.metadataHttpAllowed(r.method, r.path, null, null))
            assertFalse(AuthPolicy.requestAllowed(r.method, r.path, null))
            assertFalse(FinancePolicy.metadataHttpAllowed("POST", r.path, null, null))
            assertFalse(FinancePolicy.metadataHttpAllowed("GET", r.path, emptyMap<String, Any>(), null))
            assertFalse(FinancePolicy.metadataHttpAllowed("GET", r.path, null, "\"1\""))
            assertFalse(FinancePolicy.metadataHttpAllowed("GET", r.path, null, null, "synthetic"))
        }
    }
    @Test fun queryValidationDistinguishesComparisonRangeAndInclusiveOneHundredTwentyMonthTrendLimit() {
        request(FinanceOperation.GET_ASSET_TRENDS, mapOf("from" to "2016-02", "to" to "2026-01"))
        request(FinanceOperation.GET_ASSET_TRENDS, mapOf("from" to "2026-01", "to" to "2026-01"))
        request(query = mapOf("from" to "0001-01", "to" to "2026-01"))
        for (q in listOf(mapOf("from" to "2016-01", "to" to "2026-01"), mapOf("from" to "2026-02", "to" to "2026-01"), mapOf("to" to "2026-01"))) bad {
            request(FinanceOperation.GET_ASSET_TRENDS, q)
        }
        for (q in listOf(mapOf("to" to "0000-01"), mapOf("to" to "2026-13"), mapOf("to" to "2026-01", "from" to "2026-01"),
            mapOf("to" to "2026-01", "limit" to 201), mapOf("to" to "2026-01", "limit" to 1.0), mapOf("to" to "2026-01", "limit" to null))) bad { request(query = q) }
    }
    @Test fun filtersPaginationAndTransportOptionsCannotBroadenTheReadOnlyContract() {
        assertEquals("/api/v1/asset-comparison?to=2026-01", request(query = mapOf("to" to "2026-01", "from" to null, "cursor" to null, "asset_id" to null)).path)
        for (change in listOf(mapOf("ownership_kind" to "joint", "owner_member_id" to id), mapOf("kind" to "cash"), mapOf("category" to "card"),
            mapOf("asset_id" to "$id/reveal"), mapOf("cursor" to 1), mapOf("revision_id" to id), mapOf("account_number" to "synthetic"))) bad {
            request(query = mapOf("to" to "2026-01") + change)
        }
        for (name in listOf("path", "url", "method", "headers", "body", "ifMatch", "idempotencyKey")) bad {
            FinancePolicy.prepare(FinanceOperation.GET_ASSET_COMPARISON, mapOf("query" to mapOf("to" to "2026-01"), name to "synthetic"))
        }
        for (suffix in listOf("?to=2026-01&to=2025-12", "?limit=01&to=2026-01", "?to=2026-01#synthetic", "?to=2026%2D01"))
            assertFalse(FinancePolicy.metadataHttpAllowed("GET", "/api/v1/asset-comparison$suffix", null, null))
    }
    @Test fun comparisonPreservesExactSignedMoneyPercentNullReasonsAndHistoricValues() {
        val r = request()
        val huge = comparison() + mapOf("total_delta_krw" to "-99999999999999999999", "common_scope_delta_krw" to "99999999999999999999", "change_percent" to "-9999999999999999999900.00")
        assertEquals(huge, FinancePolicy.response(FinanceOperation.GET_ASSET_COMPARISON, r, 200, huge))
        for (reason in listOf("zero_previous_total", "negative_previous_total")) {
            val unavailable = comparison() + mapOf("change_percent" to null, "change_percent_unavailable_reason" to reason)
            assertEquals(unavailable, FinancePolicy.response(FinanceOperation.GET_ASSET_COMPARISON, r, 200, unavailable))
        }
        for (change in listOf(mapOf("total_delta_krw" to 0), mapOf("change_percent" to 0.0), mapOf("change_percent" to "1e2"), mapOf("change_percent" to "1.001"),
            mapOf("change_percent" to "01.00"), mapOf("change_percent" to null), mapOf("total_delta_krw" to "100000000000000000000"),
            mapOf("current" to period("2026-01") + mapOf("totals" to totals(provisional = true))))) bad(AuthCode.ACCESS_DENIED) {
            FinancePolicy.response(FinanceOperation.GET_ASSET_COMPARISON, r, 200, comparison() + change)
        }
    }
    @Test fun unavailableComparisonsNeverInventZeroDeltasOrPercentages() {
        for (state in listOf("no_previous_month", "current_missing", "unconfirmed")) {
            val previous = period("2025-12", if (state == "no_previous_month") "missing" else "confirmed")
            val current = period("2026-01", if (state == "current_missing") "missing" else "draft")
            val row = comparison() + mapOf("state" to state, "previous" to previous, "current" to current,
                "total_delta_krw" to null, "common_scope_delta_krw" to null, "change_percent" to null, "change_percent_unavailable_reason" to state,
                "items" to listOf(item() + mapOf("amount_delta_krw" to null, "net_assets_effect_krw" to null)))
            assertEquals(row, FinancePolicy.response(FinanceOperation.GET_ASSET_COMPARISON, request(), 200, row))
            bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.GET_ASSET_COMPARISON, request(), 200, row + mapOf("total_delta_krw" to "0")) }
        }
    }
    @Test fun responseMonthsRevisionReferencesFiltersAndItemAssetIdentityMustMatch() {
        val r = request()
        for (change in listOf(mapOf("to_month" to "2026-02"), mapOf("from_month" to "2025-11"), mapOf("filters" to filters() + mapOf("asset_id" to id)),
            mapOf("current" to period("2026-01") + mapOf("revision" to ref("2025-12"))), mapOf("previous" to period("2025-11")),
            mapOf("items" to listOf(item() + mapOf("before" to value("2025-12") + mapOf("asset_id" to other)))))) bad(AuthCode.ACCESS_DENIED) {
            FinancePolicy.response(FinanceOperation.GET_ASSET_COMPARISON, r, 200, comparison() + change)
        }
    }
    @Test fun paginationBoundsRowsButAllowsWholeScopeObservationIdsBeyondThePage() {
        val ids = (1..201).map { "00000000-0000-4000-8000-${it.toString().padStart(12, '0')}" }
        val row = comparison() + mapOf("item_count" to 201, "next_cursor" to id, "added_asset_ids" to ids,
            "current" to period("2026-01") + mapOf("dates" to dates() + mapOf("non_month_end_asset_ids" to ids)))
        assertEquals(row, FinancePolicy.response(FinanceOperation.GET_ASSET_COMPARISON, request(query = mapOf("to" to "2026-01", "limit" to 1)), 200, row))
        for (change in listOf(mapOf("items" to List(201) { item() }), mapOf("next_cursor" to other), mapOf("items" to listOf(item(), item())),
            mapOf("added_asset_ids" to listOf(id, id)), mapOf("item_count" to 0))) bad(AuthCode.ACCESS_DENIED) {
            FinancePolicy.response(FinanceOperation.GET_ASSET_COMPARISON, request(), 200, comparison() + change)
        }
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.GET_ASSET_COMPARISON, request(query = mapOf("to" to "2026-01", "cursor" to id)), 200, comparison()) }
    }
    @Test fun nestedUnknownFieldsAndUnrecognizedScopeReasonsNeverReachTheBridge() {
        for (change in listOf(mapOf("token" to "synthetic"), mapOf("current" to period("2026-01") + mapOf("ciphertext" to "synthetic")),
            mapOf("current" to period("2026-01") + mapOf("totals" to totals() + mapOf("account_number" to "synthetic"))),
            mapOf("items" to listOf(item() + mapOf("scope_reason" to "synthetic"))),
            mapOf("items" to listOf(item() + mapOf("after" to value("2026-01") + mapOf("cvc" to "synthetic")))))) bad(AuthCode.ACCESS_DENIED) {
            FinancePolicy.response(FinanceOperation.GET_ASSET_COMPARISON, request(), 200, comparison() + change)
        }
    }
    @Test fun trendKeepsMissingZeroUnconfirmedAndConfirmedAsDistinctValues() {
        val points = listOf(point("2025-10", "missing", "missing_month", null), point("2025-11", "draft", "missing_value", null),
            point("2025-12", "reopened", "unconfirmed", "99999999999999999999"), point("2026-01", amount = "0"))
        val response = trend("2025-10", "2026-01", points)
        val r = request(FinanceOperation.GET_ASSET_TRENDS, mapOf("from" to "2025-10", "to" to "2026-01"))
        assertEquals(response, FinancePolicy.response(FinanceOperation.GET_ASSET_TRENDS, r, 200, response))
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.GET_ASSET_TRENDS, r, 200, response + mapOf("points" to points.dropLast(1))) }
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.GET_ASSET_TRENDS, r, 200, response + mapOf("points" to points.reversed())) }
    }
    @Test fun trendRejectsInventedConfirmationAndMismatchedSeriesOrRevision() {
        val r = request(FinanceOperation.GET_ASSET_TRENDS, mapOf("from" to "2026-01", "to" to "2026-01"))
        for (change in listOf(mapOf("observed_amount_krw" to 0), mapOf("confirmed_amount_krw" to "1"), mapOf("state" to "draft"),
            mapOf("revision" to ref("2025-12")), mapOf("value_state" to "unconfirmed"), mapOf("as_of_date" to "2026-01-31"),
            mapOf("totals" to totals(provisional = true)), mapOf("value_state" to "missing_month", "observed_amount_krw" to null, "confirmed_amount_krw" to null),
            mapOf("dates" to dates() + mapOf("raw" to "synthetic")))) bad(AuthCode.ACCESS_DENIED) {
            FinancePolicy.response(FinanceOperation.GET_ASSET_TRENDS, r, 200, trend(points = listOf(point("2026-01") + change)))
        }
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.GET_ASSET_TRENDS, r, 200, trend() + mapOf("series_kind" to "asset_owned_amount")) }
        val filtered = request(FinanceOperation.GET_ASSET_TRENDS, mapOf("from" to "2026-01", "to" to "2026-01", "asset_id" to id))
        val asset = trend() + mapOf("filters" to filters() + mapOf("asset_id" to id), "series_kind" to "asset_owned_amount",
            "points" to listOf(point("2026-01") + mapOf("included_in_total" to false, "as_of_date" to "2026-01-30")))
        assertEquals(asset, FinancePolicy.response(FinanceOperation.GET_ASSET_TRENDS, filtered, 200, asset))
    }
    @Test fun allOneHundredTwentyPointsMustBeOrderedAndPresentWithoutExtendingTheRequestedRange() {
        val start = YearMonth.parse("2016-02")
        val points = (0..119).map { point(start.plusMonths(it.toLong()).toString()) }
        val r = request(FinanceOperation.GET_ASSET_TRENDS, mapOf("from" to "2016-02", "to" to "2026-01"))
        val response = trend("2016-02", "2026-01", points)
        assertEquals(response, FinancePolicy.response(FinanceOperation.GET_ASSET_TRENDS, r, 200, response))
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.GET_ASSET_TRENDS, r, 200, response + mapOf("points" to points + point("2026-02"))) }
    }
    @Test fun comparisonReadsRemainLockedAndErrorsOnlyExposeKnownCodes() {
        val policy = AppLockPolicy().also { it.resume(0, false) }
        for (kind in AppRequestKind.entries) {
            assertFalse(policy.httpAllowed(policy.ticket(kind), "GET", "/api/v1/asset-comparison?to=2026-01"))
            assertFalse(policy.httpAllowed(policy.ticket(kind), "GET", "/api/v1/asset-trends?from=2025-12&to=2026-01"))
        }
        val safe = AuthPolicy.safeError(422, mapOf("error" to mapOf("code" to "INVALID_TREND_RANGE", "message" to "synthetic secret")), id)!!
        assertEquals("INVALID_TREND_RANGE", (safe["error"] as Map<*, *>)["code"])
        assertFalse(safe.toString().contains("synthetic"))
    }
}
