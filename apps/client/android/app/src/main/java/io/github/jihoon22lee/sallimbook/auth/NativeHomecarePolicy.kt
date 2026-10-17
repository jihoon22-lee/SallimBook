package io.github.jihoon22lee.sallimbook.auth

import java.net.URI
import java.time.LocalDate
import java.time.OffsetDateTime

private typealias HomecareField = (Any?) -> Unit

/** Projection of the generated homecare contract. Server remains the stock and date authority. */
internal object NativeHomecarePolicy {
    private const val MAX_QUANTITY = 1_000_000L
    private const val MAX_VERSION = 9_007_199_254_740_991L
    private fun invalid(): Nothing = throw AuthFailure(AuthCode.INVALID_REQUEST)
    private fun obj(value: Any?): Map<String, Any?> {
        val row = value as? Map<*, *> ?: invalid()
        if (row.size > 48 || row.keys.any { it !is String }) invalid()
        return row.entries.associate { it.key as String to it.value }
    }
    private fun number(value: Any?, minimum: Long, maximum: Long): Long {
        val value = when (value) { is Int -> value.toLong(); is Long -> value; else -> invalid() }
        if (value !in minimum..maximum) invalid()
        return value
    }
    private fun integer(minimum: Long, maximum: Long): HomecareField = { number(it, minimum, maximum); Unit }
    private val id: HomecareField = { FinancePolicy.id(it); Unit }
    private val bool: HomecareField = { if (it !is Boolean) invalid() }
    private val quantity = integer(0, MAX_QUANTITY)
    private val positiveQuantity = integer(1, MAX_QUANTITY)
    private val version = integer(1, MAX_VERSION)
    private val delta: HomecareField = { if (number(it, -MAX_QUANTITY, MAX_QUANTITY) == 0L) invalid() }
    private val money: HomecareField = { if (it !is String || !Regex("0|[1-9][0-9]{0,19}").matches(it)) invalid() }
    private val date: HomecareField = {
        if (it !is String || !Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}").matches(it) || it.startsWith("0000")) invalid()
        try { LocalDate.parse(it) } catch (_: Exception) { invalid() }
    }
    private val timestamp: HomecareField = {
        if (it !is String || it.length > 40) invalid()
        try { OffsetDateTime.parse(it) } catch (_: Exception) { invalid() }
    }
    private fun text(maximum: Int, empty: Boolean = false): HomecareField = {
        if (it !is String || it.codePointCount(0, it.length) > maximum || !empty && it.trim().isEmpty()) invalid()
    }
    private fun choice(vararg values: String): HomecareField = { if (it !is String || it !in values) invalid() }
    private fun nullable(rule: HomecareField): HomecareField = { if (it != null) rule(it) }
    private fun shape(value: Any?, fields: Map<String, HomecareField>, required: Set<String> = fields.keys): Map<String, Any?> {
        val row = obj(value)
        if (!fields.keys.containsAll(row.keys) || !row.keys.containsAll(required)) invalid()
        row.forEach { (name, item) -> fields.getValue(name)(item) }
        return row
    }
    private fun tag(value: Any?): String {
        if (value !is String || !Regex("\"[1-9][0-9]{0,15}\"").matches(value)) invalid()
        number(value.removeSurrounding("\"").toLongOrNull(), 1, MAX_VERSION)
        return value
    }
    private fun key(value: Any?): String {
        if (value !is String || !Regex("[A-Za-z0-9._:-]{1,128}").matches(value)) invalid()
        return value
    }
    private val purchaseUrl: HomecareField = {
        if (it !is String || it.length > 2048 || it.any { c -> c.isWhitespace() || c.code < 32 }) invalid()
        try {
            val uri = URI(it)
            val authority = uri.rawAuthority ?: invalid()
            if (uri.scheme != "https" || authority.isEmpty() || '@' in authority) invalid()
            val host = if (authority.startsWith('[')) authority.substringBefore(']') + "]" else authority.substringBefore(':')
            if (host.isEmpty()) invalid()
            val suffix = authority.removePrefix(host)
            if (suffix.isNotEmpty() && (!suffix.startsWith(':') || suffix.drop(1).isNotEmpty() &&
                    (!suffix.drop(1).all(Char::isDigit) || (suffix.drop(1).toIntOrNull() ?: invalid()) !in 0..65535))) invalid()
        } catch (_: Exception) { invalid() }
    }
    private data class Route(val method: String, val path: String, val input: String, val output: String,
        val query: Map<String, HomecareField>, val version: Boolean, val idem: Boolean, val status: Int)
    private val pageQuery = mapOf("cursor" to nullable(id), "limit" to integer(1, 200))
    private val statusQuery = pageQuery + mapOf("status" to choice("active", "ended", "all"))
    private val linkQuery = pageQuery + mapOf("appliance_id" to nullable(id), "consumable_id" to nullable(id))
    private val routes = mapOf(
        FinanceOperation.LIST_APPLIANCES to Route("GET", "/api/v1/appliances", "", "ApplianceListResponse", statusQuery, false, false, 200),
        FinanceOperation.CREATE_APPLIANCE to Route("POST", "/api/v1/appliances", "ApplianceInput", "ApplianceResponse", emptyMap(), false, false, 201),
        FinanceOperation.GET_APPLIANCE to Route("GET", "/api/v1/appliances/{applianceId}", "", "ApplianceResponse", emptyMap(), false, false, 200),
        FinanceOperation.UPDATE_APPLIANCE to Route("PATCH", "/api/v1/appliances/{applianceId}", "AppliancePatch", "ApplianceResponse", emptyMap(), true, false, 200),
        FinanceOperation.LIST_CONSUMABLES to Route("GET", "/api/v1/consumables", "", "ConsumableListResponse", statusQuery, false, false, 200),
        FinanceOperation.CREATE_CONSUMABLE to Route("POST", "/api/v1/consumables", "ConsumableInput", "ConsumableResponse", emptyMap(), false, false, 201),
        FinanceOperation.GET_CONSUMABLE to Route("GET", "/api/v1/consumables/{consumableId}", "", "ConsumableResponse", emptyMap(), false, false, 200),
        FinanceOperation.UPDATE_CONSUMABLE to Route("PATCH", "/api/v1/consumables/{consumableId}", "ConsumablePatch", "ConsumableResponse", emptyMap(), true, false, 200),
        FinanceOperation.LIST_APPLIANCE_CONSUMABLES to Route("GET", "/api/v1/appliance-consumables", "", "ApplianceConsumableListResponse", linkQuery + mapOf("active" to nullable(bool)), false, false, 200),
        FinanceOperation.CREATE_APPLIANCE_CONSUMABLE to Route("POST", "/api/v1/appliance-consumables", "ApplianceConsumableCreate", "ApplianceConsumableResponse", emptyMap(), false, false, 201),
        FinanceOperation.GET_APPLIANCE_CONSUMABLE to Route("GET", "/api/v1/appliance-consumables/{linkId}", "", "ApplianceConsumableResponse", emptyMap(), false, false, 200),
        FinanceOperation.UPDATE_APPLIANCE_CONSUMABLE to Route("PATCH", "/api/v1/appliance-consumables/{linkId}", "ApplianceConsumablePatch", "ApplianceConsumableResponse", emptyMap(), true, false, 200),
        FinanceOperation.LIST_STOCK_MOVEMENTS to Route("GET", "/api/v1/consumables/{consumableId}/stock-movements", "", "StockMovementListResponse", pageQuery, false, false, 200),
        FinanceOperation.CREATE_STOCK_MOVEMENT to Route("POST", "/api/v1/consumables/{consumableId}/stock-movements", "StockMovementCreate", "StockMutationReference", emptyMap(), true, true, 201),
        FinanceOperation.GET_STOCK_MOVEMENT to Route("GET", "/api/v1/consumables/{consumableId}/stock-movements/{movementId}", "", "StockMovementResponse", emptyMap(), false, false, 200),
        FinanceOperation.CANCEL_STOCK_MOVEMENT to Route("POST", "/api/v1/consumables/{consumableId}/stock-movements/{movementId}/cancel", "StockCancellation", "StockMutationReference", emptyMap(), true, true, 200),
        FinanceOperation.LIST_CONSUMABLE_REPLACEMENTS to Route("GET", "/api/v1/appliance-consumables/{linkId}/replacements", "", "ReplacementListResponse", pageQuery, false, false, 200),
        FinanceOperation.CREATE_CONSUMABLE_REPLACEMENT to Route("POST", "/api/v1/appliance-consumables/{linkId}/replacements", "ReplacementCreate", "StockMutationReference", emptyMap(), true, true, 201),
        FinanceOperation.GET_CONSUMABLE_REPLACEMENT to Route("GET", "/api/v1/appliance-consumables/{linkId}/replacements/{replacementId}", "", "ReplacementResponse", emptyMap(), false, false, 200),
        FinanceOperation.CANCEL_CONSUMABLE_REPLACEMENT to Route("POST", "/api/v1/appliance-consumables/{linkId}/replacements/{replacementId}/cancel", "StockCancellation", "StockMutationReference", emptyMap(), true, true, 200),
        FinanceOperation.GET_HOMECARE_STATUS to Route("GET", "/api/v1/homecare/status", "", "HomecareStatusResponse", linkQuery, false, false, 200),
    )
    private val audit = mapOf("id" to id, "household_id" to id, "version" to version, "created_by_member_id" to id,
        "updated_by_member_id" to id, "created_at" to timestamp, "updated_at" to timestamp)
    private val fact = mapOf("id" to id, "household_id" to id, "consumable_id" to id,
        "created_by_member_id" to id, "created_at" to timestamp)
    private val applianceFields = mapOf("name" to text(120), "manufacturer" to nullable(text(120)), "model" to nullable(text(120)),
        "location" to nullable(text(120)), "purchased_on" to nullable(date), "purchase_price_krw" to nullable(money),
        "seller" to nullable(text(120)), "warranty_until" to nullable(date), "ended_on" to nullable(date), "note" to nullable(text(2000, true)))
    private val consumableFields = mapOf("name" to text(120), "sku_or_model" to nullable(text(120)), "unit" to text(40),
        "low_stock_threshold" to quantity, "ended_on" to nullable(date), "note" to nullable(text(2000, true)))
    private val linkFields = mapOf("interval_unit" to choice("manual", "days", "months"), "interval_count" to nullable(integer(1, 3650)),
        "quantity_per_replacement" to positiveQuantity, "next_check_override" to nullable(date), "active" to bool, "note" to nullable(text(2000, true)))
    private val linkIdentity = mapOf("appliance_id" to id, "consumable_id" to id)
    private val linkStatus = mapOf("last_replacement_id" to nullable(id), "last_replaced_on" to nullable(date),
        "next_check_on" to nullable(date), "next_check_source" to choice("override", "replacement", "unknown"),
        "stock_quantity" to quantity, "stock_version" to version, "as_of" to date, "replacement_due" to nullable(bool),
        "purchase_needed" to bool, "low_stock" to bool)
    private val movementFields = mapOf("kind" to choice("receipt", "return_in", "return_out", "adjustment"),
        "quantity_delta" to delta, "occurred_on" to date, "unit_cost_krw" to nullable(money),
        "purchase_url" to nullable(purchaseUrl), "reason" to nullable(text(500)), "note" to nullable(text(2000, true)))
    fun supports(operation: FinanceOperation) = operation in routes
    private fun chronology(row: Map<String, Any?>) {
        if (row["purchased_on"] != null && row["ended_on"] != null && (row["ended_on"] as String) < (row["purchased_on"] as String)) invalid()
    }
    private fun interval(row: Map<String, Any?>, partial: Boolean = false) {
        val unit = row["interval_unit"] ?: if (partial) return else "manual"
        if (partial && "interval_count" !in row) return
        val count = row["interval_count"]
        if (unit == "manual") { if (count != null) invalid() }
        else number(count, 1, if (unit == "months") 120 else 3650)
    }
    private fun direction(row: Map<String, Any?>) {
        val delta = number(row["quantity_delta"], -MAX_QUANTITY, MAX_QUANTITY)
        if (row["kind"] in setOf("receipt", "return_in") && delta <= 0 || row["kind"] in setOf("return_out", "replacement") && delta >= 0) invalid()
        if (row["kind"] in setOf("adjustment", "reversal") && row["reason"] == null) invalid()
    }
    private fun input(schema: String, value: Any?): Map<String, Any?> {
        val fields = when (schema) {
            "ApplianceInput", "AppliancePatch" -> applianceFields
            "ConsumableInput", "ConsumablePatch" -> consumableFields
            "ApplianceConsumableCreate" -> linkFields + linkIdentity
            "ApplianceConsumablePatch" -> linkFields
            "StockMovementCreate" -> movementFields
            "ReplacementCreate" -> mapOf("replaced_on" to date, "quantity" to positiveQuantity, "link_version" to version,
                "clear_next_check_override" to bool, "note" to nullable(text(2000, true)))
            "StockCancellation" -> mapOf("occurred_on" to date, "reason" to text(500))
            else -> invalid()
        }
        val required = when (schema) {
            "ApplianceInput" -> setOf("name")
            "ConsumableInput" -> setOf("name", "unit")
            "ApplianceConsumableCreate" -> linkIdentity.keys
            "StockMovementCreate" -> setOf("kind", "quantity_delta", "occurred_on")
            "ReplacementCreate" -> setOf("replaced_on", "quantity", "link_version", "clear_next_check_override")
            "StockCancellation" -> fields.keys
            else -> emptySet()
        }
        val row = shape(value, fields, required)
        if (row.isEmpty()) invalid()
        chronology(row)
        if (schema.startsWith("ApplianceConsumable")) interval(row, schema.endsWith("Patch"))
        if (schema == "StockMovementCreate") direction(row)
        return row
    }
    private fun query(route: Route, value: Any?): Map<String, Any?> =
        if (value == null) emptyMap() else shape(value, route.query, emptySet()).filterValues { it != null }
    fun prepare(operation: FinanceOperation, value: Any?): FinanceRequest {
        val route = routes[operation] ?: invalid()
        val args = obj(value)
        val ids = Regex("\\{([^}]+)}").findAll(route.path).map { it.groupValues[1] }.toSet()
        val required = ids + (if (route.input.isNotEmpty()) setOf("input") else emptySet()) +
            (if (route.version) setOf("ifMatch") else emptySet()) + (if (route.idem) setOf("idempotencyKey") else emptySet())
        if (!args.keys.containsAll(required) || !(required + if (route.query.isNotEmpty()) setOf("query") else emptySet()).containsAll(args.keys)) invalid()
        var path = route.path
        ids.forEach { path = path.replace("{$it}", FinancePolicy.id(args[it]).lowercase()) }
        val values = query(route, args["query"])
        if (values.isNotEmpty()) path += "?" + values.toSortedMap().entries.joinToString("&") { "${it.key}=${if (it.value is String) (it.value as String).lowercase() else it.value}" }
        return FinanceRequest(route.method, path, if (route.input.isEmpty()) null else input(route.input, args["input"]),
            if (route.version) tag(args["ifMatch"]) else null, if (route.idem) key(args["idempotencyKey"]) else null)
    }
    private fun queryValues(route: Route, uri: URI): Map<String, Any?> {
        val values = mutableMapOf<String, Any?>()
        uri.rawQuery?.let { raw ->
            if (raw.isEmpty() || route.query.isEmpty()) invalid()
            raw.split('&').forEach { part ->
                val pair = part.split('=', limit = 2)
                if (pair.size != 2 || pair[0] in values) invalid()
                values[pair[0]] = when (pair[0]) {
                    "limit" -> pair[1].toLongOrNull() ?: invalid()
                    "active" -> when (pair[1]) { "true" -> true; "false" -> false; else -> invalid() }
                    else -> pair[1]
                }
            }
        }
        return query(route, values)
    }
    fun httpAllowed(method: String, path: String, body: Any?, ifMatch: String?, idempotencyKey: String?): Boolean = try {
        val uri = URI(path)
        if (path.length > 2048 || uri.isAbsolute || uri.rawAuthority != null || uri.rawFragment != null || '%' in path || '\\' in path || path.any { it.isWhitespace() || it.code < 32 }) invalid()
        val parts = uri.rawPath.split('/')
        val entry = routes.entries.firstOrNull { (_, route) ->
            val pattern = route.path.split('/')
            route.method == method && pattern.size == parts.size && pattern.indices.all { pattern[it].startsWith('{') || pattern[it] == parts[it] }
        } ?: invalid()
        val route = entry.value
        val args = mutableMapOf<String, Any?>()
        route.path.split('/').forEachIndexed { n, p -> if (p.startsWith('{')) args[p.removeSurrounding("{", "}")] = parts[n] }
        if (route.input.isNotEmpty()) args["input"] = body else if (body != null) invalid()
        if (route.version) args["ifMatch"] = ifMatch else if (ifMatch != null) invalid()
        if (route.idem) args["idempotencyKey"] = idempotencyKey else if (idempotencyKey != null) invalid()
        if (uri.rawQuery != null) args["query"] = queryValues(route, uri)
        val request = prepare(entry.key, args)
        request.path == path && request.body == body && request.ifMatch == ifMatch && request.idempotencyKey == idempotencyKey
    } catch (_: Exception) { false }
    private fun linkState(row: Map<String, Any?>) {
        interval(row)
        if ((row["last_replacement_id"] == null) != (row["last_replaced_on"] == null)) invalid()
        val last = row["last_replaced_on"] as String?
        val override = row["next_check_override"] as String?
        val expectedSource: String
        val expectedDate: String?
        if (override != null) { expectedSource = "override"; expectedDate = override }
        else if (last == null || row["interval_unit"] == "manual") { expectedSource = "unknown"; expectedDate = null }
        else {
            expectedSource = "replacement"
            val count = (row["interval_count"] as Number).toLong()
            val date = LocalDate.parse(last)
            expectedDate = (if (row["interval_unit"] == "days") date.plusDays(count) else date.plusMonths(count)).toString()
        }
        if (row["next_check_source"] != expectedSource || row["next_check_on"] != expectedDate) invalid()
        if (row["replacement_due"] != expectedDate?.let { it <= (row["as_of"] as String) }) invalid()
        if (row["purchase_needed"] != ((row["stock_quantity"] as Number).toLong() < (row["quantity_per_replacement"] as Number).toLong())) invalid()
    }
    private fun entity(schema: String, value: Any?): Map<String, Any?> {
        val row = when (schema) {
            "ApplianceResponse" -> shape(value, applianceFields + audit + mapOf("status" to choice("active", "ended"), "as_of" to date, "warranty_status" to choice("unknown", "active", "expired")))
            "ConsumableResponse" -> shape(value, consumableFields + audit + mapOf("status" to choice("active", "ended"), "stock_quantity" to quantity, "low_stock" to bool))
            "ApplianceConsumableResponse" -> shape(value, linkFields + linkIdentity + linkStatus + audit)
            "HomecareStatusItem" -> shape(value, linkFields + linkIdentity + linkStatus + audit + mapOf("appliance_name" to text(120),
                "appliance_location" to nullable(text(120)), "consumable_name" to text(120), "sku_or_model" to nullable(text(120)),
                "unit" to text(40), "low_stock_threshold" to quantity))
            "StockMovementResponse" -> shape(value, movementFields + fact + mapOf("kind" to choice("receipt", "replacement", "return_in", "return_out", "adjustment", "reversal"),
                "reversal_of" to nullable(id), "stock_version" to version, "reversed_by" to nullable(id)))
            "ReplacementResponse" -> shape(value, fact + mapOf("appliance_consumable_id" to id, "stock_movement_id" to id,
                "replaced_on" to date, "quantity" to positiveQuantity, "note" to nullable(text(2000, true)), "cancelled_by_movement_id" to nullable(id)))
            "StockMutationReference" -> shape(value, mapOf("id" to id, "consumable_id" to id, "stock_version" to version, "replacement_id" to nullable(id)))
            else -> invalid()
        }
        chronology(row)
        if ("status" in row && row["status"] != if (row["ended_on"] == null) "active" else "ended") invalid()
        if (schema == "ApplianceResponse") {
            val warranty = row["warranty_until"] as String?
            if (row["warranty_status"] != if (warranty == null) "unknown" else if (warranty >= (row["as_of"] as String)) "active" else "expired") invalid()
        }
        if ("next_check_source" in row) linkState(row)
        if ("low_stock_threshold" in row && row["low_stock"] != ((row["stock_quantity"] as Number).toLong() <= (row["low_stock_threshold"] as Number).toLong())) invalid()
        if (schema == "StockMovementResponse") {
            direction(row)
            if ((row["kind"] == "reversal") != (row["reversal_of"] != null) || row["reversal_of"] == row["id"] || row["reversed_by"] == row["id"]) invalid()
            if (row["kind"] == "reversal" && row["reversed_by"] != null) invalid()
        }
        return row
    }
    fun response(operation: FinanceOperation, request: FinanceRequest, status: Int, value: Any?): Any? {
        try {
            val route = routes[operation] ?: invalid()
            if (status != route.status) invalid()
            val uri = URI(request.path)
            val parts = uri.path.split('/')
            val target = mutableMapOf<String, String>()
            route.path.split('/').forEachIndexed { n, p -> if (p.startsWith('{')) target[p.removeSurrounding("{", "}")] = parts[n] }
            val q = queryValues(route, uri)
            fun bound(row: Map<String, Any?>, schema: String) {
                val names = when (schema) {
                    "ApplianceResponse" -> mapOf("applianceId" to "id")
                    "ConsumableResponse" -> mapOf("consumableId" to "id")
                    "ApplianceConsumableResponse", "HomecareStatusItem" -> mapOf("linkId" to "id")
                    "StockMovementResponse" -> mapOf("consumableId" to "consumable_id", "movementId" to "id")
                    "ReplacementResponse" -> mapOf("linkId" to "appliance_consumable_id", "replacementId" to "id")
                    "StockMutationReference" -> mapOf("consumableId" to "consumable_id")
                    else -> invalid()
                }
                names.forEach { (arg, field) -> if (target[arg] != null && row[field] != target[arg]) invalid() }
                for (filter in listOf("appliance_id", "consumable_id", "active")) {
                    if (q[filter] != null && row[filter].toString().lowercase() != q[filter].toString().lowercase()) invalid()
                }
                if (schema in setOf("ApplianceResponse", "ConsumableResponse") && route.query.isNotEmpty()) {
                    val state = q["status"] ?: "active"
                    if (state != "all" && row["status"] != state) invalid()
                }
            }
            if (route.output.endsWith("ListResponse") || route.output == "HomecareStatusResponse") {
                val page = obj(value)
                val statusPage = route.output == "HomecareStatusResponse"
                if (page.keys != setOf("items", "next_cursor") + if (statusPage) setOf("as_of") else emptySet()) invalid()
                if (statusPage) date(page["as_of"])
                val items = page["items"] as? List<*> ?: invalid()
                if (items.size > ((q["limit"] as? Number)?.toInt() ?: 50)) invalid()
                val schema = when (route.output) {
                    "ApplianceListResponse" -> "ApplianceResponse"
                    "ConsumableListResponse" -> "ConsumableResponse"
                    "ApplianceConsumableListResponse" -> "ApplianceConsumableResponse"
                    "StockMovementListResponse" -> "StockMovementResponse"
                    "ReplacementListResponse" -> "ReplacementResponse"
                    "HomecareStatusResponse" -> "HomecareStatusItem"
                    else -> invalid()
                }
                var previous = (q["cursor"] as? String)?.lowercase()
                val households = mutableSetOf<Any?>()
                val dates = mutableSetOf<Any?>()
                for (item in items) {
                    val row = entity(schema, item); bound(row, schema)
                    val current = (row["id"] as String).lowercase()
                    if (previous != null && current >= previous) invalid()
                    previous = current
                    households.add(row["household_id"])
                    if ("as_of" in row) dates.add(row["as_of"])
                    if (statusPage && (row["active"] != true || row["as_of"] != page["as_of"])) invalid()
                }
                if (households.size > 1 || dates.size > 1) invalid()
                page["next_cursor"]?.let { id(it); if (items.isEmpty() || (it as String).lowercase() != previous) invalid() }
                return page
            }
            val row = entity(route.output, value); bound(row, route.output)
            if (route.output == "StockMutationReference") {
                // Retried receipts preserve the original version; never infer current stock from it.
                if ((operation == FinanceOperation.CREATE_CONSUMABLE_REPLACEMENT) != (row["replacement_id"] != null)) invalid()
                if (operation == FinanceOperation.CANCEL_STOCK_MOVEMENT && row["id"] == target["movementId"]) invalid()
            }
            if (operation == FinanceOperation.CREATE_APPLIANCE_CONSUMABLE) {
                for (field in linkIdentity.keys) if (!row[field].toString().equals(request.body?.get(field).toString(), true)) invalid()
            }
            return row
        } catch (_: Exception) { throw AuthFailure(AuthCode.ACCESS_DENIED) }
    }
}
