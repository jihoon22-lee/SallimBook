package io.github.jihoon22lee.sallimbook.auth

import java.net.URI
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.YearMonth

/** Historical metadata only; the server computes all financial differences and percentages. */
internal object ComparisonPolicy {
    private val filters = setOf("asset_id", "kind", "category", "ownership_kind", "owner_member_id")
    private val scopeReasons = setOf("previously_held_added", "started_after_previous_period", "ended_before_current_period",
        "not_in_previous_scope", "not_in_current_scope", "inclusion_changed", "filter_membership_changed", "household_share_changed", "excluded_from_total")
    private fun invalid(): Nothing = throw AuthFailure(AuthCode.INVALID_REQUEST)
    private fun obj(value: Any?, keys: Set<String>? = null): Map<String, Any?> {
        val row = value as? Map<*, *> ?: invalid()
        if (row.size > 32 || row.keys.any { it !is String } || keys != null && row.keys != keys) invalid()
        return row.entries.associate { it.key as String to it.value }
    }
    private fun month(value: Any?): YearMonth {
        if (value !is String || !Regex("[0-9]{4}-(0[1-9]|1[0-2])").matches(value) || value.startsWith("0000")) invalid()
        return try { YearMonth.parse(value) } catch (_: Exception) { invalid() }
    }
    private fun date(value: Any?) {
        if (value !is String || !Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}").matches(value) || value.startsWith("0000")) invalid()
        try { LocalDate.parse(value) } catch (_: Exception) { invalid() }
    }
    private fun timestamp(value: Any?) {
        if (value !is String || value.length > 40) invalid()
        try { OffsetDateTime.parse(value) } catch (_: Exception) { invalid() }
    }
    private fun choice(value: Any?, allowed: Set<String>) { if (value !is String || value !in allowed) invalid() }
    private fun bool(value: Any?) { if (value !is Boolean) invalid() }
    private fun integer(value: Any?, minimum: Long = 0, maximum: Long = 9_007_199_254_740_991L): Long {
        val number = when (value) { is Int -> value.toLong(); is Long -> value; else -> invalid() }
        if (number !in minimum..maximum) invalid()
        return number
    }
    private fun amount(value: Any?) {
        if (value != null && (value !is String || !Regex("0|-?[1-9][0-9]{0,19}").matches(value))) invalid()
    }
    private fun list(value: Any?, maximum: Int): List<*> {
        val items = value as? List<*> ?: invalid()
        if (items.size > maximum) invalid()
        return items
    }
    private fun ids(value: Any?) {
        // Scope/date ID collections cover the whole scope, not merely the 200-row page.
        // This cap exceeds what fits in the transport's existing 3 MiB metadata limit.
        val items = list(value, 83_000)
        items.forEach { FinancePolicy.id(it) }
        if (items.distinct().size != items.size) invalid()
    }
    private fun filterValues(value: Any?, exact: Boolean): Map<String, Any?> {
        val row = obj(value, if (exact) filters else null)
        if (!filters.containsAll(row.keys)) invalid()
        for ((name, item) in row) if (item != null) when (name) {
            "asset_id", "owner_member_id" -> FinancePolicy.id(item)
            "kind" -> choice(item, setOf("asset", "liability"))
            "category" -> choice(item, setOf("real_estate", "deposit", "financial", "loan", "other"))
            "ownership_kind" -> choice(item, setOf("individual", "joint"))
        }
        if (row["ownership_kind"] == "joint" && row["owner_member_id"] != null) invalid()
        return row
    }
    fun supports(operation: FinanceOperation) = operation in setOf(FinanceOperation.GET_ASSET_COMPARISON, FinanceOperation.GET_ASSET_TRENDS)
    private fun query(operation: FinanceOperation, value: Any?): Map<String, Any?> {
        val row = obj(value)
        val trend = operation == FinanceOperation.GET_ASSET_TRENDS
        val required = if (trend) setOf("from", "to") else setOf("to")
        val allowed = filters + setOf("from", "to") + if (trend) emptySet() else setOf("cursor", "limit")
        if (!allowed.containsAll(row.keys) || !row.keys.containsAll(required)) invalid()
        val end = month(row["to"])
        val start = row["from"]?.let(::month)
        if (trend) {
            if (start == null) invalid()
            val count = (end.year - start.year) * 12 + end.monthValue - start.monthValue + 1
            if (count !in 1..120) invalid()
        } else if (start != null && start >= end) invalid()
        filterValues(row.filterKeys { it in filters }, false)
        row["cursor"]?.let { FinancePolicy.id(it) }
        if ("limit" in row) integer(row["limit"], 1, 200)
        return row.filterValues { it != null }
    }
    fun prepare(operation: FinanceOperation, value: Any?): FinanceRequest {
        if (!supports(operation)) invalid()
        val args = obj(value, setOf("query"))
        val q = query(operation, args["query"])
        val path = if (operation == FinanceOperation.GET_ASSET_TRENDS) "/api/v1/asset-trends" else "/api/v1/asset-comparison"
        return FinanceRequest("GET", path + "?" + q.toSortedMap().entries.joinToString("&") { "${it.key}=${it.value}" }, null, null)
    }
    private fun parseQuery(uri: URI): Map<String, Any?> {
        val raw = uri.rawQuery ?: invalid()
        if (raw.isEmpty()) invalid()
        val values = mutableMapOf<String, Any?>()
        for (part in raw.split('&')) {
            val pair = part.split('=', limit = 2)
            if (pair.size != 2 || pair[0] in values) invalid()
            values[pair[0]] = if (pair[0] == "limit") pair[1].toLongOrNull() ?: invalid() else pair[1]
        }
        return values
    }
    fun httpAllowed(method: String, path: String, body: Any?, ifMatch: String?): Boolean {
        try {
            if (method != "GET" || body != null || ifMatch != null) return false
            val uri = URI(path)
            if (uri.isAbsolute || uri.rawAuthority != null || uri.rawFragment != null || '%' in path || '\\' in path || path.any { it.isWhitespace() || it.code < 32 }) return false
            val operation = when (uri.rawPath) {
                "/api/v1/asset-comparison" -> FinanceOperation.GET_ASSET_COMPARISON
                "/api/v1/asset-trends" -> FinanceOperation.GET_ASSET_TRENDS
                else -> return false
            }
            return prepare(operation, mapOf("query" to parseQuery(uri))).path == path
        } catch (_: Exception) { return false }
    }
    private fun dates(value: Any?) {
        val row = obj(value, setOf("non_month_end_asset_ids", "missing_date_asset_ids", "mixed_dates"))
        ids(row["non_month_end_asset_ids"]); ids(row["missing_date_asset_ids"]); bool(row["mixed_dates"])
    }
    private fun revision(value: Any?, expectedMonth: Any?) {
        val row = CashflowPolicy.monthReference(value)
        if (row["month"] != expectedMonth) invalid()
    }
    private fun period(value: Any?, expectedMonth: Any?): Map<String, Any?> {
        val row = obj(value, setOf("month", "state", "revision", "confirmed_at", "totals", "dates"))
        month(row["month"])
        if (row["month"] != expectedMonth) invalid()
        choice(row["state"], setOf("draft", "reopened", "confirmed", "missing"))
        dates(row["dates"])
        if (row["state"] == "missing") {
            if (row["revision"] != null || row["totals"] != null || row["confirmed_at"] != null) invalid()
        } else {
            revision(row["revision"], row["month"])
            CashflowPolicy.monthTotals(row["totals"])
            if (row["state"] == "confirmed") timestamp(row["confirmed_at"]) else if (row["confirmed_at"] != null) invalid()
        }
        return row
    }
    private fun comparisonItem(value: Any?, available: Boolean) {
        val row = obj(value, setOf("asset_id", "before", "after", "before_in_scope", "after_in_scope", "membership", "share_changed", "same_scope",
            "scope_reason", "amount_delta_krw", "net_assets_effect_krw"))
        FinancePolicy.id(row["asset_id"])
        for (key in listOf("before", "after")) row[key]?.let {
            if (CashflowPolicy.monthValue(it)["asset_id"] != row["asset_id"]) invalid()
        }
        if (row["before"] == null && row["after"] == null) invalid()
        for (key in listOf("before_in_scope", "after_in_scope", "share_changed", "same_scope")) bool(row[key])
        if (row["before_in_scope"] == true && row["before"] == null || row["after_in_scope"] == true && row["after"] == null) invalid()
        choice(row["membership"], setOf("common", "added", "removed", "excluded", "unavailable"))
        row["scope_reason"]?.let { choice(it, scopeReasons) }
        amount(row["amount_delta_krw"]); amount(row["net_assets_effect_krw"])
        if (!available && (row["amount_delta_krw"] != null || row["net_assets_effect_krw"] != null)) invalid()
        if ((row["before"] == null || row["after"] == null) && row["amount_delta_krw"] != null) invalid()
    }
    private fun comparison(value: Any?, q: Map<String, Any?>): Map<String, Any?> {
        val row = obj(value, setOf("from_month", "to_month", "filters", "state", "previous", "current", "total_delta_krw", "common_scope_delta_krw",
            "change_percent", "change_percent_unavailable_reason", "scope_changed", "added_asset_ids", "removed_asset_ids", "changed_share_asset_ids", "item_count", "items", "next_cursor"))
        val to = month(q["to"])
        val from = q["from"] ?: if (to.year == 1 && to.monthValue == 1) null else to.minusMonths(1).toString()
        if (row["from_month"] != from || row["to_month"] != q["to"]) invalid()
        if (from == null) { if (row["previous"] != null) invalid() } else period(row["previous"], from)
        val current = period(row["current"], row["to_month"])
        choice(row["state"], setOf("available", "no_previous_month", "current_missing", "unconfirmed"))
        amount(row["total_delta_krw"]); amount(row["common_scope_delta_krw"])
        val available = row["state"] == "available"
        val percent = row["change_percent"]
        if (percent != null && (percent !is String || percent.length > 27 || !Regex("-?(0|[1-9][0-9]*)\\.[0-9]{2}").matches(percent))) invalid()
        val reason = row["change_percent_unavailable_reason"]
        if (available) {
            if (row["total_delta_krw"] == null || row["common_scope_delta_krw"] == null || current["state"] != "confirmed" || obj(row["previous"])["state"] != "confirmed") invalid()
            if (obj(current["totals"])["provisional"] != false || obj(obj(row["previous"])["totals"])["provisional"] != false) invalid()
            if (percent == null) choice(reason, setOf("zero_previous_total", "negative_previous_total")) else if (reason != null) invalid()
        } else if (row["total_delta_krw"] != null || row["common_scope_delta_krw"] != null || percent != null || reason != row["state"]) invalid()
        row["scope_changed"]?.let(::bool)
        for (key in listOf("added_asset_ids", "removed_asset_ids", "changed_share_asset_ids")) ids(row[key])
        val count = integer(row["item_count"])
        val items = list(row["items"], q["limit"]?.let { integer(it, 1, 200).toInt() } ?: 50)
        if (items.size > count) invalid()
        items.forEach { comparisonItem(it, available) }
        val itemIds = items.map { obj(it)["asset_id"] as String }
        if (itemIds.distinct().size != itemIds.size) invalid()
        q["cursor"]?.let { cursor -> if (cursor in itemIds) invalid() }
        row["next_cursor"]?.let {
            FinancePolicy.id(it)
            if (itemIds.isEmpty() || it != itemIds.last()) invalid()
        }
        return row
    }
    private fun trendPoint(value: Any?, expectedMonth: String, household: Boolean) {
        val row = obj(value, setOf("month", "state", "revision", "totals", "value_state", "observed_amount_krw", "confirmed_amount_krw", "included_in_total", "as_of_date", "dates"))
        if (row["month"] != expectedMonth) invalid()
        choice(row["state"], setOf("draft", "reopened", "confirmed", "missing"))
        if (row["state"] == "missing") {
            if (row["revision"] != null || row["totals"] != null || row["value_state"] != "missing_month") invalid()
        } else {
            if (row["value_state"] == "missing_month") invalid()
            revision(row["revision"], expectedMonth); CashflowPolicy.monthTotals(row["totals"])
        }
        choice(row["value_state"], setOf("missing_month", "missing_item", "outside_filter", "missing_value", "unconfirmed", "verified"))
        amount(row["observed_amount_krw"]); amount(row["confirmed_amount_krw"])
        row["included_in_total"]?.let(::bool); row["as_of_date"]?.let(::date); dates(row["dates"])
        if (household && (row["included_in_total"] != null || row["as_of_date"] != null)) invalid()
        when (row["value_state"]) {
            "verified" -> if (row["state"] != "confirmed" || obj(row["totals"])["provisional"] != false || row["observed_amount_krw"] == null || row["confirmed_amount_krw"] != row["observed_amount_krw"]) invalid()
            "unconfirmed" -> if (row["observed_amount_krw"] == null || row["confirmed_amount_krw"] != null) invalid()
            else -> if (row["observed_amount_krw"] != null || row["confirmed_amount_krw"] != null) invalid()
        }
    }
    fun response(operation: FinanceOperation, request: FinanceRequest, status: Int, value: Any?): Map<String, Any?> {
        if (status != 200) invalid()
        val q = query(operation, parseQuery(URI(request.path)))
        val row = if (operation == FinanceOperation.GET_ASSET_COMPARISON) comparison(value, q) else {
            val result = obj(value, setOf("from_month", "to_month", "filters", "series_kind", "points"))
            if (result["from_month"] != q["from"] || result["to_month"] != q["to"]) invalid()
            val start = month(q["from"]); val end = month(q["to"])
            val points = list(result["points"], 120)
            if (points.size != (end.year - start.year) * 12 + end.monthValue - start.monthValue + 1) invalid()
            val household = q["asset_id"] == null
            if (result["series_kind"] != if (household) "household_net_assets" else "asset_owned_amount") invalid()
            points.forEachIndexed { index, point -> trendPoint(point, start.plusMonths(index.toLong()).toString(), household) }
            result
        }
        val actualFilters = filterValues(row["filters"], true)
        if (filters.any { actualFilters[it] != q[it] }) invalid()
        return row
    }
}
