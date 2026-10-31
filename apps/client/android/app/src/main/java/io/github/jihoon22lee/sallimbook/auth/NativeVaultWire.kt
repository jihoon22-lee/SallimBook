package io.github.jihoon22lee.sallimbook.auth

import java.time.OffsetDateTime

internal typealias VaultRecord = Map<String, Any?>
internal class NativeVaultFailure(val code: String) : Exception()
internal class NativeVaultOutcome<T>(val value: T? = null, val code: String? = null) {
    override fun toString() = "NativeVaultOutcome(redacted)"
}
internal enum class VaultOperation {
    STATUS, INITIALIZE, OWN_WRAP, REWRAP, RECOVERY_WRAP, RECOVER, REVOKE, SHARES, SHARE_CREATE,
    SHARE_WRAP, SHARE_ACCEPT, SHARE_CANCEL, CARD_GET, CARD_WRITE, CARD_DELETE, ROTATION_START,
    ROTATION_GET, ROTATION_PREPARE, ROTATION_CARD_WRITE, ROTATION_CARD_GET, ROTATION_OWN_WRAP,
    ROTATION_FINALIZE, ROTATION_ABORT,
}
internal class NativeVaultCommand(
    val operation: VaultOperation, val id: String? = null, val childId: String? = null,
    val body: VaultRecord? = null, val version: Long? = null, val idempotencyKey: String? = null,
    val cursor: String? = null, val limit: Int = 200,
) { override fun toString() = "NativeVaultCommand($operation)" }
internal class NativeVaultRoute(val method: String, val path: String, val success: Int)

/** Exact native-only projection of the generated vault contract. Opaque records never cross the bridge. */
internal object NativeVaultWire {
    private val uuid = Regex("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
    private val envelopeFields = setOf("format_version", "key_version", "nonce")
    private val memberFields = envelopeFields + setOf("member_id", "generation", "kdf", "iterations", "salt", "wrapped_hvk")
    private val recoveryFields = envelopeFields + setOf("generation", "kdf", "salt", "wrapped_hvk")
    private val cardFields = envelopeFields + setOf("payload_schema_version", "last_four", "ciphertext")
    private val checkFields = envelopeFields + "ciphertext"
    private val wrappingResource = setOf("id", "household_id", "version")
    private fun invalid(): Nothing = throw NativeVaultFailure("INVALID_REQUEST")
    @Suppress("UNCHECKED_CAST")
    fun record(value: Any?, fields: Set<String>): VaultRecord {
        val map = value as? Map<*, *> ?: invalid()
        if (map.keys != fields) invalid()
        return map as VaultRecord
    }
    fun id(value: Any?): String = (value as? String)?.takeIf(uuid::matches) ?: invalid()
    fun version(value: Any?): Long = when (value) { is Int -> value.toLong(); is Long -> value; else -> invalid() }
        .takeIf { it in 1..NativeVaultCrypto.MAX_VERSION } ?: invalid()
    fun bool(value: Any?): Boolean = value as? Boolean ?: invalid()
    private fun opaque(value: Any?, size: Int) {
        val bytes = try { NativeVaultCrypto.decode(value as? String ?: invalid(), size) } catch (_: VaultCryptoFailure) { invalid() }
        bytes.fill(0)
    }
    private fun timestamp(value: Any?) {
        try { OffsetDateTime.parse(value as? String ?: invalid()) } catch (_: Exception) { invalid() }
    }
    private fun one(value: Any?) { if (version(value) != 1L) invalid() }
    private fun base(row: VaultRecord) { one(row["format_version"]); version(row["key_version"]); opaque(row["nonce"], 12) }
    fun memberWrap(value: Any?, response: Boolean): VaultRecord {
        val row = record(value, memberFields + if (response) wrappingResource else emptySet())
        base(row); id(row["member_id"]); version(row["generation"])
        if (row["kdf"] != "PBKDF2-HMAC-SHA256" || version(row["iterations"]) !in 600_000..2_000_000) invalid()
        opaque(row["salt"], 16); opaque(row["wrapped_hvk"], 48)
        if (response) { id(row["id"]); id(row["household_id"]); version(row["version"]) }
        return row
    }
    fun recoveryWrap(value: Any?, response: Boolean): VaultRecord {
        val row = record(value, recoveryFields + if (response) wrappingResource else emptySet())
        base(row); version(row["generation"]); if (row["kdf"] != "HKDF-SHA256") invalid()
        opaque(row["salt"], 16); opaque(row["wrapped_hvk"], 48)
        if (response) { id(row["id"]); id(row["household_id"]); version(row["version"]) }
        return row
    }
    fun keyCheck(value: Any?, response: Boolean): VaultRecord {
        val row = record(value, checkFields + if (response) setOf("household_id") else emptySet())
        base(row); opaque(row["ciphertext"], 45); if (response) id(row["household_id"])
        return row
    }
    fun card(value: Any?, response: Boolean): VaultRecord {
        val row = record(value, cardFields + if (response) wrappingResource + setOf("card_id", "revision", "card_version") else emptySet())
        base(row); val schema=version(row["payload_schema_version"]); if(schema !in 1L..2L) invalid(); opaque(row["ciphertext"], if(schema==1L) 43 else 48)
        if ((row["last_four"] as? String)?.matches(Regex("[0-9]{4}")) != true) invalid()
        if (response) { id(row["id"]); id(row["household_id"]); id(row["card_id"])
            version(row["version"]); version(row["revision"]); version(row["card_version"]) }
        return row
    }
    fun rows(value: Any?, maximum: Int): List<*> = (value as? List<*>)?.takeIf { it.size <= maximum } ?: invalid()
    fun status(value: Any?): VaultRecord {
        val row = record(value, setOf("household_id", "initialized", "id", "version", "current_key_version", "own_membership", "rotation_required", "pending_rotation_id", "members"))
        id(row["household_id"]); bool(row["rotation_required"])
        if (row["own_membership"] !in setOf("not_enrolled", "active", "revoked")) invalid()
        val members = rows(row["members"], 2).map {
            val item = record(it, setOf("member_id", "status", "version", "next_wrapping_generation"))
            id(item["member_id"]); version(item["next_wrapping_generation"])
            if (item["status"] !in setOf("not_enrolled", "active", "revoked") || (item["status"] == "not_enrolled") != (item["version"] == null)) invalid()
            item["version"]?.let(::version); item
        }
        if (members.map { it["member_id"] }.distinct().size != members.size) invalid()
        if (bool(row["initialized"])) { id(row["id"]); version(row["version"]); version(row["current_key_version"]); row["pending_rotation_id"]?.let(::id) }
        else if (listOf("id", "version", "current_key_version", "pending_rotation_id").any { row[it] != null } ||
            row["own_membership"] != "not_enrolled" || row["rotation_required"] != false || members.isNotEmpty()) invalid()
        return row
    }
    fun share(value: Any?): VaultRecord {
        val row = record(value, setOf("id", "household_id", "source_member_id", "target_member_id", "key_version", "state", "expires_at", "closed_at", "version"))
        listOf("id", "household_id", "source_member_id", "target_member_id").forEach { id(row[it]) }
        if (row["source_member_id"] == row["target_member_id"] || row["state"] !in setOf("pending", "accepted", "cancelled", "expired")) invalid()
        version(row["key_version"]); version(row["version"]); timestamp(row["expires_at"]); row["closed_at"]?.let(::timestamp)
        if ((row["state"] == "pending") != (row["closed_at"] == null)) invalid()
        return row
    }
    fun shares(value: Any?): VaultRecord {
        val row = record(value, setOf("items", "next_cursor")); val items = rows(row["items"], 200).map(::share)
        if (items.map { it["id"] }.distinct().size != items.size || items.map { it["household_id"] }.distinct().size > 1) invalid()
        row["next_cursor"]?.let { if (id(it) != items.lastOrNull()?.get("id")) invalid() }
        return row
    }
    fun rotation(value: Any?): VaultRecord {
        val row = record(value, setOf("id", "household_id", "key_version", "source_key_version", "state", "version", "key_check_prepared", "recovery_prepared", "cards", "members"))
        id(row["id"]); id(row["household_id"]); version(row["version"])
        if (version(row["source_key_version"]) >= version(row["key_version"]) || row["state"] !in setOf("staging", "current", "retired", "aborted")) invalid()
        bool(row["key_check_prepared"]); bool(row["recovery_prepared"])
        val cards = rows(row["cards"], 2000).map {
            val item = record(it, setOf("card_id", "source_envelope_id", "source_revision", "last_four", "prepared"))
            id(item["card_id"]); id(item["source_envelope_id"]); version(item["source_revision"]); bool(item["prepared"])
            if ((item["last_four"] as? String)?.matches(Regex("[0-9]{4}")) != true) invalid(); item
        }
        val members = rows(row["members"], 2).map {
            val item = record(it, setOf("member_id", "source_membership_version", "prepared"))
            id(item["member_id"]); version(item["source_membership_version"]); bool(item["prepared"]); item
        }
        if (members.isEmpty() || members.map { it["member_id"] }.distinct().size != members.size || cards.map { it["card_id"] }.distinct().size != cards.size) invalid()
        return row
    }
    fun wrapping(value: Any?, recovery: Boolean = false, offer: Boolean = false): VaultRecord {
        val row = record(value, setOf("wrapping", "key_check") + if (offer) setOf("offer") else emptySet())
        val wrap = if (recovery) recoveryWrap(row["wrapping"], true) else memberWrap(row["wrapping"], true)
        val check = keyCheck(row["key_check"], true)
        if (wrap["household_id"] != check["household_id"] || version(wrap["key_version"]) != version(check["key_version"])) invalid()
        if (offer) {
            val item = share(row["offer"])
            if (item["household_id"] != wrap["household_id"] || item["target_member_id"] != wrap["member_id"] ||
                version(item["key_version"]) != version(wrap["key_version"]) || item["state"] != "pending") invalid()
        }
        return row
    }
    private fun bundle(check: VaultRecord, members: List<VaultRecord>, recovery: VaultRecord) {
        val all = listOf(check, recovery) + members
        if (all.any { version(it["key_version"]) != version(check["key_version"]) } || all.map { it["nonce"] }.distinct().size != all.size ||
            members.map { it["member_id"] }.distinct().size != members.size || members.map { it["salt"] }.distinct().size != members.size) invalid()
    }
    private fun confirmed(row: VaultRecord) { if (row["key_check_confirmed"] != true) invalid(); version(row["key_version"]) }
    fun route(command: NativeVaultCommand): NativeVaultRoute {
        val op = command.operation
        if(command.limit !in 1..200 || op != VaultOperation.SHARES && command.limit != 200) invalid()
        val idOperations = setOf(VaultOperation.REVOKE, VaultOperation.SHARE_WRAP, VaultOperation.SHARE_ACCEPT, VaultOperation.SHARE_CANCEL,
            VaultOperation.CARD_GET, VaultOperation.CARD_WRITE, VaultOperation.CARD_DELETE, VaultOperation.ROTATION_GET, VaultOperation.ROTATION_PREPARE,
            VaultOperation.ROTATION_CARD_WRITE, VaultOperation.ROTATION_CARD_GET, VaultOperation.ROTATION_OWN_WRAP, VaultOperation.ROTATION_FINALIZE, VaultOperation.ROTATION_ABORT)
        if ((op in idOperations) != (command.id != null)) invalid()
        command.id?.let(::id)
        if ((op in setOf(VaultOperation.ROTATION_CARD_GET, VaultOperation.ROTATION_CARD_WRITE)) != (command.childId != null)) invalid()
        command.childId?.let(::id)
        if (command.cursor != null) { if (op != VaultOperation.SHARES) invalid(); id(command.cursor) }
        val route = when (op) {
            VaultOperation.STATUS -> NativeVaultRoute("GET", "/api/v1/vault/status", 200)
            VaultOperation.INITIALIZE -> NativeVaultRoute("POST", "/api/v1/vault/initialize", 201)
            VaultOperation.OWN_WRAP -> NativeVaultRoute("GET", "/api/v1/vault/wrappings/me", 200)
            VaultOperation.REWRAP -> NativeVaultRoute("PUT", "/api/v1/vault/wrappings/me", 200)
            VaultOperation.RECOVERY_WRAP -> NativeVaultRoute("GET", "/api/v1/vault/recovery-wrap", 200)
            VaultOperation.RECOVER -> NativeVaultRoute("POST", "/api/v1/vault/recover", 200)
            VaultOperation.REVOKE -> NativeVaultRoute("POST", "/api/v1/vault/members/${command.id}/revoke", 200)
            VaultOperation.SHARES -> NativeVaultRoute("GET", "/api/v1/vault/shares?limit=${command.limit}" + (command.cursor?.let { "&cursor=$it" } ?: ""), 200)
            VaultOperation.SHARE_CREATE -> NativeVaultRoute("POST", "/api/v1/vault/shares", 201)
            VaultOperation.SHARE_WRAP -> NativeVaultRoute("GET", "/api/v1/vault/shares/${command.id}/wrapping", 200)
            VaultOperation.SHARE_ACCEPT -> NativeVaultRoute("POST", "/api/v1/vault/shares/${command.id}/accept", 200)
            VaultOperation.SHARE_CANCEL -> NativeVaultRoute("POST", "/api/v1/vault/shares/${command.id}/cancel", 200)
            VaultOperation.CARD_GET -> NativeVaultRoute("GET", "/api/v1/cards/${command.id}/secret-envelope", 200)
            VaultOperation.CARD_WRITE -> NativeVaultRoute("PUT", "/api/v1/cards/${command.id}/secret-envelope", 200)
            VaultOperation.CARD_DELETE -> NativeVaultRoute("DELETE", "/api/v1/cards/${command.id}/secret-envelope", 200)
            VaultOperation.ROTATION_START -> NativeVaultRoute("POST", "/api/v1/vault/rotations", 201)
            VaultOperation.ROTATION_GET -> NativeVaultRoute("GET", "/api/v1/vault/rotations/${command.id}", 200)
            VaultOperation.ROTATION_PREPARE -> NativeVaultRoute("POST", "/api/v1/vault/rotations/${command.id}/prepare", 200)
            VaultOperation.ROTATION_CARD_WRITE -> NativeVaultRoute("PUT", "/api/v1/vault/rotations/${command.id}/cards/${command.childId}", 200)
            VaultOperation.ROTATION_CARD_GET -> NativeVaultRoute("GET", "/api/v1/vault/rotations/${command.id}/cards/${command.childId}", 200)
            VaultOperation.ROTATION_OWN_WRAP -> NativeVaultRoute("GET", "/api/v1/vault/rotations/${command.id}/wrappings/me", 200)
            VaultOperation.ROTATION_FINALIZE -> NativeVaultRoute("POST", "/api/v1/vault/rotations/${command.id}/finalize", 200)
            VaultOperation.ROTATION_ABORT -> NativeVaultRoute("POST", "/api/v1/vault/rotations/${command.id}/abort", 200)
        }
        val mutation = route.method != "GET"
        if (mutation != (command.idempotencyKey != null) || mutation && command.idempotencyKey?.matches(Regex("[A-Za-z0-9._:-]{1,128}")) != true) invalid()
        if ((mutation && op != VaultOperation.INITIALIZE) != (command.version != null)) invalid()
        command.version?.let(::version)
        if ((mutation && op != VaultOperation.CARD_DELETE) != (command.body != null)) invalid()
        command.body?.let { body -> when (op) {
            VaultOperation.INITIALIZE -> {
                val row = record(body, setOf("key_check", "member_wrapping", "recovery_wrapping"))
                val check = keyCheck(row["key_check"], false); val member = memberWrap(row["member_wrapping"], false); val recovery = recoveryWrap(row["recovery_wrapping"], false)
                bundle(check, listOf(member), recovery)
                if (version(check["key_version"]) != 1L || version(member["generation"]) != 1L || version(recovery["generation"]) != 1L) invalid()
            }
            VaultOperation.REWRAP -> { val row=record(body,setOf("wrapping","key_check_confirmed")); memberWrap(row["wrapping"],false); if(row["key_check_confirmed"] != true) invalid() }
            VaultOperation.RECOVER -> {
                val row=record(body,setOf("member_wrapping","recovery_wrapping","key_check_confirmed")); val a=memberWrap(row["member_wrapping"],false); val b=recoveryWrap(row["recovery_wrapping"],false)
                if(row["key_check_confirmed"] != true || version(a["key_version"]) != version(b["key_version"]) || a["nonce"] == b["nonce"]) invalid()
            }
            VaultOperation.SHARE_CREATE -> memberWrap(record(body,setOf("wrapping"))["wrapping"],false)
            VaultOperation.SHARE_ACCEPT, VaultOperation.ROTATION_FINALIZE -> confirmed(record(body,setOf("key_version","key_check_confirmed")))
            VaultOperation.REVOKE, VaultOperation.SHARE_CANCEL, VaultOperation.ROTATION_ABORT -> record(body,emptySet())
            VaultOperation.CARD_WRITE -> card(body,false)
            VaultOperation.ROTATION_START -> if(record(body,setOf("reason"))["reason"] !in setOf("routine","key_compromised","member_access_removed")) invalid()
            VaultOperation.ROTATION_PREPARE -> {
                val row=record(body,setOf("key_check","member_wrappings","recovery_wrapping")); val check=keyCheck(row["key_check"],false)
                val members=rows(row["member_wrappings"],2).map { memberWrap(it,false) }; if(members.isEmpty() || version(check["key_version"]) == 1L) invalid()
                bundle(check,members,recoveryWrap(row["recovery_wrapping"],false))
            }
            VaultOperation.ROTATION_CARD_WRITE -> { val row=record(body,setOf("source_envelope_id","source_revision","envelope")); id(row["source_envelope_id"]); version(row["source_revision"]); card(row["envelope"],false) }
            else -> invalid()
        } }
        return route
    }
    fun response(command: NativeVaultCommand, responseStatus: Int, value: Any?): VaultRecord {
        try {
            if(responseStatus != route(command).success) invalid()
            return when(command.operation) {
                VaultOperation.STATUS -> status(value)
                VaultOperation.SHARES -> shares(value).also { if((it["items"] as List<*>).size > command.limit) invalid() }
                VaultOperation.ROTATION_GET -> rotation(value).also { if(it["id"] != command.id) invalid() }
                VaultOperation.OWN_WRAP, VaultOperation.ROTATION_OWN_WRAP -> wrapping(value)
                VaultOperation.RECOVERY_WRAP -> wrapping(value,recovery=true)
                VaultOperation.SHARE_WRAP -> wrapping(value,offer=true).also { if((it["offer"] as Map<*,*>)["id"] != command.id) invalid() }
                VaultOperation.CARD_GET, VaultOperation.ROTATION_CARD_GET -> card(value,true).also { if(it["card_id"] != (command.childId ?: command.id)) invalid() }
                else -> record(value,setOf("id","version")).also { id(it["id"]); version(it["version"]) }
            }
        } catch (_: NativeVaultFailure) { throw NativeVaultFailure("ACCESS_DENIED") }
    }
}
