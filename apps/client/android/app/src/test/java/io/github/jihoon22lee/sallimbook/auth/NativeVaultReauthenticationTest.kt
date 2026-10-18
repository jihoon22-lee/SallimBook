package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class NativeVaultReauthenticationTest {
    private val f=NativeVaultTestData
    private fun bad(code:String?=null,action:()->Unit) {
        try { action(); fail("Unsafe reauthentication continuation accepted") }
        catch(e:NativeVaultFailure) { if(code!=null) assertEquals(code,e.code); assertNull(e.message) }
    }
    @Test fun everyMutationResumesIdenticalOpaqueBytesVersionAndIdempotencyOnlyAfterAuthentication() {
        val commands=f.commands().filter { NativeVaultWire.route(it).method!="GET" }
        assertEquals(14,commands.size)
        for(command in commands) {
            val before=f.snapshot(command.operation!=VaultOperation.INITIALIZE)
            val flow=NativeVaultReauthentication.command(before,command)
            bad("REAUTHENTICATION_REQUIRED") { flow.retry(before) }
            flow.authenticated(before)
            repeat(3) {
                val replay=flow.retry(before)
                assertEquals(command.operation,replay.operation); assertEquals(command.id,replay.id); assertEquals(command.childId,replay.childId)
                assertEquals(command.version,replay.version); assertEquals(command.idempotencyKey,replay.idempotencyKey)
                assertArrayEquals(NativeVaultJson.encode(command),NativeVaultJson.encode(replay))
            }
            flow.challenge(); bad("REAUTHENTICATION_REQUIRED") { flow.retry(before) }
            flow.authenticated(before); assertEquals(command.body,flow.retry(before).body)
            flow.discard(); bad("AUTH_CANCELLED") { flow.retry(before) }; bad("AUTH_CANCELLED") { flow.authenticated(before) }
        }
    }
    @Test fun preparedManagementWipesBothRawKeysAndConfirmedRecoveryCodeBeforeStepUp() {
        for(command in f.commands().filter { NativeVaultWire.route(it).method!="GET" }) {
            val material=NativeVaultMaterial(f.snapshot(),f.key(),f.key())
            val code=CharArray(43)
            val flow=NativeVaultReauthentication.prepared(NativeVaultPrepared(command,material,code))
            assertTrue(material.key.all { it==0.toByte() }); assertTrue(material.nextKey!!.all { it==0.toByte() }); assertTrue(code.all { it=='\u0000' })
            flow.authenticated(f.snapshot()); assertEquals(command.body,flow.retry(f.snapshot()).body); flow.discard()
        }
    }
    @Test fun unacknowledgedRecoveryCannotBeReplayedAndAllSecretsAreStillWiped() {
        for(op in listOf(VaultOperation.INITIALIZE,VaultOperation.RECOVER,VaultOperation.ROTATION_PREPARE)) {
            val command=f.commands().single { it.operation==op }; val material=NativeVaultMaterial(f.snapshot(),f.key(),f.key()); val code="synthetic-not-acknowledged".toCharArray()
            bad("ACCESS_DENIED") { NativeVaultReauthentication.prepared(NativeVaultPrepared(command,material,code)) }
            assertTrue(code.all { it=='\u0000' }); assertTrue(material.key.all { it==0.toByte() }); assertTrue(material.nextKey!!.all { it==0.toByte() })
        }
    }
    @Test fun identityChangesPermanentlyDiscardEvenAfterSuccessfulAuthentication() {
        val before=f.snapshot(); val command=f.commands().single { it.operation==VaultOperation.REVOKE }
        val changed=listOf(
            NativeVaultSnapshot(before.me+mapOf("household_id" to f.partner),before.members,before.deviceId,before.status,before.scope),
            NativeVaultSnapshot(before.me+mapOf("member_id" to f.partner),before.members,before.deviceId,before.status,before.scope),
            NativeVaultSnapshot(before.me+mapOf("user_id" to f.partner),before.members,before.deviceId,before.status,before.scope),
            NativeVaultSnapshot(before.me,before.members,f.partner,before.status,before.scope))
        for(current in changed) {
            val flow=NativeVaultReauthentication.command(before,command); flow.authenticated(before)
            bad("ACCESS_DENIED") { flow.retry(current) }; bad("AUTH_CANCELLED") { flow.authenticated(before) }
        }
    }
    @Test fun originalMutableNestedBodiesCannotChangeTheRequestDuringLogin() {
        val original=f.commands().single { it.operation==VaultOperation.ROTATION_PREPARE }
        val member=f.memberInput(version=8).toMutableMap(); val members=mutableListOf(member)
        val body=original.body!!.toMutableMap().also { it["member_wrappings"]=members }
        val command=NativeVaultCommand(original.operation,original.id,body=body,version=original.version,idempotencyKey=original.idempotencyKey)
        val expected=NativeVaultJson.encode(command); val flow=NativeVaultReauthentication.command(f.snapshot(),command)
        member["nonce"]="unsafe"; members.clear(); body.clear()
        flow.authenticated(f.snapshot()); assertArrayEquals(expected,NativeVaultJson.encode(flow.retry(f.snapshot())))
        @Suppress("UNCHECKED_CAST") val retained=flow.retry(f.snapshot()).body as MutableMap<String,Any?>
        try { retained.clear(); fail("Mutable retained request") } catch(_:UnsupportedOperationException) { }
    }
    @Test fun readCommandsAndUnvalidatedPlaintextBodiesCannotBecomeRetainedMutations() {
        for(command in f.commands().filter { NativeVaultWire.route(it).method=="GET" }) bad("INVALID_REQUEST") { NativeVaultReauthentication.command(f.snapshot(),command) }
        val command=NativeVaultCommand(VaultOperation.ROTATION_START,body=mapOf("reason" to "routine","password" to "SYNTHETIC"),version=3,idempotencyKey="synthetic")
        val material=NativeVaultMaterial(f.snapshot(),f.key())
        bad("INVALID_REQUEST") { NativeVaultReauthentication.prepared(NativeVaultPrepared(command,material)) }
        assertTrue(material.key.all { it==0.toByte() })
    }
    @Test fun protectedReadsResumeOnlyAsBlankFormsAndNeverRetainInputs() {
        val flow=NativeVaultReauthentication.form(f.snapshot())
        assertFalse(flow.hasCommand); flow.authenticated(f.snapshot()); bad("INVALID_REQUEST") { flow.retry(f.snapshot()) }
        flow.discard(); bad("AUTH_CANCELLED") { flow.challenge() }
    }
    @Test fun onlyExplicitStepUpErrorsCanTriggerTheSameScreenChallenge() {
        assertTrue(NativeVaultReauthentication.required("REAUTHENTICATION_REQUIRED")); assertTrue(NativeVaultReauthentication.required("STEP_UP_REQUIRED"))
        for(code in listOf(null,"SESSION_EXPIRED","NETWORK_UNAVAILABLE","ACCESS_DENIED","AUTH_FAILED")) assertFalse(NativeVaultReauthentication.required(code))
    }
}
