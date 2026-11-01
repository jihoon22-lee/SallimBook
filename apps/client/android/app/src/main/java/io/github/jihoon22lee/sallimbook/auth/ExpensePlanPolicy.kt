package io.github.jihoon22lee.sallimbook.auth

import java.math.BigInteger
import java.net.URI
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.YearMonth
import java.time.temporal.ChronoUnit

private typealias PlanField = (Any?) -> Unit

/** Expense planning metadata only. Tokens stay native; dates may be unknown. */
internal object ExpensePlanPolicy {
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
    private fun text(maximum: Int, empty: Boolean = false): PlanField = {
        if (it !is String || it.codePointCount(0, it.length) > maximum || !empty && it.isBlank()) invalid()
    }
    private val id: PlanField = { FinancePolicy.id(it); Unit }
    private val positive: PlanField = { integer(it) }
    private val count: PlanField = { integer(it, 0) }
    private val bool: PlanField = { if (it !is Boolean) invalid() }
    private val money: PlanField = { if (it !is String || !Regex("0|[1-9][0-9]{0,19}").matches(it)) invalid() }
    private val signedMoney: PlanField = { if (it !is String || !Regex("0|-?[1-9][0-9]{0,19}").matches(it)) invalid() }
    private val positiveMoney: PlanField = { money(it); if (it == "0") invalid() }
    private val date: PlanField = {
        if (it !is String || !Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}").matches(it) || it.startsWith("0000")) invalid()
        try { LocalDate.parse(it) } catch (_: Exception) { invalid() }
    }
    private val month: PlanField = {
        if (it !is String || !Regex("[0-9]{4}-(0[1-9]|1[0-2])").matches(it) || it.startsWith("0000")) invalid()
        try { YearMonth.parse(it) } catch (_: Exception) { invalid() }
    }
    private val timestamp: PlanField = {
        if (it !is String || it.length > 40) invalid()
        try { OffsetDateTime.parse(it) } catch (_: Exception) { invalid() }
    }
    private val foreign: PlanField = { if (it !is String || it.length > 40 || !Regex("(0|[1-9][0-9]*)(\\.[0-9]{1,8})?").matches(it)) invalid() }
    private val currency: PlanField = { if (it !is String || !Regex("[A-Z]{3}").matches(it)) invalid() }
    private val economic = choice("expense", "loan", "asset_transfer")
    private val reason = text(500)
    private fun choice(vararg values: String): PlanField = { if (it !is String || it !in values) invalid() }
    private fun nullable(rule: PlanField): PlanField = { if (it != null) rule(it) }
    private fun shape(value: Any?, fields: Map<String, PlanField>, required: Set<String> = fields.keys): Map<String, Any?> {
        val row = obj(value)
        NativeResponseShape.accept(row, row.keys, fields.keys, required, ::invalid)
        row.forEach { (name, item) -> fields[name]?.invoke(item) }
        return row
    }
    private fun records(rule: PlanField, maximum: Int = 200, minimum: Int = 0): PlanField = {
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
        FinanceOperation.LIST_EXPENSE_PLANS to Route("GET", "/api/v1/expense-plans", query = true),
        FinanceOperation.GET_EXPENSE_PLAN to Route("GET", "/api/v1/expense-plans/{planId}"),
        FinanceOperation.CREATE_EXPENSE_PLAN to Route("POST", "/api/v1/expense-plans", status = 201),
        FinanceOperation.CHANGE_EXPENSE_PLAN to Route("PATCH", "/api/v1/expense-plans/{planId}", version = true),
        FinanceOperation.END_EXPENSE_PLAN to Route("POST", "/api/v1/expense-plans/{planId}/end", version = true),
        FinanceOperation.DELETE_EXPENSE_PLAN to Route("DELETE", "/api/v1/expense-plans/{planId}", version = true, status = 204),
        FinanceOperation.EXPENSE_PLAN_SUMMARY to Route("GET", "/api/v1/expense-plan-summary", query = true),
        FinanceOperation.PREVIEW_EXPENSE_PLAN_PAYMENT_SWITCH to Route("POST", "/api/v1/expense-plan-payment-switch/preview", query = true),
        FinanceOperation.APPLY_EXPENSE_PLAN_PAYMENT_SWITCH to Route("POST", "/api/v1/expense-plan-payment-switch/{planId}", version = true)
    )
    fun supports(operation: FinanceOperation) = operation in routes
    private fun snapshotFields() = mapOf("title" to text(120), "category" to text(40), "amount_mode" to choice("fixed", "variable"),
        "expected_amount_krw" to nullable(money), "economic_type" to economic, "loan_asset_id" to nullable(id), "account_id" to nullable(id), "card_id" to nullable(id),
        "currency_reference" to nullable(currency), "foreign_amount_reference" to nullable(foreign), "note" to nullable(text(2000, true)))
    private fun termsFields() = snapshotFields() + mapOf(
        "tracking_mode" to choice("plan_only", "scheduled"), "plan_kind" to choice("recurring", "budget"),
        "budget_treatment" to choice("included", "external_support", "payroll", "reference_only"),
        "subject_member_id" to nullable(id), "annual_month" to nullable { integer(it,1,12) }) + mapOf("anchor_date" to nullable(date), "frequency" to choice("monthly", "annual", "days"),
        "interval_count" to { value: Any? -> integer(value, 1, 3650) })
    private val requiredTerms = setOf("title", "category", "amount_mode", "economic_type", "frequency")
    private fun terms(row: Map<String, Any?>) {
        if (row["tracking_mode"] == "scheduled" && row["anchor_date"] == null) invalid()
        if (row["annual_month"] != null && row["frequency"] != "annual") invalid()
        if (row["annual_month"] != null && row["anchor_date"] != null &&
            (row["annual_month"] as Number).toInt() != LocalDate.parse(row["anchor_date"] as String).monthValue) invalid()
        if (row["plan_kind"] == "budget" && (row["tracking_mode"] == "scheduled" || row["frequency"] != "monthly" ||
                row["interval_count"] != null && (row["interval_count"] as Number).toInt() != 1)) invalid()
        if (row["loan_asset_id"] != null && row["economic_type"] != "loan" || row["account_id"] != null && row["card_id"] != null ||
            row["amount_mode"] == "fixed" && row["expected_amount_krw"] == null ||
            (row["currency_reference"] == null) != (row["foreign_amount_reference"] == null)) invalid()
    }
    private val digest: PlanField = { if (it !is String || !Regex("[0-9a-f]{64}").matches(it)) invalid() }
    private fun switchInput(value: Any?, apply: Boolean): Map<String, Any?> {
        val fields = mapOf("source_kind" to choice("account", "card"), "source_id" to id,
            "target_kind" to choice("account", "card"), "target_id" to id, "effective_on" to date) +
            if (apply) mapOf("preview_digest" to digest, "reason" to reason) else emptyMap()
        val row = shape(value, fields)
        if (row["source_kind"] == row["target_kind"] && row["source_id"] == row["target_id"]) invalid()
        return row
    }
    private fun switchRow(value: Any?): Map<String, Any?> = shape(value, mapOf("id" to id, "version" to positive,
        "title" to text(120), "periods" to records(::ruleVersion, 10_000, 1), "unchanged_period_count" to count,
        "update_occurrence_count" to count, "preserved_past_count" to count, "preserved_paid_count" to count,
        "preserved_manual_count" to count, "blocked_reason" to nullable(choice("INITIAL_PERIOD_START")), "preview_digest" to digest))
    private fun input(operation: FinanceOperation, value: Any?): Map<String, Any?> = when(operation) {
        FinanceOperation.CREATE_EXPENSE_PLAN, FinanceOperation.CHANGE_EXPENSE_PLAN -> {
            val fields = termsFields() + mapOf("effective_from" to nullable(date)) +
                if (operation == FinanceOperation.CHANGE_EXPENSE_PLAN) mapOf("reason" to reason) else emptyMap()
            val row = shape(value, fields, requiredTerms)
            terms(row); row
        }
        FinanceOperation.END_EXPENSE_PLAN -> shape(value, mapOf("effective_on" to date, "reason" to reason))
        FinanceOperation.PREVIEW_EXPENSE_PLAN_PAYMENT_SWITCH -> switchInput(value, false)
        FinanceOperation.APPLY_EXPENSE_PLAN_PAYMENT_SWITCH -> switchInput(value, true)
        else -> invalid()
    }
    private fun query(operation: FinanceOperation, value: Any?): String {
        if (value == null) return ""
        val fields = if (operation == FinanceOperation.EXPENSE_PLAN_SUMMARY) mapOf("as_of" to nullable(date)) else
            mapOf("cursor" to nullable(id), "limit" to { item: Any? -> integer(item,1,200) }) +
            if(operation == FinanceOperation.LIST_EXPENSE_PLANS) mapOf("q" to nullable(NameSearchQuery::validate), "account_id" to nullable(id), "card_id" to nullable(id)) else emptyMap()
        val row = shape(value, fields, emptySet()).filterValues { it != null }
        return if(row.isEmpty()) "" else "?" + row.toSortedMap().entries.joinToString("&") { "${it.key}=${NameSearchQuery.value(it.key,it.value)}" }
    }
    fun prepare(operation: FinanceOperation, value: Any?): FinanceRequest {
        val route = routes[operation] ?: invalid()
        val args = obj(value)
        val variables = Regex("\\{([A-Za-z]+)\\}").findAll(route.path).map { it.groupValues[1] }.toList()
        val write = route.method != "GET"
        val idem = write && operation != FinanceOperation.PREVIEW_EXPENSE_PLAN_PAYMENT_SWITCH
        // A delete is a write without a body: it still carries its version and key.
        val body = write && route.method != "DELETE"
        val required = variables.toSet() + (if (route.version) setOf("ifMatch") else emptySet()) +
            (if (idem) setOf("idempotencyKey") else emptySet()) + (if (body) setOf("input") else emptySet())
        if (!args.keys.containsAll(required) || !(required + if (route.query) setOf("query") else emptySet()).containsAll(args.keys)) invalid()
        var path = route.path
        variables.forEach { name -> path = path.replace("{$name}", FinancePolicy.id(args[name])) }
        if (route.query) path += query(operation, args["query"])
        return FinanceRequest(route.method, path, if (body) input(operation, args["input"]) else null,
            if (route.version) tag(args["ifMatch"]) else null, if (idem) key(args["idempotencyKey"]) else null)
    }
    private fun parsedQuery(raw: String, operation: FinanceOperation): Map<String, Any?> {
        if (raw.isEmpty()) invalid()
        val result = mutableMapOf<String, Any?>()
        for (part in raw.split('&')) {
            val pair = part.split('=', limit = 2)
            if (pair.size != 2 || pair[0] in result) invalid()
            result[pair[0]] = if (pair[0] == "limit") pair[1].toLongOrNull() ?: invalid() else if (pair[0] == "q") NameSearchQuery.decode(pair[1]) else pair[1]
        }
        return result
    }
    fun httpAllowed(method: String, path: String, body: Any?, ifMatch: String?, idempotencyKey: String?): Boolean {
        try {
            val uri = URI(path)
            if (uri.isAbsolute || uri.rawAuthority != null || uri.rawFragment != null || '%' in uri.rawPath || '\\' in path || path.any { it.isWhitespace() || it.code < 32 }) return false
            for ((operation, route) in routes) {
                if (route.method != method) continue
                val template = route.path.split('/'); val segments = uri.rawPath.split('/')
                if (template.size != segments.size) continue
                val args = mutableMapOf<String, Any?>()
                if (!template.zip(segments).all { (expected, actual) ->
                    if (expected.startsWith('{')) { args[expected.substring(1, expected.length - 1)] = actual; true } else expected == actual
                }) continue
                if ((ifMatch != null) != route.version || (idempotencyKey != null) != (method != "GET" && operation != FinanceOperation.PREVIEW_EXPENSE_PLAN_PAYMENT_SWITCH)) return false
                if (route.version) args["ifMatch"] = ifMatch
                if (method == "GET" || method == "DELETE") { if (body != null) return false } else args["input"] = body
                if (method != "GET" && operation != FinanceOperation.PREVIEW_EXPENSE_PLAN_PAYMENT_SWITCH) args["idempotencyKey"] = idempotencyKey
                uri.rawQuery?.let { if (!route.query) invalid(); args["query"] = parsedQuery(it, operation) }
                val expected = prepare(operation, args)
                return expected.path == path && expected.body == body && expected.ifMatch == ifMatch && expected.idempotencyKey == idempotencyKey
            }
            return false
        } catch (_: Exception) { return false }
    }
    private fun reference(value: Any?) = shape(value, mapOf("id" to id,"version" to positive))
    private fun ruleVersion(value: Any?) {
        val row = shape(value, termsFields() + mapOf("id" to id, "effective_from" to date, "effective_until" to nullable(date),
            "reason" to nullable(reason), "created_at" to timestamp, "revoked_at" to nullable(timestamp), "monthly_equivalent_krw" to nullable(money)))
        terms(row)
        if(row["effective_until"] != null && (row["effective_until"] as String) <= (row["effective_from"] as String)) invalid()
    }
    private fun rule(value: Any?): Map<String,Any?> = shape(value,mapOf("id" to id,"household_id" to id,"version" to positive,
        "ended_on" to nullable(date),"end_reason" to nullable(reason),"versions" to records(::ruleVersion,10000),"history" to records(::ruleVersion,10000,1)))
    private fun page(value: Any?, item: (Any?) -> Map<String,Any?>) = shape(value,mapOf("items" to records({ item(it); Unit }),"next_cursor" to nullable(id)))
    private fun subtotal(value: Any?) { shape(value,mapOf("key" to text(40),"known_krw" to money,"unknown_count" to count,"unconverted_count" to count,"count" to count)) }
    private fun summary(value: Any?): Map<String,Any?> = shape(value,mapOf("as_of" to date,"fixed_known_krw" to money,"budget_known_krw" to money,
        "combined_known_krw" to money,"excluded_known_krw" to money,"included_unknown_count" to count,"excluded_unknown_count" to count,
        "unconverted_count" to count,"plan_count" to count,"categories" to records(::subtotal,10000),"treatments" to records(::subtotal),"economic_types" to records(::subtotal)))
    fun response(operation: FinanceOperation, request: FinanceRequest, status: Int, value: Any?): Map<String,Any?>? {
        if(status != routes.getValue(operation).status) invalid()
        if(operation == FinanceOperation.DELETE_EXPENSE_PLAN) { if(value != null) invalid(); return null }
        val target = URI(request.path).path.split('/').getOrNull(4)
        return when(operation) {
            FinanceOperation.LIST_EXPENSE_PLANS -> page(value,::rule)
            FinanceOperation.GET_EXPENSE_PLAN -> rule(value).also { if(it["id"] != target) invalid() }
            FinanceOperation.EXPENSE_PLAN_SUMMARY -> summary(value)
            FinanceOperation.PREVIEW_EXPENSE_PLAN_PAYMENT_SWITCH -> page(value,::switchRow)
            else -> reference(value).also { if(operation != FinanceOperation.CREATE_EXPENSE_PLAN && it["id"] != target) invalid() }
        }
    }
}
