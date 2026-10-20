package io.github.jihoon22lee.sallimbook.auth

/** Read-only identities and opaque envelopes stay in native ownership, never AuthOutcome. */
internal class NativeVaultSnapshot(val me: VaultRecord, val members: List<VaultRecord>, val deviceId: String,
    val status: VaultRecord, val scope: NativeVaultScope?, val card: VaultRecord? = null) {
    val householdId: String get() = me["household_id"] as String
    val memberId: String get() = me["member_id"] as String
    val keyVersion: Long get() = NativeVaultWire.version(status["current_key_version"])
    fun requireEnrolled(): NativeVaultScope = scope ?: throw NativeVaultFailure("VAULT_ACCESS_DENIED")
    override fun toString() = "NativeVaultSnapshot(redacted)"
}

/** Created inside NativeAuthSession's serialized executor. Tokens stay in native request scope. */
internal class NativeVaultConnection(
    private val appId: String, private val origin: String, token: (Long) -> String,
    private val account: NativeAuthHttp, private val vault: NativeVaultHttp, private val gate: ForegroundRequest,
    private val local: NativeVaultLocalState,
) {
    private val access = NativeVaultAccess(gate,token)
    fun check() = gate.check()
    fun call(command: NativeVaultCommand): VaultRecord {
        check()
        val response = access.send { vault.send(command,it,gate) }
        if(response.status !in 200..299) {
            val code=NativeVaultErrors.code(response.status,response.body)
            // A per-target 403 (e.g. another member's share offer) says nothing about this device's
            // registration; only a fresh status that shows the membership ended justifies wiping it.
            if(code in setOf("SESSION_EXPIRED","VAULT_NOT_INITIALIZED") ||
                code == "VAULT_ACCESS_DENIED" && command.operation != VaultOperation.STATUS && membershipEnded()) local.clearAll()
            throw NativeVaultFailure(code)
        }
        return NativeVaultWire.response(command,response.status,response.body).also { check() }
    }
    /** An unreachable recheck keeps local data; a 401 during it has already wiped in the nested call. */
    private fun membershipEnded(): Boolean {
        val status=try { call(NativeVaultCommand(VaultOperation.STATUS)) } catch(_: AuthFailure) { return false }
        return status["initialized"] != true || status["own_membership"] != "active"
    }
    @Suppress("UNCHECKED_CAST")
    private fun identity(path: String): Any? {
        val response=access.send { account.send("GET",path,gate,accessToken=it) }
        if(response.status != 200) throw NativeVaultFailure(NativeVaultErrors.code(response.status,response.body))
        return AuthPolicy.metadataBody("GET",path,response.status,response.body)
    }
    @Suppress("UNCHECKED_CAST")
    fun metadata(operation: FinanceOperation, arguments: VaultRecord): Any? {
        if(operation !in setOf(FinanceOperation.GET_CARD,FinanceOperation.LIST_CARDS)) throw NativeVaultFailure("INVALID_REQUEST")
        val request=FinancePolicy.prepare(operation,arguments)
        val response=access.send { account.send(request.method,request.path,gate,accessToken=it) }
        if(response.status != 200) throw NativeVaultFailure(NativeVaultErrors.code(response.status,response.body))
        return FinancePolicy.response(operation,request,response.status,response.body)
    }
    @Suppress("UNCHECKED_CAST")
    fun snapshot(cardId: String? = null): NativeVaultSnapshot {
        val me=identity("/api/v1/me") as VaultRecord
        val household=NativeVaultWire.id(me["household_id"]); val member=NativeVaultWire.id(me["member_id"])
        val members=identity("/api/v1/household/members") as List<VaultRecord>
        if(members.any { it["household_id"] != household } || members.map { it["member_id"] }.distinct().size != members.size ||
            members.singleOrNull { it["member_id"] == member }?.get("user_id") != me["user_id"]) throw NativeVaultFailure("ACCESS_DENIED")
        var cursor: String?=null; var current: String?=null; val seen=mutableSetOf<String>()
        do {
            val page=identity("/api/v1/devices?limit=200"+(cursor?.let { "&cursor=$it" } ?: "")) as VaultRecord
            val devices=page["items"] as List<VaultRecord>
            for(device in devices) {
                val id=NativeVaultWire.id(device["id"])
                if(!seen.add(id) || seen.size>2000) throw NativeVaultFailure("ACCESS_DENIED")
                if(device["current"] == true) {
                    if(current != null || device["status"] != "active" || device["platform"] != "android") throw NativeVaultFailure("ACCESS_DENIED")
                    current=id
                }
            }
            val next=page["next_cursor"] as String?
            if(next != null && (next != devices.lastOrNull()?.get("id") || next == cursor)) throw NativeVaultFailure("ACCESS_DENIED")
            cursor=next
        } while(cursor != null)
        val device=current ?: throw NativeVaultFailure("SESSION_EXPIRED")
        val status=call(NativeVaultCommand(VaultOperation.STATUS))
        if(status["household_id"] != household) throw NativeVaultFailure("ACCESS_DENIED")
        val vaultMembers=status["members"] as List<VaultRecord>
        if(status["initialized"] == true && (vaultMembers.map { it["member_id"] }.toSet() != members.map { it["member_id"] }.toSet() ||
            vaultMembers.singleOrNull { it["member_id"] == member }?.get("status") != status["own_membership"])) throw NativeVaultFailure("ACCESS_DENIED")
        val scope=if(status["initialized"] == true && status["own_membership"] == "active")
            NativeVaultScope(appId,origin,household,NativeVaultWire.id(me["user_id"]),member,device,NativeVaultWire.version(status["current_key_version"])) else null
        if(scope == null) local.clearAll() else local.reconcile(scope)
        val card=cardId?.let { metadata(FinanceOperation.GET_CARD,mapOf("cardId" to NativeVaultWire.id(it))) as VaultRecord }
        if(card != null && card["household_id"] != household) throw NativeVaultFailure("ACCESS_DENIED")
        if(scope != null && card?.get("has_secret") == false) local.clearCard(scope,cardId!!)
        return NativeVaultSnapshot(me,members,device,status,scope,card).also { check() }
    }
    fun ownWrapping(snapshot: NativeVaultSnapshot, rotation: VaultRecord? = null): VaultRecord {
        snapshot.requireEnrolled()
        val result=call(if(rotation == null) NativeVaultCommand(VaultOperation.OWN_WRAP) else NativeVaultCommand(VaultOperation.ROTATION_OWN_WRAP,id=NativeVaultWire.id(rotation["id"])))
        val wrap=result["wrapping"] as Map<*,*>
        if(wrap["household_id"] != snapshot.householdId || wrap["member_id"] != snapshot.memberId ||
            NativeVaultWire.version(wrap["key_version"]) != (rotation?.let { NativeVaultWire.version(it["key_version"]) } ?: snapshot.keyVersion)) throw NativeVaultFailure("ACCESS_DENIED")
        return result
    }
    fun cardEnvelope(snapshot: NativeVaultSnapshot, cardId: String, rotation: VaultRecord? = null): VaultRecord {
        val scope=snapshot.requireEnrolled()
        val result=call(if(rotation == null) NativeVaultCommand(VaultOperation.CARD_GET,id=cardId) else NativeVaultCommand(VaultOperation.ROTATION_CARD_GET,id=NativeVaultWire.id(rotation["id"]),childId=cardId))
        if(result["household_id"] != snapshot.householdId || NativeVaultWire.version(result["key_version"]) !=
            (rotation?.let { NativeVaultWire.version(it["key_version"]) } ?: snapshot.keyVersion)) throw NativeVaultFailure("ACCESS_DENIED")
        if(rotation == null) local.reconcileCard(NativeVaultBinding(scope,cardId,NativeVaultWire.id(result["id"]),NativeVaultWire.version(result["revision"])))
        return result
    }
    fun rotation(snapshot: NativeVaultSnapshot, rotationId: String): VaultRecord {
        snapshot.requireEnrolled()
        return call(NativeVaultCommand(VaultOperation.ROTATION_GET,id=rotationId)).also {
            if(it["household_id"] != snapshot.householdId || it["state"] == "staging" && NativeVaultWire.version(it["source_key_version"]) != snapshot.keyVersion) throw NativeVaultFailure("ACCESS_DENIED")
            if(it["state"] == "staging") {
                @Suppress("UNCHECKED_CAST") val expected=(snapshot.status["members"] as List<VaultRecord>).filter { member -> member["status"]=="active" }.associateBy { member -> member["member_id"] }
                @Suppress("UNCHECKED_CAST") val actual=it["members"] as List<VaultRecord>
                if(snapshot.status["pending_rotation_id"]!=rotationId || actual.map { member -> member["member_id"] }.toSet()!=expected.keys ||
                    actual.any { member -> NativeVaultWire.version(member["source_membership_version"])!=NativeVaultWire.version(expected.getValue(member["member_id"])["version"]) }) throw NativeVaultFailure("ACCESS_DENIED")
            }
        }
    }
    @Suppress("UNCHECKED_CAST")
    fun cardList(snapshot: NativeVaultSnapshot): List<VaultRecord> {
        val result=mutableListOf<VaultRecord>(); var cursor:String?=null
        do {
            val page=metadata(FinanceOperation.LIST_CARDS,mapOf("query" to mapOf("status" to "all","limit" to 200,"cursor" to cursor))) as VaultRecord
            val items=page["items"] as List<VaultRecord>
            if(items.any { it["household_id"] != snapshot.householdId } || result.size+items.size>2000) throw NativeVaultFailure("ACCESS_DENIED")
            result.addAll(items); cursor=page["next_cursor"] as String?
            if(result.map { it["id"] }.distinct().size != result.size) throw NativeVaultFailure("ACCESS_DENIED")
        } while(cursor!=null)
        return result
    }
}
