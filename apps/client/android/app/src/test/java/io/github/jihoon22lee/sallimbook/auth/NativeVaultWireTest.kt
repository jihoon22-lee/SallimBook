package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class NativeVaultWireTest {
    private val f=NativeVaultTestData
    private fun bad(action:()->Unit) { try { action(); fail("Unsafe synthetic vault contract accepted") } catch(e:NativeVaultFailure) { assertNull(e.message); assertNull(e.cause) } }
    private fun commands():List<NativeVaultCommand> {
        val key="synthetic:vault:1"; val id=f.resource; val empty=emptyMap<String,Any?>()
        return listOf(
            NativeVaultCommand(VaultOperation.STATUS),
            NativeVaultCommand(VaultOperation.INITIALIZE,body=mapOf("key_check" to f.checkInput(1),"member_wrapping" to (f.memberInput(version=1)+mapOf("generation" to 1)),"recovery_wrapping" to (f.recoveryInput(1)+mapOf("generation" to 1))),idempotencyKey=key),
            NativeVaultCommand(VaultOperation.OWN_WRAP),
            NativeVaultCommand(VaultOperation.REWRAP,body=mapOf("wrapping" to f.memberInput(),"key_check_confirmed" to true),version=4,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.RECOVERY_WRAP),
            NativeVaultCommand(VaultOperation.RECOVER,body=mapOf("member_wrapping" to f.memberInput(),"recovery_wrapping" to f.recoveryInput(),"key_check_confirmed" to true),version=3,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.REVOKE,id=f.partner,body=empty,version=1,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.SHARES),
            NativeVaultCommand(VaultOperation.SHARE_CREATE,body=mapOf("wrapping" to f.memberInput()),version=3,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.SHARE_WRAP,id=id),
            NativeVaultCommand(VaultOperation.SHARE_ACCEPT,id=id,body=mapOf("key_version" to 7,"key_check_confirmed" to true),version=1,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.SHARE_CANCEL,id=id,body=empty,version=1,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.CARD_GET,id=f.cardId),
            NativeVaultCommand(VaultOperation.CARD_WRITE,id=f.cardId,body=f.cardInput(),version=4,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.CARD_DELETE,id=f.cardId,version=4,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.ROTATION_START,body=mapOf("reason" to "routine"),version=3,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.ROTATION_GET,id=id),
            NativeVaultCommand(VaultOperation.ROTATION_PREPARE,id=id,body=mapOf("key_check" to f.checkInput(8),"member_wrappings" to listOf(f.memberInput(version=8),f.memberInput(f.second,8)),"recovery_wrapping" to f.recoveryInput(8)),version=2,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.ROTATION_CARD_WRITE,id=id,childId=f.cardId,body=mapOf("source_envelope_id" to id,"source_revision" to 2,"envelope" to f.cardInput(8)),version=2,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.ROTATION_CARD_GET,id=id,childId=f.cardId),
            NativeVaultCommand(VaultOperation.ROTATION_OWN_WRAP,id=id),
            NativeVaultCommand(VaultOperation.ROTATION_FINALIZE,id=id,body=mapOf("key_version" to 8,"key_check_confirmed" to true),version=3,idempotencyKey=key),
            NativeVaultCommand(VaultOperation.ROTATION_ABORT,id=id,body=empty,version=3,idempotencyKey=key))
    }
    private fun copy(c:NativeVaultCommand,body:VaultRecord?=c.body,id:String?=c.id,version:Long?=c.version,key:String?=c.idempotencyKey,cursor:String?=c.cursor,child:String?=c.childId)=
        NativeVaultCommand(c.operation,id,child,body,version,key,cursor,c.limit)
    @Test fun allTwentyThreeOperationsHaveFixedMethodPathVersionAndIdempotencyContracts() {
        val commands=commands(); assertEquals(VaultOperation.entries.toSet(),commands.map { it.operation }.toSet())
        for(c in commands) {
            val r=NativeVaultWire.route(c); assertTrue(r.path.startsWith("/api/v1/")); assertFalse(r.path.contains("https:"))
            if(r.method=="GET") { assertNull(c.body); assertNull(c.version); assertNull(c.idempotencyKey); bad { NativeVaultWire.route(copy(c,key="unexpected")) } }
            else { assertNotNull(c.idempotencyKey); bad { NativeVaultWire.route(copy(c,key=null)) }
                if(c.operation==VaultOperation.INITIALIZE) bad { NativeVaultWire.route(copy(c,version=1)) }
                else { assertNotNull(c.version); bad { NativeVaultWire.route(copy(c,version=null)) } }
            }
            bad { NativeVaultWire.route(copy(c,id="https://synthetic.invalid")) }
            bad { NativeVaultWire.route(copy(c,child="../synthetic")) }
            bad { NativeVaultWire.route(copy(c,cursor="bad")) }
            bad { NativeVaultWire.route(copy(c,body=(c.body ?: emptyMap())+mapOf("cvc" to "SYNTHETIC"))) }
        }
    }
    @Test fun allSuccessResponsesAreStrictAndNeverPermitArbitraryExtraFields() {
        for(c in commands()) {
            val value=when(c.operation) {
                VaultOperation.STATUS -> f.snapshot().status
                VaultOperation.SHARES -> mapOf("items" to listOf(f.share()),"next_cursor" to null)
                VaultOperation.OWN_WRAP, VaultOperation.ROTATION_OWN_WRAP -> f.wrapResponse()
                VaultOperation.RECOVERY_WRAP -> f.wrapResponse(recovery=true)
                VaultOperation.SHARE_WRAP -> f.wrapResponse()+mapOf("offer" to f.share())
                VaultOperation.CARD_GET, VaultOperation.ROTATION_CARD_GET -> f.cardResponse()
                VaultOperation.ROTATION_GET -> f.rotation()
                else -> mapOf("id" to f.resource,"version" to 1)
            }
            val status=NativeVaultWire.route(c).success
            assertEquals(value,NativeVaultWire.response(c,status,value))
            bad { NativeVaultWire.response(c,status,value+mapOf("password" to "SYNTHETIC")) }
            bad { NativeVaultWire.response(c,204,value) }
        }
    }
    @Test fun unsafeOpaqueFormatsKdfParametersAndInconsistentBundlesAreRejected() {
        for(change in listOf(mapOf("iterations" to 599999),mapOf("iterations" to 2000001),mapOf("iterations" to 600000.0),mapOf("kdf" to "unknown"),
            mapOf("nonce" to "A".repeat(17)),mapOf("salt" to "A".repeat(21)+"B"),mapOf("wrapped_hvk" to "A".repeat(63)),mapOf("format_version" to 2),mapOf("key_version" to 0)))
            bad { NativeVaultWire.memberWrap(f.memberInput()+change,false) }
        val original=commands().single { it.operation==VaultOperation.ROTATION_PREPARE }
        bad { NativeVaultWire.route(copy(original,body=original.body!!+mapOf("member_wrappings" to listOf(f.memberInput(version=7))))) }
        bad { NativeVaultWire.route(copy(original,body=original.body!!+mapOf("member_wrappings" to listOf(f.memberInput(version=8),f.memberInput(version=8))))) }
        bad { NativeVaultWire.route(copy(original,body=original.body!!+mapOf("recovery_wrapping" to (f.recoveryInput(8)+mapOf("nonce" to f.checkInput(8)["nonce"]))))) }
    }
    @Test fun falseConfirmationAndWrongBodyPresenceCannotAuthorizeMutations() {
        for(op in listOf(VaultOperation.SHARE_ACCEPT,VaultOperation.ROTATION_FINALIZE)) {
            val original=commands().single { it.operation==op }
            for(flag in listOf(false,1,"true",null)) bad { NativeVaultWire.route(copy(original,body=original.body!!+mapOf("key_check_confirmed" to flag))) }
        }
        val delete=commands().single { it.operation==VaultOperation.CARD_DELETE }
        bad { NativeVaultWire.route(copy(delete,body=emptyMap())) }
        val abort=commands().single { it.operation==VaultOperation.ROTATION_ABORT }
        bad { NativeVaultWire.route(copy(abort,body=null)) }
    }
    @Test fun responseCrossScopeAndDifferentRequestedIdsAreRejected() {
        val command=NativeVaultCommand(VaultOperation.CARD_GET,id=f.cardId)
        bad { NativeVaultWire.response(command,200,f.cardResponse()+mapOf("card_id" to f.member)) }
        val wrap=f.wrapResponse(); @Suppress("UNCHECKED_CAST") val check=wrap["key_check"] as VaultRecord
        bad { NativeVaultWire.wrapping(wrap+mapOf("key_check" to (check+mapOf("household_id" to f.member)))) }
        bad { NativeVaultWire.wrapping(wrap+mapOf("offer" to (f.share()+mapOf("target_member_id" to f.partner))),offer=true) }
        bad { NativeVaultWire.rotation(f.rotation()+mapOf("key_version" to 7)) }
    }
    @Test fun safeMetadataAndScreenEntriesCannotSelectOpaqueOperationsOrSecrets() {
        for(op in VaultOperation.entries.filter { it !in setOf(VaultOperation.STATUS,VaultOperation.SHARES,VaultOperation.ROTATION_GET) })
            bad { NativeVaultUiPolicy.metadata(op,emptyMap<String,Any?>()) }
        assertEquals(50,NativeVaultUiPolicy.metadata(VaultOperation.SHARES,emptyMap<String,Any?>()).limit)
        bad { NativeVaultUiPolicy.metadata(VaultOperation.SHARES,mapOf("query" to mapOf("limit" to 201))) }
        bad { NativeVaultUiPolicy.metadata(VaultOperation.SHARES,mapOf("query" to mapOf("limit" to null))) }
        bad { NativeVaultUiPolicy.metadata(VaultOperation.STATUS,mapOf("key_version" to 7)) }
        for(action in NativeVaultUiPolicy.actions) {
            val field=NativeVaultUiPolicy.idField(action)
            val args=mapOf("action" to action)+(field?.let { mapOf(it to f.resource) } ?: emptyMap())
            assertEquals(action,NativeVaultUiPolicy.arguments(args).first)
            for(extra in listOf("password","recoveryCode","pan","cvc","wrapped_hvk","ciphertext","headers","url","ifMatch","biometricSuccess"))
                bad { NativeVaultUiPolicy.arguments(args+mapOf(extra to null)) }
        }
        bad { NativeVaultUiPolicy.arguments(mapOf("action" to "decrypt","cardId" to f.cardId)) }
    }
    @Test fun statusPaginationRotationAndErrorShapesAreBounded() {
        bad { NativeVaultWire.status(f.snapshot(false).status+mapOf("current_key_version" to 1)) }
        bad { NativeVaultWire.status(f.snapshot().status+mapOf("initialized" to 1)) }
        bad { NativeVaultWire.shares(mapOf("items" to listOf(f.share(),f.share()),"next_cursor" to null)) }
        bad { NativeVaultWire.shares(mapOf("items" to listOf(f.share()),"next_cursor" to f.member)) }
        val page=mapOf("items" to listOf(f.share(),f.share()+mapOf("id" to f.member)),"next_cursor" to null)
        bad { NativeVaultWire.response(NativeVaultCommand(VaultOperation.SHARES,limit=1),200,page) }
        for(code in listOf("VAULT_NONCE_REUSED","VAULT_SALT_REUSED","VAULT_GENERATION_CONFLICT")) {
            val body=mapOf("error" to mapOf("code" to code,"message" to "SYNTHETIC PRIVATE"))
            assertEquals(code,NativeVaultErrors.code(409,body)); assertEquals("ACCESS_DENIED",NativeVaultErrors.code(500,body))
            assertFalse(NativeVaultErrors.message(code).contains("SYNTHETIC PRIVATE"))
        }
    }
}
