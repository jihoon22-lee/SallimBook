package io.github.jihoon22lee.sallimbook.auth

import java.net.URI
import java.time.LocalDate
import java.time.YearMonth

/**
 * The home's read-only household figures: the current status, the month-by-month trend and the
 * premiums-against-benefits summary. The server sums every amount; this only checks the shape and
 * bounds of registered names, counts and decimal KRW strings. No number, credential or vault
 * field is part of these responses.
 */
internal object HouseholdOverviewPolicy {
    private const val PATH = "/api/v1/household-overview"
    private const val TRENDS = "/api/v1/household-trends"
    private const val INSURANCE = "/api/v1/insurance/summary"
    private const val MAX_TREND_MONTHS = 36
    private val operations = setOf(FinanceOperation.HOUSEHOLD_OVERVIEW, FinanceOperation.HOUSEHOLD_TRENDS, FinanceOperation.INSURANCE_SUMMARY)
    private val accountTypes = setOf("brokerage", "pension_savings", "irp", "dc_pension", "isa")
    private val percentPattern = Regex("-?(0|[1-9][0-9]{0,12})\\.[0-9]")
    private val groups = setOf("accounts", "financial", "real_estate", "deposit", "loan", "other")
    private val categories = setOf("real_estate", "deposit", "financial", "loan", "other")
    private val money = Regex("0|[1-9][0-9]{0,19}")
    private val signedMoney = Regex("0|-?[1-9][0-9]{0,19}")
    private val monthPattern = Regex("[0-9]{4}-(0[1-9]|1[0-2])")

    private fun invalid(): Nothing = throw AuthFailure(AuthCode.INVALID_REQUEST)
    private fun obj(value: Any?, keys: Set<String>): Map<String, Any?> {
        val row = value as? Map<*, *> ?: invalid()
        if (row.size > 32 || row.keys.any { it !is String }) invalid()
        val result = if (NativeResponseShape.tolerant) NativeResponseShape.identity(row) else row.entries.associate { it.key as String to it.value }
        NativeResponseShape.accept(result, result.keys, keys, keys, ::invalid)
        return result
    }
    private fun month(value: Any?): String {
        if (value !is String || !monthPattern.matches(value) || value.startsWith("0000")) invalid()
        try { YearMonth.parse(value) } catch (_: Exception) { invalid() }
        return value
    }
    private fun date(value: Any?) {
        if (value !is String || !Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}").matches(value) || value.startsWith("0000")) invalid()
        try { LocalDate.parse(value) } catch (_: Exception) { invalid() }
    }
    private fun count(value: Any?): Long {
        val number = when (value) { is Int -> value.toLong(); is Long -> value; else -> invalid() }
        if (number !in 0..9_007_199_254_740_991L) invalid()
        return number
    }
    private fun money(value: Any?) { if (value !is String || !money.matches(value)) invalid() }
    private fun signedMoney(value: Any?) { if (value !is String || !signedMoney.matches(value)) invalid() }
    private fun text(value: Any?, maximum: Int) {
        if (value !is String || value.isBlank() || value.codePointCount(0, value.length) > maximum) invalid()
    }
    private fun choice(value: Any?, allowed: Set<String>) { if (value !is String || value !in allowed) invalid() }
    private fun bool(value: Any?) { if (value !is Boolean) invalid() }
    private fun list(value: Any?, maximum: Int): List<*> {
        val items = value as? List<*> ?: invalid()
        if (items.size > maximum) invalid()
        return items
    }

    private fun percent(value: Any?) { if (value !is String || !percentPattern.matches(value)) invalid() }
    private fun trendMonths(value: Any?): Long {
        val number = count(value)
        if (number !in 1..MAX_TREND_MONTHS) invalid()
        return number
    }

    fun supports(operation: FinanceOperation) = operation in operations

    fun prepare(operation: FinanceOperation, value: Any?): FinanceRequest {
        if (!supports(operation)) invalid()
        val args = value as? Map<*, *> ?: invalid()
        if (operation == FinanceOperation.INSURANCE_SUMMARY) {
            if (args.isNotEmpty()) invalid()
            return FinanceRequest("GET", INSURANCE, null, null)
        }
        if (args.keys != setOf("query")) invalid()
        val query = args["query"] as? Map<*, *> ?: invalid()
        if (operation == FinanceOperation.HOUSEHOLD_TRENDS) {
            if (query.keys != setOf("to", "months")) invalid()
            return FinanceRequest("GET", "$TRENDS?to=${month(query["to"])}&months=${trendMonths(query["months"])}", null, null)
        }
        if (query.keys != setOf("month")) invalid()
        return FinanceRequest("GET", "$PATH?month=${month(query["month"])}", null, null)
    }

    fun httpAllowed(method: String, path: String, body: Any?, ifMatch: String?, idempotencyKey: String?): Boolean {
        if (method != "GET" || body != null || ifMatch != null || idempotencyKey != null) return false
        if (path == INSURANCE) return true
        val trend = Regex("/api/v1/household-trends\\?to=([0-9]{4}-[0-9]{2})&months=([1-9][0-9]?)").matchEntire(path)
        if (trend != null) {
            return try { month(trend.groupValues[1]); trend.groupValues[2].toInt() <= MAX_TREND_MONTHS } catch (_: AuthFailure) { false }
        }
        val match = Regex("/api/v1/household-overview\\?month=([0-9]{4}-[0-9]{2})").matchEntire(path) ?: return false
        return try { month(match.groupValues[1]); true } catch (_: AuthFailure) { false }
    }

    private fun named(value: Any?, maximum: Int) {
        val row = obj(value, setOf("id", "name"))
        FinancePolicy.id(row["id"]); text(row["name"], maximum)
    }
    private fun registered(value: Any?) {
        val row = obj(value, setOf("count", "items"))
        val total = count(row["count"])
        val items = list(row["items"], 4)
        if (items.size > total) invalid()
        items.forEach { named(it, 120) }
    }
    private fun holding(value: Any?) {
        val row = obj(value, setOf("asset_id", "account_id", "name", "kind", "category", "group", "included",
            "owned_amount_krw", "basis_month", "as_of_date", "stale"))
        FinancePolicy.id(row["asset_id"]); row["account_id"]?.let { FinancePolicy.id(it) }
        text(row["name"], 120)
        choice(row["kind"], setOf("asset", "liability")); choice(row["category"], categories); choice(row["group"], groups)
        bool(row["included"]); bool(row["stale"])
        row["owned_amount_krw"]?.let(::money); row["basis_month"]?.let(::month); row["as_of_date"]?.let(::date)
        // A saved amount always has the month it was saved in; an unsaved item is never out of date.
        if ((row["owned_amount_krw"] == null) != (row["basis_month"] == null)) invalid()
        if (row["stale"] == true && (row["owned_amount_krw"] == null || row["included"] != true)) invalid()
        if ((row["group"] == "accounts") != (row["account_id"] != null)) invalid()
    }
    private fun groupTotal(value: Any?) {
        val row = obj(value, setOf("group", "count", "known_count", "assets_krw", "liabilities_krw"))
        choice(row["group"], groups)
        if (count(row["known_count"]) > count(row["count"])) invalid()
        money(row["assets_krw"]); money(row["liabilities_krw"])
    }
    private fun holdings(value: Any?) {
        val row = obj(value, setOf("assets_krw", "liabilities_krw", "net_assets_krw", "item_count", "known_count",
            "missing_count", "stale_count", "current_count", "oldest_basis_month", "groups", "items"))
        money(row["assets_krw"]); money(row["liabilities_krw"]); signedMoney(row["net_assets_krw"])
        val items = count(row["item_count"]); val known = count(row["known_count"])
        if (known + count(row["missing_count"]) != items || count(row["stale_count"]) > known || count(row["current_count"]) > known) invalid()
        row["oldest_basis_month"]?.let(::month)
        val totals = list(row["groups"], groups.size)
        totals.forEach(::groupTotal)
        if (totals.map { (it as Map<*, *>)["group"] }.distinct().size != totals.size) invalid()
        // Every held item is listed once, including those left out of the totals.
        val rows = list(row["items"], 10_000)
        rows.forEach(::holding)
        if (rows.map { (it as Map<*, *>)["asset_id"] }.distinct().size != rows.size) invalid()
        if (rows.count { (it as Map<*, *>)["included"] == true }.toLong() != items) invalid()
    }
    private fun insurance(value: Any?) {
        val row = obj(value, setOf("active_policy_count", "open_case_count", "claims_in_progress_count",
            "documents_required_count", "policies"))
        val policies = count(row["active_policy_count"]); count(row["open_case_count"])
        if (count(row["documents_required_count"]) > count(row["claims_in_progress_count"])) invalid()
        val items = list(row["policies"], 4)
        if (items.size > policies) invalid()
        items.forEach { named(it, 243) }
    }
    private fun plan(value: Any?) {
        val row = obj(value, setOf("as_of", "expected_income_known_krw", "expected_income_count", "expected_income_unknown_count",
            "spending_known_krw", "loan_known_krw", "transfer_known_krw", "planned_unknown_count", "unconverted_count",
            "excluded_known_krw", "margin_before_transfers_krw", "margin_after_transfers_krw"))
        date(row["as_of"])
        for (key in listOf("expected_income_known_krw", "spending_known_krw", "loan_known_krw", "transfer_known_krw", "excluded_known_krw")) money(row[key])
        if (count(row["expected_income_unknown_count"]) > count(row["expected_income_count"])) invalid()
        count(row["planned_unknown_count"]); count(row["unconverted_count"])
        signedMoney(row["margin_before_transfers_krw"]); signedMoney(row["margin_after_transfers_krw"])
    }

    private fun investment(value: Any?) {
        val row = obj(value, setOf("asset_id", "account_id", "name", "account_type", "value_krw", "basis_month",
            "contributed_krw", "contributed_as_of", "gain_krw", "return_percent"))
        FinancePolicy.id(row["asset_id"]); FinancePolicy.id(row["account_id"]); text(row["name"], 120)
        choice(row["account_type"], accountTypes)
        money(row["value_krw"]); month(row["basis_month"]); money(row["contributed_krw"])
        row["contributed_as_of"]?.let(::date)
        signedMoney(row["gain_krw"]); row["return_percent"]?.let(::percent)
    }
    private fun investments(value: Any?) {
        val row = obj(value, setOf("count", "value_krw", "contributed_krw", "gain_krw", "return_percent",
            "missing_contribution_count", "items"))
        money(row["value_krw"]); money(row["contributed_krw"]); signedMoney(row["gain_krw"])
        row["return_percent"]?.let(::percent); count(row["missing_contribution_count"])
        val items = list(row["items"], 10_000)
        if (items.size.toLong() != count(row["count"])) invalid()
        items.forEach(::investment)
        if (items.map { (it as Map<*, *>)["account_id"] }.distinct().size != items.size) invalid()
    }
    private fun netAssetsPoint(value: Any?): String {
        val row = obj(value, setOf("month", "assets_krw", "liabilities_krw", "net_assets_krw", "item_count", "known_count",
            "entered_count", "confirmed"))
        val label = month(row["month"])
        val known = count(row["known_count"])
        if (known > count(row["item_count"]) || count(row["entered_count"]) > known) invalid()
        bool(row["confirmed"])
        // A month with no saved amount has no total at all, never a zero.
        val empty = known == 0L
        for (key in listOf("assets_krw", "liabilities_krw", "net_assets_krw")) if ((row[key] == null) != empty) invalid()
        row["assets_krw"]?.let(::money); row["liabilities_krw"]?.let(::money); row["net_assets_krw"]?.let(::signedMoney)
        return label
    }
    private fun planPoint(value: Any?): String {
        val row = obj(value, setOf("month", "as_of", "income_known_krw", "income_count", "income_unknown_count",
            "spending_known_krw", "loan_known_krw", "transfer_known_krw", "planned_unknown_count",
            "margin_before_transfers_krw", "margin_after_transfers_krw", "actual_income_krw"))
        val label = month(row["month"]); date(row["as_of"])
        for (key in listOf("income_known_krw", "spending_known_krw", "loan_known_krw", "transfer_known_krw")) money(row[key])
        val incomes = count(row["income_count"]); val unknown = count(row["income_unknown_count"])
        if (unknown > incomes) invalid()
        count(row["planned_unknown_count"]); signedMoney(row["actual_income_krw"])
        // A margin exists only when at least one expected income has an amount.
        val ready = incomes > unknown
        for (key in listOf("margin_before_transfers_krw", "margin_after_transfers_krw")) {
            if ((row[key] != null) != ready) invalid()
            row[key]?.let(::signedMoney)
        }
        return label
    }
    private fun trends(request: FinanceRequest, value: Any?): Map<String, Any?> {
        val query = URI(request.path).rawQuery ?: invalid()
        val match = Regex("to=([0-9]{4}-[0-9]{2})&months=([1-9][0-9]?)").matchEntire(query) ?: invalid()
        val row = obj(value, setOf("to_month", "months", "net_assets", "plan"))
        if (row["to_month"] != match.groupValues[1]) invalid()
        val months = trendMonths(row["months"])
        if (months > match.groupValues[2].toLong()) invalid()
        val net = list(row["net_assets"], MAX_TREND_MONTHS).map(::netAssetsPoint)
        val plans = list(row["plan"], MAX_TREND_MONTHS).map(::planPoint)
        // Both series cover the same consecutive months and end at the requested one.
        if (net.size.toLong() != months || plans != net || net.lastOrNull() != row["to_month"]) invalid()
        if (net.zipWithNext().any { (a, b) -> YearMonth.parse(a).plusMonths(1) != YearMonth.parse(b) }) invalid()
        return row
    }
    private fun policyMoney(value: Any?) {
        val row = obj(value, setOf("policy_id", "insurer", "product_name", "status", "monthly_premium_krw", "paid_before_krw",
            "paid_through", "paid_estimated_krw", "estimated_from_month", "estimated_months", "unknown_months",
            "paid_total_krw", "received_krw", "recovery_percent"))
        FinancePolicy.id(row["policy_id"]); text(row["insurer"], 120); text(row["product_name"], 120)
        choice(row["status"], setOf("active", "ended", "lapsed"))
        money(row["monthly_premium_krw"]); money(row["paid_estimated_krw"]); signedMoney(row["received_krw"])
        row["paid_before_krw"]?.let(::money); row["paid_through"]?.let(::date)
        if ((row["paid_before_krw"] == null) != (row["paid_through"] == null)) invalid()
        row["estimated_from_month"]?.let(::month)
        val counted = count(row["estimated_months"]); count(row["unknown_months"])
        if ((row["estimated_from_month"] == null) != (counted == 0L)) invalid()
        row["paid_total_krw"]?.let(::money); row["recovery_percent"]?.let(::percent)
        // Without an entered or estimated premium there is no total and no ratio.
        val known = row["paid_before_krw"] != null || counted > 0
        if ((row["paid_total_krw"] != null) != known || !known && row["recovery_percent"] != null) invalid()
    }
    private fun insuranceSummary(value: Any?): Map<String, Any?> {
        val row = obj(value, setOf("as_of", "policy_count", "paid_unknown_count", "monthly_premium_krw", "paid_total_krw",
            "received_krw", "matched_received_krw", "unassigned_received_krw", "recovery_percent", "policies"))
        date(row["as_of"])
        money(row["monthly_premium_krw"]); money(row["paid_total_krw"])
        signedMoney(row["received_krw"]); signedMoney(row["matched_received_krw"]); signedMoney(row["unassigned_received_krw"])
        row["recovery_percent"]?.let(::percent)
        val items = list(row["policies"], 10_000)
        if (items.size.toLong() != count(row["policy_count"]) || count(row["paid_unknown_count"]) > items.size) invalid()
        items.forEach(::policyMoney)
        if (items.map { (it as Map<*, *>)["policy_id"] }.distinct().size != items.size) invalid()
        return row
    }

    fun response(operation: FinanceOperation, request: FinanceRequest, status: Int, value: Any?): Map<String, Any?> {
        if (!supports(operation) || status != 200) invalid()
        if (operation == FinanceOperation.HOUSEHOLD_TRENDS) return trends(request, value)
        if (operation == FinanceOperation.INSURANCE_SUMMARY) return insuranceSummary(value)
        val expected = URI(request.path).rawQuery?.removePrefix("month=") ?: invalid()
        val row = obj(value, setOf("month", "holdings", "investments", "cards", "appliances", "insurance", "plan"))
        if (row["month"] != expected) invalid()
        holdings(row["holdings"]); investments(row["investments"])
        registered(row["cards"]); registered(row["appliances"])
        insurance(row["insurance"]); plan(row["plan"])
        return row
    }
}
