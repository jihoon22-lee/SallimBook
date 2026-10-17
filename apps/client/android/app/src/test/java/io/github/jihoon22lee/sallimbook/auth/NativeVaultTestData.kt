package io.github.jihoon22lee.sallimbook.auth

import java.io.File

@Suppress("UNCHECKED_CAST")
internal object NativeVaultTestData {
    val fixture=NativeVaultJson.decode(File("../../../../packages/test-fixtures/vault-v1.json").readText()) as VaultRecord
    val household=fixture["household_id"] as String
    val cardId=(fixture["card"] as VaultRecord)["card_id"] as String
    val first=(fixture["members"] as List<VaultRecord>)[0]
    val second=(fixture["members"] as List<VaultRecord>)[1]
    val member=first["member_id"] as String
    val partner=second["member_id"] as String
    val device="00000000-0000-4000-8000-000000000005"
    val resource="00000000-0000-4000-8000-000000000006"
    val user="00000000-0000-4000-8000-000000000007"
    fun memberInput(row:VaultRecord=first,version:Long=7)=row.filterKeys { it in setOf("member_id","generation","iterations","salt","nonce","wrapped_hvk") }+
        mapOf("format_version" to 1,"key_version" to version,"kdf" to "PBKDF2-HMAC-SHA256")
    fun recoveryInput(version:Long=7)=(fixture["recovery"] as VaultRecord).filterKeys { it in setOf("generation","salt","nonce","wrapped_hvk") }+
        mapOf("format_version" to 1,"key_version" to version,"kdf" to "HKDF-SHA256")
    fun checkInput(version:Long=7)=(fixture["key_check"] as VaultRecord).filterKeys { it in setOf("nonce","ciphertext") }+mapOf("format_version" to 1,"key_version" to version)
    fun cardInput(version:Long=7)=(fixture["card"] as VaultRecord).filterKeys { it in setOf("nonce","ciphertext") }+
        mapOf("format_version" to 1,"key_version" to version,"payload_schema_version" to 1,"last_four" to "4242")
    fun wrapResponse(recovery:Boolean=false,version:Long=7):VaultRecord=mapOf("wrapping" to
        ((if(recovery) recoveryInput(version) else memberInput(version=version))+mapOf("id" to resource,"household_id" to household,"version" to 4)),
        "key_check" to (checkInput(version)+mapOf("household_id" to household)))
    fun cardResponse(version:Long=7)=cardInput(version)+mapOf("id" to resource,"household_id" to household,"card_id" to cardId,"revision" to 2,"version" to 3,"card_version" to 4)
    fun share()=mapOf("id" to resource,"household_id" to household,"source_member_id" to partner,"target_member_id" to member,
        "key_version" to 7,"state" to "pending","expires_at" to "2026-10-18T00:15:00Z","closed_at" to null,"version" to 1)
    fun rotation()=mapOf("id" to resource,"household_id" to household,"key_version" to 8,"source_key_version" to 7,"state" to "staging","version" to 2,
        "key_check_prepared" to false,"recovery_prepared" to false,
        "cards" to listOf(mapOf("card_id" to cardId,"source_envelope_id" to resource,"source_revision" to 2,"last_four" to "4242","prepared" to false)),
        "members" to listOf(mapOf("member_id" to member,"source_membership_version" to 1,"prepared" to false),mapOf("member_id" to partner,"source_membership_version" to 1,"prepared" to false)))
    fun snapshot(initialized:Boolean=true):NativeVaultSnapshot {
        val me=mapOf("user_id" to user,"member_id" to member,"household_id" to household,"display_name" to "합성 구성원 1","role" to "owner")
        val members=listOf(me,me+mapOf("user_id" to partner,"member_id" to partner,"display_name" to "합성 구성원 2","role" to "member"))
        val status=mapOf("household_id" to household,"initialized" to initialized,"id" to if(initialized) resource else null,
            "version" to if(initialized) 3 else null,"current_key_version" to if(initialized) 7 else null,"own_membership" to if(initialized) "active" else "not_enrolled",
            "rotation_required" to false,"pending_rotation_id" to null,"members" to if(initialized) listOf(
                mapOf("member_id" to member,"status" to "active","version" to 1,"next_wrapping_generation" to 3),
                mapOf("member_id" to partner,"status" to "not_enrolled","version" to null,"next_wrapping_generation" to 1)) else emptyList())
        return NativeVaultSnapshot(me,members,device,status,if(initialized) NativeVaultScope("io.github.synthetic","https://synthetic.invalid",household,user,member,device,7) else null,
            mapOf("id" to cardId,"household_id" to household,"version" to 4,"has_secret" to true))
    }
    fun key()=(fixture["hvk_hex"] as String).chunked(2).map { it.toInt(16).toByte() }.toByteArray()
    fun commands():List<NativeVaultCommand> {
        val key="synthetic:vault:1"; val id=resource; val empty=emptyMap<String,Any?>()
        return listOf(
            NativeVaultCommand(VaultOperation.STATUS),
            NativeVaultCommand(VaultOperation.INITIALIZE,body=mapOf("key_check" to checkInput(1),"member_wrapping" to (memberInput(version=1)+mapOf("generation" to 1)),"recovery_wrapping" to (recoveryInput(1)+mapOf("generation" to 1))),idempotencyKey=key),
            NativeVaultCommand(VaultOperation.OWN_WRAP),
            NativeVaultCommand(VaultOperation.REWRAP,body=mapOf("wrapping" to memberInput(),"key_check_confirmed" to true),version=4,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.RECOVERY_WRAP),
            NativeVaultCommand(VaultOperation.RECOVER,body=mapOf("member_wrapping" to memberInput(),"recovery_wrapping" to recoveryInput(),"key_check_confirmed" to true),version=3,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.REVOKE,id=partner,body=empty,version=1,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.SHARES),
            NativeVaultCommand(VaultOperation.SHARE_CREATE,body=mapOf("wrapping" to memberInput()),version=3,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.SHARE_WRAP,id=id),
            NativeVaultCommand(VaultOperation.SHARE_ACCEPT,id=id,body=mapOf("key_version" to 7,"key_check_confirmed" to true),version=1,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.SHARE_CANCEL,id=id,body=empty,version=1,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.CARD_GET,id=cardId),
            NativeVaultCommand(VaultOperation.CARD_WRITE,id=cardId,body=cardInput(),version=4,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.CARD_DELETE,id=cardId,version=4,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.ROTATION_START,body=mapOf("reason" to "routine"),version=3,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.ROTATION_GET,id=id),
            NativeVaultCommand(VaultOperation.ROTATION_PREPARE,id=id,body=mapOf("key_check" to checkInput(8),"member_wrappings" to listOf(memberInput(version=8),memberInput(second,8)),"recovery_wrapping" to recoveryInput(8)),version=2,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.ROTATION_CARD_WRITE,id=id,childId=cardId,body=mapOf("source_envelope_id" to id,"source_revision" to 2,"envelope" to cardInput(8)),version=2,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.ROTATION_CARD_GET,id=id,childId=cardId),
            NativeVaultCommand(VaultOperation.ROTATION_OWN_WRAP,id=id),
            NativeVaultCommand(VaultOperation.ROTATION_FINALIZE,id=id,body=mapOf("key_version" to 8,"key_check_confirmed" to true),version=3,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.ROTATION_ABORT,id=id,body=empty,version=3,idempotencyKey=key))
    }
}
