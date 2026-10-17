package io.github.jihoon22lee.sallimbook.auth

import java.security.MessageDigest

internal data class NativeVaultRotationCard(val id: String, val source: String, val revision: Long, val lastFour: String)

/** No keys or plaintext. Progress is valid only for this unchanged source snapshot in this Activity. */
internal class NativeVaultRotationCursor(manifest: VaultRecord, key: ByteArray, nextKey: ByteArray) {
    private val identity=identity(manifest)
    private val cards=cards(manifest)
    private val members=members(manifest)
    private val verified=mutableSetOf<String>()
    private var closed=false
    private val keyFingerprint=fingerprint(key)
    private val nextFingerprint=fingerprint(nextKey)
    val verifiedCount: Int get() = verified.size
    val total: Int get() = cards.size
    private fun fingerprint(key: ByteArray): ByteArray {
        if(key.size!=32) throw NativeVaultFailure("VAULT_KEY_VERSION_CONFLICT")
        return MessageDigest.getInstance("SHA-256").digest(key)
    }
    /** Fingerprints of random keys retain continuity after raw keys are wiped for account reauth. */
    fun checkKeys(key: ByteArray, nextKey: ByteArray) {
        val current=fingerprint(key); val next=fingerprint(nextKey)
        try {
            if(closed || !MessageDigest.isEqual(keyFingerprint,current) || !MessageDigest.isEqual(nextFingerprint,next))
                throw NativeVaultFailure("VAULT_KEY_VERSION_CONFLICT")
        } finally { current.fill(0); next.fill(0) }
    }
    private fun identity(row: VaultRecord)=listOf(row["id"],row["household_id"],
        NativeVaultWire.version(row["source_key_version"]),NativeVaultWire.version(row["key_version"]))
    @Suppress("UNCHECKED_CAST")
    private fun cards(row: VaultRecord): List<NativeVaultRotationCard> {
        val result=(row["cards"] as List<VaultRecord>).map {
            NativeVaultRotationCard(NativeVaultWire.id(it["card_id"]),NativeVaultWire.id(it["source_envelope_id"]),
                NativeVaultWire.version(it["source_revision"]),it["last_four"] as String)
        }
        if(result.size>2000 || result.map { it.id }.toSet().size!=result.size) throw NativeVaultFailure("VAULT_ROTATION_SNAPSHOT_CONFLICT")
        return result
    }
    @Suppress("UNCHECKED_CAST")
    private fun members(row: VaultRecord): Map<String,Long> {
        val rows=row["members"] as List<VaultRecord>
        val result=rows.associate { NativeVaultWire.id(it["member_id"]) to NativeVaultWire.version(it["source_membership_version"]) }
        if(result.size!=rows.size) throw NativeVaultFailure("VAULT_ROTATION_SNAPSHOT_CONFLICT")
        return result
    }
    fun check(manifest: VaultRecord) {
        if(closed || manifest["state"]!="staging" || identity(manifest)!=identity ||
            cards(manifest).associateBy { it.id }!=cards.associateBy { it.id } || members(manifest)!=members)
            throw NativeVaultFailure("VAULT_ROTATION_SNAPSHOT_CONFLICT")
    }
    fun next(manifest: VaultRecord): NativeVaultRotationCard? { check(manifest); return cards.firstOrNull { it.id !in verified } }
    fun verified(card: NativeVaultRotationCard) {
        if(closed || cards.firstOrNull { it.id !in verified }!=card) throw NativeVaultFailure("VAULT_ROTATION_SNAPSHOT_CONFLICT")
        verified.add(card.id)
    }
    @Suppress("UNCHECKED_CAST")
    fun requireComplete(manifest: VaultRecord) {
        check(manifest)
        if(verified.size!=cards.size || manifest["key_check_prepared"]!=true || manifest["recovery_prepared"]!=true ||
            (manifest["cards"] as List<VaultRecord>).any { it["prepared"]!=true } ||
            (manifest["members"] as List<VaultRecord>).any { it["prepared"]!=true }) throw NativeVaultFailure("VAULT_ROTATION_INCOMPLETE")
    }
    fun discard() { closed=true; verified.clear(); keyFingerprint.fill(0); nextFingerprint.fill(0) }
}
