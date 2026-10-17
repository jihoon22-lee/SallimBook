package io.github.jihoon22lee.sallimbook.auth

import java.net.URI
import java.text.Normalizer
import java.time.OffsetDateTime

/** Pure policy only. It does not authenticate a user, a web frame, or a device. */
internal object AuthPolicy {
    private val uuid = Regex("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
    private val version = Regex("\"[1-9][0-9]{0,18}\"")
    private val forbiddenFields = listOf(
        "password", "token", "credential", "authorization", "cookie", "csrf", "secret",
        "privatekey", "recovery", "cvc", "cvv", "pan", "accountnumber", "policynumber",
        "ciphertext", "wrappedkey", "keymaterial", "nonce", "session", "bearer", "apikey", "salt",
        "challenge", "assertion", "attestation", "devicebinding", "grant", "clientdata", "authenticatordata", "signature",
    )

    fun apiOrigin(value: String): String? = try {
        if (value.isEmpty() || value.length > 512 || value.any { it.isWhitespace() || it.code < 32 } ||
            '%' in value || '\\' in value) null
        else {
            val uri = URI(value)
            val authority = uri.host + if (uri.port == -1) "" else ":${uri.port}"
            if (uri.scheme != "https" || uri.host.isNullOrEmpty() || uri.rawUserInfo != null ||
                !uri.rawPath.isNullOrEmpty() || uri.rawQuery != null || uri.rawFragment != null ||
                uri.port != -1 && uri.port !in 1..65535 || uri.toASCIIString() != value ||
                uri.rawAuthority != authority) null
            else value
        }
    } catch (_: Exception) { null }

    fun trustedBridgeUrl(value: String?): Boolean = try {
        val uri = URI(value ?: "")
        uri.scheme == "https" && uri.host == "localhost" && uri.port == -1 &&
            uri.rawUserInfo == null && '\\' !in (value ?: "")
    } catch (_: Exception) { false }

    fun requestAllowed(method: String, path: String, ifMatch: String?): Boolean = try {
        if (path.length > 1024 || path.any { it.isWhitespace() || it.code < 32 } ||
            '%' in path || '\\' in path || !path.startsWith("/api/v1/")) false
        else {
            val uri = URI(path)
            if (uri.isAbsolute || uri.rawAuthority != null || uri.rawFragment != null) false
            else when (method) {
                "GET" -> ifMatch == null && when (uri.rawPath) {
                    "/api/v1/me", "/api/v1/household/members" -> uri.rawQuery == null
                    "/api/v1/devices", "/api/v1/auth/passkeys" -> deviceQueryAllowed(uri.rawQuery)
                    else -> false
                }
                "DELETE" -> uri.rawQuery == null &&
                    uri.rawPath.startsWith("/api/v1/devices/") &&
                    uuid.matches(uri.rawPath.removePrefix("/api/v1/devices/")) &&
                    ifMatch != null && version.matches(ifMatch)
                else -> false
            }
        }
    } catch (_: Exception) { false }

    private fun deviceQueryAllowed(query: String?): Boolean {
        if (query == null) return true
        if (query.isEmpty()) return false
        val seen = mutableSetOf<String>()
        for (part in query.split('&')) {
            val pair = part.split('=', limit = 2)
            if (pair.size != 2 || !seen.add(pair[0])) return false
            when (pair[0]) {
                "cursor" -> if (!uuid.matches(pair[1])) return false
                "limit" -> if (!Regex("[1-9][0-9]{0,2}").matches(pair[1]) ||
                    pair[1].toInt() !in 1..200) return false
                else -> return false
            }
        }
        return true
    }

    fun safeField(name: String): Boolean {
        val normalized = Normalizer.normalize(name, Normalizer.Form.NFKC).lowercase()
            .filter { it.isLetterOrDigit() }
        return name.length in 1..128 && forbiddenFields.none { it in normalized }
    }

    /** Defense in depth for the metadata allowlist; never used to permit arbitrary endpoints. */
    fun safeJson(value: Any?, depth: Int = 0): Boolean {
        if (depth > 16) return false
        return when (value) {
            null, is Boolean, is Int, is Long -> true
            is String -> value.length <= 16_384
            is Map<*, *> -> value.size <= 200 && value.all { (key, child) ->
                key is String && safeField(key) && safeJson(child, depth + 1)
            }
            is List<*> -> value.size <= 200 && value.all { safeJson(it, depth + 1) }
            // Current metadata has no decimal-number fields. Money must remain decimal text.
            else -> false
        }
    }

    /** Security projection of the currently generated metadata contracts, not business models. */
    fun metadataBody(method: String, path: String, status: Int, value: Any?): Any? {
        if (method == "DELETE" && status == 204 && value == null &&
            URI(path).rawPath.startsWith("/api/v1/devices/") &&
            uuid.matches(URI(path).rawPath.removePrefix("/api/v1/devices/"))) return null
        if (method != "GET" || status != 200) throw AuthFailure(AuthCode.ACCESS_DENIED)
        return when (URI(path).rawPath) {
            "/api/v1/me" -> member(value)
            "/api/v1/household/members" -> {
                val members = value as? List<*> ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
                if (members.size > 2) throw AuthFailure(AuthCode.ACCESS_DENIED)
                members.map(::member)
            }
            "/api/v1/devices" -> {
                val record = record(value, setOf("items", "next_cursor"))
                val items = record["items"] as? List<*> ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
                if (items.size > 200) throw AuthFailure(AuthCode.ACCESS_DENIED)
                val cursor = record["next_cursor"]?.let(::uuidValue)
                mapOf("items" to items.map(::device), "next_cursor" to cursor)
            }
            "/api/v1/auth/passkeys" -> {
                val record = record(value, setOf("items", "next_cursor"))
                val items = record["items"] as? List<*> ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
                if (items.size > 200) throw AuthFailure(AuthCode.ACCESS_DENIED)
                mapOf("items" to items.map(::passkey), "next_cursor" to record["next_cursor"]?.let(::uuidValue))
            }
            else -> throw AuthFailure(AuthCode.ACCESS_DENIED)
        }
    }

    private fun record(value: Any?, fields: Set<String>): Map<*, *> {
        val record = value as? Map<*, *> ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
        if (record.keys != fields || !safeJson(record)) throw AuthFailure(AuthCode.ACCESS_DENIED)
        return record
    }

    private fun uuidValue(value: Any?): String {
        val text = value as? String ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
        if (!uuid.matches(text)) throw AuthFailure(AuthCode.ACCESS_DENIED)
        return text
    }

    private fun boundedText(value: Any?, maxLength: Int): String {
        val text = value as? String ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
        if (text.isBlank() || text.codePointCount(0, text.length) !in 1..maxLength) {
            throw AuthFailure(AuthCode.ACCESS_DENIED)
        }
        return text
    }

    private fun member(value: Any?): Map<String, Any?> {
        val row = record(value, setOf("user_id", "member_id", "household_id", "display_name", "role"))
        if (row["role"] !in setOf("owner", "member")) throw AuthFailure(AuthCode.ACCESS_DENIED)
        return mapOf(
            "user_id" to uuidValue(row["user_id"]), "member_id" to uuidValue(row["member_id"]),
            "household_id" to uuidValue(row["household_id"]),
            "display_name" to boundedText(row["display_name"], 80), "role" to row["role"],
        )
    }

    private fun device(value: Any?): Map<String, Any?> {
        val fields = setOf("id", "label", "platform", "status", "last_seen_at", "version", "current")
        val row = record(value, fields)
        if (row["platform"] !in setOf("web", "android") || row["status"] !in setOf("active", "revoked") ||
            row["current"] !is Boolean) throw AuthFailure(AuthCode.ACCESS_DENIED)
        val version = row["version"]
        if (!(version is Int && version > 0 || version is Long && version in 1..9_007_199_254_740_991L)) {
            throw AuthFailure(AuthCode.ACCESS_DENIED)
        }
        val seen = row["last_seen_at"] as? String ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
        try { OffsetDateTime.parse(seen) } catch (_: Exception) { throw AuthFailure(AuthCode.ACCESS_DENIED) }
        return mapOf(
            "id" to uuidValue(row["id"]), "label" to boundedText(row["label"], 80),
            "platform" to row["platform"], "status" to row["status"], "last_seen_at" to seen,
            "version" to version, "current" to row["current"],
        )
    }

    fun passkey(value: Any?): Map<String, Any?> {
        val row = record(value, setOf("id", "label", "created_at", "last_used_at", "backed_up", "device_type", "version"))
        val version = row["version"]
        if (!(version is Int && version > 0 || version is Long && version in 1..9_007_199_254_740_991L) ||
            row["backed_up"] !is Boolean || row["device_type"] !in setOf("single_device", "multi_device")) {
            throw AuthFailure(AuthCode.ACCESS_DENIED)
        }
        val created = row["created_at"] as? String ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
        val last = row["last_used_at"]
        try {
            OffsetDateTime.parse(created)
            if (last != null) OffsetDateTime.parse(last as? String ?: throw AuthFailure(AuthCode.ACCESS_DENIED))
        } catch (_: Exception) { throw AuthFailure(AuthCode.ACCESS_DENIED) }
        return mapOf("id" to uuidValue(row["id"]), "label" to boundedText(row["label"], 80),
            "created_at" to created, "last_used_at" to last, "backed_up" to row["backed_up"],
            "device_type" to row["device_type"], "version" to version)
    }

    /** Preserve only recognized server codes/correlation; messages are local constants. */
    fun safeError(status: Int, body: Any?, requestId: String?): Map<String, Any?>? {
        if (requestId == null || !uuid.matches(requestId)) return null
        val messages = mapOf(
            "BAD_REQUEST" to (400 to "요청 형식을 확인해 주세요."),
            "VERSION_REQUIRED" to (400 to "수정할 버전을 지정해 주세요."),
            "INVALID_VERSION" to (400 to "버전 형식을 확인해 주세요."),
            "UNAUTHENTICATED" to (401 to "로그인이 필요합니다."),
            "FORBIDDEN" to (403 to "허용되지 않은 요청입니다."),
            "REAUTHENTICATION_REQUIRED" to (403 to "다시 로그인한 후 진행해 주세요."),
            "NOT_FOUND" to (404 to "요청한 항목을 찾을 수 없습니다."),
            "VERSION_CONFLICT" to (409 to "다른 기기에서 수정했습니다. 다시 확인해 주세요."),
            "VALIDATION_ERROR" to (422 to "입력값을 확인해 주세요."),
            "RATE_LIMITED" to (429 to "잠시 후 다시 시도해 주세요."),
            "INTERNAL_ERROR" to (500 to "요청을 처리하지 못했습니다."),
            "DATABASE_UNAVAILABLE" to (503 to "데이터 저장소를 준비하고 있습니다."),
            "SCHEMA_UNAVAILABLE" to (503 to "데이터 저장소를 준비하고 있습니다."),
        )
        val serverError = (body as? Map<*, *>)?.get("error") as? Map<*, *>
        val suppliedCode = serverError?.get("code") as? String
        val knownCode = suppliedCode?.takeIf { messages[it]?.first == status }
        val code = knownCode ?: when (status) {
            400 -> "BAD_REQUEST"
            401 -> "UNAUTHENTICATED"
            403 -> "FORBIDDEN"
            404 -> "NOT_FOUND"
            409 -> "VERSION_CONFLICT"
            422 -> "VALIDATION_ERROR"
            429 -> "RATE_LIMITED"
            500 -> "INTERNAL_ERROR"
            else -> "REQUEST_FAILED"
        }
        val detail = mutableMapOf<String, Any?>(
            "code" to code, "message" to (messages[code]?.second ?: "요청을 처리하지 못했습니다."),
            "request_id" to requestId,
        )
        val version = serverError?.get("current_version")
        if (status == 409 && (version is Int && version > 0 || version is Long && version > 0)) {
            detail["current_version"] = version
        }
        return mapOf("error" to detail)
    }
}

/** Cancellation controls request lifetime only; it is not authentication evidence. */
internal class ForegroundRequest {
    private var active = true
    private var cancelNetwork: (() -> Unit)? = null

    @Synchronized fun cancel() {
        active = false
        cancelNetwork?.invoke()
        cancelNetwork = null
    }
    @Synchronized fun isActive(): Boolean = active
    @Synchronized fun bindNetworkCancellation(cancel: () -> Unit) {
        if (active) cancelNetwork = cancel else cancel()
    }
    @Synchronized fun releaseNetworkCancellation() { cancelNetwork = null }

    @Synchronized fun <T> whileActive(action: () -> T): T {
        if (!active) throw AuthFailure(AuthCode.AUTH_CANCELLED)
        return action()
    }

    fun check() {
        if (!isActive()) throw AuthFailure(AuthCode.AUTH_CANCELLED)
    }
}

internal enum class AuthCode {
    AUTH_UNAVAILABLE, AUTH_CANCELLED, ACCESS_DENIED, SESSION_EXPIRED, KEY_INVALIDATED,
    NETWORK_UNAVAILABLE, INVALID_REQUEST, AUTH_FAILED, REGISTRATION_FAILED,
    PASSKEYS_DISABLED, PASSKEY_REQUIRED, PASSKEY_CANCELLED, PASSKEY_FAILED, REAUTHENTICATION_REQUIRED,
}

/** Exception messages and causes deliberately contain no request, response, or credential. */
internal class AuthFailure(val code: AuthCode) : Exception()

internal class AuthOutcome private constructor(val value: Map<String, Any?>?, val code: AuthCode?) {
    companion object {
        fun success(value: Map<String, Any?>) = AuthOutcome(value, null)
        fun failure(code: AuthCode) = AuthOutcome(null, code)
    }
}
