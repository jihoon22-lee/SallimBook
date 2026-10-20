package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class PaymentLinksPolicyTest {
    private val assetId = "00000000-0000-4000-8000-000000000001"
    private val accountId = "00000000-0000-4000-8000-000000000002"
    private val cardId = "00000000-0000-4000-8000-000000000003"
    private val obligationId = "00000000-0000-4000-8000-000000000004"
    private val ruleId = "00000000-0000-4000-8000-000000000005"
    private val day = "2026-01-31"
    private val digest = "a".repeat(64)
    private val tag = "\"7\""
    private fun bad(code: AuthCode = AuthCode.INVALID_REQUEST, action: () -> Unit) {
        try { action(); fail("Unsafe usage metadata or closure confirmation accepted") }
        catch (failure: AuthFailure) { assertEquals(code, failure.code); assertNull(failure.message) }
    }
    private fun request(account: Boolean = false, query: Map<String, Any?> = mapOf("as_of_date" to day)) = FinancePolicy.prepare(
        if (account) FinanceOperation.GET_ACCOUNT_PAYMENT_LINKS else FinanceOperation.GET_CARD_PAYMENT_LINKS,
        mapOf("resourceId" to if (account) accountId else cardId, "query" to query))
    private fun op(account: Boolean) = if (account) FinanceOperation.GET_ACCOUNT_PAYMENT_LINKS else FinanceOperation.GET_CARD_PAYMENT_LINKS
    private fun method(account: Boolean) = mapOf("account_id" to if (account) accountId else null, "card_id" to if (account) null else cardId,
        "payment_basis" to if (account) "account_payment_plan" else "card_approval_plan")
    private fun rule(account: Boolean = false) = method(account) + mapOf("id" to ruleId, "rule_id" to ruleId, "rule_version" to 8,
        "title" to "합성 연결 규칙", "category" to "합성 분류", "amount_mode" to "fixed", "expected_amount_krw" to "33000", "economic_type" to "expense",
        "period" to "current", "effective_from" to "2026-01-01", "effective_until" to null, "anchor_date" to day, "frequency" to "monthly", "interval_count" to 1)
    private fun obligation(account: Boolean = false) = method(account) + mapOf("id" to obligationId, "version" to 8, "rule_id" to ruleId, "rule_version_id" to ruleId,
        "title" to "합성 미납 회차", "category" to "합성 분류", "scheduled_date" to day, "expected_amount_krw" to null, "actual_paid_krw" to "0", "status" to "unpaid")
    private fun card() = mapOf<String, Any?>("id" to cardId, "version" to 8, "issuer_name" to "합성 카드사", "product_name" to "합성 카드", "alias" to null,
        "last_four" to "1234", "ended_on" to null, "active_for_closure" to true)
    private fun page(items: List<Map<String, Any?>>) = mapOf("items" to items, "total_count" to items.size, "next_cursor" to null)
    private fun response(account: Boolean = false) = mapOf("resource_kind" to if (account) "account" else "card", "resource_id" to if (account) accountId else cardId,
        "resource_version" to 7, "asset_id" to if (account) assetId else null, "as_of_date" to day, "usage_digest" to digest, "requires_confirmation" to true,
        "coverage" to "registered_recurring_only", "account_withdrawal_total_available" to false, "rules" to page(listOf(rule(account))),
        "obligations" to page(listOf(obligation(account))), "cards" to page(if (account) listOf(card()) else emptyList()))
    private fun closure() = mapOf("ended_on" to day, "closure_ack" to true, "usage_digest" to digest)
    private fun mutation(operation: FinanceOperation, input: Map<String, Any?>): FinanceRequest {
        val card = operation in setOf(FinanceOperation.UPDATE_CARD, FinanceOperation.ARCHIVE_CARD)
        return FinancePolicy.prepare(operation, mapOf((if (card) "cardId" else "assetId") to if (card) cardId else assetId, "input" to input, "ifMatch" to tag))
    }

    @Test fun twoNamedGetCommandsUseOnlyFixedRoutesAndNoAuthenticationOrMutationHeaders() {
        for (account in listOf(false, true)) {
            val r = request(account, mapOf("as_of_date" to day, "rule_cursor" to ruleId, "obligation_cursor" to obligationId, "card_cursor" to cardId, "limit" to 200))
            assertTrue(FinancePolicy.metadataHttpAllowed("GET", r.path, null, null))
            assertFalse(AuthPolicy.requestAllowed("GET", r.path, null))
            assertFalse(FinancePolicy.metadataHttpAllowed("POST", r.path, null, null))
            assertFalse(FinancePolicy.metadataHttpAllowed("GET", r.path, emptyMap<String, Any>(), null))
            assertFalse(FinancePolicy.metadataHttpAllowed("GET", r.path, null, tag))
            assertFalse(FinancePolicy.metadataHttpAllowed("GET", r.path, null, null, "synthetic"))
            assertFalse(FinancePolicy.metadataHttpAllowed("GET", r.path.replace("payment-links", "reveal"), null, null))
        }
    }
    @Test fun queryDatesIndependentCursorsAndLimitsAreStrictAndCanonical() {
        val uppercase = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA"
        val r = FinancePolicy.prepare(FinanceOperation.GET_CARD_PAYMENT_LINKS, mapOf("resourceId" to uppercase, "query" to mapOf("rule_cursor" to uppercase)))
        assertEquals("/api/v1/cards/${uppercase.lowercase()}/payment-links?rule_cursor=${uppercase.lowercase()}", r.path)
        assertTrue(FinancePolicy.metadataHttpAllowed("GET", r.path, null, null))
        assertEquals("/api/v1/cards/$cardId/payment-links", request(query = mapOf("as_of_date" to null, "card_cursor" to null)).path)
        for (q in listOf(mapOf("as_of_date" to "2026-02-30"), mapOf("as_of_date" to "2026-01"), mapOf("rule_cursor" to 1), mapOf("limit" to 201),
            mapOf("limit" to 1.0), mapOf("limit" to null), mapOf("usage_digest" to digest), mapOf("as_of_date" to "$day&limit=200"))) bad { request(query = q) }
        for (extra in listOf("headers", "path", "url", "body", "method", "ifMatch", "idempotencyKey")) bad {
            FinancePolicy.prepare(FinanceOperation.GET_CARD_PAYMENT_LINKS, mapOf("resourceId" to cardId, extra to "synthetic"))
        }
        for (suffix in listOf("?limit=01", "?limit=1&limit=2", "?as_of_date=2026%2D01%2D31", "#synthetic"))
            assertFalse(FinancePolicy.metadataHttpAllowed("GET", "/api/v1/cards/$cardId/payment-links$suffix", null, null))
    }
    @Test fun allFourClosureCommandsKeepExplicitAckDigestAndDateTogether() {
        for (operation in listOf(FinanceOperation.UPDATE_ASSET, FinanceOperation.ARCHIVE_ASSET, FinanceOperation.UPDATE_CARD, FinanceOperation.ARCHIVE_CARD)) {
            val r = mutation(operation, closure())
            assertEquals(closure(), r.body)
            assertTrue(FinancePolicy.metadataHttpAllowed(r.method, r.path, r.body, r.ifMatch))
            assertEquals(mapOf("ended_on" to day), mutation(operation, mapOf("ended_on" to day)).body)
            assertEquals(mapOf("ended_on" to day, "closure_ack" to false, "usage_digest" to null),
                mutation(operation, mapOf("ended_on" to day, "closure_ack" to false, "usage_digest" to null)).body)
        }
    }
    @Test fun closureConfirmationCannotBeForgedFromTruthyValuesMissingPairsOrLooseDigests() {
        for (operation in listOf(FinanceOperation.UPDATE_ASSET, FinanceOperation.ARCHIVE_ASSET, FinanceOperation.UPDATE_CARD, FinanceOperation.ARCHIVE_CARD)) {
            for (body in listOf(closure() - "usage_digest", closure() - "ended_on", closure() + mapOf("ended_on" to null), closure() + mapOf("closure_ack" to false),
                closure() + mapOf("closure_ack" to 1), closure() + mapOf("closure_ack" to "true"), closure() + mapOf("closure_ack" to null),
                closure() + mapOf("usage_digest" to "A".repeat(64)), closure() + mapOf("usage_digest" to "a".repeat(63)), closure() + mapOf("usage_digest" to "g".repeat(64)),
                closure() + mapOf("usage_digest" to digest + "\n"), closure() - "closure_ack")) bad { mutation(operation, body) }
        }
        for (operation in listOf(FinanceOperation.UPDATE_ASSET, FinanceOperation.UPDATE_CARD)) {
            bad { mutation(operation, mapOf("closure_ack" to false, "usage_digest" to null)) }
        }
    }
    @Test fun closureFieldsAreCommandOnlyAndCannotEnterCreatesOrAccountMetadata() {
        val asset = mapOf("name" to "합성 자산", "kind" to "asset", "category" to "financial", "ownership_kind" to "joint", "amount_basis" to "whole", "started_on" to "2026-01-01")
        val card = mapOf("owner_member_id" to assetId, "issuer_name" to "합성", "product_name" to "합성", "card_type" to "credit")
        for ((operation, input) in listOf(FinanceOperation.CREATE_ASSET to asset, FinanceOperation.CREATE_CARD to card)) bad {
            FinancePolicy.prepare(operation, mapOf("input" to input + mapOf("closure_ack" to false)))
        }
        bad { FinancePolicy.prepare(FinanceOperation.UPDATE_ACCOUNT, mapOf("accountId" to accountId, "input" to closure(), "ifMatch" to tag)) }
        val cardGet = FinancePolicy.prepare(FinanceOperation.GET_CARD, mapOf("cardId" to cardId))
        val publicCard = mapOf<String, Any?>("id" to cardId, "household_id" to assetId, "owner_member_id" to assetId, "issuer_name" to "합성", "product_name" to "합성",
            "alias" to null, "card_type" to "credit", "has_secret" to false, "last_four" to null, "masked_number" to null, "settlement_day" to null, "settlement_account_id" to null,
            "settlement_account_status" to null, "started_on" to null, "ended_on" to null, "status" to "active", "note" to null,
            "created_by_member_id" to assetId, "updated_by_member_id" to assetId, "created_at" to "2026-01-01T00:00:00Z", "updated_at" to "2026-01-01T00:00:00Z", "version" to 7)
        assertEquals(publicCard, FinancePolicy.response(FinanceOperation.GET_CARD, cardGet, 200, publicCard))
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.GET_CARD, cardGet, 200, publicCard + mapOf("usage_digest" to digest)) }
    }
    @Test fun responseIdentityDateDigestAndLimitedCoverageMustMatchTheRequestedResource() {
        for (account in listOf(false, true)) {
            val r = request(account); val row = response(account)
            assertEquals(row, FinancePolicy.response(op(account), r, 200, row))
            for (change in listOf(mapOf("resource_kind" to "synthetic"), mapOf("resource_id" to ruleId), mapOf("resource_version" to 7.5), mapOf("as_of_date" to "2026-02-01"),
                mapOf("usage_digest" to "A".repeat(64)), mapOf("requires_confirmation" to "true"), mapOf("coverage" to "all_transactions"),
                mapOf("account_withdrawal_total_available" to true), mapOf("token" to "synthetic"))) bad(AuthCode.ACCESS_DENIED) {
                FinancePolicy.response(op(account), r, 200, row + change)
            }
        }
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(op(true), request(true), 200, response(true) + mapOf("asset_id" to null)) }
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(op(false), request(), 200, response() + mapOf("asset_id" to assetId)) }
    }
    @Test fun accountLinkedCardMayBeOnAnotherPageWithoutLosingItsRuleOrObligation() {
        val row = response(true) + mapOf("rules" to page(listOf(rule(false))), "obligations" to page(listOf(obligation(false))),
            "cards" to mapOf("items" to emptyList<Any>(), "total_count" to 10, "next_cursor" to null))
        assertEquals(row, FinancePolicy.response(op(true), request(true), 200, row))
        for (badRule in listOf(rule(true) + mapOf("account_id" to ruleId), rule(true) + mapOf("card_id" to cardId),
            rule(true) + mapOf("account_id" to null), rule(true) + mapOf("payment_basis" to "card_approval_plan"))) bad(AuthCode.ACCESS_DENIED) {
            FinancePolicy.response(op(true), request(true), 200, response(true) + mapOf("rules" to page(listOf(badRule))))
        }
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(op(false), request(), 200, response() + mapOf("rules" to page(listOf(rule() + mapOf("card_id" to assetId))))) }
    }
    @Test fun eachPageHasIndependentCursorTotalAndBoundedRowsInServerOrder() {
        val later = "00000000-0000-4000-8000-000000000006"
        val ascending = response(true) + mapOf("rules" to page(listOf(rule(true), rule(true) + mapOf("id" to later))))
        assertEquals(ascending, FinancePolicy.response(op(true), request(true), 200, ascending))
        val row = response(true) + mapOf("rules" to page(listOf(rule(true))) + mapOf("total_count" to 10, "next_cursor" to ruleId))
        assertEquals(row, FinancePolicy.response(op(true), request(true, mapOf("as_of_date" to day, "limit" to 1)), 200, row))
        for (change in listOf(mapOf("rules" to page(List(201) { rule(true) })), mapOf("rules" to page(listOf(rule(true))) + mapOf("total_count" to 0)),
            mapOf("obligations" to page(listOf(obligation(true))) + mapOf("next_cursor" to ruleId)),
            mapOf("cards" to page(listOf(card(), card()))), mapOf("cards" to page(listOf(card())) + mapOf("total_count" to -1)))) bad(AuthCode.ACCESS_DENIED) {
            FinancePolicy.response(op(true), request(true), 200, response(true) + change)
        }
        for ((cursor, itemId) in listOf("rule_cursor" to ruleId, "obligation_cursor" to obligationId, "card_cursor" to cardId)) bad(AuthCode.ACCESS_DENIED) {
            FinancePolicy.response(op(true), request(true, mapOf("as_of_date" to day, cursor to itemId)), 200, response(true))
        }
    }
    @Test fun linkedAmountsKeepNullZeroAndLargeStringsWhileCurrentFutureAndPaymentBasisRemainExplicit() {
        for (expected in listOf(null, "0", "99999999999999999999")) {
            val future = rule() + mapOf("amount_mode" to "variable", "expected_amount_krw" to expected, "period" to "future", "effective_from" to "2026-02-01", "effective_until" to "2026-03-01")
            val row = response() + mapOf("rules" to page(listOf(future)), "obligations" to page(listOf(obligation() + mapOf("expected_amount_krw" to expected, "actual_paid_krw" to "1", "status" to "partial"))))
            assertEquals(row, FinancePolicy.response(op(false), request(), 200, row))
        }
        for (change in listOf(mapOf("rules" to page(listOf(rule() + mapOf("expected_amount_krw" to 33000)))),
            mapOf("rules" to page(listOf(rule() + mapOf("period" to "future")))), mapOf("rules" to page(listOf(rule() + mapOf("effective_until" to day)))),
            mapOf("obligations" to page(listOf(obligation() + mapOf("actual_paid_krw" to 0)))), mapOf("obligations" to page(listOf(obligation() + mapOf("status" to "partial")))))) bad(AuthCode.ACCESS_DENIED) {
            FinancePolicy.response(op(false), request(), 200, response() + change)
        }
    }
    @Test fun linkedCardClosureActivityIncludesTheSelectedEndDayAndOnlyLastFourDigits() {
        for ((end, active) in listOf(null to true, "2026-01-30" to false, day to true, "2026-02-01" to true)) {
            val row = response(true) + mapOf("cards" to page(listOf(card() + mapOf("ended_on" to end, "active_for_closure" to active))))
            assertEquals(row, FinancePolicy.response(op(true), request(true), 200, row))
        }
        for (change in listOf(mapOf("active_for_closure" to false), mapOf("last_four" to "12345"), mapOf("last_four" to "１２３４"), mapOf("pan" to "synthetic"))) bad(AuthCode.ACCESS_DENIED) {
            FinancePolicy.response(op(true), request(true), 200, response(true) + mapOf("cards" to page(listOf(card() + change))))
        }
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(op(false), request(), 200, response() + mapOf("cards" to page(listOf(card())))) }
    }
    @Test fun nestedUnknownSecretsAndUnrequestedCardOrAccountFieldsNeverCrossTheBridge() {
        for (change in listOf(mapOf("rules" to page(listOf(rule() + mapOf("ciphertext" to "synthetic")))),
            mapOf("obligations" to page(listOf(obligation() + mapOf("account_number" to "synthetic")))),
            mapOf("rules" to page(listOf(rule())) + mapOf("cvc" to "synthetic")))) bad(AuthCode.ACCESS_DENIED) {
            FinancePolicy.response(op(false), request(), 200, response() + change)
        }
    }
    @Test fun lockRecoveryAndKnownClosureErrorsKeepTheirExistingBoundaries() {
        val lock = AppLockPolicy().also { it.resume(0, false) }
        for (kind in AppRequestKind.entries) assertFalse(lock.httpAllowed(lock.ticket(kind), "GET", "/api/v1/cards/$cardId/payment-links"))
        for (code in listOf("PAYMENT_LINKS_CHANGED", "PAYMENT_LINK_CONFIRMATION_REQUIRED")) {
            val safe = AuthPolicy.safeError(409, mapOf("error" to mapOf("code" to code, "message" to "synthetic secret")), ruleId)!!
            assertEquals(code, (safe["error"] as Map<*, *>)["code"])
            assertFalse(safe.toString().contains("synthetic"))
        }
    }
}
