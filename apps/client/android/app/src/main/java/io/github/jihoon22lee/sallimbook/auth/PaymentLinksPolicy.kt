package io.github.jihoon22lee.sallimbook.auth

import java.net.URI
import java.time.LocalDate

/** Registered payment usage only. A digest detects stale confirmation; it grants no access. */
internal object PaymentLinksPolicy {
    val closureFields = setOf("closure_ack", "usage_digest")
    private fun invalid(): Nothing = throw AuthFailure(AuthCode.INVALID_REQUEST)
    private fun obj(value: Any?, fields: Set<String>? = null): Map<String, Any?> {
        val row = value as? Map<*, *> ?: invalid()
        if (row.size > 24 || row.keys.any { it !is String }) invalid()
        val result = if (NativeResponseShape.tolerant) NativeResponseShape.identity(row) else row.entries.associate { it.key as String to it.value }
        if (fields != null) NativeResponseShape.accept(result, result.keys, fields, fields, ::invalid)
        return result
    }
    private fun digest(value: Any?) { if (value !is String || !Regex("[0-9a-f]{64}").matches(value)) invalid() }
    private fun date(value: Any?) {
        if (value !is String || !Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}").matches(value) || value.startsWith("0000")) invalid()
        try { LocalDate.parse(value) } catch (_: Exception) { invalid() }
    }
    private fun bool(value: Any?) { if (value !is Boolean) invalid() }
    private fun number(value: Any?, minimum: Long = 1, maximum: Long = 9_007_199_254_740_991L): Long {
        val result = when (value) { is Int -> value.toLong(); is Long -> value; else -> invalid() }
        if (result !in minimum..maximum) invalid()
        return result
    }
    private fun text(value: Any?, maximum: Int, empty: Boolean = false) {
        if (value !is String || value.codePointCount(0, value.length) > maximum || !empty && value.isBlank()) invalid()
    }
    private fun choice(value: Any?, vararg values: String) { if (value !is String || value !in values) invalid() }
    private fun money(value: Any?) { if (value !is String || !Regex("0|[1-9][0-9]{0,19}").matches(value)) invalid() }

    fun closure(row: Map<String, Any?>) {
        if ("closure_ack" in row) bool(row["closure_ack"])
        row["usage_digest"]?.let(::digest)
        if (row["closure_ack"] == true) {
            if (row["usage_digest"] == null || row["ended_on"] == null) invalid()
        } else if (row["usage_digest"] != null) invalid()
    }
    fun supports(operation: FinanceOperation) = operation in setOf(FinanceOperation.GET_CARD_PAYMENT_LINKS, FinanceOperation.GET_ACCOUNT_PAYMENT_LINKS)
    private fun query(value: Any?): Map<String, Any?> {
        if (value == null) return emptyMap()
        val row = obj(value).toMutableMap()
        if (!setOf("as_of_date", "rule_cursor", "obligation_cursor", "card_cursor", "limit").containsAll(row.keys)) invalid()
        row["as_of_date"]?.let(::date)
        for (name in listOf("rule_cursor", "obligation_cursor", "card_cursor")) row[name]?.let { row[name] = FinancePolicy.id(it).lowercase() }
        if ("limit" in row) number(row["limit"], 1, 200)
        return row.filterValues { it != null }
    }
    fun prepare(operation: FinanceOperation, value: Any?): FinanceRequest {
        if (!supports(operation)) invalid()
        val args = obj(value)
        if ("resourceId" !in args || !setOf("resourceId", "query").containsAll(args.keys)) invalid()
        val base = if (operation == FinanceOperation.GET_CARD_PAYMENT_LINKS) "cards" else "accounts"
        val q = query(args["query"])
        val suffix = if (q.isEmpty()) "" else "?" + q.toSortedMap().entries.joinToString("&") { "${it.key}=${it.value}" }
        return FinanceRequest("GET", "/api/v1/$base/${FinancePolicy.id(args["resourceId"]).lowercase()}/payment-links$suffix", null, null)
    }
    private fun parsed(uri: URI): Map<String, Any?> {
        val result = mutableMapOf<String, Any?>()
        uri.rawQuery?.let { raw ->
            if (raw.isEmpty()) invalid()
            for (part in raw.split('&')) {
                val pair = part.split('=', limit = 2)
                if (pair.size != 2 || pair[0] in result) invalid()
                result[pair[0]] = if (pair[0] == "limit") pair[1].toLongOrNull() ?: invalid() else pair[1]
            }
        }
        return query(result)
    }
    fun httpAllowed(method: String, path: String, body: Any?, ifMatch: String?): Boolean {
        try {
            if (method != "GET" || body != null || ifMatch != null) return false
            val uri = URI(path)
            if (uri.isAbsolute || uri.rawAuthority != null || uri.rawFragment != null || '%' in path || '\\' in path || path.any { it.isWhitespace() || it.code < 32 }) return false
            val parts = uri.rawPath.split('/')
            if (parts.size != 6 || parts.take(3) != listOf("", "api", "v1") || parts[5] != "payment-links") return false
            val operation = when (parts[3]) { "cards" -> FinanceOperation.GET_CARD_PAYMENT_LINKS; "accounts" -> FinanceOperation.GET_ACCOUNT_PAYMENT_LINKS; else -> return false }
            return prepare(operation, mapOf("resourceId" to parts[4], "query" to parsed(uri))).path == path
        } catch (_: Exception) { return false }
    }
    private fun method(row: Map<String, Any?>, kind: String, resourceId: String) {
        row["account_id"]?.let { FinancePolicy.id(it) }; row["card_id"]?.let { FinancePolicy.id(it) }
        if ((row["account_id"] == null) == (row["card_id"] == null)) invalid()
        if (row["payment_basis"] != if (row["card_id"] == null) "account_payment_plan" else "card_approval_plan") invalid()
        if (kind == "card" && row["card_id"] != resourceId || kind == "account" && row["account_id"] != null && row["account_id"] != resourceId) invalid()
        // For an account, card-linked rules may refer to a card on another result page.
    }
    private fun rule(value: Any?, kind: String, resourceId: String, asOf: String): Map<String, Any?> {
        val row = obj(value, setOf("id", "rule_id", "rule_version", "title", "category", "amount_mode", "expected_amount_krw", "economic_type",
            "account_id", "card_id", "payment_basis", "period", "effective_from", "effective_until", "anchor_date", "frequency", "interval_count"))
        FinancePolicy.id(row["id"]); FinancePolicy.id(row["rule_id"]); number(row["rule_version"])
        text(row["title"], 120); text(row["category"], 40); choice(row["amount_mode"], "fixed", "variable")
        row["expected_amount_krw"]?.let(::money)
        if (row["amount_mode"] == "fixed" && row["expected_amount_krw"] == null) invalid()
        choice(row["economic_type"], "expense", "loan", "asset_transfer")
        method(row, kind, resourceId)
        date(row["effective_from"]); row["effective_until"]?.let(::date); date(row["anchor_date"])
        choice(row["frequency"], "monthly", "annual", "days"); number(row["interval_count"], 1, 3650)
        if (row["period"] != if ((row["effective_from"] as String) > asOf) "future" else "current") invalid()
        if (row["effective_until"] != null && ((row["effective_until"] as String) <= asOf || (row["effective_until"] as String) <= (row["effective_from"] as String))) invalid()
        return row
    }
    private fun obligation(value: Any?, kind: String, resourceId: String): Map<String, Any?> {
        val row = obj(value, setOf("id", "version", "rule_id", "rule_version_id", "title", "category", "scheduled_date", "expected_amount_krw", "actual_paid_krw",
            "status", "account_id", "card_id", "payment_basis"))
        for (name in listOf("id", "rule_id", "rule_version_id")) FinancePolicy.id(row[name])
        number(row["version"]); text(row["title"], 120); text(row["category"], 40); date(row["scheduled_date"])
        row["expected_amount_krw"]?.let(::money); money(row["actual_paid_krw"])
        if (row["status"] != if (row["actual_paid_krw"] == "0") "unpaid" else "partial") invalid()
        method(row, kind, resourceId)
        return row
    }
    private fun card(value: Any?, asOf: String): Map<String, Any?> {
        val row = obj(value, setOf("id", "version", "issuer_name", "product_name", "alias", "last_four", "ended_on", "active_for_closure"))
        FinancePolicy.id(row["id"]); number(row["version"]); text(row["issuer_name"], 120); text(row["product_name"], 120)
        row["alias"]?.let { text(it, 80, true) }
        row["last_four"]?.let { if (it !is String || !Regex("[0-9]{4}").matches(it)) invalid() }
        row["ended_on"]?.let(::date); bool(row["active_for_closure"])
        if (row["active_for_closure"] != (row["ended_on"] == null || (row["ended_on"] as String) >= asOf)) invalid()
        return row
    }
    private fun page(value: Any?, cursor: Any?, limit: Int, item: (Any?) -> Map<String, Any?>): Map<String, Any?> {
        val row = obj(value, setOf("items", "total_count", "next_cursor"))
        val items = row["items"] as? List<*> ?: invalid()
        val count = number(row["total_count"], 0)
        if (items.size > limit || items.size > count) invalid()
        val ids = items.map { item(it)["id"] as String }
        if (ids.distinct().size != ids.size || cursor != null && cursor in ids) invalid()
        row["next_cursor"]?.let {
            FinancePolicy.id(it)
            if (ids.isEmpty() || it != ids.last()) invalid()
        }
        return row
    }
    fun response(operation: FinanceOperation, request: FinanceRequest, status: Int, value: Any?): Map<String, Any?> {
        if (status != 200) invalid()
        val row = obj(value, setOf("resource_kind", "resource_id", "resource_version", "asset_id", "as_of_date", "usage_digest", "requires_confirmation",
            "coverage", "account_withdrawal_total_available", "rules", "obligations", "cards"))
        val kind = if (operation == FinanceOperation.GET_CARD_PAYMENT_LINKS) "card" else "account"
        val uri = URI(request.path); val resourceId = uri.path.split('/')[4]; val q = parsed(uri)
        if (row["resource_kind"] != kind || row["resource_id"] != resourceId) invalid()
        FinancePolicy.id(row["resource_id"]); number(row["resource_version"])
        if (kind == "account") FinancePolicy.id(row["asset_id"]) else if (row["asset_id"] != null) invalid()
        date(row["as_of_date"])
        if (q["as_of_date"] != null && row["as_of_date"] != q["as_of_date"]) invalid()
        digest(row["usage_digest"]); bool(row["requires_confirmation"])
        if (row["coverage"] != "registered_recurring_only" || row["account_withdrawal_total_available"] != false) invalid()
        val limit = q["limit"]?.let { number(it, 1, 200).toInt() } ?: 50
        val asOf = row["as_of_date"] as String
        page(row["rules"], q["rule_cursor"], limit) { rule(it, kind, resourceId, asOf) }
        page(row["obligations"], q["obligation_cursor"], limit) { obligation(it, kind, resourceId) }
        val cards = page(row["cards"], q["card_cursor"], limit) { card(it, asOf) }
        if (kind == "card" && ((cards["items"] as List<*>).isNotEmpty() || number(cards["total_count"], 0) != 0L || cards["next_cursor"] != null)) invalid()
        return row
    }
}
