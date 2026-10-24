package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class NativeConsumableOrderPolicyTest {
    private val stockId = "00000000-0000-4000-8000-000000000010"
    private val orderId = "00000000-0000-4000-8000-000000000020"
    private val houseId = "00000000-0000-4000-8000-000000000030"
    private val otherId = "00000000-0000-4000-8000-000000000040"
    private val now = "2026-10-17T00:00:00Z"
    private val audit = mapOf("household_id" to houseId, "created_by_member_id" to houseId,
        "updated_by_member_id" to houseId, "created_at" to now, "updated_at" to now, "version" to 1)
    private fun stock() = audit + mapOf("id" to stockId, "name" to "합성 공용 필터", "sku_or_model" to null,
        "unit" to "개", "low_stock_threshold" to 0, "ended_on" to null, "note" to null,
        "status" to "active", "stock_quantity" to 1, "low_stock" to false)
    private fun source(id: String) = mapOf("link_id" to id, "appliance_id" to id,
        "appliance_name" to "합성 기기", "next_check_on" to "2026-10-17", "replacement_count" to 1, "quantity" to 1)
    private fun plan() = mapOf("consumable" to stock(), "demand_quantity" to 2, "shortage_quantity" to 1,
        "planned_quantity" to 0, "ordered_quantity" to 0, "additional_quantity" to 1,
        "open_order_count" to 0, "unscheduled_link_count" to 0, "demand_sources" to listOf(source(orderId),source(otherId)),
        "additional_source_count" to 0, "last_receipt" to null)
    private fun page(row: Map<String,Any?>) = mapOf("items" to listOf(row), "next_cursor" to null,
        "as_of" to "2026-10-17", "through" to "2026-10-17")
    private fun order() = audit + mapOf("id" to orderId, "consumable_id" to stockId,
        "consumable_name" to "합성 공용 필터", "unit" to "개", "sku_or_model" to null,
        "quantity" to 2, "unit_cost_krw" to "9007199254740993", "purchase_url" to null, "note" to null,
        "state" to "ordered", "ordered_on" to "2026-10-17", "ordered_by_member_id" to houseId,
        "received_on" to null, "received_by_member_id" to null, "stock_movement_id" to null,
        "receipt_reversed_by" to null, "cancel_reason" to null)
    private fun denied(action: () -> Unit) {
        try { action(); fail("Unexpected acceptance") } catch (error: AuthFailure) { assertEquals(AuthCode.ACCESS_DENIED,error.code) }
    }
    @Test fun ordersUseOnlyFixedPathsAndKeysWithBoundedTypedInput() {
        val create = FinancePolicy.prepare(FinanceOperation.CREATE_CONSUMABLE_ORDER, mapOf("input" to mapOf("consumable_id" to stockId, "quantity" to 1), "idempotencyKey" to "synthetic-order"))
        assertEquals("/api/v1/consumable-orders",create.path)
        assertTrue(NativeHomecarePolicy.httpAllowed(create.method,create.path,create.body,create.ifMatch,create.idempotencyKey))
        val receive = FinancePolicy.prepare(FinanceOperation.RECEIVE_CONSUMABLE_ORDER, mapOf("orderId" to orderId, "input" to mapOf("received_on" to "2026-10-17", "stock_version" to 7), "ifMatch" to "\"2\"", "idempotencyKey" to "synthetic-receive"))
        assertEquals("/api/v1/consumable-orders/$orderId/receive", receive.path)
        assertTrue(NativeHomecarePolicy.httpAllowed(receive.method,receive.path,receive.body,receive.ifMatch,receive.idempotencyKey))
        assertFalse(NativeHomecarePolicy.httpAllowed(receive.method,receive.path,receive.body,receive.ifMatch,null))
        assertFalse(NativeHomecarePolicy.httpAllowed(create.method,create.path,create.body!! + mapOf("stock_quantity" to 99),null,create.idempotencyKey))
        assertFalse(NativeHomecarePolicy.httpAllowed(create.method,create.path,create.body!! + mapOf("quantity" to 1.5),null,create.idempotencyKey))
        assertFalse(NativeHomecarePolicy.httpAllowed(receive.method,receive.path + "/other",receive.body,receive.ifMatch,receive.idempotencyKey))
        assertFalse(NativeHomecarePolicy.httpAllowed(receive.method,receive.path,receive.body!! + mapOf("received_by_member_id" to otherId),receive.ifMatch,receive.idempotencyKey))
    }
    @Test fun sharedStockPlanKeepsPhysicalShortageAndUnknownDatesDistinct() {
        val op = FinanceOperation.GET_PURCHASE_PLAN
        val request = FinancePolicy.prepare(op, emptyMap<String,Any>())
        assertEquals("/api/v1/homecare/purchase-plan", request.path)
        NativeHomecarePolicy.response(op, request, 200, page(plan()))
        denied { NativeHomecarePolicy.response(op, request, 200, page(plan() + mapOf("shortage_quantity" to 0))) }
        denied { NativeHomecarePolicy.response(op, request, 200, page(plan() + mapOf("demand_quantity" to 1))) }
        denied { NativeHomecarePolicy.response(op, request, 200, page(plan()) + mapOf("through" to "2026-10-18")) }
        val unknown = plan() + mapOf("demand_quantity" to 1, "shortage_quantity" to 0, "additional_quantity" to 0,
            "unscheduled_link_count" to 1, "demand_sources" to listOf(source(orderId),source(otherId)+mapOf("next_check_on" to null,"replacement_count" to null,"quantity" to null)))
        NativeHomecarePolicy.response(op, request, 200, page(unknown))
        denied { NativeHomecarePolicy.response(op, request, 200, page(unknown + mapOf("unscheduled_link_count" to 0))) }
    }
    @Test fun orderIdentityStateAndOriginalVersionReceiptAreValidated() {
        val op = FinanceOperation.GET_CONSUMABLE_ORDER
        val request = FinancePolicy.prepare(op, mapOf("orderId" to orderId))
        NativeHomecarePolicy.response(op, request, 200, order())
        denied { NativeHomecarePolicy.response(op, request, 200, order() + mapOf("id" to otherId)) }
        denied { NativeHomecarePolicy.response(op, request, 200, order() + mapOf("state" to "received")) }
        val list = FinancePolicy.prepare(FinanceOperation.LIST_CONSUMABLE_ORDERS, mapOf("query" to mapOf("state" to "planned")))
        denied { NativeHomecarePolicy.response(FinanceOperation.LIST_CONSUMABLE_ORDERS,list,200,mapOf("items" to listOf(order()),"next_cursor" to null)) }
        val command = FinancePolicy.prepare(FinanceOperation.SUBMIT_CONSUMABLE_ORDER, mapOf("orderId" to orderId,"input" to mapOf("ordered_on" to "2026-10-17"),"ifMatch" to "\"1\"","idempotencyKey" to "synthetic"))
        NativeHomecarePolicy.response(FinanceOperation.SUBMIT_CONSUMABLE_ORDER,command,200,mapOf("id" to orderId,"version" to 2))
        denied { NativeHomecarePolicy.response(FinanceOperation.SUBMIT_CONSUMABLE_ORDER,command,200,mapOf("id" to otherId,"version" to 2)) }
    }
}
