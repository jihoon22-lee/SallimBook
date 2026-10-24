package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class NativeVaultWireTest {
    private val f=NativeVaultTestData
    private fun bad(action:()->Unit) { try { action(); fail("Unsafe synthetic vault contract accepted") } catch(e:NativeVaultFailure) { assertNull(e.message); assertNull(e.cause) } }
    private fun copy(c:NativeVaultCommand,body:VaultRecord?=c.body,id:String?=c.id,version:Long?=c.version,key:String?=c.idempotencyKey,cursor:String?=c.cursor,child:String?=c.childId)=
        NativeVaultCommand(c.operation,id,child,body,version,key,cursor,c.limit)
    @Test fun allTwentyThreeOperationsHaveFixedMethodPathVersionAndIdempotencyContracts() {
        val commands=f.commands(); assertEquals(VaultOperation.entries.toSet(),commands.map { it.operation }.toSet())
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
        for(c in f.commands()) {
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
        val original=f.commands().single { it.operation==VaultOperation.ROTATION_PREPARE }
        bad { NativeVaultWire.route(copy(original,body=original.body!!+mapOf("member_wrappings" to listOf(f.memberInput(version=7))))) }
        bad { NativeVaultWire.route(copy(original,body=original.body!!+mapOf("member_wrappings" to listOf(f.memberInput(version=8),f.memberInput(version=8))))) }
        bad { NativeVaultWire.route(copy(original,body=original.body!!+mapOf("recovery_wrapping" to (f.recoveryInput(8)+mapOf("nonce" to f.checkInput(8)["nonce"]))))) }
    }
    @Test fun falseConfirmationAndWrongBodyPresenceCannotAuthorizeMutations() {
        for(op in listOf(VaultOperation.SHARE_ACCEPT,VaultOperation.ROTATION_FINALIZE)) {
            val original=f.commands().single { it.operation==op }
            for(flag in listOf(false,1,"true",null)) bad { NativeVaultWire.route(copy(original,body=original.body!!+mapOf("key_check_confirmed" to flag))) }
        }
        val delete=f.commands().single { it.operation==VaultOperation.CARD_DELETE }
        bad { NativeVaultWire.route(copy(delete,body=emptyMap())) }
        val abort=f.commands().single { it.operation==VaultOperation.ROTATION_ABORT }
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
    @Test fun sharePagesAcceptBusinessOrderWithoutUuidOrderAndKeepCursorShape() {
        val ids=listOf("00000000-0000-4000-8000-000000000002", "00000000-0000-4000-8000-000000000009", "00000000-0000-4000-8000-000000000001")
        val command=NativeVaultCommand(VaultOperation.SHARES,limit=2)
        val first=mapOf("items" to ids.take(2).map { f.share()+mapOf("id" to it) }, "next_cursor" to ids[1])
        assertEquals(first,NativeVaultWire.response(command,200,first))
        val next=NativeVaultCommand(VaultOperation.SHARES,cursor=ids[1],limit=2)
        assertTrue(NativeVaultWire.route(next).path.endsWith("&cursor=${ids[1]}"))
        val last=mapOf("items" to listOf(f.share()+mapOf("id" to ids[2])), "next_cursor" to null)
        assertEquals(last,NativeVaultWire.response(next,200,last))
        bad { NativeVaultWire.response(command,200,first+mapOf("next_cursor" to ids[0])) }
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
