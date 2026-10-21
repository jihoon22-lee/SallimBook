package io.github.jihoon22lee.sallimbook.auth

import java.math.BigInteger
import java.net.URI
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.YearMonth
import java.time.temporal.ChronoUnit

private typealias FixedField = (Any?) -> Unit

/** Generated fixed-cost DTOs projected through fixed native commands; no schedule execution here. */
internal object FixedCostPolicy {
    private fun invalid(): Nothing = throw AuthFailure(AuthCode.INVALID_REQUEST)
    private fun obj(value: Any?): Map<String, Any?> {
        val row = value as? Map<*, *> ?: invalid()
        if (row.size > 48 || row.keys.any { it !is String }) invalid()
        if (NativeResponseShape.tolerant) return NativeResponseShape.identity(row)
        return row.entries.associate { it.key as String to it.value }
    }
    private fun integer(value: Any?, minimum: Long = 1, maximum: Long = 9_007_199_254_740_991L) {
        val number = when (value) { is Int -> value.toLong(); is Long -> value; else -> invalid() }
        if (number !in minimum..maximum) invalid()
    }
    private fun text(maximum: Int, empty: Boolean = false): FixedField = {
        if (it !is String || it.codePointCount(0, it.length) > maximum || !empty && it.isBlank()) invalid()
    }
    private val id: FixedField = { FinancePolicy.id(it); Unit }
    private val positive: FixedField = { integer(it) }
    private val count: FixedField = { integer(it, 0) }
    private val bool: FixedField = { if (it !is Boolean) invalid() }
    private val money: FixedField = { if (it !is String || !Regex("0|[1-9][0-9]{0,19}").matches(it)) invalid() }
    private val signedMoney: FixedField = { if (it !is String || !Regex("0|-?[1-9][0-9]{0,19}").matches(it)) invalid() }
    private val positiveMoney: FixedField = { money(it); if (it == "0") invalid() }
    private val date: FixedField = {
        if (it !is String || !Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}").matches(it) || it.startsWith("0000")) invalid()
        try { LocalDate.parse(it) } catch (_: Exception) { invalid() }
    }
    private val month: FixedField = {
        if (it !is String || !Regex("[0-9]{4}-(0[1-9]|1[0-2])").matches(it) || it.startsWith("0000")) invalid()
        try { YearMonth.parse(it) } catch (_: Exception) { invalid() }
    }
    private val timestamp: FixedField = {
        if (it !is String || it.length > 40) invalid()
        try { OffsetDateTime.parse(it) } catch (_: Exception) { invalid() }
    }
    private val foreign: FixedField = { if (it !is String || it.length > 40 || !Regex("(0|[1-9][0-9]*)(\\.[0-9]{1,8})?").matches(it)) invalid() }
    private val currency: FixedField = { if (it !is String || !Regex("[A-Z]{3}").matches(it)) invalid() }
    private val economic = choice("expense", "loan", "asset_transfer")
    private val reason = text(500)
    private fun choice(vararg values: String): FixedField = { if (it !is String || it !in values) invalid() }
    private fun nullable(rule: FixedField): FixedField = { if (it != null) rule(it) }
    private fun shape(value: Any?, fields: Map<String, FixedField>, required: Set<String> = fields.keys): Map<String, Any?> {
        val row = obj(value)
        NativeResponseShape.accept(row, row.keys, fields.keys, required, ::invalid)
        row.forEach { (name, item) -> fields[name]?.invoke(item) }
        return row
    }
    private fun records(rule: FixedField, maximum: Int = 200, minimum: Int = 0): FixedField = {
        val list = it as? List<*> ?: invalid()
        if (list.size !in minimum..maximum) invalid()
        list.forEach(rule)
    }
    private fun tag(value: Any?): String {
        if (value !is String || !Regex("\"[1-9][0-9]{0,18}\"").matches(value)) invalid()
        return value
    }
    private fun key(value: Any?): String {
        if (value !is String || !Regex("[A-Za-z0-9_.:-]{1,128}").matches(value)) invalid()
        return value
    }
    private data class Route(val method: String, val path: String, val version: Boolean = false, val query: Boolean = false, val status: Int = 200)
    private val routes = mapOf(
        FinanceOperation.LIST_RECURRING_RULES to Route("GET", "/api/v1/recurring-rules", query = true),
        FinanceOperation.CREATE_RECURRING_RULE to Route("POST", "/api/v1/recurring-rules", status = 201),
        FinanceOperation.GET_RECURRING_RULE to Route("GET", "/api/v1/recurring-rules/{ruleId}"),
        FinanceOperation.CHANGE_RECURRING_RULE to Route("PATCH", "/api/v1/recurring-rules/{ruleId}", version = true),
        FinanceOperation.END_RECURRING_RULE to Route("POST", "/api/v1/recurring-rules/{ruleId}/end", version = true),
        FinanceOperation.GENERATE_OBLIGATIONS to Route("POST", "/api/v1/obligations/generate", status = 201),
        FinanceOperation.LIST_OBLIGATIONS to Route("GET", "/api/v1/obligations", query = true),
        FinanceOperation.FIXED_COST_SUMMARY to Route("GET", "/api/v1/obligations/summary", query = true),
        FinanceOperation.GET_OBLIGATION to Route("GET", "/api/v1/obligations/{obligationId}"),
        FinanceOperation.OBLIGATION_HISTORY to Route("GET", "/api/v1/obligations/{obligationId}/history", query = true),
        FinanceOperation.RESCHEDULE_OBLIGATION to Route("PATCH", "/api/v1/obligations/{obligationId}", version = true),
        FinanceOperation.SKIP_OBLIGATION to Route("POST", "/api/v1/obligations/{obligationId}/skip", version = true),
        FinanceOperation.UNSKIP_OBLIGATION to Route("POST", "/api/v1/obligations/{obligationId}/unskip", version = true),
        FinanceOperation.COMPLETE_OBLIGATION to Route("POST", "/api/v1/obligations/{obligationId}/complete", version = true),
        FinanceOperation.REOPEN_OBLIGATION to Route("POST", "/api/v1/obligations/{obligationId}/reopen", version = true),
        FinanceOperation.SETTLE_OBLIGATION to Route("POST", "/api/v1/obligations/{obligationId}/settlements", version = true, status = 201),
        FinanceOperation.LIST_OBLIGATION_SETTLEMENTS to Route("GET", "/api/v1/obligations/{obligationId}/settlements", query = true),
        FinanceOperation.VOID_FIXED_SETTLEMENT to Route("POST", "/api/v1/settlements/{settlementId}/void", version = true),
    )
    fun supports(operation: FinanceOperation) = operation in routes
    private fun snapshotFields() = mapOf("title" to text(120), "category" to text(40), "amount_mode" to choice("fixed", "variable"),
        "expected_amount_krw" to nullable(money), "economic_type" to economic, "loan_asset_id" to nullable(id), "account_id" to nullable(id), "card_id" to nullable(id),
        "currency_reference" to nullable(currency), "foreign_amount_reference" to nullable(foreign), "note" to nullable(text(2000, true)))
    private fun termsFields() = snapshotFields() + mapOf("anchor_date" to date, "frequency" to choice("monthly", "annual", "days"),
        "interval_count" to { value: Any? -> integer(value, 1, 3650) })
    private val requiredTerms = setOf("title", "category", "amount_mode", "economic_type", "anchor_date", "frequency")
    private fun terms(row: Map<String, Any?>) {
        if (row["loan_asset_id"] != null && row["economic_type"] != "loan" || row["account_id"] != null && row["card_id"] != null ||
            row["amount_mode"] == "fixed" && row["expected_amount_krw"] == null ||
            (row["currency_reference"] == null) != (row["foreign_amount_reference"] == null)) invalid()
    }
    private fun input(operation: FinanceOperation, value: Any?): Map<String, Any?> = when (operation) {
        FinanceOperation.CREATE_RECURRING_RULE -> {
            val row = shape(value, termsFields() + mapOf("effective_from" to date, "effective_until" to nullable(date), "end_reason" to nullable(reason)), requiredTerms + "effective_from")
            terms(row)
            if ((row["effective_until"] == null) != (row["end_reason"] == null) || row["effective_until"] != null && (row["effective_until"] as String) <= (row["effective_from"] as String)) invalid()
            row
        }
        FinanceOperation.CHANGE_RECURRING_RULE -> {
            val row = shape(value, termsFields() + mapOf("effective_from" to date, "reason" to reason), requiredTerms + setOf("effective_from", "reason"))
            terms(row); row
        }
        FinanceOperation.END_RECURRING_RULE -> shape(value, mapOf("effective_on" to date, "reason" to reason))
        FinanceOperation.GENERATE_OBLIGATIONS -> {
            val row = shape(value, mapOf("start_date" to date, "end_date" to date, "rule_id" to nullable(id)), setOf("start_date", "end_date"))
            if (ChronoUnit.DAYS.between(LocalDate.parse(row["start_date"] as String), LocalDate.parse(row["end_date"] as String)) !in 0..365) invalid()
            row
        }
        FinanceOperation.RESCHEDULE_OBLIGATION -> shape(value, mapOf("scheduled_date" to date, "reason" to reason))
        FinanceOperation.SETTLE_OBLIGATION -> {
            val row = shape(value, mapOf("amount_krw" to positiveMoney, "occurred_on" to date, "account_id" to nullable(id), "card_id" to nullable(id),
                "principal_krw" to money, "interest_krw" to nullable(money), "note" to nullable(text(2000, true))), setOf("amount_krw", "occurred_on"))
            if (row["account_id"] != null && row["card_id"] != null) invalid()
            row
        }
        FinanceOperation.SKIP_OBLIGATION, FinanceOperation.UNSKIP_OBLIGATION, FinanceOperation.COMPLETE_OBLIGATION,
        FinanceOperation.REOPEN_OBLIGATION, FinanceOperation.VOID_FIXED_SETTLEMENT -> shape(value, mapOf("reason" to reason))
        else -> invalid()
    }
    private fun query(operation: FinanceOperation, value: Any?): String {
        val monthRequired = operation in setOf(FinanceOperation.LIST_OBLIGATIONS, FinanceOperation.FIXED_COST_SUMMARY)
        if (value == null) { if (monthRequired) invalid(); return "" }
        val fields = if (operation == FinanceOperation.FIXED_COST_SUMMARY) mapOf("month" to month) else
            mapOf("cursor" to nullable(if (operation == FinanceOperation.OBLIGATION_HISTORY) positive else id), "limit" to { item: Any? -> integer(item, 1, 200) }) +
                if (monthRequired) mapOf("month" to month) else emptyMap()
        val row = shape(value, fields, if (monthRequired) setOf("month") else emptySet()).filterValues { it != null }
        return if (row.isEmpty()) "" else "?" + row.toSortedMap().entries.joinToString("&") { "${it.key}=${it.value}" }
    }
    fun prepare(operation: FinanceOperation, value: Any?): FinanceRequest {
        val route = routes[operation] ?: invalid()
        val args = obj(value)
        val variables = Regex("\\{([A-Za-z]+)\\}").findAll(route.path).map { it.groupValues[1] }.toList()
        val write = route.method != "GET"
        val required = variables.toSet() + (if (route.version) setOf("ifMatch") else emptySet()) + (if (write) setOf("input", "idempotencyKey") else emptySet())
        if (!args.keys.containsAll(required) || !(required + if (route.query) setOf("query") else emptySet()).containsAll(args.keys)) invalid()
        var path = route.path
        variables.forEach { name -> path = path.replace("{$name}", FinancePolicy.id(args[name])) }
        if (route.query) path += query(operation, args["query"])
        return FinanceRequest(route.method, path, if (write) input(operation, args["input"]) else null,
            if (route.version) tag(args["ifMatch"]) else null, if (write) key(args["idempotencyKey"]) else null)
    }
    private fun parsedQuery(raw: String, operation: FinanceOperation): Map<String, Any?> {
        if (raw.isEmpty()) invalid()
        val result = mutableMapOf<String, Any?>()
        for (part in raw.split('&')) {
            val pair = part.split('=', limit = 2)
            if (pair.size != 2 || pair[0] in result) invalid()
            result[pair[0]] = if (pair[0] == "limit" || pair[0] == "cursor" && operation == FinanceOperation.OBLIGATION_HISTORY) pair[1].toLongOrNull() ?: invalid() else pair[1]
        }
        return result
    }
    fun httpAllowed(method: String, path: String, body: Any?, ifMatch: String?, idempotencyKey: String?): Boolean {
        try {
            val uri = URI(path)
            if (uri.isAbsolute || uri.rawAuthority != null || uri.rawFragment != null || '%' in path || '\\' in path || path.any { it.isWhitespace() || it.code < 32 }) return false
            for ((operation, route) in routes) {
                if (route.method != method) continue
                val template = route.path.split('/'); val segments = uri.rawPath.split('/')
                if (template.size != segments.size) continue
                val args = mutableMapOf<String, Any?>()
                if (!template.zip(segments).all { (expected, actual) ->
                    if (expected.startsWith('{')) { args[expected.substring(1, expected.length - 1)] = actual; true } else expected == actual
                }) continue
                if ((ifMatch != null) != route.version || (idempotencyKey != null) != (method != "GET")) return false
                if (route.version) args["ifMatch"] = ifMatch
                if (method != "GET") { args["input"] = body; args["idempotencyKey"] = idempotencyKey } else if (body != null) return false
                uri.rawQuery?.let { if (!route.query) invalid(); args["query"] = parsedQuery(it, operation) }
                val expected = prepare(operation, args)
                return expected.path == path && expected.body == body && expected.ifMatch == ifMatch && expected.idempotencyKey == idempotencyKey
            }
            return false
        } catch (_: Exception) { return false }
    }
    private fun reference(value: Any?): Map<String, Any?> = shape(value, mapOf("id" to id, "version" to positive))
    private fun ruleVersion(value: Any?) {
        val row = shape(value, termsFields() + mapOf("id" to id, "effective_from" to date, "effective_until" to nullable(date), "reason" to nullable(reason), "created_at" to timestamp))
        terms(row)
        if (row["effective_until"] != null && (row["effective_until"] as String) <= (row["effective_from"] as String)) invalid()
    }
    fun ruleMetadata(value: Any?): Map<String, Any?> = rule(value)
    private fun rule(value: Any?): Map<String, Any?> {
        // Versions are historical scope, not a 200-row page; 10,000 exceeds the 3 MiB transport capacity.
        val row = shape(value, mapOf("id" to id, "household_id" to id, "version" to positive, "ended_on" to nullable(date),
            "end_reason" to nullable(reason), "versions" to records(::ruleVersion, 10_000, 1)))
        if ((row["ended_on"] == null) != (row["end_reason"] == null)) invalid()
        return row
    }
    private fun obligation(value: Any?): Map<String, Any?> {
        val row = shape(value, snapshotFields() + mapOf("id" to id, "household_id" to id, "rule_id" to id, "rule_version_id" to id, "version" to positive,
            "nominal_date" to date, "scheduled_date" to date, "schedule_state" to choice("active", "superseded"), "manual_override" to bool,
            "skipped" to bool, "manually_completed" to bool, "status" to choice("unpaid", "partial", "paid", "skipped", "superseded"),
            "actual_amount_krw" to money, "difference_krw" to nullable(signedMoney), "consumption_krw" to money, "principal_krw" to money,
            "asset_transfer_krw" to money, "created_at" to timestamp, "updated_at" to timestamp))
        terms(row)
        if ((row["expected_amount_krw"] == null) != (row["difference_krw"] == null)) invalid()
        return row
    }
    private fun history(value: Any?): Map<String, Any?> = shape(value, mapOf("id" to id, "version" to positive, "rule_version_id" to id,
        "expected_amount_krw" to nullable(money), "nominal_date" to date, "scheduled_date" to date, "schedule_state" to choice("active", "superseded"),
        "manual_override" to bool, "skipped" to bool, "manually_completed" to bool, "action" to text(80), "reason" to nullable(reason), "updated_at" to timestamp))
    private fun settlement(value: Any?): Map<String, Any?> {
        val row = shape(value, mapOf("id" to id, "obligation_id" to id, "economic_type" to economic, "principal_krw" to money,
            "consumption_krw" to money, "asset_transfer_krw" to money, "cash" to { CashflowPolicy.fixedPayment(it); Unit }))
        // Check the received decomposition with integer arithmetic; never derive or change it.
        val total = listOf("principal_krw", "consumption_krw", "asset_transfer_krw").fold(BigInteger.ZERO) { sum, name -> sum + BigInteger(row[name] as String) }
        if (total != BigInteger(obj(row["cash"])["amount_krw"] as String)) invalid()
        when (row["economic_type"]) {
            "expense" -> if (row["principal_krw"] != "0" || row["asset_transfer_krw"] != "0") invalid()
            "loan" -> if (row["asset_transfer_krw"] != "0") invalid()
            "asset_transfer" -> if (row["principal_krw"] != "0" || row["consumption_krw"] != "0") invalid()
        }
        return row
    }
    private fun page(value: Any?, item: (Any?) -> Map<String, Any?>, history: Boolean = false): Map<String, Any?> =
        shape(value, mapOf("items" to records({ item(it); Unit }), "next_cursor" to nullable(if (history) positive else id)))
    fun response(operation: FinanceOperation, request: FinanceRequest, status: Int, value: Any?): Map<String, Any?> {
        if (status != routes.getValue(operation).status) invalid()
        val uri = URI(request.path); val target = uri.path.split('/').getOrNull(4)
        return when (operation) {
            FinanceOperation.LIST_RECURRING_RULES -> page(value, ::rule)
            FinanceOperation.GET_RECURRING_RULE -> rule(value).also { if (it["id"] != target) invalid() }
            FinanceOperation.GENERATE_OBLIGATIONS -> shape(value, mapOf("id" to id, "version" to { integer(it, 1, 1) }, "items" to records({ reference(it); Unit }, 2000)))
            FinanceOperation.LIST_OBLIGATIONS -> page(value, ::obligation).also { row ->
                val month = parsedQuery(uri.rawQuery, operation)["month"]
                if ((row["items"] as List<*>).any { (obj(it)["scheduled_date"] as String).take(7) != month }) invalid()
            }
            FinanceOperation.FIXED_COST_SUMMARY -> shape(value, mapOf("expected_known_krw" to money, "unknown_expected_count" to count,
                "actual_amount_krw" to money, "consumption_krw" to money, "principal_krw" to money, "asset_transfer_krw" to money, "obligation_count" to count))
            FinanceOperation.GET_OBLIGATION -> obligation(value).also { if (it["id"] != target) invalid() }
            FinanceOperation.OBLIGATION_HISTORY -> page(value, ::history, true).also { row ->
                if ((row["items"] as List<*>).any { obj(it)["id"] != target }) invalid()
            }
            FinanceOperation.LIST_OBLIGATION_SETTLEMENTS -> page(value, ::settlement).also { row ->
                if ((row["items"] as List<*>).any { obj(it)["obligation_id"] != target }) invalid()
            }
            FinanceOperation.SETTLE_OBLIGATION, FinanceOperation.VOID_FIXED_SETTLEMENT -> settlement(value).also { row ->
                if (operation == FinanceOperation.SETTLE_OBLIGATION) {
                    if (row["obligation_id"] != target || obj(row["cash"])["state"] != "active") invalid()
                } else if (row["id"] != target || obj(row["cash"])["state"] != "void") invalid()
            }
            else -> reference(value).also { if (operation != FinanceOperation.CREATE_RECURRING_RULE && it["id"] != target) invalid() }
        }
    }
}
