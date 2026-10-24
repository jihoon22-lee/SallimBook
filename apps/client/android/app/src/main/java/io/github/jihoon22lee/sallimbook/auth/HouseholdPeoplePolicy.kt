package io.github.jihoon22lee.sallimbook.auth

import java.net.URI
import java.time.OffsetDateTime

/** Metadata projection only. A family person never becomes an authenticated member. */
internal object HouseholdPeoplePolicy {
    private const val base = "/api/v1/household/people"
    private val operations = setOf(FinanceOperation.LIST_HOUSEHOLD_PEOPLE, FinanceOperation.CREATE_HOUSEHOLD_PERSON, FinanceOperation.UPDATE_HOUSEHOLD_PERSON)
    private val fields = setOf("id", "household_id", "member_id", "display_name", "relation", "active", "archived_at", "version", "created_at", "updated_at", "created_by_member_id", "updated_by_member_id")
    private fun invalid(): Nothing = throw AuthFailure(AuthCode.INVALID_REQUEST)
    private fun obj(value: Any?): Map<String, Any?> {
        val row = value as? Map<*, *> ?: invalid()
        if (row.size > 16 || row.keys.any { it !is String }) invalid()
        return row.entries.associate { it.key as String to it.value }
    }
    private fun text(value: Any?) {
        if (value !is String || value.isBlank() || value.codePointCount(0, value.length) > 120) invalid()
    }
    private fun positive(value: Any?): Long {
        val number = when (value) { is Int -> value.toLong(); is Long -> value; else -> invalid() }
        if (number !in 1..9_007_199_254_740_991L) invalid()
        return number
    }
    private fun stamp(value: Any?) {
        if (value !is String || value.length > 40) invalid()
        try { OffsetDateTime.parse(value) } catch (_: Exception) { invalid() }
    }
    fun supports(operation: FinanceOperation) = operation in operations
    fun prepare(operation: FinanceOperation, value: Any?): FinanceRequest {
        val args = obj(value)
        return when(operation) {
            FinanceOperation.LIST_HOUSEHOLD_PEOPLE -> {
                if (args.keys.any { it != "query" }) invalid()
                val query = args["query"]?.let(::obj) ?: emptyMap()
                if (query.keys.any { it !in setOf("cursor", "limit") }) invalid()
                query["cursor"]?.let { FinancePolicy.id(it) }
                query["limit"]?.let { if (positive(it) > 200) invalid() }
                val pairs = query.filterValues { it != null }.toSortedMap()
                FinanceRequest("GET", base + if (pairs.isEmpty()) "" else "?" + pairs.entries.joinToString("&") { "${it.key}=${it.value}" }, null, null)
            }
            FinanceOperation.CREATE_HOUSEHOLD_PERSON, FinanceOperation.UPDATE_HOUSEHOLD_PERSON -> {
                val create = operation == FinanceOperation.CREATE_HOUSEHOLD_PERSON
                if (args.keys != if(create) setOf("input", "idempotencyKey") else setOf("personId", "input", "ifMatch")) invalid()
                val input = obj(args["input"])
                val allowed = setOf("display_name", "relation") + if(create) emptySet() else setOf("active")
                if (input.isEmpty() || !allowed.containsAll(input.keys) || create && input.keys != allowed) invalid()
                input.forEach { (key, item) -> when(key) {
                    "display_name" -> text(item)
                    "relation" -> if (item !in setOf("child", "parent", "other")) invalid()
                    "active" -> if (item !is Boolean) invalid()
                } }
                if(create) {
                    val key = args["idempotencyKey"] as? String ?: invalid()
                    if(!Regex("[A-Za-z0-9_.:-]{1,128}").matches(key)) invalid()
                    FinanceRequest("POST", base, input, null, key)
                } else {
                    val tag = args["ifMatch"] as? String ?: invalid()
                    if(!Regex("\"[1-9][0-9]{0,15}\"").matches(tag)) invalid()
                    positive(tag.removeSurrounding("\"").toLongOrNull())
                    FinanceRequest("PATCH", "$base/${FinancePolicy.id(args["personId"])}", input, tag)
                }
            }
            else -> invalid()
        }
    }
    fun httpAllowed(method: String, path: String, body: Any?, ifMatch: String?, key: String?): Boolean = try {
        val request = when {
            method == "GET" && (path == base || path.startsWith("$base?")) && body == null && ifMatch == null && key == null -> {
                val query = linkedMapOf<String, Any?>()
                URI(path).rawQuery?.split('&')?.forEach {
                    val pair = it.split('=', limit=2)
                    if(pair.size != 2 || query.containsKey(pair[0])) invalid()
                    query[pair[0]] = if(pair[0] == "limit") {
                        if(!Regex("[1-9][0-9]{0,2}").matches(pair[1])) invalid()
                        pair[1].toInt()
                    } else pair[1]
                }
                prepare(FinanceOperation.LIST_HOUSEHOLD_PEOPLE, mapOf("query" to query))
            }
            method == "POST" && path == base && ifMatch == null -> prepare(FinanceOperation.CREATE_HOUSEHOLD_PERSON, mapOf("input" to body, "idempotencyKey" to key))
            method == "PATCH" && path.startsWith("$base/") && key == null -> prepare(FinanceOperation.UPDATE_HOUSEHOLD_PERSON, mapOf("personId" to path.removePrefix("$base/"), "input" to body, "ifMatch" to ifMatch))
            else -> invalid()
        }
        request.path == path
    } catch (_: Exception) { false }
    private fun person(value: Any?): Map<String, Any?> {
        val raw = obj(value)
        if(!raw.keys.containsAll(fields)) invalid()
        val row = raw.filterKeys { it in fields }
        for (key in listOf("id", "household_id", "created_by_member_id", "updated_by_member_id")) FinancePolicy.id(row[key])
        row["member_id"]?.let { FinancePolicy.id(it) }
        text(row["display_name"]); positive(row["version"])
        stamp(row["created_at"]); stamp(row["updated_at"]); row["archived_at"]?.let(::stamp)
        if(row["active"] !is Boolean) invalid()
        if(row["member_id"] != null) {
            if(row["member_id"] != row["id"] || row["relation"] != "member" || row["archived_at"] != null) invalid()
        } else if(row["relation"] !in setOf("child", "parent", "other") || row["active"] != (row["archived_at"] == null)) invalid()
        return row
    }
    fun response(operation: FinanceOperation, request: FinanceRequest, status: Int, value: Any?): Any {
        if(status != if(operation == FinanceOperation.CREATE_HOUSEHOLD_PERSON) 201 else 200) invalid()
        if(operation == FinanceOperation.CREATE_HOUSEHOLD_PERSON) {
            val row = obj(value)
            FinancePolicy.id(row["id"]); positive(row["version"])
            return mapOf("id" to row["id"], "version" to row["version"])
        }
        if(operation == FinanceOperation.UPDATE_HOUSEHOLD_PERSON) {
            val row = person(value)
            if(row["id"] != request.path.substringAfterLast('/')) invalid()
            return row
        }
        val row = obj(value)
        if(!row.keys.containsAll(setOf("items", "next_cursor"))) invalid()
        val raw = row["items"] as? List<*> ?: invalid()
        val limit = URI(request.path).rawQuery?.split('&')?.find { it.startsWith("limit=") }?.substringAfter('=')?.toInt() ?: 50
        if(raw.size > limit) invalid()
        val items = raw.map(::person)
        if(items.map { it["id"] }.distinct().size != items.size || items.map { it["household_id"] }.distinct().size > 1) invalid()
        val cursor = row["next_cursor"]?.let { FinancePolicy.id(it) }
        if(cursor != null && (items.size != limit || items.last()["id"] != cursor)) invalid()
        return mapOf("items" to items, "next_cursor" to cursor)
    }
}
