package io.github.jihoon22lee.sallimbook.auth

import java.net.URLDecoder
import java.net.URLEncoder
import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZoneOffset
import java.util.Base64

internal class NativeAuditRequest(val path:String,val limit:Int,val query:Map<String,Any>,val activity:Boolean=false)

/** Security projection of generated audit DTOs; values, raw safe_diff and arbitrary URLs are excluded. */
internal object NativeAuditWire {
    private val uuid=Regex("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
    private val stamp=Regex("[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\\.[0-9]{1,9})?(Z|[+-][0-9]{2}:[0-9]{2})")
    private val queryFields=listOf("limit","cursor","entity_type","entity_id","actor_member_id","action","since","until")
    private val rowFields=setOf("id","actor_member_id","entity_type","entity_id","action","request_id","before_version","after_version","occurred_at","changed_fields")
    private fun invalid():Nothing=throw AuthFailure(AuthCode.INVALID_REQUEST)
    private fun record(value:Any?,fields:Set<String>):Map<*,*> {
        val row=value as? Map<*,*> ?: invalid()
        if(row.keys!=fields) invalid()
        return row
    }
    private fun id(value:Any?):String=(value as? String)?.takeIf(uuid::matches) ?: invalid()
    private fun time(value:Any?,utc:Boolean=false):Instant {
        val text=value as? String ?: invalid()
        if(!stamp.matches(text)) invalid()
        val parsed=try { OffsetDateTime.parse(text) } catch(_:Exception) { invalid() }
        if(utc && parsed.offset!=ZoneOffset.UTC) invalid()
        return parsed.toInstant()
    }
    private fun integer(value:Any?,maximum:Long):Long {
        val number=when(value) { is Int -> value.toLong(); is Long -> value; else -> invalid() }
        if(number !in 1..maximum) invalid()
        return number
    }
    private fun cursor(value:Any?):Pair<Instant,String> {
        val text=value as? String ?: invalid()
        if(!Regex("[A-Za-z0-9_-]{1,1024}").matches(text)) invalid()
        try {
            val bytes=Base64.getUrlDecoder().decode(text)
            if(Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)!=text || bytes.any { it.toInt() !in 32..126 }) invalid()
            val json=bytes.toString(Charsets.US_ASCII)
            val values=NativeVaultJson.decode(json) as? List<*> ?: invalid()
            if(values.size!=3 || values.any { it !is String }) invalid()
            val occurred=time(values[0],true); val identifier=id(values[1])
            if(!(values[2] as String).matches(Regex("[0-9a-f]{64}")) || json!=values.joinToString(",","[","]") { "\"$it\"" }) invalid()
            return occurred to identifier
        } catch(_:Exception) { invalid() }
    }
    fun prepare(value:Any?):NativeAuditRequest {
        val arguments=value as? Map<*,*> ?: invalid()
        if(arguments.keys.any { it!="query" && it!="activity" }) invalid()
        val activity=arguments["activity"]?.let { if(it!=true) invalid(); true } ?: false
        val input=if(arguments.containsKey("query")) arguments["query"] as? Map<*,*> ?: invalid() else emptyMap<Any,Any>()
        if(input.keys.any { it !in queryFields }) invalid()
        val limit=if(input.containsKey("limit")) integer(input["limit"],200).toInt() else 50
        val query=linkedMapOf<String,Any>("limit" to limit)
        for(key in queryFields.drop(1)) input[key]?.let { value ->
            when(key) {
                "cursor" -> cursor(value)
                "entity_id","actor_member_id" -> id(value)
                "entity_type" -> if(value !in entityTypes) invalid()
                "action" -> if(value !in actions) invalid()
                "since","until" -> time(value)
            }
            query[key]=value
        }
        if(query["since"]!=null && query["until"]!=null && time(query["since"])>=time(query["until"])) invalid()
        val path=(if(activity) "/api/v1/activity-events?" else "/api/v1/audit-events?")+query.entries.joinToString("&") { (key,item) -> "$key="+URLEncoder.encode(item.toString(),Charsets.UTF_8.name()).replace("+","%20") }
        return NativeAuditRequest(path,limit,query.toMap(),activity)
    }
    fun httpAllowed(method:String,path:String,body:Any?,ifMatch:String?,idempotencyKey:String?,stepUp:String?):Boolean=try {
        if(method!="GET" || body!=null || ifMatch!=null || idempotencyKey!=null || stepUp!=null ||
            !(path.startsWith("/api/v1/audit-events?") || path.startsWith("/api/v1/activity-events?")) || path.length>2048) false
        else {
            val query=linkedMapOf<String,Any>()
            for(part in path.substringAfter('?').split('&')) {
                val pair=part.split('=',limit=2)
                if(pair.size!=2 || query.containsKey(pair[0])) invalid()
                val value=URLDecoder.decode(pair[1],Charsets.UTF_8.name())
                query[pair[0]]=if(pair[0]=="limit") {
                    if(!Regex("[1-9][0-9]{0,2}").matches(value)) invalid()
                    value.toInt()
                } else value
            }
            prepare(if(path.startsWith("/api/v1/activity-events?")) mapOf("query" to query,"activity" to true) else mapOf("query" to query)).path==path
        }
    } catch(_:Exception) { false }
    /** Current identity is fetched through the existing /me security projection, never supplied by JS. */
    fun identity(value:Any?):List<String> = try {
        val row=AuthPolicy.metadataBody("GET","/api/v1/me",200,value) as Map<*,*>
        listOf(id(row["household_id"]),id(row["member_id"]),id(row["user_id"]))
    } catch(_:Exception) { throw AuthFailure(AuthCode.ACCESS_DENIED) }
    fun response(request:NativeAuditRequest,status:Int,value:Any?):Map<String,Any?> = try {
        if(status!=200) invalid()
        val page=record(value,setOf("items","next_cursor"))
        val raw=page["items"] as? List<*> ?: invalid()
        if(raw.size>request.limit) invalid()
        val seen=mutableSetOf<String>(); var previous:Pair<Instant,String>?=request.query["cursor"]?.let(::cursor)
        val items=raw.map { entry ->
            val row=record(entry,if(request.activity) rowFields+setOf("target_name","target_path") else rowFields); val identifier=id(row["id"]); val actor=id(row["actor_member_id"]); val entity=id(row["entity_id"])
            if(!seen.add(identifier) || row["entity_type"] !in entityTypes || row["action"] !in actions) invalid()
            for(key in listOf("entity_type","entity_id","actor_member_id","action")) if(request.query[key]!=null && request.query[key]!=row[key]) invalid()
            val occurred=time(row["occurred_at"],true)
            if(request.query["since"]?.let { occurred<time(it) }==true || request.query["until"]?.let { occurred>=time(it) }==true) invalid()
            previous?.let { if(occurred>it.first || occurred==it.first && identifier>=it.second) invalid() }
            previous=occurred to identifier
            val correlation=row["request_id"]?.let { (it as? String)?.takeIf { text -> Regex("[A-Za-z0-9._-]{1,128}").matches(text) } ?: invalid() }
            val before=row["before_version"]?.let { integer(it,9_007_199_254_740_991L) }
            val after=row["after_version"]?.let { integer(it,9_007_199_254_740_991L) }
            val fields=row["changed_fields"] as? List<*> ?: invalid()
            if(fields.size>64 || fields.any { it !in knownFields }) invalid()
            @Suppress("UNCHECKED_CAST") val names=fields as List<String>
            if(names!=names.distinct().sorted()) invalid()
            val projected=mapOf("id" to identifier,"actor_member_id" to actor,"entity_type" to row["entity_type"],"entity_id" to entity,
                "action" to row["action"],"request_id" to correlation,"before_version" to before,"after_version" to after,
                "occurred_at" to row["occurred_at"],"changed_fields" to names.toList())
            if(request.activity) {
                if(row["entity_type"] !in businessTypes || row["action"]=="reveal") invalid()
                val name=row["target_name"]?.let { (it as? String)?.takeIf { text -> text.length in 1..500 && text.none { c -> c.code<32 || c.code==127 } } ?: invalid() }
                val path=row["target_path"]?.let { (it as? String)?.takeIf(::activityPath) ?: invalid() }
                if(name==null && path!=null) invalid()
                projected+mapOf("target_name" to name,"target_path" to path)
            } else projected
        }
        val next=page["next_cursor"]
        if(next!=null && (items.size!=request.limit || cursor(next)!=previous)) invalid()
        mapOf("items" to items,"next_cursor" to next)
    } catch(_:Exception) { throw AuthFailure(AuthCode.ACCESS_DENIED) }

    private val businessTypes=setOf("asset","financial_account","card","insurance_policy","insurance_coverage","policy_premium_link","insurance_case","medical_node","medical_expense","medical_refund","insurance_claim","insurance_payout","insurance_return","payout_allocation","appliance","consumable","appliance_consumable","stock_movement","consumable_replacement","consumable_order","obligation","fixed_settlement","asset_month","recurring_rule","cash_record","income_conversion","household_person")
    private fun activityPath(path:String):Boolean {
        val id=uuid.pattern
        return path=="/settings/people" || path=="/income" || listOf(
            "/(assets|accounts|cards|appliances|consumables|appliance-consumables|consumable-orders|income|fixed-payments)/$id",
            "/fixed-payments/rules/$id", "/insurance/(policies|cases|expenses|refunds|claims|payouts|returns)/$id",
            "/insurance/cases/$id/nodes/$id", "/consumables/$id/stock/$id",
            "/appliance-consumables/$id/replacements/$id",
            "/assets/months/[0-9]{4}-(0[1-9]|1[0-2])\\?revision=[1-9][0-9]*"
        ).any { Regex(it).matches(path) }
    }

    // Exact reviewed server metadata names, not values. Source: core/audit.py and audit/service.py.
    val entityTypes=setOf(
        "household_person",
        "appliance","appliance_consumable","asset","asset_month","card","card_secret_envelope",
        "cash_record","consumable","consumable_replacement","consumable_order","document","document_link","financial_account",
        "fixed_settlement","income_conversion","insurance_case","insurance_claim","insurance_coverage","insurance_payout",
        "insurance_policy","insurance_return","medical_expense","medical_node","medical_refund","obligation",
        "payout_allocation","policy_premium_link","recurring_rule","stock_movement","user_export","vault",
        "vault_member_wrapping","vault_membership","vault_recovery_wrapping","vault_rotation","vault_share",
        "registered_device","passkey","invitation","user",
    )
    val actions=setOf(
        "archive","complete","confirm","convert","correct","create",
        "delete","export","regenerate","reopen","reschedule","reveal",
        "settle","skip","sync_scope","unskip","update","void",
        "void_settlement","login","revoke","accept",
    )
    val knownFields=setOf(
        "ordered_on","ordered_by_member_id","received_on","received_by_member_id","cancel_reason",
        "relation",
        "aaguid","aborted_at","access_expires_at","account_id","account_number","account_number_ciphertext",
        "account_type","acknowledge_non_month_end_dates","acknowledge_scope_change","action","activated_at","active",
        "actor_id","after_version","alias","allocation_id","allocations","amount_basis",
        "amount_krw","amount_mode","anchor_date","appliance_consumable_id","appliance_id","archived_at",
        "as_of_date","asset","asset_id","asset_transfer_krw","attempts","authenticated_at",
        "backed_up","base_currency","before_version","beneficiary_note","benefit_type","binding_hash",
        "card_id","card_type","cards","case_id","cash","cash_record_id",
        "category","challenge_hash","change_reason","changed_at","changed_by_member_id","checksum_sha256",
        "ciphertext","claim_id","claim_reference","claim_state","claim_version","clear_next_check_override",
        "closed_at","closed_on","closure_ack","completed_at","confirmed_at","confirmed_by_member_id",
        "consumable_id","consumed_at","consumption_krw","contains_no_card_data","contract_end","contract_start",
        "conversion_id","copy_previous","correction_of_id","correction_reason","coverage_end","coverage_start",
        "created_at","created_by_member_id","created_device_id","credential_id","credential_record_id","csrf_hash",
        "currency_reference","current_key_version","current_revision_id","date_precision","decided_krw","decision_note",
        "deleted_at","deletion_reason","detail_type","device_id","device_type","diagnosis_code",
        "diagnosis_note","disabled_at","display_name","document_id","economic_type","effective_from",
        "effective_on","effective_until","encryption_key_version","end_date","end_on","end_reason",
        "ended_at","ended_on","entity_id","entity_type","expected_amount_krw","expected_card_count",
        "expected_member_count","expense_id","expense_ids","expenses","expires_at","financial_state",
        "flow","foreign_amount_reference","format_version","formats","frequency","generation",
        "generation_id","grant_hash","gross_medical_krw","household_id","household_share","id",
        "inclusion_status","input_amount_krw","institution_name","insured_amount_krw","insured_member_id","insurer",
        "insurer_note","intended_login","interval_count","interval_unit","is_current","issuer_name",
        "iterations","joined_key_version","kdf","key","key_check","key_hash",
        "key_version","kind","label","last_four","last_seen_at","last_used_at",
        "lines","links","loan_asset_id","location","login_name","low_stock_threshold",
        "manual_override","manually_completed","manufacturer","medical_node_id","member_id","member_wrapping",
        "mime_type","model","month_id","name","next_check_override","next_key_version",
        "node_id","nominal_date","nonce","note","number_key_version","number_nonce",
        "obligation_id","obligation_version","occurred_at","occurred_on","opened_on","operation",
        "origin","origin_revision_id","original_allocation_id","original_name","orphaned_at","owned_amount_krw",
        "owner_member_id","ownership_kind","parent_id","password_hash","patient_member_id","payload_schema_version",
        "payment_basis","payment_end","payment_start","payout_id","pending_device_id","pending_expires_at",
        "period_month","platform","policy_hash","policy_id","policy_number","policy_number_ciphertext",
        "policyholder_member_id","previous_revision_id","principal_krw","product_name","provider_name","public_coverage_krw",
        "public_key","purchase_price_krw","purchase_url","purchased_on","purged_at","purpose",
        "quantity","quantity_delta","quantity_per_replacement","reason","receipt_reference","recovery_wrapping",
        "released_at","reopened_reason","replaced_on","replacements","request_hash","request_id",
        "requested_krw","resource_id","resource_type","resource_version","response_status","retired_at",
        "reversal_of","reverses_id","revision","revision_id","revision_no","revoked_at",
        "role","rotation_required","rp_id","rule_id","rule_version_id","safe_diff",
        "salt","schedule_state","scheduled_date","scope","secret_envelope","selected_documents",
        "seller","session_hash","session_id","settlement_account_id","settlement_day","settlements",
        "sign_count","size_bytes","skipped","sku_or_model","slot","sort_order",
        "source_asset_version","source_envelope_id","source_key_version","source_member_id","source_membership_version","source_revision",
        "sources","start_date","start_on","started_on","state","status",
        "stock_movement_id","stock_quantity","stock_version","storage_key","stored_at","submitted_on",
        "target","target_id","target_member_id","timezone","title","token_hash",
        "transport","transports","treatment_state","unit","unit_cost_krw","updated_at",
        "updated_by_member_id","usage_digest","used_at","user_id","valuation_asset_id","values",
        "verification_state","version","warranty_until","window_started_at","wrapped_hvk","wrapping_id",
        "wrappings",
    )
}
