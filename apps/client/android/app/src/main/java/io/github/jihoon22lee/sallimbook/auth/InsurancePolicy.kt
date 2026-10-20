package io.github.jihoon22lee.sallimbook.auth

import java.net.URI
import java.time.LocalDate
import java.time.OffsetDateTime

private typealias InsuranceField = (Any?) -> Unit

/** Strict insurance metadata projection; policy number plaintext is a separate native-only path. */
internal object InsurancePolicy {
    private fun invalid(): Nothing = throw AuthFailure(AuthCode.INVALID_REQUEST)
    private fun obj(value: Any?): Map<String, Any?> {
        val row = value as? Map<*, *> ?: invalid()
        if (row.size > 48 || row.keys.any { it !is String }) invalid()
        return row.entries.associate { it.key as String to it.value }
    }
    private fun integer(value: Any?, minimum: Long = 1, maximum: Long = 9_007_199_254_740_991L) {
        val number = when (value) { is Int -> value.toLong(); is Long -> value; else -> invalid() }
        if (number !in minimum..maximum) invalid()
    }
    private fun text(maximum: Int, empty: Boolean = false): InsuranceField = {
        if (it !is String || it.codePointCount(0, it.length) > maximum || !empty && it.isBlank()) invalid()
    }
    private val id: InsuranceField = { FinancePolicy.id(it); Unit }
    private val positive: InsuranceField = { integer(it) }
    private val count: InsuranceField = { integer(it, 0) }
    private val bool: InsuranceField = { if (it !is Boolean) invalid() }
    private val money: InsuranceField = { if (it !is String || !Regex("0|[1-9][0-9]{0,19}").matches(it)) invalid() }
    private val signedMoney: InsuranceField = { if (it !is String || !Regex("0|-?[1-9][0-9]{0,19}").matches(it)) invalid() }
    private val positiveMoney: InsuranceField = { money(it); if (it == "0") invalid() }
    private val date: InsuranceField = {
        if (it !is String || !Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}").matches(it) || it.startsWith("0000")) invalid()
        try { LocalDate.parse(it) } catch (_: Exception) { invalid() }
    }
    private val timestamp: InsuranceField = {
        if (it !is String || it.length > 40) invalid()
        try { OffsetDateTime.parse(it) } catch (_: Exception) { invalid() }
    }
    private fun choice(vararg values: String): InsuranceField = { if (it !is String || it !in values) invalid() }
    private fun nullable(rule: InsuranceField): InsuranceField = { if (it != null) rule(it) }
    // Same bound as the server's SignedKrwString; a case's net burden can be negative.
    private val signedKrw: InsuranceField = { if (it !is String || !Regex("^(0|-?[1-9][0-9]{0,19})\$").matches(it)) invalid() }
    private fun shape(value: Any?, fields: Map<String, InsuranceField>, required: Set<String> = fields.keys): Map<String, Any?> {
        val row = obj(value)
        if (!fields.keys.containsAll(row.keys) || !row.keys.containsAll(required)) invalid()
        row.forEach { (name, item) -> fields.getValue(name)(item) }
        return row
    }
    private fun tag(value: Any?): String {
        if (value !is String || !Regex("\"[1-9][0-9]{0,18}\"").matches(value)) invalid()
        return value
    }
    private data class Route(val method: String, val path: String, val input: String, val output: String, val query: Boolean, val version: Boolean, val status: Int)
    private val routes = mapOf(
        FinanceOperation.LIST_INSURANCE_CASES to Route("GET", "/api/v1/insurance/cases", "", "CaseListResponse", true, false, 200),
        FinanceOperation.CREATE_INSURANCE_CASE to Route("POST", "/api/v1/insurance/cases", "CaseInput", "CaseResponse", false, false, 201),
        FinanceOperation.GET_INSURANCE_CASE to Route("GET", "/api/v1/insurance/cases/{caseId}", "", "CaseResponse", false, false, 200),
        FinanceOperation.UPDATE_INSURANCE_CASE to Route("PATCH", "/api/v1/insurance/cases/{caseId}", "CasePatch", "CaseResponse", false, true, 200),
        FinanceOperation.INSURANCE_CASE_HISTORY to Route("GET", "/api/v1/insurance/cases/{caseId}/history", "", "CaseHistoryResponse", true, false, 200),
        FinanceOperation.LIST_MEDICAL_NODES to Route("GET", "/api/v1/insurance/cases/{caseId}/nodes", "", "MedicalNodeListResponse", true, false, 200),
        FinanceOperation.CREATE_MEDICAL_NODE to Route("POST", "/api/v1/insurance/cases/{caseId}/nodes", "MedicalNodeInput", "MedicalNodeResponse", false, false, 201),
        FinanceOperation.DELETE_MEDICAL_NODE to Route("DELETE", "/api/v1/insurance/cases/{caseId}/nodes/{nodeId}", "", "", false, true, 204),
        FinanceOperation.GET_MEDICAL_NODE to Route("GET", "/api/v1/insurance/cases/{caseId}/nodes/{nodeId}", "", "MedicalNodeResponse", false, false, 200),
        FinanceOperation.UPDATE_MEDICAL_NODE to Route("PATCH", "/api/v1/insurance/cases/{caseId}/nodes/{nodeId}", "MedicalNodePatch", "MedicalNodeResponse", false, true, 200),
        FinanceOperation.LIST_INSURANCE_POLICIES to Route("GET", "/api/v1/insurance/policies", "", "PolicyListResponse", true, false, 200),
        FinanceOperation.CREATE_INSURANCE_POLICY to Route("POST", "/api/v1/insurance/policies", "PolicyCreate", "PolicyResponse", false, false, 201),
        FinanceOperation.GET_INSURANCE_POLICY to Route("GET", "/api/v1/insurance/policies/{policyId}", "", "PolicyResponse", false, false, 200),
        FinanceOperation.UPDATE_INSURANCE_POLICY to Route("PATCH", "/api/v1/insurance/policies/{policyId}", "PolicyPatch", "PolicyResponse", false, true, 200),
        FinanceOperation.LIST_INSURANCE_COVERAGES to Route("GET", "/api/v1/insurance/policies/{policyId}/coverages", "", "CoverageListResponse", true, false, 200),
        FinanceOperation.CREATE_INSURANCE_COVERAGE to Route("POST", "/api/v1/insurance/policies/{policyId}/coverages", "CoverageInput", "CoverageResponse", false, false, 201),
        FinanceOperation.UPDATE_INSURANCE_COVERAGE to Route("PATCH", "/api/v1/insurance/policies/{policyId}/coverages/{coverageId}", "CoveragePatch", "CoverageResponse", false, true, 200),
        FinanceOperation.LIST_POLICY_PREMIUM_LINKS to Route("GET", "/api/v1/insurance/policies/{policyId}/premium-links", "", "PremiumLinkListResponse", true, false, 200),
        FinanceOperation.CREATE_POLICY_PREMIUM_LINK to Route("POST", "/api/v1/insurance/policies/{policyId}/premium-links", "PremiumLinkCreate", "PremiumLinkResponse", false, false, 201),
        FinanceOperation.UPDATE_POLICY_PREMIUM_LINK to Route("PATCH", "/api/v1/insurance/policies/{policyId}/premium-links/{linkId}", "PremiumLinkPatch", "PremiumLinkResponse", false, true, 200)
    )
    private val audit = mapOf("id" to id, "household_id" to id, "created_by_member_id" to id, "updated_by_member_id" to id,
        "created_at" to timestamp, "updated_at" to timestamp, "version" to positive)
    private val policyFields = mapOf("insurer" to text(120), "product_name" to text(120), "policyholder_member_id" to nullable(id),
        "insured_member_id" to nullable(id), "beneficiary_note" to nullable(text(1000, true)), "contract_start" to nullable(date),
        "contract_end" to nullable(date), "coverage_start" to date, "coverage_end" to nullable(date), "payment_start" to nullable(date),
        "payment_end" to nullable(date), "status" to choice("active", "ended", "lapsed"), "valuation_asset_id" to nullable(id), "note" to nullable(text(2000, true)))
    private val coverageFields = mapOf("name" to text(120), "benefit_type" to choice("reimbursement", "fixed", "other"),
        "insured_amount_krw" to nullable(money), "coverage_start" to nullable(date), "coverage_end" to nullable(date), "note" to nullable(text(2000, true)), "active" to bool)
    private val caseFields = mapOf("title" to text(120), "patient_member_id" to id, "diagnosis_note" to nullable(text(2000, true)),
        "diagnosis_code" to nullable(text(80, true)), "start_on" to date, "end_on" to nullable(date), "treatment_state" to choice("ongoing", "ended"), "financial_state" to choice("open", "settled"))
    private val nodeFields = mapOf("parent_id" to nullable(id), "kind" to choice("outpatient", "inpatient", "surgery", "prescription", "pharmacy", "follow_up", "group"),
        "label" to text(120), "provider_name" to nullable(text(120)), "start_on" to nullable(date), "end_on" to nullable(date),
        "sort_order" to { v: Any? -> integer(v, 0, 1_000_000) }, "note" to nullable(text(2000, true)))
    fun supports(operation: FinanceOperation) = operation in routes
    private fun periods(row: Map<String, Any?>) {
        for ((start, end) in listOf("contract_start" to "contract_end", "coverage_start" to "coverage_end", "payment_start" to "payment_end", "start_on" to "end_on")) {
            if (row[start] != null && row[end] != null && (row[start] as String) > (row[end] as String)) invalid()
        }
    }
    private fun casePeriod(row: Map<String, Any?>) {
        periods(row)
        if ((row["treatment_state"] == "ended") != (row["end_on"] != null)) invalid()
    }
    private fun input(schema: String, value: Any?): Map<String, Any?> {
        val patch = schema.endsWith("Patch")
        val fields = when (schema) {
            "PolicyCreate", "PolicyPatch" -> policyFields
            "CoverageInput", "CoveragePatch" -> coverageFields
            "CaseInput" -> caseFields
            "CasePatch" -> caseFields + mapOf("reason" to text(500))
            "MedicalNodeInput", "MedicalNodePatch" -> nodeFields
            "PremiumLinkCreate" -> mapOf("rule_id" to id)
            "PremiumLinkPatch" -> mapOf("active" to bool)
            else -> invalid()
        }
        val required = when (schema) {
            "PolicyCreate" -> setOf("insurer", "product_name", "coverage_start")
            "CoverageInput" -> setOf("name", "benefit_type")
            "CaseInput" -> setOf("title", "patient_member_id", "start_on")
            "MedicalNodeInput" -> setOf("kind", "label")
            "CasePatch" -> setOf("reason")
            "PremiumLinkCreate", "PremiumLinkPatch" -> fields.keys
            else -> emptySet()
        }
        val row = shape(value, fields, required)
        if (row.isEmpty() || patch && (row.keys - "reason").isEmpty()) invalid()
        periods(row)
        if (schema == "CaseInput") casePeriod(mapOf("treatment_state" to "ongoing") + row)
        if (schema == "CasePatch" && row.keys.containsAll(setOf("treatment_state", "end_on"))) casePeriod(row)
        return row
    }
    private fun query(operation: FinanceOperation, value: Any?): Map<String, Any?> {
        if (value == null) return emptyMap()
        val fields = mapOf("cursor" to nullable(if (operation == FinanceOperation.INSURANCE_CASE_HISTORY) positive else id), "limit" to { v: Any? -> integer(v, 1, 200) }) + when (operation) {
            FinanceOperation.LIST_INSURANCE_POLICIES -> mapOf("status" to nullable(choice("active", "ended", "lapsed")), "insured_member_id" to nullable(id), "policyholder_member_id" to nullable(id))
            FinanceOperation.LIST_INSURANCE_CASES -> mapOf("patient_member_id" to nullable(id), "treatment_state" to nullable(choice("ongoing", "ended")), "financial_state" to nullable(choice("open", "settled")))
            FinanceOperation.LIST_INSURANCE_COVERAGES, FinanceOperation.LIST_POLICY_PREMIUM_LINKS -> mapOf("active" to nullable(bool))
            else -> emptyMap()
        }
        return shape(value, fields, emptySet()).filterValues { it != null }
    }
    fun prepare(operation: FinanceOperation, value: Any?): FinanceRequest {
        val route = routes[operation] ?: invalid()
        val args = obj(value)
        val ids = Regex("\\{([^}]+)\\}").findAll(route.path).map { it.groupValues[1] }.toSet()
        val required = ids + (if (route.input.isNotEmpty()) setOf("input") else emptySet()) + (if (route.version) setOf("ifMatch") else emptySet())
        if (!args.keys.containsAll(required) || !(required + if (route.query) setOf("query") else emptySet()).containsAll(args.keys)) invalid()
        var path = route.path
        ids.forEach { path = path.replace("{$it}", FinancePolicy.id(args[it])) }
        val values = if (route.query) query(operation, args["query"]) else emptyMap()
        if (values.isNotEmpty()) path += "?" + values.toSortedMap().entries.joinToString("&") { "${it.key}=${it.value}" }
        val body = if (route.input.isEmpty()) null else input(route.input, args["input"])
        if (body?.get("parent_id") != null && body["parent_id"] == args["nodeId"]) invalid()
        return FinanceRequest(route.method, path, body, if (route.version) tag(args["ifMatch"]) else null)
    }
    fun httpAllowed(method: String, path: String, body: Any?, ifMatch: String?): Boolean = try {
        val uri = URI(path)
        if (uri.isAbsolute || uri.rawAuthority != null || uri.rawFragment != null || '%' in path || '\\' in path || path.any { it.isWhitespace() || it.code < 32 }) invalid()
        val parts = uri.rawPath.split('/')
        val entry = routes.entries.firstOrNull { (_, route) ->
            val pattern = route.path.split('/')
            route.method == method && pattern.size == parts.size && pattern.indices.all { pattern[it].startsWith('{') || pattern[it] == parts[it] }
        } ?: invalid()
        val args = mutableMapOf<String, Any?>()
        entry.value.path.split('/').forEachIndexed { n, part -> if (part.startsWith('{')) args[part.removeSurrounding("{", "}")] = parts[n] }
        if (entry.value.input.isNotEmpty()) args["input"] = body else if (body != null) invalid()
        if (entry.value.version) args["ifMatch"] = ifMatch else if (ifMatch != null) invalid()
        if (uri.rawQuery != null) {
            if (!entry.value.query || uri.rawQuery.isEmpty()) invalid()
            val values = mutableMapOf<String, Any?>()
            uri.rawQuery.split('&').forEach { part ->
                val pair = part.split('=', limit = 2)
                if (pair.size != 2 || pair[0] in values) invalid()
                values[pair[0]] = when {
                    pair[0] == "active" -> when (pair[1]) { "true" -> true; "false" -> false; else -> invalid() }
                    pair[0] == "limit" || pair[0] == "cursor" && entry.key == FinanceOperation.INSURANCE_CASE_HISTORY -> pair[1].toLongOrNull() ?: invalid()
                    else -> pair[1]
                }
            }
            args["query"] = values
        }
        val request = prepare(entry.key, args)
        request.path == path && request.body == body && request.ifMatch == ifMatch
    } catch (_: Exception) { false }
    fun policy(value: Any?): Map<String, Any?> {
        val row = shape(value, policyFields + audit + mapOf("has_number" to bool, "masked_number" to nullable(text(9))))
        periods(row)
        val masked = row["masked_number"]
        if (row["has_number"] == true && (masked !is String || !Regex("\\*\\*\\*\\* [A-Za-z0-9]{4}").matches(masked)) || row["has_number"] == false && masked != null) invalid()
        return row
    }
    private fun entity(schema: String, value: Any?): Map<String, Any?> {
        val row = when (schema) {
            "PolicyResponse" -> policy(value)
            "CoverageResponse" -> shape(value, coverageFields + audit + mapOf("policy_id" to id))
            "PremiumLinkResponse" -> shape(value, audit + mapOf("policy_id" to id, "rule_id" to id, "active" to bool,
                "ended_at" to nullable(timestamp), "rule" to { v: Any? -> FixedCostPolicy.ruleMetadata(v); Unit }))
            "CaseResponse" -> shape(value, caseFields + audit)
            "CaseListItem" -> shape(value, (caseFields - setOf("diagnosis_note", "diagnosis_code")) + audit + mapOf("net_burden_krw" to signedKrw))
            "CaseRevisionResponse" -> shape(value, caseFields + mapOf("case_id" to id, "version" to positive, "changed_by_member_id" to id, "changed_at" to timestamp, "reason" to nullable(text(500))))
            "MedicalNodeResponse" -> shape(value, nodeFields + audit + mapOf("case_id" to id))
            else -> invalid()
        }
        periods(row)
        if (schema.startsWith("Case")) casePeriod(row)
        if (schema == "PremiumLinkResponse") {
            val rule = obj(row["rule"])
            if (rule["id"] != row["rule_id"] || rule["household_id"] != row["household_id"] || (row["active"] == true) != (row["ended_at"] == null)) invalid()
        }
        if (schema == "MedicalNodeResponse" && row["parent_id"] == row["id"]) invalid()
        return row
    }
    fun response(operation: FinanceOperation, request: FinanceRequest, status: Int, value: Any?): Any? {
        val route = routes[operation] ?: invalid()
        if (status != route.status) invalid()
        if (status == 204) { if (value != null) invalid(); return null }
        val parts = URI(request.path).path.split('/')
        fun bound(row: Map<String, Any?>) {
            if (row.containsKey("policy_id") && row["policy_id"] != parts[5]) invalid()
            if (row.containsKey("case_id") && row["case_id"] != parts[5]) invalid()
        }
        if (route.query) {
            val page = obj(value)
            if (page.keys != setOf("items", "next_cursor")) invalid()
            val items = page["items"] as? List<*> ?: invalid()
            val params = URI(request.path).rawQuery?.split('&')?.associate { it.substringBefore('=') to it.substringAfter('=') } ?: emptyMap()
            if (items.size > (params["limit"]?.toInt() ?: 50)) invalid()
            val history = operation == FinanceOperation.INSURANCE_CASE_HISTORY
            val schema = when (route.output) {
                "PolicyListResponse" -> "PolicyResponse"
                "CoverageListResponse" -> "CoverageResponse"
                "PremiumLinkListResponse" -> "PremiumLinkResponse"
                "CaseListResponse" -> "CaseListItem"
                "CaseHistoryResponse" -> "CaseRevisionResponse"
                "MedicalNodeListResponse" -> "MedicalNodeResponse"
                else -> invalid()
            }
            var previous: String? = params["cursor"]
            val seen = mutableSetOf<String>().apply { params["cursor"]?.let(::add) }
            for (item in items) {
                val row = entity(schema, item); bound(row)
                val current = row[if (history) "version" else "id"].toString()
                if (!seen.add(current)) invalid()
                // All metadata pages keep server order; the UUID cursor is an opaque position.
                if (history && previous != null && current.toLong() >= previous.toLong()) invalid()
                previous = current
            }
            page["next_cursor"]?.let {
                if (history) positive(it) else id(it)
                if (items.isEmpty() || it.toString() != previous) invalid()
            }
            return page
        }
        val row = entity(route.output, value); bound(row)
        if (route.method != "POST" && row["id"] != parts.last()) invalid()
        return row
    }
    fun numberPath(path: String, reveal: Boolean): Boolean {
        val prefix = "/api/v1/insurance/policies/"
        if (!path.startsWith(prefix)) return false
        val suffix = path.removePrefix(prefix)
        return if (reveal) suffix.endsWith("/reveal") && PasskeyPolicy.uuid.matches(suffix.removeSuffix("/reveal")) else PasskeyPolicy.uuid.matches(suffix)
    }
    fun numberHttpAllowed(method: String, path: String, body: Any?, ifMatch: String?): Boolean = try {
        val row = obj(body)
        when {
            method == "PATCH" && numberPath(path, false) && PasskeyPolicy.target(path.substringAfterLast('/'), ifMatch) && row.keys == setOf("policy_number") -> {
                if (row["policy_number"] == null) true else {
                    val chars = (row["policy_number"] as? String)?.toCharArray() ?: invalid()
                    try { FinancePolicy.number(chars) } finally { chars.fill('\u0000') }
                }
            }
            method == "POST" && numberPath(path, true) && ifMatch == null && row.isEmpty() -> true
            else -> false
        }
    } catch (_: Exception) { false }
    fun readNumber(value: Any?, policyId: String): CharArray {
        try {
            val row = obj(value)
            if (row.keys != setOf("id", "policy_number", "display_for_seconds") || row["id"] != FinancePolicy.id(policyId) || row["display_for_seconds"] != 30) invalid()
            val result = (row["policy_number"] as? String)?.toCharArray() ?: invalid()
            if (!FinancePolicy.number(result)) { result.fill('\u0000'); invalid() }
            return result
        } catch (_: Exception) { throw AuthFailure(AuthCode.ACCESS_DENIED) }
    }
}
