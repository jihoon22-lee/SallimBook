package io.github.jihoon22lee.sallimbook.auth

import java.net.URI
import java.time.OffsetDateTime
import java.util.Locale

private typealias DocumentField = (Any?) -> Unit

internal class NativeDocumentInfo(val id: String, val name: String, val mime: String, val size: Int, val checksum: String) {
    override fun toString() = "NativeDocumentInfo(redacted)"
}

/** Six public metadata commands; create and binary content are native file-screen operations only. */
internal object NativeDocumentPolicy {
    val errorMessages = mapOf(
        "DOCUMENT_STORAGE_QUOTA_EXCEEDED" to (413 to "첨부파일 보관 용량을 초과했어요. 기존 문서를 확인해 주세요."),
        "DOCUMENT_STORAGE_CAPACITY_UNAVAILABLE" to (503 to "첨부파일 저장 공간을 사용할 수 없어요. 잠시 후 목록을 확인해 주세요."),
        "DOCUMENT_UPLOAD_BUSY" to (503 to "다른 첨부파일을 처리하고 있어요. 잠시 후 목록을 확인해 주세요."),
        "INVALID_DOCUMENT_TARGET" to (422 to "첨부할 항목의 종류와 대상을 확인해 주세요."),
        "DOCUMENT_UNAVAILABLE" to (409 to "삭제된 첨부파일입니다."),
        "DOCUMENT_UPLOAD_EXPIRED" to (409 to "첨부 대기 시간이 끝났습니다. 목록을 확인한 뒤 다시 등록해 주세요."),
        "DOCUMENT_UNLINKED" to (409 to "연결된 항목이 없는 첨부파일입니다."),
        "DOCUMENT_ALREADY_LINKED" to (409 to "이미 연결된 첨부파일입니다."),
        "DOCUMENT_CONTENT_MISMATCH" to (422 to "선택한 파일의 크기와 내용을 다시 확인해 주세요."),
        "DOCUMENT_CONTENT_EXISTS" to (409 to "이미 업로드한 첨부파일입니다. 목록을 다시 확인해 주세요."),
        "DOCUMENT_NOT_READY" to (409 to "첨부파일 업로드를 먼저 완료해 주세요."),
        "DOCUMENT_LINK_ENDED" to (409 to "이미 해제한 첨부 연결입니다."),
        "DOCUMENT_CONTENT_TYPE" to (422 to "PDF·JPEG·PNG 원본 파일을 선택해 주세요."),
        "DOCUMENT_CONTENT_LENGTH" to (422 to "선택한 파일의 크기를 확인해 주세요."),
        "DOCUMENT_TOO_LARGE" to (413 to "첨부파일은 20MiB 이하로 선택해 주세요."),
        "DOCUMENT_UPLOAD_TIMEOUT" to (408 to "파일 전송 시간이 초과됐습니다. 목록을 확인해 주세요."),
        "DOCUMENT_UNSAFE" to (422 to "지원하는 안전한 PDF·JPEG·PNG 문서를 선택해 주세요."),
        "DOCUMENT_MALWARE" to (422 to "보안 검사에서 허용하지 않은 파일입니다."),
        "DOCUMENT_CARD_DATA" to (422 to "카드번호·보안코드 또는 카드 사진은 첨부할 수 없습니다."),
        "DOCUMENT_UNREADABLE" to (422 to "글자를 명확히 읽을 수 있는 영수증·문서를 선택해 주세요."),
        "DOCUMENT_SCAN_UNAVAILABLE" to (503 to "파일 보안 검사를 준비하고 있습니다. 나중에 다시 확인해 주세요."),
        "DOCUMENT_OCR_UNAVAILABLE" to (503 to "문서 내용 검사를 준비하고 있습니다. 나중에 다시 확인해 주세요."),
        "DOCUMENT_STORAGE_UNAVAILABLE" to (503 to "첨부파일 저장소를 확인해 주세요."),
    )
    fun errorMessage(code: String?): String = errorMessages[code]?.second ?: when (code) {
        "UNAUTHENTICATED", "REAUTHENTICATION_REQUIRED" -> "화면을 닫고 다시 로그인한 후 진행해 주세요."
        "VERSION_CONFLICT", "IDEMPOTENCY_CONFLICT" -> "첨부 상태가 변경됐습니다. 목록을 다시 확인해 주세요."
        "NOT_FOUND", "FORBIDDEN" -> "이 첨부파일에 접근할 수 없습니다. 연결된 항목을 확인해 주세요."
        else -> "파일 처리를 완료하지 못했습니다. 자동 재전송하지 않았으니 목록을 다시 확인해 주세요."
    }
    private fun invalid(): Nothing = throw AuthFailure(AuthCode.INVALID_REQUEST)
    private fun obj(value: Any?): Map<String, Any?> {
        val row = value as? Map<*, *> ?: invalid()
        if (row.size > 24 || row.keys.any { it !is String }) invalid()
        return row.entries.associate { it.key as String to it.value }
    }
    private fun integer(value: Any?, min: Long = 1, max: Long = 9_007_199_254_740_991L) {
        val number = when (value) { is Int -> value.toLong(); is Long -> value; else -> invalid() }
        if (number !in min..max) invalid()
    }
    private val id: DocumentField = { FinancePolicy.id(it); Unit }
    private val version: DocumentField = { integer(it) }
    private val bool: DocumentField = { if (it !is Boolean) invalid() }
    private val timestamp: DocumentField = {
        if (it !is String || it.length > 40) invalid()
        try { OffsetDateTime.parse(it) } catch (_: Exception) { invalid() }
    }
    private val size: DocumentField = { integer(it, 1, NativeDocumentBytes.MAX_BYTES.toLong()) }
    private val hash: DocumentField = { if (it !is String || !Regex("[0-9a-f]{64}").matches(it)) invalid() }
    private fun text(max: Int): DocumentField = { if (it !is String || it.trim().isEmpty() || it.codePointCount(0, it.length) > max) invalid() }
    private fun choice(vararg values: String): DocumentField = { if (it !is String || it !in values) invalid() }
    private fun nullable(rule: DocumentField): DocumentField = { if (it != null) rule(it) }
    private val kind = choice("policy", "case", "medical_node", "expense", "claim", "appliance", "asset")
    private val mime = choice("application/pdf", "image/jpeg", "image/png")
    private fun shape(value: Any?, fields: Map<String, DocumentField>, required: Set<String> = fields.keys): Map<String, Any?> {
        val row = obj(value)
        if (!fields.keys.containsAll(row.keys) || !row.keys.containsAll(required)) invalid()
        row.forEach { (name, item) -> fields.getValue(name)(item) }
        return row
    }
    fun target(value: Any?) = shape(value, mapOf("kind" to kind, "id" to id))
    fun tag(value: Any?): String {
        if (value !is String || !Regex("\"[1-9][0-9]{0,15}\"").matches(value)) invalid()
        integer(value.removeSurrounding("\"").toLongOrNull())
        return value
    }
    fun key(value: Any?): String {
        if (value !is String || !Regex("[A-Za-z0-9._:-]{1,128}").matches(value)) invalid()
        return value
    }
    fun filename(name: String, mimeType: String) {
        text(255)(name); mime(mimeType)
        if (name != name.trim() || name in setOf(".", "..") || name.codePoints().anyMatch {
                it == '/'.code || it == '\\'.code || Character.getType(it) in setOf(Character.CONTROL.toInt(), Character.FORMAT.toInt())
            }) invalid()
        val extensions = when (mimeType) { "application/pdf" -> setOf("pdf"); "image/jpeg" -> setOf("jpg", "jpeg"); else -> setOf("png") }
        if ('.' !in name || name.substringAfterLast('.').lowercase(Locale.ROOT) !in extensions) invalid()
    }
    private data class Route(val method: String, val path: String, val input: String, val output: String,
        val query: Boolean = false, val change: Boolean = false, val status: Int = 200)
    private val routes = mapOf(
        FinanceOperation.LIST_DOCUMENTS to Route("GET", "/api/v1/documents", "", "DocumentListResponse", query = true),
        FinanceOperation.GET_DOCUMENT to Route("GET", "/api/v1/documents/{documentId}", "", "DocumentResponse"),
        FinanceOperation.DELETE_DOCUMENT to Route("POST", "/api/v1/documents/{documentId}/delete", "DocumentReason", "DocumentMutationReference", change = true),
        FinanceOperation.CREATE_DOCUMENT_LINK to Route("POST", "/api/v1/document-links", "DocumentLinkCreate", "DocumentMutationReference", change = true, status = 201),
        FinanceOperation.LIST_DOCUMENT_LINKS to Route("GET", "/api/v1/documents/{documentId}/links", "", "DocumentLinkListResponse", query = true),
        FinanceOperation.END_DOCUMENT_LINK to Route("POST", "/api/v1/document-links/{linkId}/end", "DocumentReason", "DocumentMutationReference", change = true),
    )
    fun supports(operation: FinanceOperation) = operation in routes
    private fun query(operation: FinanceOperation, value: Any?): Map<String, Any?> {
        val fields = mapOf("cursor" to nullable(id), "limit" to { v: Any? -> integer(v, 1, 200) }) +
            if (operation == FinanceOperation.LIST_DOCUMENTS) mapOf("target_kind" to nullable(kind), "target_id" to nullable(id)) else emptyMap()
        val row = if (value == null) emptyMap() else shape(value, fields, emptySet()).filterValues { it != null }
        if ((row["target_kind"] == null) != (row["target_id"] == null)) invalid()
        return row
    }
    fun prepare(operation: FinanceOperation, value: Any?): FinanceRequest {
        val route = routes[operation] ?: invalid()
        val args = obj(value)
        val ids = Regex("\\{([^}]+)}").findAll(route.path).map { it.groupValues[1] }.toSet()
        val required = ids + if (route.change) setOf("input", "ifMatch", "idempotencyKey") else emptySet()
        if (!args.keys.containsAll(required) || !(required + if (route.query) setOf("query") else emptySet()).containsAll(args.keys)) invalid()
        var path = route.path
        ids.forEach { path = path.replace("{$it}", FinancePolicy.id(args[it]).lowercase()) }
        val q = if (route.query) query(operation, args["query"]) else emptyMap()
        if (q.isNotEmpty()) path += "?" + q.toSortedMap().entries.joinToString("&") { "${it.key}=${it.value.toString().lowercase()}" }
        val body = when (route.input) {
            "DocumentReason" -> shape(args["input"], mapOf("reason" to text(500)))
            "DocumentLinkCreate" -> shape(args["input"], mapOf("document_id" to id, "target" to { target(it); Unit }))
            else -> null
        }
        return FinanceRequest(route.method, path, body, if (route.change) tag(args["ifMatch"]) else null,
            if (route.change) key(args["idempotencyKey"]) else null)
    }
    fun create(value: Any?, idempotencyKey: String): FinanceRequest {
        val row = shape(value, mapOf("original_name" to text(255), "mime_type" to mime, "size_bytes" to size, "checksum_sha256" to hash,
            "target" to { target(it); Unit }, "contains_no_card_data" to { if (it != true) invalid() }))
        filename(row["original_name"] as String, row["mime_type"] as String)
        return FinanceRequest("POST", "/api/v1/documents", row, null, key(idempotencyKey))
    }
    fun createHttpAllowed(method: String, path: String, body: Any?, ifMatch: String?, idempotencyKey: String?): Boolean = try {
        method == "POST" && path == "/api/v1/documents" && ifMatch == null && create(body, key(idempotencyKey)).body == body
    } catch (_: Exception) { false }
    fun binaryPath(documentId: String, upload: Boolean): String =
        "/api/v1/documents/${FinancePolicy.id(documentId).lowercase()}/${if (upload) "content" else "download"}"
    fun httpAllowed(method: String, path: String, body: Any?, ifMatch: String?, idempotencyKey: String?): Boolean = try {
        val uri = URI(path)
        if (path.length > 2048 || uri.isAbsolute || uri.rawAuthority != null || uri.rawFragment != null || '%' in path || '\\' in path || path.any { it.isWhitespace() || it.code < 32 }) invalid()
        val parts = uri.rawPath.split('/')
        val entry = routes.entries.firstOrNull { (_, route) ->
            val p = route.path.split('/')
            method == route.method && p.size == parts.size && p.indices.all { p[it].startsWith('{') || p[it] == parts[it] }
        } ?: invalid()
        val args = mutableMapOf<String, Any?>()
        entry.value.path.split('/').forEachIndexed { n, p -> if (p.startsWith('{')) args[p.removeSurrounding("{", "}")] = parts[n] }
        if (entry.value.change) { args["input"] = body; args["ifMatch"] = ifMatch; args["idempotencyKey"] = idempotencyKey }
        else if (body != null || ifMatch != null || idempotencyKey != null) invalid()
        uri.rawQuery?.let { raw ->
            if (!entry.value.query || raw.isEmpty()) invalid()
            val q = mutableMapOf<String, Any?>()
            raw.split('&').forEach { part ->
                val pair = part.split('=', limit = 2)
                if (pair.size != 2 || pair[0] in q) invalid()
                q[pair[0]] = if (pair[0] == "limit") pair[1].toLongOrNull() ?: invalid() else pair[1]
            }
            args["query"] = q
        }
        val r = prepare(entry.key, args)
        r.path == path && r.body == body && r.ifMatch == ifMatch && r.idempotencyKey == idempotencyKey
    } catch (_: Exception) { false }
    private val audit = mapOf("id" to id, "household_id" to id, "version" to version, "created_by_member_id" to id,
        "updated_by_member_id" to id, "created_at" to timestamp, "updated_at" to timestamp)
    fun reference(value: Any?, expectedId: String? = null): Map<String, Any?> {
        val row = shape(value, mapOf("id" to id, "version" to version))
        if (expectedId != null && !(row["id"] as String).equals(expectedId, true)) invalid()
        return row
    }
    private fun document(value: Any?): Map<String, Any?> {
        val row = shape(value, audit + mapOf("original_name" to text(255), "mime_type" to mime, "size_bytes" to size, "checksum_sha256" to hash,
            "state" to choice("pending", "ready", "deleted"), "pending_expires_at" to timestamp, "stored_at" to nullable(timestamp),
            "orphaned_at" to nullable(timestamp), "deleted_at" to nullable(timestamp), "active_link_count" to { integer(it, 0) }))
        filename(row["original_name"] as String, row["mime_type"] as String)
        if (row["state"] == "pending" && row["stored_at"] != null || row["state"] == "ready" && row["stored_at"] == null ||
            (row["state"] == "deleted") != (row["deleted_at"] != null) || row["orphaned_at"] != null && (row["active_link_count"] as Number).toLong() != 0L) invalid()
        return row
    }
    private fun linked(value: Any?): Map<String, Any?> {
        val row = shape(value, audit + mapOf("document_id" to id, "target" to { target(it); Unit }, "active" to bool,
            "ended_at" to nullable(timestamp), "end_reason" to nullable(text(500))))
        if ((row["active"] == true) != (row["ended_at"] == null) || row["active"] == false && row["end_reason"] == null) invalid()
        return row
    }
    fun info(value: Any?, documentId: String): NativeDocumentInfo {
        try {
            val row = document(value)
            if (!(row["id"] as String).equals(FinancePolicy.id(documentId), true) || row["state"] != "ready" || (row["active_link_count"] as Number).toLong() < 1) invalid()
            return NativeDocumentInfo(row["id"] as String, row["original_name"] as String, row["mime_type"] as String,
                (row["size_bytes"] as Number).toInt(), row["checksum_sha256"] as String)
        } catch (_: Exception) { throw AuthFailure(AuthCode.ACCESS_DENIED) }
    }
    fun response(operation: FinanceOperation, request: FinanceRequest, status: Int, value: Any?): Any? {
        try {
            val route = routes[operation] ?: invalid()
            if (status != route.status) invalid()
            val uri = URI(request.path); val parts = uri.path.split('/')
            if (route.change) return reference(value, if (operation == FinanceOperation.CREATE_DOCUMENT_LINK) null else parts[4])
            if (operation == FinanceOperation.GET_DOCUMENT) return document(value).also { if (it["id"] != parts[4]) invalid() }
            val page = obj(value)
            if (page.keys != setOf("items", "next_cursor")) invalid()
            val items = page["items"] as? List<*> ?: invalid()
            val query = uri.rawQuery?.split('&')?.associate { it.substringBefore('=') to it.substringAfter('=') } ?: emptyMap()
            if (items.size > (query["limit"]?.toInt() ?: 50)) invalid()
            var previous = query["cursor"]
            val households = mutableSetOf<Any?>()
            for (item in items) {
                val row = if (operation == FinanceOperation.LIST_DOCUMENT_LINKS) linked(item) else document(item)
                val current = (row["id"] as String).lowercase()
                if (previous != null && current >= previous) invalid()
                previous = current; households.add(row["household_id"])
                if (operation == FinanceOperation.LIST_DOCUMENT_LINKS && row["document_id"] != parts[4] ||
                    operation == FinanceOperation.LIST_DOCUMENTS && row["state"] == "deleted") invalid()
            }
            if (households.size > 1) invalid()
            page["next_cursor"]?.let { id(it); if (items.isEmpty() || (it as String).lowercase() != previous) invalid() }
            return page
        } catch (_: Exception) { throw AuthFailure(AuthCode.ACCESS_DENIED) }
    }
}
