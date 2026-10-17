package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test
import java.time.Instant

class FinancePolicyTest {
    private val assetId = "00000000-0000-4000-8000-000000000001"
    private val accountId = "00000000-0000-4000-8000-000000000002"
    private val householdId = "00000000-0000-4000-8000-000000000003"
    private val memberId = "00000000-0000-4000-8000-000000000004"
    private val now = "2026-01-01T00:00:00Z"
    private fun input() = mapOf<String, Any?>("name" to "합성 자산", "kind" to "asset", "category" to "financial",
        "ownership_kind" to "joint", "owner_member_id" to null, "household_share" to "0.5", "amount_basis" to "whole",
        "inclusion_status" to "included", "started_on" to "2026-01-01", "ended_on" to null, "note" to null)
    private fun asset() = input() + mapOf("id" to assetId, "household_id" to householdId, "status" to "active", "archived_at" to null,
        "created_by_member_id" to memberId, "updated_by_member_id" to memberId, "created_at" to now, "updated_at" to now, "version" to 1)
    private fun account() = mapOf<String, Any?>("id" to accountId, "household_id" to householdId, "asset_id" to assetId,
        "asset" to asset(), "institution_name" to "합성 기관", "account_type" to "irp", "masked_number" to "**** A123",
        "has_number" to true, "purpose" to null, "opened_on" to null, "closed_on" to null, "status" to "active",
        "created_by_member_id" to memberId, "updated_by_member_id" to memberId, "created_at" to now, "updated_at" to now, "version" to 2)
    private fun invalid(code: AuthCode = AuthCode.INVALID_REQUEST, action: () -> Unit) {
        try { action(); fail("Unsafe finance input accepted") } catch (failure: AuthFailure) {
            assertEquals(code, failure.code); assertNull(failure.message)
        }
    }

    @Test fun namedAssetOperationsBuildOnlyTheirFixedHttpContracts() {
        val create = FinancePolicy.prepare(FinanceOperation.CREATE_ASSET, mapOf("input" to input()))
        assertEquals("POST", create.method); assertEquals("/api/v1/assets", create.path); assertEquals(input(), create.body)
        val update = FinancePolicy.prepare(FinanceOperation.UPDATE_ASSET, mapOf("assetId" to assetId, "input" to mapOf("note" to null), "ifMatch" to "\"3\""))
        assertEquals("PATCH", update.method); assertEquals("\"3\"", update.ifMatch)
        val archive = FinancePolicy.prepare(FinanceOperation.ARCHIVE_ASSET, mapOf("assetId" to assetId, "input" to mapOf("ended_on" to "2026-12-31"), "ifMatch" to "\"3\""))
        assertEquals("/api/v1/assets/$assetId/archive", archive.path)
        val delete = FinancePolicy.prepare(FinanceOperation.DELETE_ASSET, mapOf("assetId" to assetId, "ifMatch" to "\"3\""))
        assertNull(FinancePolicy.response(FinanceOperation.DELETE_ASSET, delete, 204, null))
        for (request in listOf(create, update, archive, delete)) assertTrue(FinancePolicy.metadataHttpAllowed(request.method, request.path, request.body, request.ifMatch))
    }

    @Test fun unconfirmedClosureDefaultPreservesExistingMetadataCommands() {
        val patch = FinancePolicy.prepare(FinanceOperation.UPDATE_ASSET, mapOf("assetId" to assetId,
            "input" to mapOf("note" to "합성 수정", "closure_ack" to false), "ifMatch" to "\"1\""))
        val archive = FinancePolicy.prepare(FinanceOperation.ARCHIVE_ASSET, mapOf("assetId" to assetId,
            "input" to mapOf("ended_on" to "2026-12-31", "closure_ack" to false), "ifMatch" to "\"1\""))
        for (request in listOf(patch, archive)) assertTrue(FinancePolicy.metadataHttpAllowed(request.method, request.path, request.body, request.ifMatch))
        invalid { FinancePolicy.assetInput(mapOf("closure_ack" to false), true) }
        invalid { FinancePolicy.assetInput(mapOf("note" to "합성", "closure_ack" to true, "payment_links_digest" to "invalid"), true) }
        invalid { FinancePolicy.assetInput(input() + ("closure_ack" to false), false) }
    }

    @Test fun urlsHeadersUnknownFieldsAndWeakVersionsCannotEnterNamedCommands() {
        for (extra in listOf("url", "path", "method", "headers", "Authorization", "body", "stepUpToken")) {
            invalid { FinancePolicy.prepare(FinanceOperation.GET_ASSET, mapOf("assetId" to assetId, extra to "synthetic")) }
        }
        for (id in listOf("https://synthetic.invalid", "../$assetId", "$assetId/reveal", "$assetId?x=1")) {
            invalid { FinancePolicy.prepare(FinanceOperation.GET_ASSET, mapOf("assetId" to id)) }
        }
        for (tag in listOf(null, "1", "\"0\"", "W/\"1\"", "*")) invalid {
            FinancePolicy.prepare(FinanceOperation.UPDATE_ASSET, mapOf("assetId" to assetId, "input" to mapOf("name" to "합성"), "ifMatch" to tag))
        }
    }

    @Test fun filterQueriesAcceptOnlyBoundedTypedEnumsIdsAndPagination() {
        val request = FinancePolicy.prepare(FinanceOperation.LIST_ASSETS, mapOf("query" to mapOf("limit" to 200, "status" to "all", "kind" to "liability", "owner_member_id" to memberId)))
        assertEquals("/api/v1/assets?kind=liability&limit=200&owner_member_id=$memberId&status=all", request.path)
        assertTrue(FinancePolicy.metadataHttpAllowed("GET", request.path, null, null))
        for (query in listOf(mapOf("limit" to 201), mapOf("limit" to 1.0), mapOf("kind" to "cash"), mapOf("cursor" to "synthetic"), mapOf("account_number" to "synthetic"))) {
            invalid { FinancePolicy.prepare(FinanceOperation.LIST_ASSETS, mapOf("query" to query)) }
        }
        assertFalse(FinancePolicy.metadataHttpAllowed("GET", "/api/v1/assets?limit=1&limit=2", null, null))
        assertFalse(FinancePolicy.metadataHttpAllowed("GET", "/api/v1/assets?limit=01", null, null))
    }

    @Test fun assetInputsKeepDecimalStringsNullsAndDateOnlyRules() {
        assertEquals("0.5", FinancePolicy.assetInput(input(), false)["household_share"])
        assertTrue(FinancePolicy.assetInput(mapOf("ended_on" to null, "note" to null), true).containsKey("ended_on"))
        for (change in listOf(mapOf("household_share" to 0.5), mapOf("household_share" to "1.1"),
            mapOf("started_on" to "2026-02-30"), mapOf("started_on" to "2026-01-01T00:00:00Z"),
            mapOf("ended_on" to "2025-12-31"), mapOf("ownership_kind" to "individual"), mapOf("name" to null))) {
            invalid { FinancePolicy.assetInput(input()+change, false) }
        }
        invalid { FinancePolicy.assetInput(emptyMap<String, Any>(), true) }
    }

    @Test fun accountMetadataNeverAcceptsNumberCiphertextOrGrantEvenAsNull() {
        val create = mapOf("asset_id" to assetId, "institution_name" to "합성 기관", "account_type" to "irp")
        assertEquals(create, FinancePolicy.accountInput(create, false))
        assertEquals("pension_savings", FinancePolicy.accountInput(mapOf("account_type" to "pension_savings"), true)["account_type"])
        for (field in listOf("account_number", "accountNumber", "account_number_ciphertext", "number_nonce", "number_key_version", "grant_token")) {
            invalid { FinancePolicy.accountInput(create+mapOf(field to null), false) }
            invalid { FinancePolicy.accountInput(mapOf(field to "synthetic"), true) }
        }
        invalid { FinancePolicy.accountInput(create+mapOf("asset" to input()), false) }
        invalid { FinancePolicy.accountInput(mapOf("institution_name" to "합성", "account_type" to "irp", "asset" to input()+mapOf("category" to "deposit")), false) }
    }

    @Test fun responseProjectionRejectsFullNumbersAndMalformedMasksOrNestedSecretFields() {
        assertEquals(account(), FinancePolicy.account(account()))
        val request = FinancePolicy.prepare(FinanceOperation.GET_ACCOUNT, mapOf("accountId" to accountId))
        for (change in listOf(mapOf("masked_number" to "SYNTHETIC-ACCOUNT-123"), mapOf("masked_number" to "**** 12345"),
            mapOf("has_number" to false), mapOf("account_number" to "synthetic"),
            mapOf("asset" to asset()+mapOf("account_number" to "synthetic")), mapOf("asset_id" to memberId),
            mapOf("asset" to asset()+mapOf("household_id" to memberId)), mapOf("version" to 2.5))) {
            invalid(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.GET_ACCOUNT, request, 200, account()+change) }
        }
        assertEquals(null, FinancePolicy.account(account()+mapOf("has_number" to false, "masked_number" to null))["masked_number"])
        invalid(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.GET_ACCOUNT, request, 200, account()+mapOf("id" to assetId)) }
    }

    @Test fun listProjectionLimitsCardinalityAndRejectsUnknownTopLevelFields() {
        val request = FinancePolicy.prepare(FinanceOperation.LIST_ASSETS, emptyMap<String, Any>())
        val list = mapOf("items" to listOf(asset()), "next_cursor" to null)
        assertEquals(list, FinancePolicy.response(FinanceOperation.LIST_ASSETS, request, 200, list))
        invalid(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.LIST_ASSETS, request, 200, list+mapOf("items" to List(201) { asset() })) }
        invalid(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.LIST_ASSETS, request, 200, list+mapOf("token" to "synthetic")) }
    }

    @Test fun numberRequestsStayOutsideBothGenericAndFinanceMetadataPaths() {
        val path = "/api/v1/accounts/$accountId"
        assertFalse(AuthPolicy.requestAllowed("GET", path, null))
        assertFalse(AuthPolicy.requestAllowed("POST", "$path/reveal", null))
        assertFalse(FinancePolicy.metadataHttpAllowed("POST", "$path/reveal", emptyMap<String, Any>(), null))
        assertFalse(FinancePolicy.metadataHttpAllowed("PATCH", path, mapOf("account_number" to null), "\"1\""))
        assertFalse(FinancePolicy.metadataHttpAllowed("DELETE", path, null, "\"1\""))
        assertTrue(FinancePolicy.numberPath(path, false))
        assertTrue(FinancePolicy.numberPath("$path/reveal", true))
        for (bad in listOf("$path/reveal?x=1", "$path/../reveal", "https://synthetic.invalid$path/reveal")) assertFalse(FinancePolicy.numberPath(bad, true))
    }

    @Test fun accountRevealGrantIsBoundToPurposeTargetExpiryAndOnlyItsPostEndpoint() {
        val token = "A".repeat(43)
        val grant = mapOf("grant_token" to token, "purpose" to "account.reveal", "target_id" to accountId, "expires_at" to "2026-01-01T00:02:00Z")
        assertEquals(token, PasskeyPolicy.grant(grant, "account.reveal", accountId, Instant.parse(now)))
        for ((purpose, id) in listOf("device.revoke" to accountId, "account.reveal" to assetId)) {
            invalid(AuthCode.PASSKEY_FAILED) { PasskeyPolicy.grant(grant, purpose, id, Instant.parse(now)) }
        }
        assertTrue(PasskeyPolicy.stepUpHeaderAllowed("POST", "/api/v1/accounts/$accountId/reveal", null, token))
        assertFalse(PasskeyPolicy.stepUpHeaderAllowed("PATCH", "/api/v1/accounts/$accountId", "\"1\"", token))
    }

    @Test fun nativeNumberValidationUsesOnlyBoundedAsciiIdentifiers() {
        for (number in listOf("SYNTHETIC123", "SYN-THETIC 123", "12345")) assertTrue(FinancePolicy.number(number.toCharArray()))
        for (number in listOf("1234", "A".repeat(41), "-SYNTHETIC", "SYNTHETIC-", "합성12345", "ABCDE\n", "A   B")) assertFalse(FinancePolicy.number(number.toCharArray()))
    }

    @Test fun revealResponseRequiresTheRequestedAccountAndExactThirtySecondPolicy() {
        val response = mapOf("id" to accountId, "account_number" to "SYNTHETIC123", "display_for_seconds" to 30)
        val number = FinancePolicy.readNumber(response, accountId)
        assertEquals("SYNTHETIC123", String(number)); number.fill('\u0000')
        for (change in listOf(mapOf("id" to assetId), mapOf("display_for_seconds" to 31),
            mapOf("account_number" to "invalid/format"), mapOf("ciphertext" to "synthetic"))) {
            invalid(AuthCode.ACCESS_DENIED) { FinancePolicy.readNumber(response+change, accountId) }
        }
    }
}
