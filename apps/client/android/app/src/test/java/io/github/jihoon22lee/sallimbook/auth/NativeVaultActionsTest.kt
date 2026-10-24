package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

@Suppress("UNCHECKED_CAST")
class NativeVaultActionsTest {
    private val f=NativeVaultTestData
    private val password="synthetic-new-vault-password".toCharArray()
    private fun response(wrap:VaultRecord,check:VaultRecord)=mapOf("wrapping" to (wrap+mapOf("id" to f.resource,"household_id" to f.household,"version" to 1)),
        "key_check" to (check+mapOf("household_id" to f.household)))
    private fun bad(action:()->Unit) { try { action(); fail("Invalid synthetic workflow accepted") } catch(_:NativeVaultFailure) { } catch(_:VaultCryptoFailure) { } }
    @Test fun initializeCreatesIndependentRandomWrapsAndOfflineRecoveryCodeBeforeAnyTransport() {
        val prepared=NativeVaultActions.initialize(f.snapshot(false),password)
        try {
            val body=prepared.command.body!!; val member=body["member_wrapping"] as VaultRecord; val recovery=body["recovery_wrapping"] as VaultRecord; val check=body["key_check"] as VaultRecord
            assertEquals(VaultOperation.INITIALIZE,prepared.command.operation); assertNotNull(prepared.recoveryCode); assertNull(prepared.command.version)
            val own=NativeVaultActions.unlock(password,response(member,check),f.household,f.member,1)
            val restored=NativeVaultActions.unlockRecovery(prepared.recoveryCode!!,response(recovery,check),f.household,1)
            assertArrayEquals(prepared.material.key,own); assertArrayEquals(own,restored)
            assertEquals(3,listOf(member,recovery,check).map { it["nonce"] }.toSet().size)
            val encoded=NativeVaultJson.encode(prepared.command)!!.toString(Charsets.UTF_8)
            assertFalse(encoded.contains(String(password))); assertFalse(encoded.contains(String(prepared.recoveryCode)))
            assertSame(prepared.command.body,prepared.command.body); val key=prepared.command.idempotencyKey
            repeat(3) { NativeVaultWire.route(prepared.command); assertEquals(key,prepared.command.idempotencyKey) }
            own.fill(0); restored.fill(0)
        } finally { prepared.discard() }
        assertTrue(prepared.material.key.all { it==0.toByte() }); assertTrue(prepared.recoveryCode!!.all { it=='\u0000' })
    }
    @Test fun newPasswordPolicyCountsUnicodeCodepointsAndNeverTrimsOrNormalizes() {
        bad { NativeVaultActions.newPassword("12345678901".toCharArray()) }
        bad { NativeVaultActions.newPassword("🔐".repeat(11).toCharArray()) }
        NativeVaultActions.newPassword("🔐".repeat(12).toCharArray())
        NativeVaultActions.newPassword(" 1234567890 ".toCharArray())
        bad { NativeVaultActions.newPassword(CharArray(400) { '한' }) }
        bad { NativeVaultActions.newPassword(charArrayOf('\uD800')+"synthetic-valid".toCharArray()) }
    }
    @Test fun changePasswordKeepsHvkAndUsesWrappingVersionWithNextGeneration() {
        val material=NativeVaultMaterial(f.snapshot(),f.key())
        val prepared=NativeVaultActions.changePassword(material,password,f.wrapResponse())
        try {
            assertEquals(4L,prepared.command.version)
            val wrap=prepared.command.body!!["wrapping"] as VaultRecord
            assertEquals(3L,NativeVaultWire.version(wrap["generation"]))
            val opened=NativeVaultActions.unlock(password,response(wrap,f.checkInput()),f.household,f.member,7)
            assertArrayEquals(f.key(),opened); opened.fill(0)
        } finally { prepared.discard() }
    }
    @Test fun recoveryReplacesBothWrapsAndOldOrWrongCodesCannotOpenNewRecovery() {
        val material=NativeVaultMaterial(f.snapshot(),f.key()); val prepared=NativeVaultActions.recover(material,password,f.wrapResponse(true))
        try {
            assertEquals(3L,prepared.command.version); val body=prepared.command.body!!
            val member=body["member_wrapping"] as VaultRecord; val recovery=body["recovery_wrapping"] as VaultRecord
            assertEquals(3L,NativeVaultWire.version(member["generation"])); assertEquals(4L,NativeVaultWire.version(recovery["generation"]))
            val restored=NativeVaultActions.unlockRecovery(prepared.recoveryCode!!,response(recovery,f.checkInput()),f.household,7)
            assertArrayEquals(f.key(),restored); restored.fill(0)
            bad { NativeVaultActions.unlockRecovery(((f.fixture["recovery"] as VaultRecord)["code"] as String).toCharArray(),response(recovery,f.checkInput()),f.household,7) }
        } finally { prepared.discard() }
    }
    @Test fun shareTargetsOnlyOtherExistingMemberAndUsesTheirIndependentPassword() {
        val material=NativeVaultMaterial(f.snapshot(),f.key())
        bad { NativeVaultActions.share(material,f.member,password) }; bad { NativeVaultActions.share(material,f.cardId,password) }
        val prepared=NativeVaultActions.share(material,f.partner,password)
        try {
            val wrapping=prepared.command.body!!["wrapping"] as VaultRecord
            assertEquals(f.partner,wrapping["member_id"]); assertEquals(1L,NativeVaultWire.version(wrapping["generation"]))
            val opened=NativeVaultActions.unlock(password,response(wrapping,f.checkInput()),f.household,f.partner,7)
            assertArrayEquals(f.key(),opened); opened.fill(0)
        } finally { prepared.discard() }
    }
    @Test fun cardWriteKeepsLastFourAtomicAndRejectsMismatchingOpenedMetadata() {
        val material=NativeVaultMaterial(f.snapshot(),f.key()); val secret=VaultCardSecret("4242424242424242".toCharArray(),2032,12)
        val prepared=NativeVaultActions.writeCard(material,secret)
        try {
            assertEquals(4L,prepared.command.version); assertEquals(f.cardId,prepared.command.id); assertEquals("4242",prepared.command.body!!["last_four"])
            val envelope=prepared.command.body!!+mapOf("id" to f.resource,"household_id" to f.household,"card_id" to f.cardId,"revision" to 3,"version" to 1,"card_version" to 5)
            val opened=NativeVaultActions.openCard(material.key,envelope,f.household,7); assertArrayEquals(secret.pan,opened.pan); opened.discard()
            bad { NativeVaultActions.openCard(material.key,envelope+mapOf("last_four" to "9999"),f.household,7) }
        } finally { secret.discard(); prepared.discard() }
    }
    @Test fun rotationRequiresEveryRetainedMemberAndCanResumeFromStagedOwnWrap() {
        val material=NativeVaultMaterial(f.snapshot(),f.key()); val rotation=f.rotation()
        bad { NativeVaultActions.prepareRotation(material,rotation,mapOf(f.member to password)) }
        val prepared=NativeVaultActions.prepareRotation(material,rotation,mapOf(f.member to password,f.partner to "synthetic-partner-password".toCharArray()))
        try {
            val body=prepared.command.body!!; val wraps=body["member_wrappings"] as List<VaultRecord>; val check=body["key_check"] as VaultRecord
            val newKey=NativeVaultActions.unlock(password,response(wraps.single { it["member_id"]==f.member },check),f.household,f.member,8)
            assertArrayEquals(prepared.material.nextKey,newKey); assertFalse(newKey.contentEquals(f.key()))
            val stage=NativeVaultActions.stageCard(prepared.material,rotation,f.cardResponse())
            assertEquals(2L,stage.version); assertEquals(f.resource,stage.id); assertEquals(f.cardId,stage.childId)
            val envelope=(stage.body!!["envelope"] as VaultRecord)+mapOf("id" to f.resource,"household_id" to f.household,"card_id" to f.cardId,"revision" to 3,"version" to 1,"card_version" to 4)
            val newSecret=NativeVaultActions.openCard(newKey,envelope,f.household,8); assertEquals("4242424242424242",String(newSecret.pan)); newSecret.discard()
            bad { NativeVaultActions.openCard(newKey,f.cardResponse(),f.household,7) }; newKey.fill(0)
        } finally { prepared.discard() }
    }
    @Test fun localBindingSeparatesAppOriginIdentityKeyCardEnvelopeAndRevision() {
        val scope=f.snapshot().scope!!; val baseline=NativeVaultBinding(scope); val cvc=NativeVaultBinding(scope,f.cardId,f.resource,2)
        assertFalse(baseline.aad().contentEquals(cvc.aad())); assertNotEquals(baseline.name,cvc.name)
        val scopes=listOf(
            NativeVaultScope("io.github.other",scope.origin,scope.householdId,scope.userId,scope.memberId,scope.deviceId,7),
            NativeVaultScope(scope.appId,"https://other.invalid",scope.householdId,scope.userId,scope.memberId,scope.deviceId,7),
            NativeVaultScope(scope.appId,scope.origin,f.partner,scope.userId,scope.memberId,scope.deviceId,7),
            NativeVaultScope(scope.appId,scope.origin,scope.householdId,f.partner,scope.memberId,scope.deviceId,7),
            NativeVaultScope(scope.appId,scope.origin,scope.householdId,scope.userId,scope.memberId,f.partner,7),
            NativeVaultScope(scope.appId,scope.origin,scope.householdId,scope.userId,scope.memberId,scope.deviceId,8))
        for(other in scopes) assertFalse(baseline.aad().contentEquals(NativeVaultBinding(other).aad()))
        for(other in listOf(NativeVaultBinding(scope,f.partner,f.resource,2),NativeVaultBinding(scope,f.cardId,f.partner,2),NativeVaultBinding(scope,f.cardId,f.resource,3)))
            assertFalse(cvc.aad().contentEquals(other.aad()))
        assertEquals(cvc.name,NativeVaultBinding(scope,f.cardId,f.resource,2).name)
        bad { NativeVaultBinding(scope,f.cardId,null,2) }; bad { NativeVaultBinding(scope,null,f.resource,2) }
    }
}
