package io.github.jihoon22lee.sallimbook.auth

import java.util.UUID

internal class NativeVaultMaterial(val snapshot: NativeVaultSnapshot, val key: ByteArray, val nextKey: ByteArray? = null) {
    fun discard() { key.fill(0); nextKey?.fill(0) }
    override fun toString() = "NativeVaultMaterial(redacted)"
}
internal class NativeVaultPrepared(val command: NativeVaultCommand, val material: NativeVaultMaterial, val recoveryCode: CharArray? = null) {
    fun discard() { material.discard(); recoveryCode?.fill('\u0000') }
    override fun toString() = "NativeVaultPrepared(redacted)"
}

/** Constructs only the frozen opaque protocol. Raw inputs/keys never enter a command body. */
internal object NativeVaultActions {
    private val crypto = NativeVaultCrypto()
    private fun number(record: VaultRecord, field: String) = NativeVaultWire.version(record[field])
    fun newPassword(password: CharArray) {
        val bytes=try { NativeVaultCrypto.passwordUtf8(password) } catch(_:VaultCryptoFailure) { throw NativeVaultFailure("PASSWORD_POLICY") }
        try {
            if(Character.codePointCount(password,0,password.size)<12) throw NativeVaultFailure("PASSWORD_POLICY")
        } finally { bytes.fill(0) }
    }
    private fun base(version: Long, sealed: VaultSealed) = mapOf<String,Any?>("format_version" to 1,"key_version" to version,"nonce" to NativeVaultCrypto.encode(sealed.nonce))
    private fun checkInput(key: ByteArray, household: String, version: Long): VaultRecord {
        val sealed=crypto.sealKeyCheck(key,household,version)
        return try { base(version,sealed)+mapOf("ciphertext" to NativeVaultCrypto.encode(sealed.ciphertext)) } finally { sealed.discard() }
    }
    private fun memberInput(key: ByteArray, password: CharArray, household: String, member: String, version: Long, generation: Long): VaultRecord {
        newPassword(password); val salt=crypto.newSalt(); var kek:ByteArray?=null; var sealed:VaultSealed?=null
        try {
            kek=NativeVaultCrypto.deriveMemberKey(password,salt,NativeVaultCrypto.MIN_ITERATIONS)
            sealed=crypto.wrapMember(kek,key,household,member,version,generation,NativeVaultCrypto.MIN_ITERATIONS,salt)
            return base(version,sealed)+mapOf("member_id" to member,"generation" to generation,"kdf" to "PBKDF2-HMAC-SHA256",
                "iterations" to NativeVaultCrypto.MIN_ITERATIONS,"salt" to NativeVaultCrypto.encode(salt),"wrapped_hvk" to NativeVaultCrypto.encode(sealed.ciphertext))
        } finally { salt.fill(0); kek?.fill(0); sealed?.discard() }
    }
    private fun recoveryInput(key: ByteArray, code: ByteArray, household: String, version: Long, generation: Long): VaultRecord {
        val salt=crypto.newSalt(); var kek:ByteArray?=null; var sealed:VaultSealed?=null
        try {
            kek=NativeVaultCrypto.deriveRecoveryKey(code,salt); sealed=crypto.wrapRecovery(kek,key,household,version,generation,salt)
            return base(version,sealed)+mapOf("generation" to generation,"kdf" to "HKDF-SHA256","salt" to NativeVaultCrypto.encode(salt),"wrapped_hvk" to NativeVaultCrypto.encode(sealed.ciphertext))
        } finally { salt.fill(0); kek?.fill(0); sealed?.discard() }
    }
    private fun sealed(row: VaultRecord, field: String, size: Int) = VaultSealed(NativeVaultCrypto.decode(row["nonce"] as String,12),NativeVaultCrypto.decode(row[field] as String,size))
    @Suppress("UNCHECKED_CAST")
    fun verify(key: ByteArray, wrapping: VaultRecord, household: String, version: Long) {
        val check=wrapping["key_check"] as VaultRecord
        if(check["household_id"] != household || number(check,"key_version") != version) throw NativeVaultFailure("ACCESS_DENIED")
        val sealed=sealed(check,"ciphertext",45)
        try { NativeVaultCrypto.verifyKey(key,sealed,household,version) } finally { sealed.discard() }
    }
    @Suppress("UNCHECKED_CAST")
    fun unlock(password: CharArray, wrapping: VaultRecord, household: String, member: String, version: Long): ByteArray {
        val row=wrapping["wrapping"] as VaultRecord
        if(row["household_id"] != household || row["member_id"] != member || number(row,"key_version") != version) throw NativeVaultFailure("ACCESS_DENIED")
        val salt=NativeVaultCrypto.decode(row["salt"] as String,16); val encrypted=sealed(row,"wrapped_hvk",48); var kek:ByteArray?=null; var key:ByteArray?=null
        try {
            kek=NativeVaultCrypto.deriveMemberKey(password,salt,number(row,"iterations").toInt())
            key=NativeVaultCrypto.unwrapMember(kek,encrypted,household,member,version,number(row,"generation"),number(row,"iterations").toInt(),salt)
            verify(key,wrapping,household,version)
            return key.also { key=null }
        } finally { key?.fill(0); kek?.fill(0); salt.fill(0); encrypted.discard() }
    }
    @Suppress("UNCHECKED_CAST")
    fun unlockRecovery(code: CharArray, wrapping: VaultRecord, household: String, version: Long): ByteArray {
        val row=wrapping["wrapping"] as VaultRecord
        if(row["household_id"] != household || number(row,"key_version") != version) throw NativeVaultFailure("ACCESS_DENIED")
        val raw=NativeVaultCrypto.decode(String(code),32); val salt=NativeVaultCrypto.decode(row["salt"] as String,16)
        val encrypted=sealed(row,"wrapped_hvk",48); var kek:ByteArray?=null; var key:ByteArray?=null
        try {
            kek=NativeVaultCrypto.deriveRecoveryKey(raw,salt); key=NativeVaultCrypto.unwrapRecovery(kek,encrypted,household,version,number(row,"generation"),salt)
            verify(key,wrapping,household,version); return key.also { key=null }
        } finally { key?.fill(0); kek?.fill(0); raw.fill(0); salt.fill(0); encrypted.discard() }
    }
    fun openCard(key: ByteArray, envelope: VaultRecord, household: String, version: Long): VaultCardSecret {
        if(envelope["household_id"] != household || number(envelope,"key_version") != version) throw NativeVaultFailure("ACCESS_DENIED")
        val schema=NativeVaultWire.version(envelope["payload_schema_version"]).toInt()
        if(schema !in 1..2) throw NativeVaultFailure("INVALID_FORMAT")
        val encrypted=sealed(envelope,"ciphertext",if(schema==1) 43 else 48)
        val result=try { NativeVaultCrypto.openCard(key,encrypted,household,NativeVaultWire.id(envelope["card_id"]),version,schema) } finally { encrypted.discard() }
        if(!result.pan.takeLast(4).toCharArray().contentEquals((envelope["last_four"] as String).toCharArray())) { result.discard(); throw NativeVaultFailure("ACCESS_DENIED") }
        return result
    }
    private fun cardInput(key: ByteArray, secret: VaultCardSecret, household: String, cardId: String, version: Long): VaultRecord {
        val encrypted=crypto.sealCard(key,secret,household,cardId,version)
        return try { base(version,encrypted)+mapOf("payload_schema_version" to secret.schemaVersion,"last_four" to String(secret.pan,secret.pan.size-4,4),"ciphertext" to NativeVaultCrypto.encode(encrypted.ciphertext)) }
        finally { encrypted.discard() }
    }
    private fun command(op: VaultOperation, body: VaultRecord?, version: Long? = null, id: String? = null, childId: String? = null) =
        NativeVaultCommand(op,id,childId,body,version,UUID.randomUUID().toString()).also { NativeVaultWire.route(it) }
    fun initialize(snapshot: NativeVaultSnapshot, password: CharArray): NativeVaultPrepared {
        if(snapshot.status["initialized"] != false) throw NativeVaultFailure("VAULT_ALREADY_INITIALIZED")
        val key=crypto.newKey(); val code=crypto.newKey()
        try {
            val body=mapOf("key_check" to checkInput(key,snapshot.householdId,1),
                "member_wrapping" to memberInput(key,password,snapshot.householdId,snapshot.memberId,1,1),
                "recovery_wrapping" to recoveryInput(key,code,snapshot.householdId,1,1))
            return NativeVaultPrepared(command(VaultOperation.INITIALIZE,body),NativeVaultMaterial(snapshot,key),NativeVaultCrypto.encode(code).toCharArray())
        } catch (failure:Exception) { key.fill(0); throw failure } finally { code.fill(0) }
    }
    @Suppress("UNCHECKED_CAST")
    fun changePassword(material: NativeVaultMaterial, newPassword: CharArray, wrapping: VaultRecord): NativeVaultPrepared {
        val snapshot=material.snapshot; val previous=wrapping["wrapping"] as VaultRecord
        val body=mapOf("wrapping" to memberInput(material.key,newPassword,snapshot.householdId,snapshot.memberId,snapshot.keyVersion,number(previous,"generation")+1),"key_check_confirmed" to true)
        return NativeVaultPrepared(command(VaultOperation.REWRAP,body,number(previous,"version")),material)
    }
    @Suppress("UNCHECKED_CAST")
    fun recover(material: NativeVaultMaterial, password: CharArray, recovery: VaultRecord): NativeVaultPrepared {
        val snapshot=material.snapshot; val prior=recovery["wrapping"] as VaultRecord
        val members=snapshot.status["members"] as List<VaultRecord>; val member=members.single { it["member_id"]==snapshot.memberId }
        val code=crypto.newKey()
        try {
            val body=mapOf("member_wrapping" to memberInput(material.key,password,snapshot.householdId,snapshot.memberId,snapshot.keyVersion,number(member,"next_wrapping_generation")),
                "recovery_wrapping" to recoveryInput(material.key,code,snapshot.householdId,snapshot.keyVersion,number(prior,"generation")+1),"key_check_confirmed" to true)
            return NativeVaultPrepared(command(VaultOperation.RECOVER,body,number(snapshot.status,"version")),material,NativeVaultCrypto.encode(code).toCharArray())
        } finally { code.fill(0) }
    }
    @Suppress("UNCHECKED_CAST")
    fun share(material: NativeVaultMaterial, memberId: String, password: CharArray): NativeVaultPrepared {
        val s=material.snapshot; val member=(s.status["members"] as List<VaultRecord>).singleOrNull { it["member_id"]==memberId } ?: throw NativeVaultFailure("VAULT_MEMBER_UNAVAILABLE")
        if(memberId==s.memberId || member["status"]=="active") throw NativeVaultFailure("VAULT_SHARE_TARGET")
        val wrapping=memberInput(material.key,password,s.householdId,memberId,s.keyVersion,number(member,"next_wrapping_generation"))
        return NativeVaultPrepared(command(VaultOperation.SHARE_CREATE,mapOf("wrapping" to wrapping),number(s.status,"version")),material)
    }
    fun writeCard(material: NativeVaultMaterial, secret: VaultCardSecret): NativeVaultPrepared {
        val s=material.snapshot; val card=s.card ?: throw NativeVaultFailure("INVALID_REQUEST")
        return NativeVaultPrepared(command(VaultOperation.CARD_WRITE,cardInput(material.key,secret,s.householdId,NativeVaultWire.id(card["id"]),s.keyVersion),number(card,"version"),NativeVaultWire.id(card["id"])),material)
    }
    fun simple(op: VaultOperation, snapshot: NativeVaultSnapshot, id: String? = null, version: Long? = null, body: VaultRecord? = emptyMap()): NativeVaultCommand =
        command(op,body,version ?: number(snapshot.status,"version"),id)
    fun prepareRotation(material: NativeVaultMaterial, rotation: VaultRecord, passwords: Map<String,CharArray>): NativeVaultPrepared {
        val s=material.snapshot; val keyVersion=number(rotation,"key_version"); val key=crypto.newKey(); val code=crypto.newKey()
        try {
            @Suppress("UNCHECKED_CAST") val members=rotation["members"] as List<VaultRecord>
            if(passwords.keys!=members.map { NativeVaultWire.id(it["member_id"]) }.toSet()) throw NativeVaultFailure("VAULT_ROTATION_INCOMPLETE")
            val wraps=members.map { member -> val id=NativeVaultWire.id(member["member_id"]); memberInput(key,passwords.getValue(id),s.householdId,id,keyVersion,1) }
            val body=mapOf("key_check" to checkInput(key,s.householdId,keyVersion),"member_wrappings" to wraps,"recovery_wrapping" to recoveryInput(key,code,s.householdId,keyVersion,1))
            return NativeVaultPrepared(command(VaultOperation.ROTATION_PREPARE,body,number(rotation,"version"),NativeVaultWire.id(rotation["id"])),NativeVaultMaterial(s,material.key,key),NativeVaultCrypto.encode(code).toCharArray())
        } catch(failure:Exception) { key.fill(0); throw failure } finally { code.fill(0) }
    }
    fun stageCard(material: NativeVaultMaterial, rotation: VaultRecord, source: VaultRecord): NativeVaultCommand {
        val s=material.snapshot; val secret=openCard(material.key,source,s.householdId,s.keyVersion)
        return try {
            val envelope=cardInput(material.nextKey ?: throw NativeVaultFailure("VAULT_NOT_PREPARED"),secret,s.householdId,NativeVaultWire.id(source["card_id"]),number(rotation,"key_version"))
            command(VaultOperation.ROTATION_CARD_WRITE,mapOf("source_envelope_id" to source["id"],"source_revision" to source["revision"],"envelope" to envelope),number(rotation,"version"),NativeVaultWire.id(rotation["id"]),NativeVaultWire.id(source["card_id"]))
        } finally { secret.discard() }
    }
}
