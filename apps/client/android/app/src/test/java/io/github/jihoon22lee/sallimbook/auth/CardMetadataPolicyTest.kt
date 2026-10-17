package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class CardMetadataPolicyTest {
    private val id = "00000000-0000-4000-8000-000000000001"
    private val accountId = "00000000-0000-4000-8000-000000000002"
    private val version = "\"3\""
    private fun input() = mapOf<String, Any?>("owner_member_id" to id, "issuer_name" to "합성 카드사", "product_name" to "합성 카드", "alias" to null,
        "card_type" to "credit", "last_four" to "1234", "settlement_day" to 31, "settlement_account_id" to accountId,
        "started_on" to "2026-01-01", "ended_on" to null, "note" to null)
    private fun card() = input() + mapOf("id" to id, "household_id" to id, "masked_number" to "**** 1234", "settlement_account_status" to "active",
        "status" to "active", "created_by_member_id" to id, "updated_by_member_id" to id, "created_at" to "2026-01-01T00:00:00Z",
        "updated_at" to "2026-01-01T00:00:00Z", "version" to 3)
    private fun request(op: FinanceOperation, args: Map<String, Any?>) = FinancePolicy.prepare(op, args)
    private fun bad(code: AuthCode = AuthCode.INVALID_REQUEST, action: () -> Unit) {
        try { action(); fail("Unsafe card input or response accepted") }
        catch (failure: AuthFailure) { assertEquals(code, failure.code); assertNull(failure.message) }
    }

    @Test fun sixCommandsOnlyReachFixedMetadataPathsWithStrongVersions() {
        val requests = listOf(
            request(FinanceOperation.LIST_CARDS, mapOf("query" to mapOf("owner_member_id" to id, "card_type" to "debit", "settlement_account_id" to accountId, "limit" to 200, "status" to "all"))),
            request(FinanceOperation.GET_CARD, mapOf("cardId" to id)),
            request(FinanceOperation.CREATE_CARD, mapOf("input" to input())),
            request(FinanceOperation.UPDATE_CARD, mapOf("cardId" to id, "input" to mapOf("alias" to null), "ifMatch" to version)),
            request(FinanceOperation.ARCHIVE_CARD, mapOf("cardId" to id, "input" to mapOf("ended_on" to "2026-01-31"), "ifMatch" to version)),
            request(FinanceOperation.DELETE_CARD, mapOf("cardId" to id, "ifMatch" to version)),
        )
        for (r in requests) {
            assertTrue(FinancePolicy.metadataHttpAllowed(r.method, r.path, r.body, r.ifMatch))
            assertFalse(AuthPolicy.requestAllowed(r.method, r.path, r.ifMatch))
            assertFalse(FinancePolicy.metadataHttpAllowed(r.method, r.path, r.body, r.ifMatch, "synthetic"))
            assertFalse(FinancePolicy.metadataHttpAllowed(r.method, r.path + "/secret", r.body, r.ifMatch))
        }
        assertTrue(requests[0].path.startsWith("/api/v1/cards?card_type=debit&limit=200&owner_member_id="))
        assertNull(FinancePolicy.response(FinanceOperation.DELETE_CARD, requests[5], 204, null))
    }
    @Test fun panExpiryCvcCiphertextAndArbitraryTransportFieldsNeverEnterMetadataCommands() {
        for (field in listOf("pan", "card_number", "expiry", "expiry_month", "expiry_year", "cvc", "cvv", "ciphertext", "secret", "secret_envelope", "grant_token")) {
            bad { request(FinanceOperation.CREATE_CARD, mapOf("input" to input() + mapOf(field to null))) }
            bad { request(FinanceOperation.UPDATE_CARD, mapOf("cardId" to id, "input" to mapOf(field to "synthetic"), "ifMatch" to version)) }
            assertFalse(FinancePolicy.metadataHttpAllowed("PATCH", "/api/v1/cards/$id", mapOf(field to "synthetic"), version))
        }
        for (field in listOf("url", "path", "method", "body", "headers", "accessToken", "idempotencyKey")) bad {
            request(FinanceOperation.GET_CARD, mapOf("cardId" to id, field to "synthetic"))
        }
        for (path in listOf("/api/v1/cards/$id/reveal", "/api/v1/cards/$id/secret-envelope", "/api/v1/cards/$id/cvc")) {
            assertFalse(FinancePolicy.metadataHttpAllowed("GET", path, null, null))
            assertFalse(FinancePolicy.metadataHttpAllowed("POST", path, emptyMap<String, Any>(), null))
        }
    }
    @Test fun lastFourIsExactlyFourAsciiDigitsAndSettlementDayIsAnInteger() {
        for (value in listOf("123", "12345", "１２３４", "SYNTHETIC", 1234)) bad {
            request(FinanceOperation.CREATE_CARD, mapOf("input" to input() + mapOf("last_four" to value)))
        }
        for (value in listOf(0, 32, 31.0, "31")) bad {
            request(FinanceOperation.CREATE_CARD, mapOf("input" to input() + mapOf("settlement_day" to value)))
        }
        for (value in listOf(null, "0000", "1234")) request(FinanceOperation.CREATE_CARD, mapOf("input" to input() + mapOf("last_four" to value)))
    }
    @Test fun requiredMetadataCannotBeNullAndOptionalFieldsCanBeExplicitlyCleared() {
        val patch = mapOf("alias" to null, "last_four" to null, "settlement_day" to null, "settlement_account_id" to null, "started_on" to null, "ended_on" to null, "note" to null)
        assertEquals(patch, request(FinanceOperation.UPDATE_CARD, mapOf("cardId" to id, "input" to patch, "ifMatch" to version)).body)
        for (field in listOf("owner_member_id", "issuer_name", "product_name", "card_type")) {
            bad { request(FinanceOperation.CREATE_CARD, mapOf("input" to input() - field)) }
            bad { request(FinanceOperation.UPDATE_CARD, mapOf("cardId" to id, "input" to mapOf(field to null), "ifMatch" to version)) }
        }
        bad { request(FinanceOperation.UPDATE_CARD, mapOf("cardId" to id, "input" to emptyMap<String, Any>(), "ifMatch" to version)) }
        bad { request(FinanceOperation.CREATE_CARD, mapOf("input" to input() + mapOf("ended_on" to "2025-12-31"))) }
        bad { request(FinanceOperation.ARCHIVE_CARD, mapOf("cardId" to id, "input" to mapOf("ended_on" to "2026-02-30"), "ifMatch" to version)) }
    }
    @Test fun idsQueriesAndVersionTagsCannotSmugglePathsOrMalformedNumbers() {
        for (value in listOf("$id/reveal", "../$id", "https://synthetic.invalid", "$id?x=1")) bad {
            request(FinanceOperation.GET_CARD, mapOf("cardId" to value))
        }
        for (tag in listOf("3", "W/\"3\"", "*", "\"0\"", "\"3\"\r\nX: synthetic")) bad {
            request(FinanceOperation.DELETE_CARD, mapOf("cardId" to id, "ifMatch" to tag))
        }
        for (query in listOf(mapOf("limit" to 201), mapOf("limit" to 1.0), mapOf("card_type" to "other"), mapOf("status" to null), mapOf("last_four" to "1234"))) bad {
            request(FinanceOperation.LIST_CARDS, mapOf("query" to query))
        }
        assertEquals("/api/v1/cards", request(FinanceOperation.LIST_CARDS, mapOf("query" to mapOf("cursor" to null, "card_type" to null))).path)
        for (suffix in listOf("?limit=01", "?limit=1&limit=2", "?cursor=", "#synthetic", "/$id/../$id"))
            assertFalse(FinancePolicy.metadataHttpAllowed("GET", "/api/v1/cards$suffix", null, null))
    }
    @Test fun publicResponseRequiresMatchingLastFourMaskTargetAndClosedAccountMetadata() {
        val get = request(FinanceOperation.GET_CARD, mapOf("cardId" to id))
        assertEquals(card(), FinancePolicy.response(FinanceOperation.GET_CARD, get, 200, card()))
        val closed = card() + mapOf("settlement_account_status" to "closed")
        assertEquals(closed, FinancePolicy.response(FinanceOperation.GET_CARD, get, 200, closed))
        for (change in listOf(mapOf("id" to accountId), mapOf("masked_number" to "**** 9999"), mapOf("masked_number" to "SYNTHETIC FULL NUMBER"),
            mapOf("last_four" to null), mapOf("settlement_account_status" to null), mapOf("settlement_account_id" to null),
            mapOf("status" to "closed"), mapOf("version" to 3.5), mapOf("note" to mapOf("secret" to "synthetic")), mapOf("cvc" to "synthetic"))) bad(AuthCode.ACCESS_DENIED) {
            FinancePolicy.response(FinanceOperation.GET_CARD, get, 200, card() + change)
        }
        val absent = card() + mapOf("last_four" to null, "masked_number" to null, "settlement_account_id" to null, "settlement_account_status" to null)
        assertEquals(absent, FinancePolicy.response(FinanceOperation.GET_CARD, get, 200, absent))
    }
    @Test fun listAndDeletionResponsesCannotReturnUnexpectedSecretsOrOversizedCollections() {
        val list = request(FinanceOperation.LIST_CARDS, emptyMap())
        val body = mapOf("items" to listOf(card()), "next_cursor" to null)
        assertEquals(body, FinancePolicy.response(FinanceOperation.LIST_CARDS, list, 200, body))
        for (change in listOf(mapOf("items" to List(201) { card() }), mapOf("items" to listOf(card() + mapOf("ciphertext" to "synthetic"))),
            mapOf("next_cursor" to "synthetic"), mapOf("pan" to "synthetic"))) bad(AuthCode.ACCESS_DENIED) {
            FinancePolicy.response(FinanceOperation.LIST_CARDS, list, 200, body + change)
        }
        val delete = request(FinanceOperation.DELETE_CARD, mapOf("cardId" to id, "ifMatch" to version))
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.DELETE_CARD, delete, 204, card()) }
    }
    @Test fun lockedRecoveryCannotReadCardsAndKnownErrorsDoNotCopyServerSecrets() {
        val lock = AppLockPolicy().also { it.resume(0, false) }
        for (kind in AppRequestKind.entries) assertFalse(lock.httpAllowed(lock.ticket(kind), "GET", "/api/v1/cards"))
        val error = AuthPolicy.safeError(409, mapOf("error" to mapOf("code" to "CARD_IN_USE", "message" to "synthetic secret")), id)!!
        assertEquals("CARD_IN_USE", (error["error"] as Map<*, *>)["code"])
        assertFalse(error.toString().contains("synthetic"))
    }
}
