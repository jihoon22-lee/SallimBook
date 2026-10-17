package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

@Suppress("UNCHECKED_CAST")
class NativeVaultRotationCursorTest {
    private val originalKey=ByteArray(32) { 1 }
    private val stagedKey=ByteArray(32) { 2 }
    private fun makeCursor(row:VaultRecord)=NativeVaultRotationCursor(row,originalKey,stagedKey)
    private fun id(n:Int)="00000000-0000-4000-8000-${n.toString().padStart(12,'0')}"
    private fun manifest(count:Int):VaultRecord=NativeVaultTestData.rotation().let { base -> base+mapOf(
        "key_check_prepared" to true,"recovery_prepared" to true,
        "members" to (base["members"] as List<VaultRecord>).map { it+mapOf("prepared" to true) },
        "cards" to (0 until count).map { mapOf("card_id" to id(it+100),"source_envelope_id" to id(it+10_000),
            "source_revision" to 2,"last_four" to "4242","prepared" to (it%2==0)) }) }
    private fun bad(action:()->Unit) { try { action(); fail("Stale or incomplete rotation accepted") } catch (_:NativeVaultFailure) { } }
    @Test fun delayedMixedPreparedCardsAdvanceAcrossWorkLeasesAndReachFinalize() {
        var row=manifest(120); val cursor=makeCursor(row); var now=0L
        val lifetime=NativeVaultLifetime { now }.apply { presentation(true,true,true,true) }
        var steps=0; var checkedPrepared=0; var staged=0
        while(true) {
            val work=lifetime.beginWork()!!
            // Fresh identity/current key/manifest/staging key checks are repeated for every bounded step.
            repeat(7) { now+=1_000; assertTrue(lifetime.workActive(work)) }
            val card=cursor.next(row)
            if(card==null) { cursor.requireComplete(row); assertTrue(lifetime.finishWork(work,false)); break }
            val cards=row["cards"] as List<VaultRecord>
            if(cards.single { it["card_id"]==card.id }["prepared"]==true) checkedPrepared++ else staged++
            repeat(2) { now+=1_000; assertTrue(lifetime.workActive(work)) }
            cursor.verified(card)
            row=row+mapOf("version" to (steps+3),"cards" to cards.map { if(it["card_id"]==card.id) it+mapOf("prepared" to true) else it })
            assertTrue(lifetime.finishWork(work,false)); steps++
        }
        assertEquals(120,steps); assertEquals(60,checkedPrepared); assertEquals(60,staged)
        assertEquals(120,cursor.verifiedCount); assertTrue(now>NativeVaultLifetime.REQUEST_MILLIS)
    }
    @Test fun restartRechecksPreparedPrefixButCanAdvanceUnderNewLeases() {
        val row=manifest(4); val old=makeCursor(row)
        val first=old.next(row)!!; old.verified(first); old.discard()
        bad { old.next(row) }
        val fresh=makeCursor(row); assertEquals(first,fresh.next(row))
        repeat(4) { fresh.verified(fresh.next(row)!!) }; assertNull(fresh.next(row))
    }
    @Test fun finalizationRequiresEveryLocalVerificationAndEveryServerPreparedFlag() {
        var row=manifest(2); val cursor=makeCursor(row)
        bad { cursor.requireComplete(row) }
        repeat(2) { cursor.verified(cursor.next(row)!!) }
        bad { cursor.requireComplete(row) }
        row=row+mapOf("cards" to (row["cards"] as List<VaultRecord>).map { it+mapOf("prepared" to true) })
        cursor.requireComplete(row)
        bad { cursor.requireComplete(row+mapOf("recovery_prepared" to false)) }
        bad { cursor.requireComplete(row+mapOf("members" to (row["members"] as List<VaultRecord>).map { it+mapOf("prepared" to false) })) }
    }
    @Test fun sourceCardMutationRemovalOrAdditionInvalidatesAccumulatedVerification() {
        val row=manifest(2); val cursor=makeCursor(row); cursor.verified(cursor.next(row)!!)
        val cards=row["cards"] as List<VaultRecord>
        for(field in listOf("source_envelope_id","source_revision","last_four")) {
            val changed=cards[0]+mapOf(field to when(field) { "source_revision" -> 3; "last_four" -> "9999"; else -> id(999) })
            bad { cursor.next(row+mapOf("cards" to listOf(changed,cards[1]))) }
        }
        bad { cursor.next(row+mapOf("cards" to cards.drop(1))) }
        bad { cursor.next(manifest(3)) }
    }
    @Test fun rotationIdentityMemberVersionAndStateCannotChangeBetweenWorkLeases() {
        val row=manifest(1); val cursor=makeCursor(row)
        for(field in listOf("id","household_id","source_key_version","key_version","state")) {
            val value=when(field) { "state" -> "aborted"; "source_key_version","key_version" -> 99; else -> id(999) }
            bad { cursor.next(row+mapOf(field to value)) }
        }
        bad { cursor.next(row+mapOf("members" to (row["members"] as List<VaultRecord>).map { it+mapOf("source_membership_version" to 99) })) }
    }
    @Test fun onlyNextCardCanBeVerifiedAndRepeatedCardIdsAreRejected() {
        val row=manifest(2); val cursor=makeCursor(row); val first=cursor.next(row)!!
        bad { cursor.verified(first.copy(id=id(999))) }; cursor.verified(first); bad { cursor.verified(first) }
        val cards=row["cards"] as List<VaultRecord>
        bad { makeCursor(row+mapOf("cards" to listOf(cards[0],cards[0]))) }
        bad { makeCursor(manifest(2001)) }
    }
    @Test fun emptyRotationCanFinalizeOnlyAfterFreshPreparedKeyAndMemberChecks() {
        val row=manifest(0); val cursor=makeCursor(row)
        assertNull(cursor.next(row)); cursor.requireComplete(row)
        bad { cursor.requireComplete(row+mapOf("key_check_prepared" to false)) }
    }
    @Test fun fiveMinuteManagementExpiryCanReauthenticateWithoutRecheckingCompletedPrefix() {
        var row=manifest(120); val cursor=makeCursor(row); var now=0L; var authenticatedAt=0L
        var old=originalKey.clone(); var fresh=stagedKey.clone(); var reauthentications=0; var reads=0
        val lifetime=NativeVaultLifetime { now }.apply { presentation(true,true,true,true) }
        fun reauthenticateIfRequired() {
            if(now-authenticatedAt<300_000) return
            val verified=cursor.verifiedCount
            old.fill(0); fresh.fill(0); assertTrue(old.all { it==0.toByte() }); assertTrue(fresh.all { it==0.toByte() })
            now+=15_000 // Separate account reauth and native vault-password entry.
            authenticatedAt=now; reauthentications++
            old=originalKey.clone(); fresh=stagedKey.clone()
            cursor.check(row); cursor.checkKeys(old,fresh); assertEquals(verified,cursor.verifiedCount)
        }
        while(true) {
            val work=lifetime.beginWork()!!; repeat(7) { now+=1_000; assertTrue(lifetime.workActive(work)) }
            cursor.checkKeys(old,fresh); val card=cursor.next(row)
            if(card==null) {
                assertTrue(lifetime.finishWork(work,false)); reauthenticateIfRequired()
                cursor.requireComplete(row); break
            }
            val cards=row["cards"] as List<VaultRecord>; val prepared=cards.single { it["card_id"]==card.id }["prepared"]==true
            now+=2_000; assertTrue(lifetime.finishWork(work,false))
            if(!prepared) reauthenticateIfRequired()
            cursor.checkKeys(old,fresh); cursor.verified(card); reads++
            row=row+mapOf("cards" to cards.map { if(it["card_id"]==card.id) it+mapOf("prepared" to true) else it })
        }
        assertTrue(now>300_000); assertTrue(reauthentications>=3); assertEquals(120,reads); assertEquals(120,cursor.verifiedCount)
        old.fill(0); fresh.fill(0); cursor.discard()
    }
    @Test fun reauthenticationCannotReuseProgressWithDifferentRecoveredKeysOrClosedCursor() {
        val row=manifest(2); val cursor=makeCursor(row); cursor.verified(cursor.next(row)!!)
        cursor.checkKeys(originalKey.clone(),stagedKey.clone())
        bad { cursor.checkKeys(ByteArray(32) { 3 },stagedKey) }
        bad { cursor.checkKeys(originalKey,ByteArray(32) { 3 }) }
        bad { cursor.checkKeys(ByteArray(31),stagedKey) }
        cursor.discard(); bad { cursor.checkKeys(originalKey,stagedKey) }; bad { cursor.next(row) }
    }
}
