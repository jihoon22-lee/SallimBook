package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class NativeDocumentPolicyTest {
    private val id = "00000000-0000-4000-8000-000000000030"
    private val link = "00000000-0000-4000-8000-000000000020"
    private val target = "00000000-0000-4000-8000-000000000010"
    private val now = "2026-01-01T00:00:00Z"
    private val hash = "a".repeat(64)
    private val tag = "\"7\""
    private val targetValue = mapOf("kind" to "case", "id" to target)
    private val audit = mapOf("household_id" to target, "created_by_member_id" to target, "updated_by_member_id" to target,
        "created_at" to now, "updated_at" to now, "version" to 7)
    private val document = audit + mapOf("id" to id, "original_name" to "합성.pdf", "mime_type" to "application/pdf",
        "size_bytes" to 100, "checksum_sha256" to hash, "state" to "ready", "pending_expires_at" to now,
        "stored_at" to now, "orphaned_at" to null, "deleted_at" to null, "active_link_count" to 1)
    private val linked = audit + mapOf("id" to link, "document_id" to id, "target" to targetValue,
        "active" to true, "ended_at" to null, "end_reason" to null)
    private val reason = mapOf("reason" to "합성 정정")
    private val headers = mapOf("ifMatch" to tag, "idempotencyKey" to "synthetic:document:1")
    private fun bad(code: AuthCode = AuthCode.INVALID_REQUEST, action: () -> Unit) {
        try { action(); fail("Invalid synthetic attachment accepted") }
        catch (failure: AuthFailure) { assertEquals(code, failure.code); assertNull(failure.message) }
    }
    private fun commands() = listOf(
        FinanceOperation.LIST_DOCUMENTS to emptyMap(),
        FinanceOperation.GET_DOCUMENT to mapOf("documentId" to id),
        FinanceOperation.DELETE_DOCUMENT to headers + mapOf("documentId" to id, "input" to reason),
        FinanceOperation.CREATE_DOCUMENT_LINK to headers + mapOf("input" to mapOf("document_id" to id, "target" to targetValue)),
        FinanceOperation.LIST_DOCUMENT_LINKS to mapOf("documentId" to id),
        FinanceOperation.END_DOCUMENT_LINK to headers + mapOf("linkId" to link, "input" to reason))
    @Test fun sixMetadataCommandsHaveFixedRoutesAndNoFileAccess() {
        for ((op, args) in commands()) {
            val r = FinancePolicy.prepare(op, args)
            assertTrue(FinancePolicy.metadataHttpAllowed(r.method, r.path, r.body, r.ifMatch, r.idempotencyKey))
            assertFalse(AuthPolicy.requestAllowed(r.method, r.path, r.ifMatch))
            for (field in listOf("url", "uri", "bytes", "base64", "headers", "contains_no_card_data")) bad { FinancePolicy.prepare(op, args + mapOf(field to null)) }
            if (r.ifMatch != null) bad { FinancePolicy.prepare(op, args - "ifMatch") }
            else bad { FinancePolicy.prepare(op, args + mapOf("ifMatch" to tag)) }
            if (r.idempotencyKey != null) bad { FinancePolicy.prepare(op, args - "idempotencyKey") }
        }
        for ((method, path) in listOf("POST" to "/api/v1/documents", "PUT" to "/api/v1/documents/$id/content", "GET" to "/api/v1/documents/$id/download"))
            assertFalse(FinancePolicy.metadataHttpAllowed(method, path, null, null))
    }
    @Test fun metadataResponsesHaveExactShapesAndImmutableReceiptVersions() {
        for ((op, args) in commands()) {
            val value = when (op) {
                FinanceOperation.LIST_DOCUMENTS -> mapOf("items" to listOf(document), "next_cursor" to null)
                FinanceOperation.GET_DOCUMENT -> document
                FinanceOperation.LIST_DOCUMENT_LINKS -> mapOf("items" to listOf(linked), "next_cursor" to null)
                FinanceOperation.DELETE_DOCUMENT -> mapOf("id" to id, "version" to 2)
                else -> mapOf("id" to link, "version" to 1)
            }
            val request = FinancePolicy.prepare(op, args)
            val status = if (op == FinanceOperation.CREATE_DOCUMENT_LINK) 201 else 200
            assertEquals(value, FinancePolicy.response(op, request, status, value))
            assertEquals(value, FinancePolicy.response(op, request, status, withAddedFields(value)))
            assertEquals(value, FinancePolicy.response(op, request, status, value + mapOf("content" to "synthetic")))
            bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(op, request, status, value + mapOf("content_token" to "synthetic")) }
            bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(op, request, 202, value) }
        }
    }
    @Test fun targetsQueriesAndHeadersRejectCrossDomainAndCoercion() {
        for (kind in listOf("card", "account", "vault", "document", "unknown")) bad { NativeDocumentPolicy.target(mapOf("kind" to kind, "id" to target)) }
        for (query in listOf(mapOf("target_kind" to "case"), mapOf("target_id" to target), mapOf("limit" to "2"), mapOf("limit" to 2.0), mapOf("limit" to 201), mapOf("url" to "synthetic")))
            bad { FinancePolicy.prepare(FinanceOperation.LIST_DOCUMENTS, mapOf("query" to query)) }
        FinancePolicy.prepare(FinanceOperation.LIST_DOCUMENTS, mapOf("query" to mapOf("target_kind" to "case", "target_id" to target)))
        for (version in listOf("7", "W/\"7\"", "\"0\"", "\"9007199254740992\"")) bad {
            FinancePolicy.prepare(FinanceOperation.DELETE_DOCUMENT, headers + mapOf("documentId" to id, "input" to reason, "ifMatch" to version))
        }
    }
    @Test fun nativeOnlyCreateValidatesConfirmationHashActualSizeAndName() {
        val input = mapOf("original_name" to "합성.pdf", "mime_type" to "application/pdf", "size_bytes" to 100,
            "checksum_sha256" to hash, "target" to targetValue, "contains_no_card_data" to true)
        assertEquals(input, NativeDocumentPolicy.create(input, "synthetic:create").body)
        for (change in listOf(mapOf("contains_no_card_data" to false), mapOf("contains_no_card_data" to "true"),
            mapOf("size_bytes" to 0), mapOf("size_bytes" to 20_971_521), mapOf("size_bytes" to 100.0), mapOf("checksum_sha256" to hash.uppercase()),
            mapOf("uri" to "content://synthetic/private"), mapOf("mime_type" to "text/html"))) bad { NativeDocumentPolicy.create(input + change, "synthetic:create") }
        for (name in listOf("../합성.pdf", "합성/파일.pdf", "합성\\파일.pdf", " 합성.pdf", "합성.pdf ", "합성\u200b.pdf", "합성\n.pdf", "합성.jpg", ".", ".."))
            bad { NativeDocumentPolicy.create(input + mapOf("original_name" to name), "synthetic:create") }
        assertFalse(NativeDocumentPolicy.createHttpAllowed("POST", "/api/v1/documents", input, tag, "synthetic:create"))
        assertFalse(NativeDocumentPolicy.createHttpAllowed("POST", "/api/v1/documents?x=1", input, null, "synthetic:create"))
    }
    @Test fun documentStatesAndTypedLinksCannotSmuggleBytesOrInternalStoragePaths() {
        val request = FinancePolicy.prepare(FinanceOperation.GET_DOCUMENT, mapOf("documentId" to id))
        for (change in listOf(mapOf("id" to link), mapOf("size_bytes" to 0), mapOf("size_bytes" to 100.0),
            mapOf("stored_at" to null), mapOf("state" to "pending"), mapOf("checksum_sha256" to "x"),
            mapOf("nonce" to null), mapOf("ciphertext" to listOf(1, 2)), mapOf("deleted_at" to now)))
            bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.GET_DOCUMENT, request, 200, document + change) }
        // Added fields that are not secrets are dropped, so bytes or storage paths never reach the WebView.
        for (change in listOf(mapOf("storage_key" to "synthetic"), mapOf("bytes" to listOf(1, 2))))
            assertEquals(document, FinancePolicy.response(FinanceOperation.GET_DOCUMENT, request, 200, document + change))
        val linkRequest = FinancePolicy.prepare(FinanceOperation.LIST_DOCUMENT_LINKS, mapOf("documentId" to id))
        for (change in listOf(mapOf("document_id" to link), mapOf("active" to false), mapOf("target" to mapOf("kind" to "card", "id" to target))))
            bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(FinanceOperation.LIST_DOCUMENT_LINKS, linkRequest, 200, mapOf("items" to listOf(linked + change), "next_cursor" to null)) }
    }
    @Test fun listsRespectDefaultLimitCursorHouseholdAndDeletedState() {
        val op = FinanceOperation.LIST_DOCUMENTS
        val request = FinancePolicy.prepare(op, mapOf("query" to mapOf("limit" to 1)))
        for (body in listOf(mapOf("items" to listOf(document, document), "next_cursor" to null),
            mapOf("items" to listOf(document), "next_cursor" to link), mapOf("items" to listOf(document + mapOf("state" to "deleted", "deleted_at" to now)), "next_cursor" to null)))
            bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(op, request, 200, body) }
        val cursor = FinancePolicy.prepare(op, mapOf("query" to mapOf("cursor" to id)))
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(op, cursor, 200, mapOf("items" to listOf(document), "next_cursor" to null)) }
    }
    @Test fun downloadRequiresReadyLinkedDocumentAndNoHttpPathInjection() {
        val info = NativeDocumentPolicy.info(document, id)
        assertEquals(100, info.size)
        assertEquals("/api/v1/documents/$id/download", NativeDocumentPolicy.binaryPath(id, false))
        assertEquals("/api/v1/documents/$id/content", NativeDocumentPolicy.binaryPath(id, true))
        bad { NativeDocumentPolicy.binaryPath("$id/../secret", false) }
        bad(AuthCode.ACCESS_DENIED) { NativeDocumentPolicy.info(document + mapOf("active_link_count" to 0), id) }
        bad(AuthCode.ACCESS_DENIED) { NativeDocumentPolicy.info(document + mapOf("state" to "pending", "stored_at" to null), id) }
        assertFalse(info.toString().contains("합성"))
    }
    @Test fun aReferenceReadAfterAWriteToleratesAddedFieldsAndIsOtherwiseUnknown() {
        val id = "00000000-0000-4000-8000-000000000001"
        assertEquals(mapOf("id" to id, "version" to 1), NativeDocumentPolicy.written(mapOf("id" to id, "version" to 1, "state" to "pending")))
        assertEquals(mapOf("id" to id, "version" to 2), NativeDocumentPolicy.written(mapOf("id" to id, "version" to 2), id))
        for (reply in listOf<Any?>(mapOf("id" to id), mapOf("id" to id, "version" to 1, "secret" to "x"), null)) {
            try { NativeDocumentPolicy.written(reply); fail("Synthetic reference accepted") }
            catch (failure: AuthFailure) { assertEquals(AuthCode.NETWORK_UNAVAILABLE, failure.code) }
        }
        try { NativeDocumentPolicy.written(mapOf("id" to id, "version" to 1), "00000000-0000-4000-8000-000000000002"); fail() }
        catch (failure: AuthFailure) { assertEquals(AuthCode.NETWORK_UNAVAILABLE, failure.code) }
        val session = java.io.File("src/main/java/io/github/jihoon22lee/sallimbook/auth/NativeAuthSession.kt").readText()
        assertEquals(2, Regex("NativeDocumentPolicy\\.written\\(").findAll(session).count())
        assertFalse(session.contains("NativeDocumentPolicy.reference("))
    }

    @Test fun tooComplexCodeKeepsStatusAndNamesThePageLimit() {
        val raw = mapOf("error" to mapOf("code" to "DOCUMENT_TOO_COMPLEX", "message" to "SYNTHETIC PRIVATE"))
        assertEquals("DOCUMENT_TOO_COMPLEX", (AuthPolicy.safeError(422, raw, id)!!["error"] as Map<*, *>)["code"])
        assertTrue(NativeDocumentPolicy.errorMessage("DOCUMENT_TOO_COMPLEX").contains("${NativeDocumentPolicy.MAX_PDF_PAGES}쪽"))
        assertEquals("REQUEST_FAILED", (AuthPolicy.safeError(503, raw, id)!!["error"] as Map<*, *>)["code"])
    }
    @Test fun unsupportedImageCodeKeepsStatusAndLocalMessage() {
        val raw = mapOf("error" to mapOf("code" to "DOCUMENT_IMAGE_UNSUPPORTED", "message" to "SYNTHETIC PRIVATE"))
        val safe = AuthPolicy.safeError(422, raw, id)!!
        assertEquals("DOCUMENT_IMAGE_UNSUPPORTED", (safe["error"] as Map<*, *>)["code"])
        assertEquals(NativeDocumentPolicy.errorMessages.getValue("DOCUMENT_IMAGE_UNSUPPORTED").second,
            NativeDocumentPolicy.errorMessage("DOCUMENT_IMAGE_UNSUPPORTED"))
        assertFalse(safe.toString().contains("SYNTHETIC PRIVATE"))
        assertEquals("REQUEST_FAILED", (AuthPolicy.safeError(503, raw, id)!!["error"] as Map<*, *>)["code"])
    }
    @Test fun documentErrorsKeepOnlyKnownStatusMatchedCodesAndLocalMessages() {
        for ((code, detail) in NativeDocumentPolicy.errorMessages) {
            val raw = mapOf("error" to mapOf("code" to code, "message" to "SYNTHETIC PRIVATE", "uri" to "content://synthetic/private"))
            val safe = AuthPolicy.safeError(detail.first, raw, id)!!
            assertEquals(code, (safe["error"] as Map<*, *>)["code"])
            assertFalse(safe.toString().contains("SYNTHETIC PRIVATE"))
            assertFalse(safe.toString().contains("content://"))
            assertEquals("INTERNAL_ERROR", (AuthPolicy.safeError(500, raw, id)!!["error"] as Map<*, *>)["code"])
        }
    }
    @Test fun listsKeepServerOrderButRejectRepeatedRowsOrCursor() {
        val op = FinanceOperation.LIST_DOCUMENTS
        val ascending = listOf(document + mapOf("id" to link), document)
        FinancePolicy.response(op, FinancePolicy.prepare(op, emptyMap<String, Any?>()), 200, mapOf("items" to ascending, "next_cursor" to null))
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(op, FinancePolicy.prepare(op, emptyMap<String, Any?>()), 200, mapOf("items" to listOf(document, document), "next_cursor" to null)) }
        val cursor = FinancePolicy.prepare(op, mapOf("query" to mapOf("cursor" to link)))
        bad(AuthCode.ACCESS_DENIED) { FinancePolicy.response(op, cursor, 200, mapOf("items" to ascending, "next_cursor" to null)) }
    }
}
