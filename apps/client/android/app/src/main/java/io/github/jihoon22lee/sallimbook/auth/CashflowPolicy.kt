package io.github.jihoon22lee.sallimbook.auth

import java.net.URI
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.YearMonth

private typealias FieldRule = (Any?) -> Unit

/** Bounded metadata projection. These rules limit the bridge; the API owns domain calculations. */
internal object CashflowPolicy {
    private fun invalid(): Nothing = throw AuthFailure(AuthCode.INVALID_REQUEST)
    private fun obj(value: Any?): Map<String, Any?> {
        val row = value as? Map<*, *> ?: invalid()
        if (row.size > 40 || row.keys.any { it !is String }) invalid()
        return row.entries.associate { it.key as String to it.value }
    }
    private fun str(value: Any?, maximum: Int, empty: Boolean = false) {
        val text = value as? String ?: invalid()
        if ((!empty && text.isBlank()) || text.codePointCount(0, text.length) > maximum) invalid()
    }
    private fun integer(value: Any?, minimum: Long = 1, maximum: Long = 9_007_199_254_740_991L) {
        val number = when (value) { is Int -> value.toLong(); is Long -> value; else -> invalid() }
        if (number !in minimum..maximum) invalid()
    }
    private val id: FieldRule = { FinancePolicy.id(it); Unit }
    private val bool: FieldRule = { if (it !is Boolean) invalid() }
    private val positive: FieldRule = { integer(it) }
    private val count: FieldRule = { integer(it, 0) }
    private val date: FieldRule = {
        if (it !is String || !Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}").matches(it) || it.startsWith("0000")) invalid()
        try { LocalDate.parse(it) } catch (_: Exception) { invalid() }
    }
    private val timestamp: FieldRule = {
        if (it !is String || it.length > 40) invalid()
        try { OffsetDateTime.parse(it) } catch (_: Exception) { invalid() }
    }
    private val month: FieldRule = {
        if (it !is String || !Regex("[0-9]{4}-(0[1-9]|1[0-2])").matches(it) || it.startsWith("0000")) invalid()
        try { YearMonth.parse(it) } catch (_: Exception) { invalid() }
    }
    private val money: FieldRule = { if (it !is String || !Regex("0|[1-9][0-9]{0,19}").matches(it)) invalid() }
    private val signedMoney: FieldRule = { if (it !is String || !Regex("0|-?[1-9][0-9]{0,19}").matches(it)) invalid() }
    private val share: FieldRule = { if (it !is String || !Regex("(0(?:\\.[0-9]{1,18})?|1(?:\\.0{1,18})?)").matches(it)) invalid() }
    private val reason: FieldRule = { str(it, 1000) }
    private fun text(maximum: Int, empty: Boolean = false): FieldRule = { str(it, maximum, empty) }
    private fun nullable(rule: FieldRule): FieldRule = { if (it != null) rule(it) }
    private fun choice(vararg options: String): FieldRule = { if (it !is String || it !in options) invalid() }
    private fun shape(value: Any?, fields: Map<String, FieldRule>, required: Set<String> = fields.keys): Map<String, Any?> {
        val row = obj(value)
        if (!fields.keys.containsAll(row.keys) || !row.keys.containsAll(required)) invalid()
        row.forEach { (key, item) -> fields.getValue(key)(item) }
        return row
    }
    private fun record(fields: Map<String, FieldRule>): FieldRule = { shape(it, fields); Unit }
    private fun list(rule: FieldRule, maximum: Int = 200, minimum: Int = 0): FieldRule = {
        val items = it as? List<*> ?: invalid()
        if (items.size !in minimum..maximum) invalid()
        items.forEach(rule)
    }
    private fun tag(value: Any?): String {
        if (value !is String || !Regex("\"[1-9][0-9]{0,18}\"").matches(value)) invalid()
        return value
    }
    private fun key(value: Any?): String {
        if (value !is String || !Regex("[A-Za-z0-9_.:-]{1,128}").matches(value)) invalid()
        return value
    }

    private data class Route(val method: String, val path: String, val version: Boolean = false,
        val idempotent: Boolean = false, val query: Boolean = false, val status: Int = 200)
    private val routes = mapOf(
        FinanceOperation.GET_ASSET_MONTH to Route("GET", "/api/v1/asset-months/{month}", query = true),
        FinanceOperation.GET_ASSET_MONTH_REVISION to Route("GET", "/api/v1/asset-months/{month}/revisions/{revisionNo}", query = true),
        FinanceOperation.LIST_ASSET_MONTH_REVISIONS to Route("GET", "/api/v1/asset-months/{month}/revisions", query = true),
        FinanceOperation.CREATE_ASSET_MONTH_DRAFT to Route("POST", "/api/v1/asset-months/{month}/draft", idempotent = true, status = 201),
        FinanceOperation.UPDATE_ASSET_MONTH_VALUE to Route("PATCH", "/api/v1/asset-months/{month}/values/{assetId}", version = true),
        FinanceOperation.SYNCHRONIZE_ASSET_MONTH_SCOPE to Route("POST", "/api/v1/asset-months/{month}/sync-scope", version = true),
        FinanceOperation.CONFIRM_ASSET_MONTH to Route("POST", "/api/v1/asset-months/{month}/confirm", version = true, idempotent = true),
        FinanceOperation.REOPEN_ASSET_MONTH to Route("POST", "/api/v1/asset-months/{month}/reopen", version = true, idempotent = true, status = 201),
        FinanceOperation.LIST_INCOME to Route("GET", "/api/v1/income", query = true),
        FinanceOperation.INCOME_SUMMARY to Route("GET", "/api/v1/income/summary", query = true),
        FinanceOperation.INCOME_DUPLICATE_CANDIDATES to Route("GET", "/api/v1/income/duplicates", query = true),
        FinanceOperation.GET_INCOME to Route("GET", "/api/v1/income/{recordId}"),
        FinanceOperation.INCOME_HISTORY to Route("GET", "/api/v1/income/{recordId}/history", query = true),
        FinanceOperation.CREATE_INCOME to Route("POST", "/api/v1/income", idempotent = true, status = 201),
        FinanceOperation.CORRECT_INCOME to Route("PATCH", "/api/v1/income/{recordId}", version = true, idempotent = true),
        FinanceOperation.VOID_INCOME to Route("POST", "/api/v1/income/{recordId}/void", version = true, idempotent = true),
        FinanceOperation.RETURN_INCOME to Route("POST", "/api/v1/income/{recordId}/returns", version = true, idempotent = true, status = 201),
        FinanceOperation.CONVERT_INCOME_PRECISION to Route("POST", "/api/v1/income/convert", idempotent = true, status = 201),
    )
    fun supports(operation: FinanceOperation) = operation in routes

    private fun input(operation: FinanceOperation, value: Any?): Map<String, Any?> = when (operation) {
        FinanceOperation.CREATE_ASSET_MONTH_DRAFT -> shape(value, mapOf("copy_previous" to bool), emptySet())
        FinanceOperation.SYNCHRONIZE_ASSET_MONTH_SCOPE -> shape(value, mapOf("revision_id" to id))
        FinanceOperation.CONFIRM_ASSET_MONTH -> shape(value, mapOf("revision_id" to id,
            "acknowledge_non_month_end_dates" to bool, "acknowledge_scope_change" to bool), setOf("revision_id"))
        FinanceOperation.REOPEN_ASSET_MONTH -> shape(value, mapOf("revision_id" to id, "reason" to reason))
        FinanceOperation.UPDATE_ASSET_MONTH_VALUE -> {
            val row = shape(value, mapOf("revision_id" to id, "value_id" to id, "input_amount_krw" to nullable(money),
                "as_of_date" to nullable(date), "unchanged" to bool, "change_reason" to nullable(reason)), setOf("revision_id", "value_id"))
            if (row["unchanged"] == true) {
                if ("input_amount_krw" in row || row["as_of_date"] == null) invalid()
            } else if ("input_amount_krw" !in row) invalid()
            if (row["input_amount_krw"] != null && row["as_of_date"] == null) invalid()
            row
        }
        FinanceOperation.CREATE_INCOME -> incomeInput(value, create = true)
        FinanceOperation.CORRECT_INCOME -> {
            val row = shape(value, cashInputFields() + mapOf("kind" to incomeKind, "member_id" to id,
                "reason" to text(500), "duplicate_acknowledged" to bool), setOf("reason"))
            if ((row.keys - setOf("reason", "duplicate_acknowledged")).isEmpty()) invalid()
            row
        }
        FinanceOperation.VOID_INCOME -> shape(value, mapOf("reason" to text(500)))
        FinanceOperation.RETURN_INCOME -> {
            val row = shape(value, cashInputFields() + mapOf("reason" to text(500), "member_id" to { if (it != null) invalid() }, "card_id" to { if (it != null) invalid() }),
                setOf("amount_krw", "period_month", "date_precision", "reason"))
            precision(row)
            row
        }
        FinanceOperation.CONVERT_INCOME_PRECISION -> {
            val row = shape(value, mapOf("reason" to text(500), "sources" to list(record(mapOf("id" to id, "version" to positive)), 100, 1),
                "replacements" to list({ incomeInput(it); Unit }, 100, 1)))
            val sources = row["sources"] as List<*>
            if (sources.map { obj(it)["id"] }.distinct().size != sources.size) invalid()
            row
        }
        else -> invalid()
    }

    private val incomeKind = choice("salary", "bonus", "other_income")
    private val projectedIncomeKind = choice("salary", "bonus", "other_income", "income_return", "insurance_receipt", "insurance_return")
    private val positiveMoney: FieldRule = { money(it); if (it == "0") invalid() }
    private fun cashInputFields() = mapOf("amount_krw" to positiveMoney, "period_month" to month, "date_precision" to choice("day", "month"),
        "occurred_on" to nullable(date), "member_id" to nullable(id), "account_id" to nullable(id), "note" to nullable(text(2000, true)))
    private fun precision(row: Map<String, Any?>) {
        if ((row["date_precision"] == "day") != (row["occurred_on"] != null)) invalid()
    }
    private fun incomeInput(value: Any?, create: Boolean = false): Map<String, Any?> {
        val row = shape(value, cashInputFields() + mapOf("kind" to incomeKind, "member_id" to id, "card_id" to { if (it != null) invalid() }) +
            if (create) mapOf("duplicate_acknowledged" to bool) else emptyMap(),
            setOf("amount_krw", "period_month", "date_precision", "kind", "member_id"))
        precision(row)
        return row
    }

    private fun integerCursor(operation: FinanceOperation) = operation in setOf(FinanceOperation.LIST_ASSET_MONTH_REVISIONS, FinanceOperation.INCOME_HISTORY)
    private fun requiredQuery(operation: FinanceOperation) = operation in setOf(FinanceOperation.LIST_INCOME, FinanceOperation.INCOME_SUMMARY, FinanceOperation.INCOME_DUPLICATE_CANDIDATES)

    private fun query(operation: FinanceOperation, value: Any?): String {
        if (value == null) { if (requiredQuery(operation)) invalid(); return "" }
        val paging = mapOf("cursor" to nullable(if (integerCursor(operation)) positive else id), "limit" to { item: Any? -> integer(item, 1, 200) })
        val fields = when (operation) {
            FinanceOperation.INCOME_SUMMARY -> mapOf("month" to month)
            FinanceOperation.LIST_INCOME -> paging + mapOf("month" to month, "member_id" to nullable(id), "kind" to nullable(projectedIncomeKind), "state" to choice("active", "void", "all"))
            FinanceOperation.INCOME_DUPLICATE_CANDIDATES -> mapOf("month" to month, "kind" to incomeKind, "member_id" to id, "date_precision" to choice("day", "month"))
            else -> paging
        }
        val required = if (operation == FinanceOperation.INCOME_DUPLICATE_CANDIDATES) fields.keys else if (requiredQuery(operation)) setOf("month") else emptySet()
        val row = shape(value, fields, required).filterValues { it != null }
        return if (row.isEmpty()) "" else "?" + row.toSortedMap().entries.joinToString("&") { "${it.key}=${it.value}" }
    }

    fun prepare(operation: FinanceOperation, value: Any?): FinanceRequest {
        val route = routes[operation] ?: invalid()
        val args = obj(value)
        val variables = Regex("\\{([A-Za-z]+)}").findAll(route.path).map { it.groupValues[1] }.toList()
        val required = variables.toSet() + (if (route.version) setOf("ifMatch") else emptySet()) +
            (if (route.idempotent) setOf("idempotencyKey") else emptySet()) + (if (route.method != "GET") setOf("input") else emptySet())
        val allowed = required + if (route.query) setOf("query") else emptySet()
        if (!args.keys.containsAll(required) || !allowed.containsAll(args.keys)) invalid()
        var path = route.path
        for (name in variables) {
            when (name) { "month" -> month(args[name]); "revisionNo" -> positive(args[name]); else -> id(args[name]) }
            path = path.replace("{$name}", args[name].toString())
        }
        if (route.query) path += query(operation, args["query"])
        return FinanceRequest(route.method, path, if (route.method == "GET") null else input(operation, args["input"]),
            if (route.version) tag(args["ifMatch"]) else null, if (route.idempotent) key(args["idempotencyKey"]) else null)
    }

    fun httpAllowed(method: String, path: String, body: Any?, ifMatch: String?, idempotencyKey: String?): Boolean {
        try {
            val uri = URI(path)
            if (uri.isAbsolute || uri.rawAuthority != null || uri.rawFragment != null || '%' in path || '\\' in path ||
                path.any { it.isWhitespace() || it.code < 32 }) return false
            for ((operation, route) in routes) {
                if (route.method != method) continue
                val template = route.path.split('/')
                val segments = uri.rawPath.split('/')
                if (template.size != segments.size) continue
                val args = mutableMapOf<String, Any?>()
                if (!template.zip(segments).all { (expected, actual) ->
                    if (expected.startsWith('{')) {
                        val name = expected.substring(1, expected.length - 1)
                        args[name] = if (name == "revisionNo") actual.toLongOrNull() ?: invalid() else actual
                        true
                    } else expected == actual
                }) continue
                if ((ifMatch != null) != route.version || (idempotencyKey != null) != route.idempotent) return false
                if (route.version) args["ifMatch"] = ifMatch
                if (route.idempotent) args["idempotencyKey"] = idempotencyKey
                if (method != "GET") args["input"] = body else if (body != null) return false
                uri.rawQuery?.let { raw ->
                    if (!route.query || raw.isEmpty()) invalid()
                    val values = mutableMapOf<String, Any?>()
                    for (part in raw.split('&')) {
                        val pair = part.split('=', limit = 2)
                        if (pair.size != 2 || pair[0] in values) invalid()
                        values[pair[0]] = if (pair[0] == "limit" || pair[0] == "cursor" && integerCursor(operation))
                            pair[1].toLongOrNull() ?: invalid() else pair[1]
                    }
                    args["query"] = values
                }
                val expected = prepare(operation, args)
                return expected.path == path && expected.body == body && expected.ifMatch == ifMatch && expected.idempotencyKey == idempotencyKey
            }
            return false
        } catch (_: Exception) { return false }
    }

    private fun referenceFields() = mapOf("month" to month, "revision_id" to id, "revision_no" to positive, "version" to positive)
    private fun historyFields() = referenceFields() + mapOf("state" to choice("draft", "reopened", "confirmed"),
        "previous_revision_id" to nullable(id), "reopened_reason" to nullable(reason), "confirmed_at" to nullable(timestamp), "created_at" to timestamp)
    private fun totalsFields() = mapOf("assets_krw" to nullable(money), "liabilities_krw" to nullable(money), "net_assets_krw" to nullable(signedMoney),
        "verified_count" to count, "item_count" to count, "missing_count" to count, "carried_count" to count, "provisional" to bool)
    private fun valueFields() = mapOf("id" to id, "asset_id" to id, "name" to text(120), "kind" to choice("asset", "liability"),
        "category" to choice("real_estate", "deposit", "financial", "loan", "other"), "ownership_kind" to choice("individual", "joint"),
        "owner_member_id" to nullable(id), "household_share" to share, "amount_basis" to choice("whole", "owned"),
        "inclusion_status" to choice("included", "excluded"), "started_on" to date, "ended_on" to nullable(date), "source_asset_version" to positive,
        "input_amount_krw" to nullable(money), "owned_amount_krw" to nullable(money), "as_of_date" to nullable(date),
        "verification_state" to choice("missing", "carried_unconfirmed", "verified"), "origin" to choice("manual", "carried"),
        "origin_revision_id" to nullable(id), "change_reason" to nullable(reason), "version" to positive)

    // Comparison endpoints embed these same generated monthly schemas.
    fun monthReference(value: Any?) = shape(value, referenceFields())
    fun monthTotals(value: Any?) = shape(value, totalsFields())
    fun monthValue(value: Any?) = shape(value, valueFields())

    fun response(operation: FinanceOperation, request: FinanceRequest, status: Int, value: Any?): Any? {
        if (status != routes.getValue(operation).status) invalid()
        if (routes.getValue(operation).path.startsWith("/api/v1/income")) return incomeResponse(operation, request, value)
        val segments = URI(request.path).path.split('/')
        val row = when (operation) {
            FinanceOperation.GET_ASSET_MONTH, FinanceOperation.GET_ASSET_MONTH_REVISION -> shape(value, historyFields() + mapOf(
                "confirmed_by_member_id" to nullable(id), "totals" to record(totalsFields()), "scope_stale" to bool,
                "values" to list(record(valueFields())), "next_cursor" to nullable(id)))
            FinanceOperation.LIST_ASSET_MONTH_REVISIONS -> {
                val result = shape(value, mapOf("items" to list(record(historyFields())), "next_cursor" to nullable(positive)))
                (result["items"] as List<*>).forEach { if (obj(it)["month"] != segments[4]) invalid() }
                return result
            }
            FinanceOperation.UPDATE_ASSET_MONTH_VALUE -> {
                val result = shape(value, mapOf("value" to record(valueFields()), "revision_version" to positive, "totals" to record(totalsFields())))
                val item = obj(result["value"])
                if (item["asset_id"] != segments[6] || item["id"] != request.body?.get("value_id")) invalid()
                return result
            }
            else -> shape(value, referenceFields())
        }
        if (row["month"] != segments[4]) invalid()
        if (operation == FinanceOperation.GET_ASSET_MONTH_REVISION && row["revision_no"].toString() != segments[6]) invalid()
        if (operation in setOf(FinanceOperation.CONFIRM_ASSET_MONTH, FinanceOperation.SYNCHRONIZE_ASSET_MONTH_SCOPE) &&
            row["revision_id"] != request.body?.get("revision_id")) invalid()
        return row
    }

    private fun cashFields() = cashInputFields() + mapOf("id" to id, "household_id" to id, "kind" to projectedIncomeKind, "card_id" to nullable(id),
        "flow" to choice("in", "out"), "reverses_id" to nullable(id), "state" to choice("active", "void"),
        "created_by_member_id" to id, "updated_by_member_id" to id, "created_at" to timestamp, "updated_at" to timestamp,
        "version" to positive, "action" to choice("create", "correct", "void", "convert_source", "convert_result"),
        "reason" to nullable(text(500)), "conversion_id" to nullable(id), "editable" to bool, "voidable" to bool)
    private val cash: FieldRule = { val row = shape(it, cashFields()); precision(row) }
    private fun incomeTotalsFields() = mapOf("salary_krw" to money, "bonus_krw" to money, "other_income_krw" to money,
        "income_returns_krw" to money, "insurance_receipts_krw" to money, "insurance_returns_krw" to money,
        "earned_net_krw" to signedMoney, "insurance_net_krw" to signedMoney, "net_inflow_krw" to signedMoney, "record_count" to count)
    private fun incomeResponse(operation: FinanceOperation, request: FinanceRequest, value: Any?): Map<String, Any?> {
        val uri = URI(request.path)
        val recordId = uri.path.split('/').getOrNull(4)
        return when (operation) {
            FinanceOperation.LIST_INCOME, FinanceOperation.INCOME_HISTORY -> {
                val row = shape(value, mapOf("items" to list(cash), "next_cursor" to nullable(if (operation == FinanceOperation.INCOME_HISTORY) positive else id)))
                if (operation == FinanceOperation.INCOME_HISTORY && (row["items"] as List<*>).any { obj(it)["id"] != recordId }) invalid()
                row
            }
            FinanceOperation.INCOME_SUMMARY -> {
                val row = shape(value, mapOf("period_month" to month, "totals" to record(incomeTotalsFields()),
                    "members" to list(record(mapOf("member_id" to nullable(id), "totals" to record(incomeTotalsFields()))))))
                if (row["period_month"] != uri.rawQuery.removePrefix("month=")) invalid()
                row
            }
            FinanceOperation.INCOME_DUPLICATE_CANDIDATES -> shape(value, mapOf("suspected" to bool, "items" to list(cash), "truncated" to bool))
            FinanceOperation.CONVERT_INCOME_PRECISION -> shape(value, mapOf("id" to id, "version" to { integer(it, 1, 1) },
                "reason" to text(500), "created_at" to timestamp, "sources" to list(cash, 100, 1), "replacements" to list(cash, 100, 1)))
            else -> {
                cash(value)
                val row = obj(value)
                if (operation in setOf(FinanceOperation.GET_INCOME, FinanceOperation.CORRECT_INCOME, FinanceOperation.VOID_INCOME) && row["id"] != recordId) invalid()
                if (operation == FinanceOperation.RETURN_INCOME && (row["reverses_id"] != recordId || row["kind"] != "income_return")) invalid()
                row
            }
        }
    }
}
