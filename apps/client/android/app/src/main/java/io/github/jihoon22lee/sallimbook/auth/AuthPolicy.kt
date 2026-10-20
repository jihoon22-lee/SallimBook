package io.github.jihoon22lee.sallimbook.auth

import java.net.URI
import java.text.Normalizer
import java.time.OffsetDateTime

/** Pure policy only. It does not authenticate a user, a web frame, or a device. */
internal object AuthPolicy {
    /** Login/reauthentication refusals: a rate limit or outage must not read as a wrong password. */
    fun credentialFailure(status: Int): AuthCode = when (status) {
        429 -> AuthCode.RATE_LIMITED
        in 500..599 -> AuthCode.NETWORK_UNAVAILABLE
        else -> AuthCode.AUTH_FAILED
    }

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
            "INVALID_CURSOR" to (400 to "페이지 기준을 다시 확인해 주세요."),
            "INVALID_AUDIT_FILTER" to (422 to "감사 조회 조건과 기간을 확인해 주세요."),
            "AUDIT_METADATA_INVALID" to (503 to "감사 기록을 확인하지 못했습니다. 잠시 후 다시 시도해 주세요."),
            "INVALID_HOMECARE_DATE" to (422 to "실제 기록 날짜와 취소 날짜를 확인해 주세요."),
            "APPLIANCE_IN_USE" to (409 to "연결 또는 사용 이력이 있는 가전입니다. 사용 종료로 보관해 주세요."),
            "CONSUMABLE_IN_USE" to (409 to "연결 또는 재고 이력이 있는 소모품입니다. 사용 종료로 보관해 주세요."),
            "APPLIANCE_CONSUMABLE_IN_USE" to (409 to "교체 이력이 있는 연결입니다. 연결을 비활성화해 보관해 주세요."),
            "INVALID_HOMECARE_INPUT" to (422 to "가전·소모품의 입력 항목과 날짜·주기를 확인해 주세요."),
            "APPLIANCE_UNAVAILABLE" to (422 to "사용 중인 가전을 선택해 주세요."),
            "CONSUMABLE_UNAVAILABLE" to (422 to "사용 중인 소모품을 선택해 주세요."),
            "APPLIANCE_CONSUMABLE_UNAVAILABLE" to (422 to "사용 중인 기기별 소모품 연결을 선택해 주세요."),
            "CONSUMABLE_SKU_EXISTS" to (409 to "이미 등록된 규격입니다. 공용 재고를 확인해 주세요."),
            "CONSUMABLE_UNIT_IN_USE" to (409 to "재고 이력이 있어 단위를 바꿀 수 없습니다."),
            "APPLIANCE_CONSUMABLE_EXISTS" to (409 to "이미 연결된 소모품입니다. 기존 연결을 확인해 주세요."),
            "INSUFFICIENT_STOCK" to (409 to "공용 재고가 부족합니다. 현재 재고를 확인해 주세요."),
            "STOCK_LIMIT_EXCEEDED" to (422 to "허용 재고 수량을 초과합니다."),
            "INVALID_STOCK_REVERSAL" to (422 to "취소 기록을 다시 취소할 수 없습니다."),
            "STOCK_MOVEMENT_ALREADY_REVERSED" to (409 to "이미 취소된 재고 기록입니다."),
            "REPLACEMENT_CANCEL_REQUIRED" to (409 to "기기별 교체 기록에서 취소해 주세요."),
            "RETURN_EXCEEDS_ALLOCATION" to (409 to "반환 합계가 원래 배분 금액을 초과합니다."),
            "INSURANCE_PAYOUT_HAS_RETURNS" to (409 to "활성 반환을 먼저 확인해 주세요."),
            "CLAIM_ALLOCATION_MISMATCH" to (422 to "청구와 같은 사건·보험계약을 선택해 주세요."),
            "INVALID_SUBMISSION_DATE" to (422 to "실제 접수 날짜를 확인해 주세요."),
            "MEDICAL_EXPENSE_UNAVAILABLE" to (422 to "활성 의료비를 선택해 주세요."),
            "MEDICAL_EXPENSE_IN_CLAIM" to (409 to "청구의 현재 비용 근거를 먼저 정정해 주세요."),
            "MEDICAL_EXPENSE_HAS_REFUNDS" to (409 to "활성 환불을 먼저 확인해 주세요."),
            "PRESCRIPTION_HAS_NO_PAYMENT" to (422 to "처방전에는 비용을 입력할 수 없습니다."),
            "EVENT_ALREADY_VOID" to (409 to "이미 무효 처리된 기록입니다."),
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
            "AUTH_BUSY" to (429 to "로그인 확인 요청이 몰려 있어요. 잠시 후 다시 시도해 주세요."),
            "INTERNAL_ERROR" to (500 to "요청을 처리하지 못했습니다."),
            "DATABASE_UNAVAILABLE" to (503 to "데이터 저장소를 준비하고 있습니다."),
            "SCHEMA_UNAVAILABLE" to (503 to "데이터 저장소를 준비하고 있습니다."),
            "INVALID_IDEMPOTENCY_KEY" to (400 to "재시도 식별자를 확인해 주세요."),
            "OPERATION_IN_PROGRESS" to (409 to "진행 중인 요청을 다시 확인해 주세요."),
            "IDEMPOTENCY_CONFLICT" to (409 to "같은 식별자로 다른 내용을 보낼 수 없습니다."),
            "MONTH_NOT_FOUND" to (404 to "이 달의 자산 기록을 먼저 만들어 주세요."),
            "MONTH_ALREADY_EXISTS" to (409 to "이미 있는 월 기록을 불러와 주세요."),
            "MONTH_IN_FUTURE" to (422 to "아직 시작하지 않은 달은 기록할 수 없습니다."),
            "PREVIOUS_MONTH_UNCONFIRMED" to (409 to "전월을 먼저 확정해 주세요."),
            "MONTH_CONFIRMED" to (409 to "확정한 월은 정정 사유를 남기고 다시 열어 주세요."),
            "REVISION_CONFLICT" to (409 to "현재 월 기록을 다시 불러와 주세요."),
            "VALUE_CONFLICT" to (409 to "현재 입력 행을 다시 불러와 주세요."),
            "INVALID_AS_OF_DATE" to (422 to "선택 월 안의 실제 확인 날짜를 입력해 주세요."),
            "NO_CARRIED_VALUE" to (422 to "불러온 금액이 있는지 확인해 주세요."),
            "MONTH_SCOPE_CHANGED" to (409 to "바뀐 자산 목록과 지분을 다시 확인해 주세요."),
            "MONTH_UNVERIFIED" to (409 to "미입력·미확인 항목을 모두 확인해 주세요."),
            "AS_OF_DATE_ACK_REQUIRED" to (409 to "월말과 다른 기준일을 확인해 주세요."),
            "SCOPE_ACK_REQUIRED" to (409 to "비교 범위와 지분 변경을 확인해 주세요."),
            "MONTH_NOT_CONFIRMED" to (409 to "확정한 월만 새 정정본으로 열 수 있습니다."),
            "INVALID_PAGE_SIZE" to (422 to "조회 범위를 확인해 주세요."),
            "TOTAL_OUT_OF_RANGE" to (422 to "합산 가능한 금액 범위를 확인해 주세요."),
            "INVALID_OCCURRED_DATE" to (422 to "실제 입금·지급이 확인된 날짜를 입력해 주세요."),
            "ACCOUNT_UNAVAILABLE" to (422 to "사용 중인 계좌를 선택해 주세요."),
            "MEMBER_UNAVAILABLE" to (422 to "현재 가계 구성원을 선택해 주세요."),
            "INCOME_HAS_RETURNS" to (409 to "반환 기록을 먼저 확인한 뒤 원본을 정정해 주세요."),
            "INVALID_CASH_KIND" to (422 to "금전 기록의 종류와 원본을 확인해 주세요."),
            "MEMBER_REQUIRED" to (422 to "수입 구성원을 선택해 주세요."),
            "INVALID_REVERSAL" to (409 to "반환할 원본을 확인해 주세요."),
            "RETURN_EXCEEDS_ORIGINAL" to (409 to "반환 합계가 원본 금액을 초과합니다."),
            "SOURCE_DOMAIN_REQUIRED" to (409 to "원본을 등록한 영역에서 수정해 주세요."),
            "INCOME_VOID" to (409 to "무효 처리된 기록은 수정할 수 없습니다."),
            "INCOME_DUPLICATE_SUSPECTED" to (409 to "같은 월의 일별·월합계 수입을 확인해 주세요."),
            "INVALID_INCOME" to (422 to "수입 날짜·정밀도와 입력 항목을 확인해 주세요."),
            "INVALID_CONVERSION" to (422 to "전환할 월·구성원·종류·정밀도를 확인해 주세요."),
            "CONVERSION_TOTAL_MISMATCH" to (422 to "전환 전후의 수입 합계가 같아야 합니다."),
            "INCOMPLETE_CONVERSION" to (409 to "같은 범위의 활성 수입을 모두 확인해 주세요."),
            "AMOUNT_OUT_OF_RANGE" to (422 to "집계 금액이 지원 범위를 초과합니다."),
            "INVALID_CARD" to (422 to "카드 사용 기간과 입력 항목을 확인해 주세요."),
            "INVALID_CARD_DATES" to (422 to "실제로 사용을 종료한 날짜를 입력해 주세요."),
            "CARD_IN_USE" to (409 to "기록에서 사용하는 카드입니다. 사용 종료로 보관해 주세요."),
            "INVALID_COMPARISON_RANGE" to (422 to "비교할 이전 월은 확인 월보다 앞서야 합니다."),
            "INVALID_COMPARISON_FILTERS" to (422 to "소유자와 공동 소유 조건을 확인해 주세요."),
            "INVALID_TREND_RANGE" to (422 to "시작·종료 월과 최대 120개월 범위를 확인해 주세요."),
            "LOAN_UNAVAILABLE" to (422 to "사용 중인 부채를 선택해 주세요."),
            "CARD_UNAVAILABLE" to (422 to "사용 중인 납부 카드를 선택해 주세요."),
            "RULE_PERIOD_OVERLAP" to (409 to "기존 마지막 규칙 이후 적용일을 선택해 주세요."),
            "PAST_RULE_CHANGE" to (409 to "지난 규칙은 변경할 수 없습니다."),
            "GENERATION_TOO_LARGE" to (422 to "규칙 또는 생성 기간을 줄여 주세요."),
            "OBLIGATION_SUPERSEDED" to (409 to "현재 적용되는 회차를 선택해 주세요."),
            "OBLIGATION_HAS_PAYMENT" to (409 to "납부·처리 이력이 있는 회차를 확인해 주세요."),
            "INVALID_OBLIGATION_STATE" to (409 to "회차 상태를 확인해 주세요."),
            "ACTUAL_PAYMENT_REQUIRED" to (409 to "실제 납부를 기록한 뒤 완료해 주세요."),
            "OBLIGATION_CLOSED" to (409 to "납부 가능한 회차를 선택해 주세요."),
            "INVALID_PAYMENT_SPLIT" to (422 to "원금·이자 합계와 실제 납부액을 확인해 주세요."),
            "PAYMENT_LINKS_CHANGED" to (409 to "연결 내역이 바뀌었습니다. 다시 확인해 주세요."),
            "PAYMENT_LINK_CONFIRMATION_REQUIRED" to (409 to "연결된 납부 내역을 확인한 뒤 종료해 주세요."),
            "VALUATION_ASSET_UNAVAILABLE" to (422 to "보험 평가액에 연결할 금융 자산을 확인해 주세요."),
            "INVALID_INSURANCE_INPUT" to (422 to "보험 입력 항목을 확인해 주세요."),
            "POLICY_NUMBER_NOT_SET" to (409 to "등록된 증권번호가 없습니다."),
            "POLICY_NUMBER_UNAVAILABLE" to (503 to "증권번호를 열 수 없습니다."),
            "POLICY_UNAVAILABLE" to (422 to "사용 중인 보험계약을 선택해 주세요."),
            "RECURRING_RULE_UNAVAILABLE" to (422 to "사용 중인 납부 규칙을 선택해 주세요."),
            "PREMIUM_RULE_ALREADY_LINKED" to (409 to "이미 보험계약에 연결된 납부 규칙입니다."),
            "INVALID_MEDICAL_DATES" to (422 to "실제 진료 날짜를 확인해 주세요."),
            "MEDICAL_NODE_CYCLE" to (422 to "진료 항목의 상위 관계를 확인해 주세요."),
            "MEDICAL_NODE_IN_USE" to (409 to "연결된 기록이 있는 진료 항목입니다."),
            "INSURANCE_ASSET_REQUIRED" to (422 to "보험 평가액에 연결된 금융 자산은 종류를 바꿀 수 없습니다."),
            "INVALID_ASSET" to (422 to "자산 입력 항목을 확인해 주세요."),
            "OWNER_UNAVAILABLE" to (422 to "소유자를 확인해 주세요."),
            "ASSET_KIND_IN_USE" to (409 to "월별 금액 기록이 있어 자산·부채 구분을 바꿀 수 없습니다."),
            "ASSET_UNAVAILABLE" to (422 to "사용 중인 금융 자산을 선택해 주세요."),
            "ASSET_END_IN_FUTURE" to (422 to "실제로 보유를 종료한 날짜를 입력해 주세요."),
            "ASSET_IN_USE" to (409 to "연결된 기록이 있는 자산입니다."),
            "ASSET_ALREADY_LINKED" to (409 to "이미 계좌와 연결된 자산입니다."),
            "ACCOUNT_IN_USE" to (409 to "연결된 기록이 있는 계좌입니다."),
            "FINANCIAL_ASSET_REQUIRED" to (422 to "금융 자산을 선택해 주세요."),
            "INVALID_ACCOUNT_DATES" to (422 to "개설일과 종료일을 확인해 주세요."),
            "ACCOUNT_NUMBER_NOT_SET" to (409 to "등록된 계좌번호가 없습니다."),
            "FIELD_ENCRYPTION_UNAVAILABLE" to (503 to "계좌번호 보호 설정을 확인해 주세요."),
            "ACCOUNT_NUMBER_UNAVAILABLE" to (503 to "계좌번호를 열 수 없습니다."),
        ) + NativeDocumentPolicy.errorMessages
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
    private val networkOwner = Any()
    private val cancellation = mutableMapOf<Any, () -> Unit>()
    private var lockPolicy: AppLockPolicy? = null
    private var lockTicket: AppLockTicket? = null
    private var deviceUnlocked: (() -> Boolean)? = null
    private var lockBound = false

    init { AppLockRequests.register?.invoke(this) }

    @Synchronized fun captureAppLock(policy: AppLockPolicy, ticket: AppLockTicket, unlocked: () -> Boolean) {
        lockPolicy = policy; lockTicket = ticket; deviceUnlocked = unlocked
    }

    @Synchronized fun bindAppLock(policy: AppLockPolicy, ticket: AppLockTicket, unlocked: () -> Boolean) {
        if (lockPolicy != null) {
            if (lockPolicy !== policy || lockTicket?.generation != ticket.generation ||
                lockBound && lockTicket?.kind != ticket.kind) throw AuthFailure(AuthCode.APP_LOCKED)
            if (lockBound) return
        }
        lockPolicy = policy; lockTicket = ticket; deviceUnlocked = unlocked
        lockBound = true
    }
    @Synchronized fun appLockTicket(): AppLockTicket? = lockTicket
    @Synchronized private fun checkLock() {
        val ticket = lockTicket ?: return
        if (lockPolicy?.allowed(ticket) != true || deviceUnlocked?.invoke() != true) throw AuthFailure(AuthCode.APP_LOCKED)
    }
    @Synchronized fun checkHttp(method: String, path: String) {
        check()
        val ticket = lockTicket ?: throw AuthFailure(AuthCode.APP_LOCKED)
        if (lockPolicy?.httpAllowed(ticket, method, path) != true) throw AuthFailure(AuthCode.APP_LOCKED)
    }

    fun cancel() {
        val actions = synchronized(this) {
            active = false
            cancellation.values.toList().also { cancellation.clear() }
        }
        actions.forEach { try { it() } catch (_: Exception) { /* Continue cancelling other owners. */ } }
    }
    @Synchronized fun isActive(): Boolean = active
    fun bindCancellation(owner: Any, cancel: () -> Unit) {
        val cancelled = synchronized(this) {
            if (active) { cancellation[owner] = cancel; false } else true
        }
        if (cancelled) cancel()
    }
    @Synchronized fun releaseCancellation(owner: Any) { cancellation.remove(owner) }
    fun bindNetworkCancellation(cancel: () -> Unit) = bindCancellation(networkOwner, cancel)
    fun releaseNetworkCancellation() = releaseCancellation(networkOwner)

    @Synchronized fun <T> whileActive(action: () -> T): T {
        if (!active) throw AuthFailure(AuthCode.AUTH_CANCELLED)
        checkLock()
        return action()
    }

    fun check() {
        if (!isActive()) throw AuthFailure(AuthCode.AUTH_CANCELLED)
        checkLock()
    }
}

internal enum class AuthCode {
    AUTH_UNAVAILABLE, AUTH_CANCELLED, ACCESS_DENIED, SESSION_EXPIRED, KEY_INVALIDATED,
    NETWORK_UNAVAILABLE, INVALID_REQUEST, AUTH_FAILED, REGISTRATION_FAILED,
    PASSKEYS_DISABLED, PASSKEY_REQUIRED, PASSKEY_CANCELLED, PASSKEY_FAILED, REAUTHENTICATION_REQUIRED,
    VERSION_CONFLICT, APP_LOCKED,
    SETUP_UNAVAILABLE, SETUP_COMPLETE, INVALID_CONNECTION_CODE, REGISTRATION_CONFLICT,
    HOUSEHOLD_FULL, LOGIN_UNAVAILABLE, RATE_LIMITED, VALIDATION_ERROR,
}

/** Exception messages and causes deliberately contain no request, response, or credential. */
internal class AuthFailure(val code: AuthCode) : Exception()

internal class AuthOutcome private constructor(val value: Map<String, Any?>?, val code: AuthCode?) {
    companion object {
        fun success(value: Map<String, Any?>) = AuthOutcome(value, null)
        fun failure(code: AuthCode) = AuthOutcome(null, code)
    }
}
