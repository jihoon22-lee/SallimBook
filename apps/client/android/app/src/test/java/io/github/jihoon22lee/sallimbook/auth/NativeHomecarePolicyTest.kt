package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class NativeHomecarePolicyTest {
    private val applianceId = "00000000-0000-4000-8000-000000000010"
    private val consumableId = "00000000-0000-4000-8000-000000000020"
    private val linkId = "00000000-0000-4000-8000-000000000030"
    private val movementId = "00000000-0000-4000-8000-000000000040"
    private val replacementId = "00000000-0000-4000-8000-000000000050"
    private val householdId = "00000000-0000-4000-8000-000000000060"
    private val now = "2026-02-28T00:00:00Z"
    private val tag = "\"7\""
    private val audit = mapOf("household_id" to householdId, "created_by_member_id" to householdId,
        "updated_by_member_id" to householdId, "created_at" to now, "updated_at" to now, "version" to 7)
    private val applianceInput = mapOf("name" to "합성 공기청정기", "purchase_price_krw" to "99999999999999999999")
    private val consumableInput = mapOf("name" to "합성 필터", "unit" to "개", "low_stock_threshold" to 0)
    private val linkInput = mapOf("appliance_id" to applianceId, "consumable_id" to consumableId,
        "interval_unit" to "months", "interval_count" to 1, "quantity_per_replacement" to 1)
    private val movementInput = mapOf("kind" to "receipt", "quantity_delta" to 3, "occurred_on" to "2026-01-31")
    private val replacementInput = mapOf("replaced_on" to "2026-01-31", "quantity" to 1,
        "link_version" to 3, "clear_next_check_override" to false)
    private val cancelInput = mapOf("occurred_on" to "2026-02-28", "reason" to "합성 취소 사유")
    private fun appliance() = audit + applianceInput + mapOf("id" to applianceId, "manufacturer" to null,
        "model" to null, "location" to null, "purchased_on" to null, "seller" to null,
        "warranty_until" to "2026-02-28", "ended_on" to null, "note" to null,
        "status" to "active", "as_of" to "2026-02-28", "warranty_status" to "active")
    private fun consumable() = audit + consumableInput + mapOf("id" to consumableId, "sku_or_model" to null,
        "ended_on" to null, "note" to null, "status" to "active", "stock_quantity" to 3, "low_stock" to false)
    private fun link() = audit + linkInput + mapOf("id" to linkId, "next_check_override" to null,
        "active" to true, "note" to null, "last_replacement_id" to replacementId, "last_replaced_on" to "2026-01-31",
        "next_check_on" to "2026-02-28", "next_check_source" to "replacement", "stock_quantity" to 3,
        "stock_version" to 11, "as_of" to "2026-02-28", "replacement_due" to true, "purchase_needed" to false, "low_stock" to false)
    private fun statusItem() = link() + mapOf("appliance_name" to "합성 공기청정기", "appliance_location" to null,
        "consumable_name" to "합성 필터", "sku_or_model" to null, "unit" to "개", "low_stock_threshold" to 0)
    private fun movement() = mapOf("id" to movementId, "household_id" to householdId, "consumable_id" to consumableId,
        "kind" to "receipt", "quantity_delta" to 3, "occurred_on" to "2026-01-31", "unit_cost_krw" to "0",
        "purchase_url" to null, "reversal_of" to null, "reason" to null, "note" to null, "stock_version" to 7,
        "created_by_member_id" to householdId, "created_at" to now, "reversed_by" to null)
    private fun replacement() = mapOf("id" to replacementId, "household_id" to householdId, "appliance_consumable_id" to linkId,
        "consumable_id" to consumableId, "stock_movement_id" to movementId, "replaced_on" to "2026-01-31", "quantity" to 1,
        "note" to null, "created_by_member_id" to householdId, "created_at" to now, "cancelled_by_movement_id" to null)
    private fun reference(replacement: Boolean = false) = mapOf("id" to householdId, "consumable_id" to consumableId,
        "stock_version" to 2, "replacement_id" to if (replacement) replacementId else null)
    private fun page(vararg items: Any?) = mapOf("items" to items.toList(), "next_cursor" to null)
    private fun change(input: Map<String, Any?>) = mapOf("input" to input, "ifMatch" to tag, "idempotencyKey" to "synthetic:homecare:1")
    private fun request(op: FinanceOperation, args: Map<String, Any?>) = FinancePolicy.prepare(op, args)
    private fun response(op: FinanceOperation, args: Map<String, Any?>, value: Any?, status: Int = 200) =
        FinancePolicy.response(op, request(op, args), status, value)
    private fun bad(code: AuthCode = AuthCode.INVALID_REQUEST, action: () -> Unit) {
        try { action(); fail("Invalid synthetic homecare value accepted") }
        catch (e: AuthFailure) { assertEquals(code, e.code); assertNull(e.message) }
    }
    private fun commands(): List<Pair<FinanceOperation, Map<String, Any?>>> = listOf(
        FinanceOperation.LIST_APPLIANCES to emptyMap(), FinanceOperation.CREATE_APPLIANCE to mapOf("input" to applianceInput),
        FinanceOperation.GET_APPLIANCE to mapOf("applianceId" to applianceId),
        FinanceOperation.UPDATE_APPLIANCE to mapOf("applianceId" to applianceId, "input" to mapOf("ended_on" to "2026-02-28"), "ifMatch" to tag),
        FinanceOperation.LIST_CONSUMABLES to emptyMap(), FinanceOperation.CREATE_CONSUMABLE to mapOf("input" to consumableInput),
        FinanceOperation.GET_CONSUMABLE to mapOf("consumableId" to consumableId),
        FinanceOperation.UPDATE_CONSUMABLE to mapOf("consumableId" to consumableId, "input" to mapOf("sku_or_model" to null), "ifMatch" to tag),
        FinanceOperation.LIST_APPLIANCE_CONSUMABLES to emptyMap(), FinanceOperation.CREATE_APPLIANCE_CONSUMABLE to mapOf("input" to linkInput),
        FinanceOperation.GET_APPLIANCE_CONSUMABLE to mapOf("linkId" to linkId),
        FinanceOperation.UPDATE_APPLIANCE_CONSUMABLE to mapOf("linkId" to linkId, "input" to mapOf("active" to false), "ifMatch" to tag),
        FinanceOperation.LIST_STOCK_MOVEMENTS to mapOf("consumableId" to consumableId),
        FinanceOperation.CREATE_STOCK_MOVEMENT to change(movementInput) + mapOf("consumableId" to consumableId),
        FinanceOperation.GET_STOCK_MOVEMENT to mapOf("consumableId" to consumableId, "movementId" to movementId),
        FinanceOperation.CANCEL_STOCK_MOVEMENT to change(cancelInput) + mapOf("consumableId" to consumableId, "movementId" to movementId),
        FinanceOperation.LIST_CONSUMABLE_REPLACEMENTS to mapOf("linkId" to linkId),
        FinanceOperation.CREATE_CONSUMABLE_REPLACEMENT to change(replacementInput) + mapOf("linkId" to linkId),
        FinanceOperation.GET_CONSUMABLE_REPLACEMENT to mapOf("linkId" to linkId, "replacementId" to replacementId),
        FinanceOperation.CANCEL_CONSUMABLE_REPLACEMENT to change(cancelInput) + mapOf("linkId" to linkId, "replacementId" to replacementId),
        FinanceOperation.GET_HOMECARE_STATUS to emptyMap(),
        FinanceOperation.DELETE_APPLIANCE to mapOf("applianceId" to applianceId, "ifMatch" to tag),
        FinanceOperation.DELETE_CONSUMABLE to mapOf("consumableId" to consumableId, "ifMatch" to tag),
        FinanceOperation.DELETE_APPLIANCE_CONSUMABLE to mapOf("linkId" to linkId, "ifMatch" to tag))

    @Test fun allTwentyFourCommandsUseFixedPathsAndExactHeaders() {
        assertEquals(24, commands().size)
        for ((op, args) in commands()) {
            val r = request(op, args)
            assertTrue(op.name, FinancePolicy.metadataHttpAllowed(r.method, r.path, r.body, r.ifMatch, r.idempotencyKey))
            assertFalse(AuthPolicy.requestAllowed(r.method, r.path, r.ifMatch))
            for (field in listOf("url", "headers", "body", "access_token")) bad { request(op, args + mapOf(field to null)) }
            if (r.idempotencyKey != null) bad { request(op, args - "idempotencyKey") }
            else bad { request(op, args + mapOf("idempotencyKey" to "unexpected")) }
            if (r.ifMatch != null) {
                bad { request(op, args - "ifMatch") }
                for (v in listOf("7", "W/\"7\"", "*", "\"0\"", "\"01\"", "\"9007199254740992\"")) bad { request(op, args + mapOf("ifMatch" to v)) }
            } else bad { request(op, args + mapOf("ifMatch" to tag)) }
        }
    }
    @Test fun allTwentyFourResponsesFollowActualContractWithoutDroppingNullsOrZeroes() {
        for ((op, args) in commands()) {
            val body = when (op) {
                FinanceOperation.DELETE_APPLIANCE, FinanceOperation.DELETE_CONSUMABLE, FinanceOperation.DELETE_APPLIANCE_CONSUMABLE -> null
                FinanceOperation.LIST_APPLIANCES -> page(appliance())
                FinanceOperation.CREATE_APPLIANCE, FinanceOperation.GET_APPLIANCE, FinanceOperation.UPDATE_APPLIANCE -> appliance()
                FinanceOperation.LIST_CONSUMABLES -> page(consumable())
                FinanceOperation.CREATE_CONSUMABLE, FinanceOperation.GET_CONSUMABLE, FinanceOperation.UPDATE_CONSUMABLE -> consumable()
                FinanceOperation.LIST_APPLIANCE_CONSUMABLES -> page(link())
                FinanceOperation.CREATE_APPLIANCE_CONSUMABLE, FinanceOperation.GET_APPLIANCE_CONSUMABLE, FinanceOperation.UPDATE_APPLIANCE_CONSUMABLE -> link()
                FinanceOperation.LIST_STOCK_MOVEMENTS -> page(movement())
                FinanceOperation.GET_STOCK_MOVEMENT -> movement()
                FinanceOperation.LIST_CONSUMABLE_REPLACEMENTS -> page(replacement())
                FinanceOperation.GET_CONSUMABLE_REPLACEMENT -> replacement()
                FinanceOperation.GET_HOMECARE_STATUS -> page(statusItem()) + mapOf("as_of" to "2026-02-28")
                else -> reference(op == FinanceOperation.CREATE_CONSUMABLE_REPLACEMENT)
            }
            val status = if (op.name.startsWith("CREATE")) 201 else if (op.name.startsWith("DELETE")) 204 else 200
            assertEquals(op.name, body, response(op, args, body, status))
            if (body != null) assertEquals(op.name, body, response(op, args, withAddedFields(body), status))
            bad(AuthCode.ACCESS_DENIED) { response(op, args, body, 202) }
            bad(AuthCode.ACCESS_DENIED) { response(op, args, (body ?: emptyMap()) + mapOf("token" to "synthetic"), status) }
        }
    }
    @Test fun quantitiesAreBoundedIntegersAndMoneyRemainsDecimalStrings() {
        for (quantity in listOf(null, true, 1.0, "1", -1, 1_000_001)) bad {
            request(FinanceOperation.CREATE_CONSUMABLE, mapOf("input" to consumableInput + mapOf("low_stock_threshold" to quantity)))
        }
        for (quantity in listOf(0, 1_000_000)) request(FinanceOperation.CREATE_CONSUMABLE, mapOf("input" to consumableInput + mapOf("low_stock_threshold" to quantity)))
        for (quantity in listOf(0, true, 1.0, "1", -1, 1_000_001)) bad {
            request(FinanceOperation.CREATE_CONSUMABLE_REPLACEMENT, change(replacementInput + mapOf("quantity" to quantity)) + mapOf("linkId" to linkId))
        }
        for (money in listOf(0, 1.0, "01", "-1", "1.0", "100000000000000000000")) bad {
            request(FinanceOperation.CREATE_APPLIANCE, mapOf("input" to applianceInput + mapOf("purchase_price_krw" to money)))
        }
        for (money in listOf(null, "0", "99999999999999999999")) request(FinanceOperation.CREATE_APPLIANCE,
            mapOf("input" to applianceInput + mapOf("purchase_price_krw" to money)))
    }
    @Test fun replacementRequiresIndependentLinkVersionAndExplicitOverrideChoice() {
        val op = FinanceOperation.CREATE_CONSUMABLE_REPLACEMENT
        fun args(input: Map<String, Any?>) = change(input) + mapOf("linkId" to linkId)
        for (field in listOf("link_version", "clear_next_check_override")) bad { request(op, args(replacementInput - field)) }
        for (v in listOf(null, 0, -1, true, "3", 3.0, 9_007_199_254_740_992L)) bad { request(op, args(replacementInput + mapOf("link_version" to v))) }
        for (v in listOf(null, 0, "false")) bad { request(op, args(replacementInput + mapOf("clear_next_check_override" to v))) }
        for (clear in listOf(false, true)) assertEquals(clear, request(op, args(replacementInput + mapOf("clear_next_check_override" to clear))).body!!["clear_next_check_override"])
        assertEquals(tag, request(op, args(replacementInput)).ifMatch)
        assertEquals(3, request(op, args(replacementInput)).body!!["link_version"])
    }
    @Test fun movementDirectionsReasonsAndCancellationCannotBeForged() {
        val op = FinanceOperation.CREATE_STOCK_MOVEMENT
        fun args(input: Map<String, Any?>) = change(input) + mapOf("consumableId" to consumableId)
        for (kind in listOf("replacement", "reversal", "unknown")) bad { request(op, args(movementInput + mapOf("kind" to kind))) }
        for (delta in listOf(0, true, "3", 3.0, -1, 1_000_001)) bad { request(op, args(movementInput + mapOf("quantity_delta" to delta))) }
        bad { request(op, args(movementInput + mapOf("kind" to "return_out"))) }
        bad { request(op, args(movementInput + mapOf("kind" to "adjustment"))) }
        request(op, args(movementInput + mapOf("kind" to "adjustment", "quantity_delta" to -1, "reason" to "합성 조정")))
        request(op, args(movementInput + mapOf("kind" to "return_out", "quantity_delta" to -1)))
        for (field in listOf("stock_quantity", "stock_version", "household_id", "reversal_of", "cvc")) bad { request(op, args(movementInput + mapOf(field to null))) }
        bad { request(FinanceOperation.CANCEL_STOCK_MOVEMENT, change(cancelInput + mapOf("quantity_delta" to -1)) + mapOf("consumableId" to consumableId, "movementId" to movementId)) }
    }
    @Test fun patchesRejectEmptyRequiredNullsIdentityChangesAndBadIntervals() {
        for ((op, identity, fields) in listOf(
            Triple(FinanceOperation.UPDATE_APPLIANCE, "applianceId" to applianceId, listOf("name")),
            Triple(FinanceOperation.UPDATE_CONSUMABLE, "consumableId" to consumableId, listOf("name", "unit", "low_stock_threshold")),
            Triple(FinanceOperation.UPDATE_APPLIANCE_CONSUMABLE, "linkId" to linkId, listOf("interval_unit", "quantity_per_replacement", "active")))) {
            bad { request(op, mapOf(identity, "input" to emptyMap<String, Any?>(), "ifMatch" to tag)) }
            for (field in fields) bad { request(op, mapOf(identity, "input" to mapOf(field to null), "ifMatch" to tag)) }
        }
        for (change in listOf(mapOf("interval_unit" to "manual", "interval_count" to 1), mapOf("interval_unit" to "months", "interval_count" to 121),
            mapOf("interval_unit" to "days", "interval_count" to 3651), mapOf("interval_unit" to "days", "interval_count" to null))) bad {
            request(FinanceOperation.CREATE_APPLIANCE_CONSUMABLE, mapOf("input" to linkInput + change))
        }
        request(FinanceOperation.UPDATE_APPLIANCE_CONSUMABLE, mapOf("linkId" to linkId, "input" to mapOf("interval_count" to 2), "ifMatch" to tag))
        bad { request(FinanceOperation.UPDATE_APPLIANCE_CONSUMABLE, mapOf("linkId" to linkId, "input" to mapOf("consumable_id" to householdId), "ifMatch" to tag)) }
    }
    @Test fun datesAndPurchaseUrlsAreValidatedWithoutCreatingFetchCapability() {
        for (date in listOf("2026-02-30", "0000-01-01", "2026-2-01", "2026-02-01T00:00:00Z")) bad {
            request(FinanceOperation.CREATE_APPLIANCE, mapOf("input" to applianceInput + mapOf("purchased_on" to date)))
        }
        bad { request(FinanceOperation.CREATE_APPLIANCE, mapOf("input" to applianceInput + mapOf("purchased_on" to "2026-02-02", "ended_on" to "2026-02-01"))) }
        for (url in listOf("http://synthetic.invalid/item", "https://user@synthetic.invalid", "https://synthetic.invalid:bad/", "https://synthetic.invalid/a b", "javascript:alert(1)")) bad {
            request(FinanceOperation.CREATE_STOCK_MOVEMENT, change(movementInput + mapOf("purchase_url" to url)) + mapOf("consumableId" to consumableId))
        }
        val url = "https://synthetic.invalid/item?variant=2#part"
        val r = request(FinanceOperation.CREATE_STOCK_MOVEMENT, change(movementInput + mapOf("purchase_url" to url)) + mapOf("consumableId" to consumableId))
        assertEquals(url, r.body!!["purchase_url"])
        assertEquals("/api/v1/consumables/$consumableId/stock-movements", r.path)
    }
    @Test fun statusSeparatesUnknownOverrideReplacementAndPurchaseNeed() {
        val op = FinanceOperation.GET_APPLIANCE_CONSUMABLE; val args = mapOf("linkId" to linkId)
        val unknown = link() + mapOf("last_replacement_id" to null, "last_replaced_on" to null,
            "next_check_on" to null, "next_check_source" to "unknown", "replacement_due" to null, "stock_quantity" to 0, "purchase_needed" to true, "low_stock" to true)
        response(op, args, unknown)
        response(op, args, unknown + mapOf("next_check_override" to "2026-03-01", "next_check_on" to "2026-03-01", "next_check_source" to "override", "replacement_due" to false))
        response(op, args, link() + mapOf("interval_unit" to "manual", "interval_count" to null, "next_check_on" to null, "next_check_source" to "unknown", "replacement_due" to null))
        for (change in listOf(mapOf("next_check_source" to "receipt"), mapOf("next_check_on" to "2026-03-03"),
            mapOf("replacement_due" to false), mapOf("purchase_needed" to true), mapOf("last_replacement_id" to null))) bad(AuthCode.ACCESS_DENIED) { response(op, args, link() + change) }
        bad(AuthCode.ACCESS_DENIED) { response(op, args, unknown + mapOf("replacement_due" to false)) }
    }
    @Test fun statusPageUsesServerAsOfAndRejectsMonthQueriesAndMixedDates() {
        val op = FinanceOperation.GET_HOMECARE_STATUS
        response(op, emptyMap(), page(statusItem()) + mapOf("as_of" to "2026-02-28"))
        for (field in listOf("month", "as_of", "as_of_date", "active", "status")) bad { request(op, mapOf("query" to mapOf(field to "2025-01"))) }
        bad(AuthCode.ACCESS_DENIED) { response(op, emptyMap(), page(statusItem()) + mapOf("as_of" to "2026-03-01")) }
        bad(AuthCode.ACCESS_DENIED) { response(op, emptyMap(), page(statusItem() + mapOf("active" to false)) + mapOf("as_of" to "2026-02-28")) }
        bad(AuthCode.ACCESS_DENIED) { response(op, emptyMap(), page(statusItem() + mapOf("low_stock" to true)) + mapOf("as_of" to "2026-02-28")) }
    }
    @Test fun mutationReferencesRetainCapturedVersionAndUseNewCancellationMovement() {
        val stockArgs = change(movementInput) + mapOf("consumableId" to consumableId)
        response(FinanceOperation.CREATE_STOCK_MOVEMENT, stockArgs, reference(), 201)
        val cancelArgs = change(cancelInput) + mapOf("consumableId" to consumableId, "movementId" to movementId)
        response(FinanceOperation.CANCEL_STOCK_MOVEMENT, cancelArgs, reference())
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.CANCEL_STOCK_MOVEMENT, cancelArgs, reference() + mapOf("id" to movementId)) }
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.CREATE_STOCK_MOVEMENT, stockArgs, reference() + mapOf("consumable_id" to householdId), 201) }
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.CREATE_STOCK_MOVEMENT, stockArgs, reference(true), 201) }
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.CREATE_CONSUMABLE_REPLACEMENT, change(replacementInput) + mapOf("linkId" to linkId), reference(), 201) }
        // Latest stock added to the receipt is dropped; the receipt keeps the captured version only.
        assertEquals(reference(), response(FinanceOperation.CREATE_STOCK_MOVEMENT, stockArgs, reference() + mapOf("stock_quantity" to 4), 201))
    }
    @Test fun nestedRecordsBindParentsAndRejectSecretFieldsInEveryResponse() {
        val movementArgs = mapOf("consumableId" to consumableId, "movementId" to movementId)
        for (change in listOf(mapOf("consumable_id" to householdId), mapOf("id" to householdId), mapOf("quantity_delta" to 3.0),
            mapOf("reversal_of" to householdId), mapOf("cvc" to null))) bad(AuthCode.ACCESS_DENIED) {
            response(FinanceOperation.GET_STOCK_MOVEMENT, movementArgs, movement() + change)
        }
        val replacementArgs = mapOf("linkId" to linkId, "replacementId" to replacementId)
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.GET_CONSUMABLE_REPLACEMENT, replacementArgs, replacement() + mapOf("appliance_consumable_id" to applianceId)) }
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.CREATE_APPLIANCE_CONSUMABLE, mapOf("input" to linkInput), link() + mapOf("consumable_id" to householdId), 201) }
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.GET_CONSUMABLE, mapOf("consumableId" to consumableId), consumable() - "note") }
    }
    @Test fun listsValidateFiltersOrderingCursorBoundsAndHouseholdConsistency() {
        val op = FinanceOperation.LIST_CONSUMABLES
        for (change in listOf(mapOf("status" to "ended"), mapOf("cursor" to consumableId))) bad(AuthCode.ACCESS_DENIED) {
            response(op, mapOf("query" to change), page(consumable()))
        }
        bad(AuthCode.ACCESS_DENIED) { response(op, emptyMap(), page(consumable(), consumable())) }
        bad(AuthCode.ACCESS_DENIED) { response(op, emptyMap(), page(consumable()) + mapOf("next_cursor" to householdId)) }
        bad(AuthCode.ACCESS_DENIED) { response(op, mapOf("query" to mapOf("limit" to 1)), page(consumable(), consumable() + mapOf("id" to applianceId))) }
        bad(AuthCode.ACCESS_DENIED) { response(op, emptyMap(), page(consumable(), consumable() + mapOf("id" to applianceId, "household_id" to applianceId))) }
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.LIST_APPLIANCE_CONSUMABLES, mapOf("query" to mapOf("active" to false)), page(link())) }
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.LIST_STOCK_MOVEMENTS, mapOf("consumableId" to householdId), page(movement())) }
    }
    @Test fun lowLevelAllowlistRejectsTraversalUnexpectedMethodsAndHeaderCrossover() {
        val path = "/api/v1/consumables"
        for (suffix in listOf("?limit=01", "?limit=201", "?limit=1&limit=2", "?status=unknown", "?cursor=$consumableId%2f", "#fragment", "/../appliances"))
            assertFalse(FinancePolicy.metadataHttpAllowed("GET", path + suffix, null, null))
        assertFalse(FinancePolicy.metadataHttpAllowed("GET", "https://synthetic.invalid$path", null, null))
        assertFalse(FinancePolicy.metadataHttpAllowed("DELETE", "$path/$consumableId", null, null))
        assertFalse(FinancePolicy.metadataHttpAllowed("DELETE", "$path/$consumableId", emptyMap<String, Any?>(), tag))
        assertFalse(FinancePolicy.metadataHttpAllowed("DELETE", "$path/$consumableId", null, tag, "unexpected"))
        assertFalse(FinancePolicy.metadataHttpAllowed("PATCH", "$path/$consumableId", mapOf("name" to "합성"), tag, "unexpected"))
        assertFalse(FinancePolicy.metadataHttpAllowed("POST", "$path/$consumableId/stock-movements", movementInput, null, "synthetic"))
        assertFalse(FinancePolicy.metadataHttpAllowed("POST", "$path/$consumableId/stock-movements", movementInput, tag, "bad key"))
        assertFalse(FinancePolicy.metadataHttpAllowed("GET", "/api/v1/appliance-consumables?active=1", null, null))
    }
    @Test fun warrantyAndStockFlagsRetainUnknownAndInclusiveBounds() {
        val args = mapOf("applianceId" to applianceId)
        response(FinanceOperation.GET_APPLIANCE, args, appliance() + mapOf("warranty_until" to null, "warranty_status" to "unknown"))
        response(FinanceOperation.GET_APPLIANCE, args, appliance() + mapOf("warranty_until" to "2026-02-27", "warranty_status" to "expired"))
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.GET_APPLIANCE, args, appliance() + mapOf("warranty_status" to "expired")) }
        bad(AuthCode.ACCESS_DENIED) { response(FinanceOperation.GET_CONSUMABLE, mapOf("consumableId" to consumableId), consumable() + mapOf("low_stock" to true)) }
        response(FinanceOperation.GET_CONSUMABLE, mapOf("consumableId" to consumableId), consumable() + mapOf("stock_quantity" to 0, "low_stock" to true))
    }
    @Test fun domainErrorsKeepKnownCodesWithoutServerTextOrSubmittedValues() {
        for ((code, status) in listOf("INSUFFICIENT_STOCK" to 409, "STOCK_MOVEMENT_ALREADY_REVERSED" to 409,
            "INVALID_HOMECARE_DATE" to 422, "STOCK_LIMIT_EXCEEDED" to 422, "CONSUMABLE_UNIT_IN_USE" to 409,
            "REPLACEMENT_CANCEL_REQUIRED" to 409, "APPLIANCE_CONSUMABLE_UNAVAILABLE" to 422,
            "APPLIANCE_IN_USE" to 409, "CONSUMABLE_IN_USE" to 409, "APPLIANCE_CONSUMABLE_IN_USE" to 409)) {
            val raw = mapOf("error" to mapOf("code" to code, "message" to "SYNTHETIC PRIVATE", "details" to mapOf("note" to "SYNTHETIC PRIVATE")))
            val safe = AuthPolicy.safeError(status, raw, householdId)!!
            assertEquals(code, (safe["error"] as Map<*, *>)["code"])
            assertFalse(safe.toString().contains("SYNTHETIC PRIVATE"))
            assertEquals("INTERNAL_ERROR", (AuthPolicy.safeError(500, raw, householdId)!!["error"] as Map<*, *>)["code"])
        }
    }
    @Test fun listsKeepServerOrderButRejectRepeatedRowsCursorAndWrongNextCursor() {
        val op = FinanceOperation.LIST_CONSUMABLES
        val ascending = listOf(consumable() + mapOf("id" to applianceId), consumable())
        response(op, emptyMap(), mapOf("items" to ascending, "next_cursor" to null))
        val two = mapOf("query" to mapOf("limit" to 2))
        response(op, two, mapOf("items" to ascending, "next_cursor" to consumableId))
        bad(AuthCode.ACCESS_DENIED) { response(op, two, mapOf("items" to ascending, "next_cursor" to applianceId)) }
        bad(AuthCode.ACCESS_DENIED) { response(op, mapOf("query" to mapOf("cursor" to consumableId)), mapOf("items" to ascending, "next_cursor" to null)) }
    }
}
