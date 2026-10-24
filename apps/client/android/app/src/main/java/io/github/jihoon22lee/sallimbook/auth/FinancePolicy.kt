package io.github.jihoon22lee.sallimbook.auth

import java.net.URI
import java.time.LocalDate
import java.time.OffsetDateTime

internal enum class FinanceOperation {
    GET_PURCHASE_PLAN, LIST_CONSUMABLE_ORDERS, CREATE_CONSUMABLE_ORDER, GET_CONSUMABLE_ORDER, UPDATE_CONSUMABLE_ORDER, SUBMIT_CONSUMABLE_ORDER, RECEIVE_CONSUMABLE_ORDER, CANCEL_CONSUMABLE_ORDER,
    LIST_HOUSEHOLD_PEOPLE, CREATE_HOUSEHOLD_PERSON, UPDATE_HOUSEHOLD_PERSON,
    DELETE_APPLIANCE, DELETE_CONSUMABLE, DELETE_APPLIANCE_CONSUMABLE,
    CREATE_DOCUMENT_LINK, END_DOCUMENT_LINK, LIST_DOCUMENTS, GET_DOCUMENT, DELETE_DOCUMENT, LIST_DOCUMENT_LINKS,
    LIST_APPLIANCE_CONSUMABLES, CREATE_APPLIANCE_CONSUMABLE, GET_APPLIANCE_CONSUMABLE, UPDATE_APPLIANCE_CONSUMABLE, LIST_CONSUMABLE_REPLACEMENTS, CREATE_CONSUMABLE_REPLACEMENT, GET_CONSUMABLE_REPLACEMENT, CANCEL_CONSUMABLE_REPLACEMENT, LIST_APPLIANCES, CREATE_APPLIANCE, GET_APPLIANCE, UPDATE_APPLIANCE, LIST_CONSUMABLES, CREATE_CONSUMABLE, GET_CONSUMABLE, UPDATE_CONSUMABLE, LIST_STOCK_MOVEMENTS, CREATE_STOCK_MOVEMENT, GET_STOCK_MOVEMENT, CANCEL_STOCK_MOVEMENT, GET_HOMECARE_STATUS,
    MEDICAL_NODE_SUMMARY, INSURANCE_CASE_SUMMARY, LIST_INSURANCE_CLAIMS, CREATE_INSURANCE_CLAIM, GET_INSURANCE_CLAIM, UPDATE_INSURANCE_CLAIM, INSURANCE_CLAIM_HISTORY, LIST_MEDICAL_EXPENSES, CREATE_MEDICAL_EXPENSE, GET_MEDICAL_EXPENSE, CORRECT_MEDICAL_EXPENSE, MEDICAL_EXPENSE_HISTORY, LIST_MEDICAL_REFUNDS, CREATE_MEDICAL_REFUND, VOID_MEDICAL_EXPENSE, GET_MEDICAL_REFUND, CORRECT_MEDICAL_REFUND, MEDICAL_REFUND_HISTORY, VOID_MEDICAL_REFUND, GET_PAYOUT_ALLOCATION, LINK_PAYOUT_ALLOCATION, PAYOUT_ALLOCATION_HISTORY, LIST_INSURANCE_PAYOUTS, CREATE_INSURANCE_PAYOUT, GET_INSURANCE_PAYOUT, CORRECT_INSURANCE_PAYOUT, INSURANCE_PAYOUT_HISTORY, LIST_INSURANCE_RETURNS, CREATE_INSURANCE_RETURN, VOID_INSURANCE_PAYOUT, GET_INSURANCE_RETURN, CORRECT_INSURANCE_RETURN, INSURANCE_RETURN_HISTORY, VOID_INSURANCE_RETURN,
    LIST_ASSETS, GET_ASSET, CREATE_ASSET, UPDATE_ASSET, ARCHIVE_ASSET, DELETE_ASSET,
    LIST_ACCOUNTS, GET_ACCOUNT, CREATE_ACCOUNT, UPDATE_ACCOUNT, DELETE_ACCOUNT,
    GET_ASSET_MONTH, GET_ASSET_MONTH_REVISION, LIST_ASSET_MONTH_REVISIONS, CREATE_ASSET_MONTH_DRAFT,
    UPDATE_ASSET_MONTH_VALUE, SYNCHRONIZE_ASSET_MONTH_SCOPE, CONFIRM_ASSET_MONTH, REOPEN_ASSET_MONTH,
    CARRY_PREVIOUS_ASSET_MONTH,
    GET_INCOME_INSURANCE_SOURCE, GET_RECURRING_RULE_INSURANCE_LINK,
    LIST_INCOME, INCOME_SUMMARY, INCOME_DUPLICATE_CANDIDATES, GET_INCOME, INCOME_HISTORY,
    CREATE_INCOME, CORRECT_INCOME, VOID_INCOME, RETURN_INCOME, CONVERT_INCOME_PRECISION,
    LIST_CARDS, GET_CARD, CREATE_CARD, UPDATE_CARD, ARCHIVE_CARD, DELETE_CARD,
    GET_ASSET_COMPARISON, GET_ASSET_TRENDS,
    LIST_RECURRING_RULES, CREATE_RECURRING_RULE, GET_RECURRING_RULE, CHANGE_RECURRING_RULE, END_RECURRING_RULE, DELETE_RECURRING_RULE,
    GENERATE_OBLIGATIONS, LIST_OBLIGATIONS, LIST_OVERDUE_OBLIGATIONS, FIXED_COST_SUMMARY, GET_OBLIGATION, OBLIGATION_HISTORY,
    RESCHEDULE_OBLIGATION, SKIP_OBLIGATION, UNSKIP_OBLIGATION, COMPLETE_OBLIGATION, REOPEN_OBLIGATION,
    SETTLE_OBLIGATION, LIST_OBLIGATION_SETTLEMENTS, VOID_FIXED_SETTLEMENT,
    GET_CARD_PAYMENT_LINKS, GET_ACCOUNT_PAYMENT_LINKS, PREVIEW_PAYMENT_SWITCH, APPLY_PAYMENT_SWITCH,
    LIST_INSURANCE_CASES, CREATE_INSURANCE_CASE, GET_INSURANCE_CASE, UPDATE_INSURANCE_CASE, DELETE_INSURANCE_CASE, INSURANCE_CASE_HISTORY, LIST_MEDICAL_NODES, CREATE_MEDICAL_NODE, DELETE_MEDICAL_NODE, GET_MEDICAL_NODE, UPDATE_MEDICAL_NODE, LIST_INSURANCE_POLICIES, CREATE_INSURANCE_POLICY, GET_INSURANCE_POLICY, UPDATE_INSURANCE_POLICY, DELETE_INSURANCE_POLICY, LIST_INSURANCE_COVERAGES, CREATE_INSURANCE_COVERAGE, UPDATE_INSURANCE_COVERAGE, LIST_POLICY_PREMIUM_LINKS, CREATE_POLICY_PREMIUM_LINK, UPDATE_POLICY_PREMIUM_LINK,
}

/** Constructed from named metadata commands, never from a JS URL, headers or encoded body. */
internal class FinanceRequest(val method: String, val path: String, val body: Map<String, Any?>?, val ifMatch: String?, val idempotencyKey: String? = null) {
    override fun toString() = "FinanceRequest(redacted)"
}

/** Security projection of the generated asset/account schemas. Server owns all domain rules. */
internal object FinancePolicy {
    private val uuid = PasskeyPolicy.uuid
    private val versionTag = Regex("\"[1-9][0-9]{0,18}\"")
    private val share = Regex("(0(?:\\.[0-9]{1,18})?|1(?:\\.0{1,18})?)")
    private val assetKinds = setOf("asset", "liability")
    private val categories = setOf("real_estate", "deposit", "financial", "loan", "other")
    private val owners = setOf("individual", "joint")
    private val basis = setOf("whole", "owned")
    private val inclusion = setOf("included", "excluded")
    private val accountTypes = setOf("checking", "savings", "term_deposit", "brokerage", "pension_savings",
        "irp", "dc_pension", "isa", "cma", "other")
    private val assetFields = setOf("name", "kind", "category", "ownership_kind", "owner_member_id", "household_share",
        "amount_basis", "inclusion_status", "started_on", "ended_on", "note")
    private val assetRequired = setOf("name", "kind", "category", "ownership_kind", "amount_basis", "started_on")
    private val accountFields = setOf("institution_name", "account_type", "purpose", "opened_on")
    private val auditFields = setOf("id", "household_id", "created_by_member_id", "updated_by_member_id", "created_at", "updated_at", "version")

    private fun invalid(): Nothing = throw AuthFailure(AuthCode.INVALID_REQUEST)
    private fun objectValue(value: Any?): Map<String, Any?> {
        val row = value as? Map<*, *> ?: invalid()
        if (row.keys.any { it !is String } || row.size > 32) invalid()
        if (NativeResponseShape.tolerant) return NativeResponseShape.identity(row)
        return row.entries.associate { it.key as String to it.value }
    }
    fun id(value: Any?): String {
        val text = value as? String ?: invalid()
        if (!uuid.matches(text)) invalid()
        return text
    }
    private fun tag(value: Any?): String {
        val text = value as? String ?: invalid()
        if (!versionTag.matches(text)) invalid()
        return text
    }
    private fun text(value: Any?, max: Int, empty: Boolean = false): String {
        val result = value as? String ?: invalid()
        val trimmed = result.trim()
        if ((!empty && trimmed.isEmpty()) || result.codePointCount(0, result.length) > max) invalid()
        return result
    }
    private fun date(value: Any?): String {
        val result = value as? String ?: invalid()
        if (!Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}").matches(result)) invalid()
        try { LocalDate.parse(result) } catch (_: Exception) { invalid() }
        return result
    }
    private fun timestamp(value: Any?): String {
        val result = value as? String ?: invalid()
        try { OffsetDateTime.parse(result) } catch (_: Exception) { invalid() }
        return result
    }
    private fun choice(value: Any?, allowed: Set<String>): String {
        val result = value as? String ?: invalid()
        if (result !in allowed) invalid()
        return result
    }
    private fun version(value: Any?): Any {
        if (!(value is Int && value > 0 || value is Long && value in 1..9_007_199_254_740_991L)) invalid()
        return value!!
    }

    fun assetInput(value: Any?, patch: Boolean): Map<String, Any?> {
        val row = objectValue(value)
        val allowed = assetFields + if (patch) PaymentLinksPolicy.closureFields else emptySet()
        if ((row.keys - PaymentLinksPolicy.closureFields).isEmpty() || !allowed.containsAll(row.keys) || !patch && !row.keys.containsAll(assetRequired)) invalid()
        for ((key, item) in row) when (key) {
            "name" -> text(item, 120)
            "kind" -> choice(item, assetKinds)
            "category" -> choice(item, categories)
            "ownership_kind" -> choice(item, owners)
            "owner_member_id" -> if (item != null) id(item)
            "household_share" -> if (item !is String || item.length > 20 || !share.matches(item)) invalid()
            "amount_basis" -> choice(item, basis)
            "inclusion_status" -> choice(item, inclusion)
            "started_on" -> date(item)
            "ended_on" -> if (item != null) date(item)
            "note" -> if (item != null) text(item, 2000, true)
        }
        if (!patch && ((row["ownership_kind"] == "individual") != (row["owner_member_id"] != null))) invalid()
        if (row["started_on"] != null && row["ended_on"] != null && (row["ended_on"] as String) < (row["started_on"] as String)) invalid()
        if (patch) PaymentLinksPolicy.closure(row)
        return row
    }

    fun accountInput(value: Any?, patch: Boolean): Map<String, Any?> {
        val row = objectValue(value)
        val permitted = accountFields + if (patch) emptySet() else setOf("asset_id", "asset")
        if (row.isEmpty() || !permitted.containsAll(row.keys)) invalid()
        if (!patch && (!row.keys.containsAll(setOf("institution_name", "account_type")) ||
                (row["asset_id"] == null) == (row["asset"] == null))) invalid()
        for ((key, item) in row) when (key) {
            "institution_name" -> text(item, 120)
            "account_type" -> choice(item, accountTypes)
            "purpose" -> if (item != null) text(item, 500, true)
            "opened_on" -> if (item != null) date(item)
            "asset_id" -> if (item != null) id(item)
            "asset" -> if (item != null) {
                val asset = assetInput(item, false)
                if (asset["kind"] != "asset" || asset["category"] != "financial") invalid()
            }
        }
        return row
    }

    private fun query(value: Any?, account: Boolean): String {
        if (value == null) return ""
        val row = objectValue(value)
        val allowed = if (account) setOf("q", "cursor", "limit", "account_type", "owner_member_id", "status")
            else setOf("q", "cursor", "limit", "kind", "category", "ownership_kind", "owner_member_id", "inclusion_status", "status")
        if (!allowed.containsAll(row.keys)) invalid()
        for ((key, item) in row) when (key) {
            "q" -> if (item != null) NameSearchQuery.validate(item)
            "cursor", "owner_member_id" -> id(item)
            "limit" -> if (item !is Int || item !in 1..200) invalid()
            "account_type" -> choice(item, accountTypes)
            "kind" -> choice(item, assetKinds)
            "category" -> choice(item, categories)
            "ownership_kind" -> choice(item, owners)
            "inclusion_status" -> choice(item, inclusion)
            "status" -> choice(item, if (account) setOf("active", "closed", "all") else setOf("active", "archived", "all"))
        }
        // Only q uses URL encoding; all other values keep their exact bounded format.
        val values = row.filterValues { it != null }
        return if (values.isEmpty()) "" else "?" + values.toSortedMap().entries.joinToString("&") { "${it.key}=${NameSearchQuery.value(it.key, it.value)}" }
    }

    fun prepare(operation: FinanceOperation, value: Any?): FinanceRequest {
        if (HouseholdPeoplePolicy.supports(operation)) return HouseholdPeoplePolicy.prepare(operation, value)
        if (CashflowPolicy.supports(operation)) return CashflowPolicy.prepare(operation, value)
        if (CardMetadataPolicy.supports(operation)) return CardMetadataPolicy.prepare(operation, value)
        if (ComparisonPolicy.supports(operation)) return ComparisonPolicy.prepare(operation, value)
        if (FixedCostPolicy.supports(operation)) return FixedCostPolicy.prepare(operation, value)
        if (PaymentLinksPolicy.supports(operation)) return PaymentLinksPolicy.prepare(operation, value)
        if (NativeDocumentPolicy.supports(operation)) return NativeDocumentPolicy.prepare(operation, value)
        if (NativeHomecarePolicy.supports(operation)) return NativeHomecarePolicy.prepare(operation, value)
        if (InsuranceEventPolicy.supports(operation)) return InsuranceEventPolicy.prepare(operation, value)
        if (InsurancePolicy.supports(operation)) return InsurancePolicy.prepare(operation, value)
        val args = objectValue(value)
        val account = operation in setOf(FinanceOperation.LIST_ACCOUNTS, FinanceOperation.GET_ACCOUNT, FinanceOperation.CREATE_ACCOUNT,
            FinanceOperation.UPDATE_ACCOUNT, FinanceOperation.DELETE_ACCOUNT)
        val base = if (account) "/api/v1/accounts" else "/api/v1/assets"
        val idKey = if (account) "accountId" else "assetId"
        return when (operation) {
            FinanceOperation.LIST_ASSETS, FinanceOperation.LIST_ACCOUNTS -> {
                if (!setOf("query").containsAll(args.keys)) invalid()
                FinanceRequest("GET", base + query(args["query"], account), null, null)
            }
            FinanceOperation.GET_ASSET, FinanceOperation.GET_ACCOUNT -> {
                if (args.keys != setOf(idKey)) invalid()
                FinanceRequest("GET", "$base/${id(args[idKey])}", null, null)
            }
            FinanceOperation.CREATE_ASSET, FinanceOperation.CREATE_ACCOUNT -> {
                if (args.keys != setOf("input")) invalid()
                FinanceRequest("POST", base, if (account) accountInput(args["input"], false) else assetInput(args["input"], false), null)
            }
            FinanceOperation.UPDATE_ASSET, FinanceOperation.UPDATE_ACCOUNT -> {
                if (args.keys != setOf(idKey, "input", "ifMatch")) invalid()
                FinanceRequest("PATCH", "$base/${id(args[idKey])}", if (account) accountInput(args["input"], true) else assetInput(args["input"], true), tag(args["ifMatch"]))
            }
            FinanceOperation.ARCHIVE_ASSET -> {
                if (args.keys != setOf(idKey, "input", "ifMatch")) invalid()
                val input = objectValue(args["input"])
                if ("ended_on" !in input || !(setOf("ended_on") + PaymentLinksPolicy.closureFields).containsAll(input.keys)) invalid()
                date(input["ended_on"])
                PaymentLinksPolicy.closure(input)
                FinanceRequest("POST", "$base/${id(args[idKey])}/archive", input, tag(args["ifMatch"]))
            }
            FinanceOperation.DELETE_ASSET, FinanceOperation.DELETE_ACCOUNT -> {
                if (args.keys != setOf(idKey, "ifMatch")) invalid()
                FinanceRequest("DELETE", "$base/${id(args[idKey])}", null, tag(args["ifMatch"]))
            }
            else -> invalid()
        }
    }

    fun metadataHttpAllowed(method: String, path: String, body: Any?, ifMatch: String?, idempotencyKey: String? = null): Boolean { return try {
        if (HouseholdPeoplePolicy.httpAllowed(method, path, body, ifMatch, idempotencyKey)) return true
        if (CashflowPolicy.httpAllowed(method, path, body, ifMatch, idempotencyKey)) return true
        if (FixedCostPolicy.httpAllowed(method, path, body, ifMatch, idempotencyKey)) return true
        if (NativeDocumentPolicy.httpAllowed(method, path, body, ifMatch, idempotencyKey)) return true
        if (NativeHomecarePolicy.httpAllowed(method, path, body, ifMatch, idempotencyKey)) return true
        if (InsuranceEventPolicy.httpAllowed(method, path, body, ifMatch, idempotencyKey)) return true
        if (idempotencyKey != null) return false
        if (CardMetadataPolicy.httpAllowed(method, path, body, ifMatch)) return true
        if (ComparisonPolicy.httpAllowed(method, path, body, ifMatch)) return true
        if (PaymentLinksPolicy.httpAllowed(method, path, body, ifMatch)) return true
        if (InsurancePolicy.httpAllowed(method, path, body, ifMatch)) return true
        val uri = URI(path)
        if (uri.isAbsolute || uri.rawAuthority != null || uri.rawFragment != null || '%' in uri.rawPath || '\\' in path ||
            path.any { it.isWhitespace() || it.code < 32 }) false
        else {
            val pieces = uri.rawPath.split('/')
            val account = pieces.getOrNull(3) == "accounts"
            val base = if (account) "/api/v1/accounts" else "/api/v1/assets"
            if (uri.rawPath != base && !uri.rawPath.startsWith("$base/")) false
            else {
                val idKey = if (account) "accountId" else "assetId"
                val args = mutableMapOf<String, Any?>()
                val operation = when {
                    uri.rawPath == base && method == "GET" && body == null && ifMatch == null -> {
                        val values = mutableMapOf<String, Any?>()
                        uri.rawQuery?.let { query ->
                            if (query.isEmpty()) invalid()
                            for (part in query.split('&')) {
                                val pair = part.split('=', limit = 2)
                                if (pair.size != 2 || pair[0] in values) invalid()
                                values[pair[0]] = if (pair[0] == "limit") {
                                    val number = pair[1].toIntOrNull() ?: invalid()
                                    if (number.toString() != pair[1]) invalid()
                                    number
                                } else if (pair[0] == "q") NameSearchQuery.decode(pair[1]) else pair[1]
                            }
                        }
                        args["query"] = values
                        if (account) FinanceOperation.LIST_ACCOUNTS else FinanceOperation.LIST_ASSETS
                    }
                    uri.rawPath == base && method == "POST" && uri.rawQuery == null && ifMatch == null -> {
                        args["input"] = body
                        if (account) FinanceOperation.CREATE_ACCOUNT else FinanceOperation.CREATE_ASSET
                    }
                    pieces.size == 5 && uri.rawQuery == null -> {
                        args[idKey] = id(pieces[4])
                        when (method) {
                            "GET" -> {
                                if (body != null || ifMatch != null) invalid()
                                if (account) FinanceOperation.GET_ACCOUNT else FinanceOperation.GET_ASSET
                            }
                            "PATCH" -> {
                                args["input"] = body; args["ifMatch"] = ifMatch
                                if (account) FinanceOperation.UPDATE_ACCOUNT else FinanceOperation.UPDATE_ASSET
                            }
                            "DELETE" -> {
                                if (body != null) invalid()
                                args["ifMatch"] = ifMatch
                                if (account) FinanceOperation.DELETE_ACCOUNT else FinanceOperation.DELETE_ASSET
                            }
                            else -> invalid()
                        }
                    }
                    !account && pieces.size == 6 && pieces[5] == "archive" && method == "POST" && uri.rawQuery == null -> {
                        args[idKey] = id(pieces[4]); args["input"] = body; args["ifMatch"] = ifMatch
                        FinanceOperation.ARCHIVE_ASSET
                    }
                    else -> invalid()
                }
                prepare(operation, args).let { it.method == method && it.path == path && it.ifMatch == ifMatch }
            }
        }
    } catch (_: Exception) { false }
    }

    fun asset(value: Any?): Map<String, Any?> {
        val row = objectValue(value)
        val known = assetFields + auditFields + setOf("status", "archived_at")
        NativeResponseShape.accept(row, row.keys, known, known, ::invalid)
        assetInput(row.filterKeys { it in assetFields }, false)
        audit(row)
        choice(row["status"], setOf("active", "archived"))
        row["archived_at"]?.let(::timestamp)
        return row
    }

    fun account(value: Any?): Map<String, Any?> {
        val row = objectValue(value)
        val known = accountFields + auditFields + setOf("asset_id", "asset", "masked_number", "has_number", "closed_on", "status")
        NativeResponseShape.accept(row, row.keys, known, known, ::invalid)
        audit(row)
        id(row["asset_id"])
        val asset = asset(row["asset"])
        if (asset["id"] != row["asset_id"] || asset["household_id"] != row["household_id"] ||
            asset["kind"] != "asset" || asset["category"] != "financial") invalid()
        text(row["institution_name"], 120)
        choice(row["account_type"], accountTypes)
        row["purpose"]?.let { text(it, 500, true) }
        row["opened_on"]?.let(::date)
        row["closed_on"]?.let(::date)
        choice(row["status"], setOf("active", "closed"))
        val hasNumber = row["has_number"] as? Boolean ?: invalid()
        val masked = row["masked_number"]
        if (hasNumber && (masked !is String || !Regex("\\*\\*\\*\\* [A-Za-z0-9]{4}").matches(masked)) || !hasNumber && masked != null) invalid()
        return NativeResponseShape.known(row) + mapOf("asset" to asset)
    }

    private fun audit(row: Map<String, Any?>) {
        listOf("id", "household_id", "created_by_member_id", "updated_by_member_id").forEach { id(row[it]) }
        timestamp(row["created_at"]); timestamp(row["updated_at"]); version(row["version"])
    }

    /** Metadata responses tolerate fields added by a later API version and drop them; see NativeResponseShape. */
    fun response(operation: FinanceOperation, request: FinanceRequest, status: Int, value: Any?): Any? =
        NativeResponseShape.project { validatedResponse(operation, request, status, value) }

    /** A 2xx reply to a write means the server already stored it. An unreadable reply is still withheld,
     * but reported as an unknown outcome so the screen asks the user to check instead of resubmitting. */
    fun reply(operation: FinanceOperation, request: FinanceRequest, status: Int, value: Any?): Any? = try {
        response(operation, request, status, value)
    } catch (failure: AuthFailure) {
        if (request.method == "GET") throw failure
        throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
    }

    private fun validatedResponse(operation: FinanceOperation, request: FinanceRequest, status: Int, value: Any?): Any? {
        try {
            if (CashflowPolicy.supports(operation)) return CashflowPolicy.response(operation, request, status, value)
            if (CardMetadataPolicy.supports(operation)) return CardMetadataPolicy.response(operation, request, status, value)
            if (ComparisonPolicy.supports(operation)) return ComparisonPolicy.response(operation, request, status, value)
            if (FixedCostPolicy.supports(operation)) return FixedCostPolicy.response(operation, request, status, value)
            if (PaymentLinksPolicy.supports(operation)) return PaymentLinksPolicy.response(operation, request, status, value)
            if (NativeDocumentPolicy.supports(operation)) return NativeDocumentPolicy.response(operation, request, status, value)
            if (HouseholdPeoplePolicy.supports(operation)) return HouseholdPeoplePolicy.response(operation, request, status, value)
            if (NativeHomecarePolicy.supports(operation)) return NativeHomecarePolicy.response(operation, request, status, value)
            if (InsuranceEventPolicy.supports(operation)) return InsuranceEventPolicy.response(operation, request, status, value)
            if (InsurancePolicy.supports(operation)) return InsurancePolicy.response(operation, request, status, value)
            if (operation in setOf(FinanceOperation.DELETE_ASSET, FinanceOperation.DELETE_ACCOUNT)) {
                if (status != 204 || value != null) invalid()
                return null
            }
            val expected = if (operation in setOf(FinanceOperation.CREATE_ASSET, FinanceOperation.CREATE_ACCOUNT)) 201 else 200
            if (status != expected) invalid()
            val account = operation in setOf(FinanceOperation.LIST_ACCOUNTS, FinanceOperation.GET_ACCOUNT, FinanceOperation.CREATE_ACCOUNT, FinanceOperation.UPDATE_ACCOUNT)
            if (operation in setOf(FinanceOperation.LIST_ASSETS, FinanceOperation.LIST_ACCOUNTS)) {
                val row = objectValue(value)
                NativeResponseShape.accept(row, row.keys, setOf("items", "next_cursor"), setOf("items", "next_cursor"), ::invalid)
                val items = row["items"] as? List<*> ?: invalid()
                if (items.size > 200) invalid()
                return mapOf("items" to items.map { if (account) account(it) else asset(it) },
                    "next_cursor" to row["next_cursor"]?.let(::id))
            }
            val row = if (account) account(value) else asset(value)
            if (operation !in setOf(FinanceOperation.CREATE_ASSET, FinanceOperation.CREATE_ACCOUNT) &&
                row["id"] != URI(request.path).path.split('/')[4]) invalid()
            return row
        } catch (_: Exception) { throw AuthFailure(AuthCode.ACCESS_DENIED) }
    }

    /** Internal number routes have a separate validator and never enter metadata projection. */
    fun numberPath(path: String, reveal: Boolean): Boolean {
        val prefix = "/api/v1/accounts/"
        if (!path.startsWith(prefix)) return false
        val suffix = path.removePrefix(prefix)
        return if (reveal) suffix.endsWith("/reveal") && uuid.matches(suffix.removeSuffix("/reveal")) else uuid.matches(suffix)
    }

    fun number(value: CharArray): Boolean {
        if (value.size !in 5..64 || !value.first().isAsciiLetterOrDigit() || !value.last().isAsciiLetterOrDigit()) return false
        if (value.any { !it.isAsciiLetterOrDigit() && it != ' ' && it != '-' }) return false
        return value.count { it != ' ' && it != '-' } in 5..40
    }

    fun readNumber(value: Any?, accountId: String): CharArray {
        try {
            val row = objectValue(value)
            if (row.keys != setOf("id", "account_number", "display_for_seconds") || row["id"] != id(accountId) || row["display_for_seconds"] != 30) invalid()
            val result = (row["account_number"] as? String)?.toCharArray() ?: invalid()
            if (!number(result)) { result.fill('\u0000'); invalid() }
            return result
        } catch (_: Exception) { throw AuthFailure(AuthCode.ACCESS_DENIED) }
    }
    private fun Char.isAsciiLetterOrDigit() = this in 'a'..'z' || this in 'A'..'Z' || this in '0'..'9'
}
