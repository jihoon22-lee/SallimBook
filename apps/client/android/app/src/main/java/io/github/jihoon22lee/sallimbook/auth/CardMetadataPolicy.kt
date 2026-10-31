package io.github.jihoon22lee.sallimbook.auth

import java.net.URI
import java.time.LocalDate
import java.time.OffsetDateTime

/** Card metadata only. PAN, expiry, CVC and encrypted envelopes have no route through this policy. */
internal object CardMetadataPolicy {
    private const val BASE = "/api/v1/cards"
    private val operations = setOf(FinanceOperation.LIST_CARDS, FinanceOperation.GET_CARD, FinanceOperation.CREATE_CARD,
        FinanceOperation.UPDATE_CARD, FinanceOperation.ARCHIVE_CARD, FinanceOperation.DELETE_CARD)
    private val fields = setOf("owner_member_id", "issuer_name", "product_name", "alias", "card_type", "last_four",
        "settlement_day", "settlement_account_id", "started_on", "ended_on", "note", "annual_fee_krw", "is_family_card")
    private val required = setOf("owner_member_id", "issuer_name", "product_name", "card_type")
    private fun invalid(): Nothing = throw AuthFailure(AuthCode.INVALID_REQUEST)
    private fun obj(value: Any?): Map<String, Any?> {
        val row = value as? Map<*, *> ?: invalid()
        if (row.size > 30 || row.keys.any { it !is String }) invalid()
        if (NativeResponseShape.tolerant) return NativeResponseShape.identity(row)
        return row.entries.associate { it.key as String to it.value }
    }
    private fun text(value: Any?, maximum: Int, empty: Boolean = false) {
        if (value !is String || value.codePointCount(0, value.length) > maximum || !empty && value.isBlank()) invalid()
    }
    private fun choice(value: Any?, vararg allowed: String) { if (value !is String || value !in allowed) invalid() }
    private fun integer(value: Any?, minimum: Long = 1, maximum: Long = 9_007_199_254_740_991L) {
        val number = when (value) { is Int -> value.toLong(); is Long -> value; else -> invalid() }
        if (number !in minimum..maximum) invalid()
    }
    private fun date(value: Any?) {
        if (value !is String || !Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}").matches(value) || value.startsWith("0000")) invalid()
        try { LocalDate.parse(value) } catch (_: Exception) { invalid() }
    }
    private fun timestamp(value: Any?) {
        if (value !is String || value.length > 40) invalid()
        try { OffsetDateTime.parse(value) } catch (_: Exception) { invalid() }
    }
    private fun tag(value: Any?): String {
        if (value !is String || !Regex("\"[1-9][0-9]{0,18}\"").matches(value)) invalid()
        return value
    }
    fun supports(operation: FinanceOperation) = operation in operations
    private fun input(value: Any?, patch: Boolean): Map<String, Any?> {
        val row = obj(value)
        val allowed = fields + if (patch) PaymentLinksPolicy.closureFields else emptySet()
        if ((row.keys - PaymentLinksPolicy.closureFields).isEmpty() || !allowed.containsAll(row.keys) || !patch && !row.keys.containsAll(required)) invalid()
        for ((key, item) in row) when (key) {
            "owner_member_id" -> FinancePolicy.id(item)
            "issuer_name", "product_name" -> text(item, 120)
            "alias" -> if (item != null) text(item, 80, true)
            "annual_fee_krw" -> if (item != null && (item !is String || !Regex("0|[1-9][0-9]{0,19}").matches(item))) invalid()
            "is_family_card" -> if (item != null && item !is Boolean) invalid()
            "card_type" -> choice(item, "credit", "debit")
            "last_four" -> if (item != null && (item !is String || !Regex("[0-9]{4}").matches(item))) invalid()
            "settlement_day" -> if (item != null) integer(item, 1, 31)
            "settlement_account_id" -> if (item != null) FinancePolicy.id(item)
            "started_on", "ended_on" -> if (item != null) date(item)
            "note" -> if (item != null) text(item, 500, true)
        }
        if (row["started_on"] != null && row["ended_on"] != null && (row["started_on"] as String) > (row["ended_on"] as String)) invalid()
        if (patch) PaymentLinksPolicy.closure(row)
        return row
    }
    private fun query(value: Any?): String {
        if (value == null) return ""
        val row = obj(value)
        if (!setOf("q", "owner_member_id", "card_type", "settlement_account_id", "status", "cursor", "limit").containsAll(row.keys)) invalid()
        for ((key, item) in row) when (key) {
            "q" -> if (item != null) NameSearchQuery.validate(item)
            "owner_member_id", "settlement_account_id", "cursor" -> if (item != null) FinancePolicy.id(item)
            "card_type" -> if (item != null) choice(item, "credit", "debit")
            "status" -> choice(item, "active", "closed", "all")
            "limit" -> integer(item, 1, 200)
        }
        val values = row.filterValues { it != null }
        return if (values.isEmpty()) "" else "?" + values.toSortedMap().entries.joinToString("&") { "${it.key}=${NameSearchQuery.value(it.key, it.value)}" }
    }
    fun prepare(operation: FinanceOperation, value: Any?): FinanceRequest {
        val args = obj(value)
        return when (operation) {
            FinanceOperation.LIST_CARDS -> {
                if (!setOf("query").containsAll(args.keys)) invalid()
                FinanceRequest("GET", BASE + query(args["query"]), null, null)
            }
            FinanceOperation.GET_CARD -> {
                if (args.keys != setOf("cardId")) invalid()
                FinanceRequest("GET", "$BASE/${FinancePolicy.id(args["cardId"])}", null, null)
            }
            FinanceOperation.CREATE_CARD -> {
                if (args.keys != setOf("input")) invalid()
                FinanceRequest("POST", BASE, input(args["input"], false), null)
            }
            FinanceOperation.UPDATE_CARD -> {
                if (args.keys != setOf("cardId", "input", "ifMatch")) invalid()
                FinanceRequest("PATCH", "$BASE/${FinancePolicy.id(args["cardId"])}", input(args["input"], true), tag(args["ifMatch"]))
            }
            FinanceOperation.ARCHIVE_CARD -> {
                if (args.keys != setOf("cardId", "input", "ifMatch")) invalid()
                val body = obj(args["input"])
                if ("ended_on" !in body || !(setOf("ended_on") + PaymentLinksPolicy.closureFields).containsAll(body.keys)) invalid()
                date(body["ended_on"])
                PaymentLinksPolicy.closure(body)
                FinanceRequest("POST", "$BASE/${FinancePolicy.id(args["cardId"])}/archive", body, tag(args["ifMatch"]))
            }
            FinanceOperation.DELETE_CARD -> {
                if (args.keys != setOf("cardId", "ifMatch")) invalid()
                FinanceRequest("DELETE", "$BASE/${FinancePolicy.id(args["cardId"])}", null, tag(args["ifMatch"]))
            }
            else -> invalid()
        }
    }
    fun httpAllowed(method: String, path: String, body: Any?, ifMatch: String?): Boolean {
        try {
            val uri = URI(path)
            if (uri.isAbsolute || uri.rawAuthority != null || uri.rawFragment != null || '%' in uri.rawPath || '\\' in path || path.any { it.isWhitespace() || it.code < 32 }) return false
            val segments = uri.rawPath.split('/')
            val args = mutableMapOf<String, Any?>()
            val operation = when {
                uri.rawPath == BASE && method == "GET" && body == null && ifMatch == null -> {
                    val values = mutableMapOf<String, Any?>()
                    uri.rawQuery?.let { raw ->
                        if (raw.isEmpty()) invalid()
                        for (part in raw.split('&')) {
                            val pair = part.split('=', limit = 2)
                            if (pair.size != 2 || pair[0] in values) invalid()
                            values[pair[0]] = if (pair[0] == "limit") pair[1].toLongOrNull() ?: invalid() else if (pair[0] == "q") NameSearchQuery.decode(pair[1]) else pair[1]
                        }
                    }
                    args["query"] = values
                    FinanceOperation.LIST_CARDS
                }
                uri.rawPath == BASE && method == "POST" && uri.rawQuery == null && ifMatch == null -> {
                    args["input"] = body
                    FinanceOperation.CREATE_CARD
                }
                uri.rawPath.startsWith("$BASE/") && segments.size in 5..6 && uri.rawQuery == null -> {
                    args["cardId"] = FinancePolicy.id(segments[4])
                    when {
                        segments.size == 5 && method == "GET" && body == null && ifMatch == null -> FinanceOperation.GET_CARD
                        segments.size == 5 && method == "PATCH" -> {
                            args["input"] = body; args["ifMatch"] = ifMatch; FinanceOperation.UPDATE_CARD
                        }
                        segments.size == 5 && method == "DELETE" && body == null -> {
                            args["ifMatch"] = ifMatch; FinanceOperation.DELETE_CARD
                        }
                        segments.size == 6 && segments[5] == "archive" && method == "POST" -> {
                            args["input"] = body; args["ifMatch"] = ifMatch; FinanceOperation.ARCHIVE_CARD
                        }
                        else -> invalid()
                    }
                }
                else -> invalid()
            }
            val request = prepare(operation, args)
            return request.path == path && request.body == body && request.ifMatch == ifMatch
        } catch (_: Exception) { return false }
    }
    private fun card(value: Any?): Map<String, Any?> {
        val row = obj(value)
        val extra = setOf("id", "household_id", "masked_number", "has_secret", "settlement_account_status", "status", "created_by_member_id", "updated_by_member_id", "created_at", "updated_at", "version")
        NativeResponseShape.accept(row, row.keys, fields + extra, (fields + extra) - setOf("annual_fee_krw", "is_family_card"), ::invalid)
        input(row.filterKeys { it in fields }, false)
        for (key in listOf("id", "household_id", "created_by_member_id", "updated_by_member_id")) FinancePolicy.id(row[key])
        timestamp(row["created_at"]); timestamp(row["updated_at"]); integer(row["version"])
        if (row["masked_number"] != row["last_four"]?.let { "**** $it" }) invalid()
        if (row["has_secret"] !is Boolean || row["has_secret"] == true && row["last_four"] == null) invalid()
        choice(row["status"], "active", "closed")
        if ((row["status"] == "closed") != (row["ended_on"] != null)) invalid()
        if (row["settlement_account_id"] == null) {
            if (row["settlement_account_status"] != null) invalid()
        } else choice(row["settlement_account_status"], "active", "closed")
        return row
    }
    fun response(operation: FinanceOperation, request: FinanceRequest, status: Int, value: Any?): Any? {
        if (operation == FinanceOperation.DELETE_CARD) {
            if (status != 204 || value != null) invalid()
            return null
        }
        if (status != if (operation == FinanceOperation.CREATE_CARD) 201 else 200) invalid()
        if (operation == FinanceOperation.LIST_CARDS) {
            val row = obj(value)
            NativeResponseShape.accept(row, row.keys, setOf("items", "next_cursor"), setOf("items", "next_cursor"), ::invalid)
            val items = row["items"] as? List<*> ?: invalid()
            if (items.size > 200) invalid()
            items.forEach(::card)
            row["next_cursor"]?.let { FinancePolicy.id(it) }
            return row
        }
        val row = card(value)
        if (operation != FinanceOperation.CREATE_CARD && row["id"] != URI(request.path).path.split('/')[4]) invalid()
        return row
    }
}
