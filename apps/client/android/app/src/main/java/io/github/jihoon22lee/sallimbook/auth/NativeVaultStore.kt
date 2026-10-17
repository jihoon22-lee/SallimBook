package io.github.jihoon22lee.sallimbook.auth

import android.content.Context
import android.content.pm.ApplicationInfo
import android.os.Build
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import java.io.File
import java.nio.ByteBuffer
import java.security.KeyStore
import java.security.MessageDigest
import java.util.concurrent.atomic.AtomicBoolean
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** Server-verified identities only. Never constructed from bridge-provided identity fields. */
internal class NativeVaultScope(val appId: String, val origin: String, val householdId: String, val userId: String,
    val memberId: String, val deviceId: String, val keyVersion: Long) {
    init {
        if (AuthPolicy.apiOrigin(origin) == null || !Regex("[a-zA-Z0-9_.]{1,180}").matches(appId)) throw NativeVaultFailure("INVALID_REQUEST")
        listOf(householdId, userId, memberId, deviceId).forEach(NativeVaultWire::id); NativeVaultWire.version(keyVersion)
    }
    fun bytes(): ByteArray {
        val strings = listOf(appId, origin, householdId, userId, memberId, deviceId).map { it.toByteArray(Charsets.UTF_8) }
        return ByteBuffer.allocate(8 + strings.sumOf { it.size + 4 }).apply {
            strings.forEach { putInt(it.size); put(it) }; putLong(keyVersion)
        }.array()
    }
    override fun toString() = "NativeVaultScope(redacted)"
}
internal class NativeVaultBinding(val scope: NativeVaultScope, val cardId: String? = null, val envelopeId: String? = null, val revision: Long? = null) {
    val localCode = cardId != null
    init {
        if (localCode) { NativeVaultWire.id(cardId); NativeVaultWire.id(envelopeId); NativeVaultWire.version(revision) }
        else if (envelopeId != null || revision != null) throw NativeVaultFailure("INVALID_REQUEST")
    }
    private fun digest(bytes: ByteArray) = MessageDigest.getInstance("SHA-256").digest(bytes).joinToString("") { "%02x".format(it) }
    val scopeName: String get() = digest(scope.bytes())
    val cardName: String get() = cardId?.let { digest(it.toByteArray(Charsets.US_ASCII)) } ?: "key"
    fun aad(): ByteArray = (if(localCode) "SallimBook/local-cvc/v1\u0000" else "SallimBook/device-vault/v1\u0000").toByteArray(Charsets.US_ASCII) +
        scope.bytes() + if(localCode) (cardId + "\u0000" + envelopeId + "\u0000" + revision).toByteArray(Charsets.US_ASCII) else byteArrayOf()
    val name: String get() = "$scopeName.${if(localCode) "cvc" else "hvk"}.$cardName.${digest(aad())}"
    override fun toString() = "NativeVaultBinding(redacted)"
}
internal class NativeVaultKeyOperation(val cipher: Cipher, val binding: NativeVaultBinding, val encrypt: Boolean, val sealed: VaultSealed?) {
    val consumed = AtomicBoolean(false)
    fun discard() { consumed.set(true); sealed?.discard() }
    override fun toString() = "NativeVaultKeyOperation(redacted)"
}

/** Encrypted native-only local storage. No HTTP, bridge, backup, export or plaintext serialization. */
internal class NativeVaultStore private constructor(context: Context) {
    companion object {
        @Volatile private var instance: NativeVaultStore? = null
        fun get(context: Context): NativeVaultStore = instance ?: synchronized(this) {
            instance ?: NativeVaultStore(context.applicationContext).also { instance = it }
        }
        // Release activation requires the separately recorded security + Galaxy acceptance gate.
        // Neither a JS flag, Intent extra, server setting nor SharedPreferences can enable this.
        const val LOCAL_CVC_ACCEPTANCE_VERIFIED = false
    }
    private val app = context.applicationContext
    private val directory = File(app.noBackupFilesDir, "sallimbook-vault-v1")
    private val prefix = app.packageName + ".vault.v1."
    private val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
    init { if ((app.applicationInfo.flags and ApplicationInfo.FLAG_ALLOW_BACKUP) != 0) throw NativeVaultFailure("ACCESS_DENIED") }
    private fun file(binding: NativeVaultBinding): AtomicFile {
        if (!directory.exists() && !directory.mkdirs()) throw NativeVaultFailure("KEY_INVALIDATED")
        if (directory.canonicalFile != directory.absoluteFile) throw NativeVaultFailure("KEY_INVALIDATED")
        return AtomicFile(File(directory, binding.name + ".bin"))
    }
    @Synchronized fun exists(binding: NativeVaultBinding): Boolean = file(binding).let {
        it.baseFile.exists() || File(it.baseFile.path + ".bak").exists() || File(it.baseFile.path + ".new").exists()
    }
    @Synchronized fun reconcile(scope: NativeVaultScope) {
        val keep = NativeVaultBinding(scope).scopeName + "."
        removeMatching { !it.startsWith(keep) }
    }
    @Synchronized fun reconcileCard(binding: NativeVaultBinding) {
        if (!binding.localCode) throw NativeVaultFailure("INVALID_REQUEST")
        val cardPrefix = "${binding.scopeName}.cvc.${binding.cardName}."
        removeMatching { it.startsWith(cardPrefix) && it != binding.name }
    }
    @Synchronized fun clearCard(scope: NativeVaultScope, cardId: String) {
        NativeVaultWire.id(cardId)
        val probe = NativeVaultBinding(scope, cardId, cardId, 1)
        val cardPrefix = "${probe.scopeName}.cvc.${probe.cardName}."
        removeMatching { it.startsWith(cardPrefix) }
    }
    @Synchronized fun clearAll() = removeMatching { true }
    private fun removeMatching(predicate: (String) -> Boolean) {
        val names = mutableSetOf<String>()
        store.aliases().toList().filter { it.startsWith(prefix) }.forEach { names.add(it.removePrefix(prefix)) }
        directory.listFiles()?.forEach { file ->
            val name = file.name.removeSuffix(".bak").removeSuffix(".new").removeSuffix(".bin")
            names.add(name)
        }
        for (name in names.filter(predicate)) {
            val alias = prefix + name
            val keyGone = try { store.deleteEntry(alias); !store.containsAlias(alias) } catch (_: Exception) { false }
            val target = AtomicFile(File(directory, "$name.bin"))
            val fileGone = try { target.delete(); !target.baseFile.exists() && !File(target.baseFile.path + ".bak").exists() && !File(target.baseFile.path + ".new").exists() }
                catch (_: Exception) { false }
            if (!keyGone && !fileGone) throw NativeVaultFailure("KEY_INVALIDATED")
        }
    }
    @Synchronized fun prepareEncryption(binding: NativeVaultBinding, replaceConfirmed: Boolean): NativeVaultKeyOperation {
        if (binding.localCode && !LOCAL_CVC_ACCEPTANCE_VERIFIED) throw NativeVaultFailure("CVC_GATE_CLOSED")
        val alias = prefix + binding.name
        if (store.containsAlias(alias) && !replaceConfirmed) throw NativeVaultFailure("KEY_INVALIDATED")
        if (store.containsAlias(alias)) removeMatching { it == binding.name }
        val specification = KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setKeySize(256).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setRandomizedEncryptionRequired(true).setUserAuthenticationRequired(true)
            .setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG).setInvalidatedByBiometricEnrollment(true)
            // Official API notes identify unlocked-device bugs through Android 14. Strong auth-per-use remains required on every supported API.
            .apply { if (Build.VERSION.SDK_INT >= 35) setUnlockedDeviceRequired(true) }.build()
        try {
            val key = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply { init(specification) }.generateKey()
            val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.ENCRYPT_MODE, key) }
            return NativeVaultKeyOperation(cipher, binding, true, null)
        } catch (_: Exception) { throw NativeVaultFailure("KEY_INVALIDATED") }
    }
    @Synchronized fun prepareDecryption(binding: NativeVaultBinding): NativeVaultKeyOperation {
        if (binding.localCode && !LOCAL_CVC_ACCEPTANCE_VERIFIED) throw NativeVaultFailure("CVC_GATE_CLOSED")
        var bytes: ByteArray? = null
        var sealed: VaultSealed? = null
        try {
            val key = store.getKey(prefix + binding.name, null) as? SecretKey ?: throw NativeVaultFailure("KEY_INVALIDATED")
            bytes = file(binding).openRead().use { stream ->
                val data = ByteArray(65)
                try { var size = 0; while(size < data.size) { val n=stream.read(data,size,data.size-size); if(n<0) break; size+=n }
                    if (size !in if(binding.localCode) 32..33 else 61..61) throw NativeVaultFailure("KEY_INVALIDATED")
                    data.copyOf(size)
                } finally { data.fill(0) }
            }
            if (bytes[0] != 1.toByte()) throw NativeVaultFailure("KEY_INVALIDATED")
            sealed = VaultSealed(bytes.copyOfRange(1,13),bytes.copyOfRange(13,bytes.size))
            val cipher = Cipher.getInstance("AES/GCM/NoPadding").apply { init(Cipher.DECRYPT_MODE,key,GCMParameterSpec(128,sealed.nonce)) }
            return NativeVaultKeyOperation(cipher,binding,false,sealed)
        } catch (_: Exception) { sealed?.discard(); throw NativeVaultFailure("KEY_INVALIDATED") }
        finally { bytes?.fill(0) }
    }
    /** Called only while the request gate is active, after matching the prompt's actual returned Cipher. */
    @Synchronized fun finish(operation: NativeVaultKeyOperation, returned: Cipher, plaintext: ByteArray? = null): ByteArray? {
        if (returned !== operation.cipher || !operation.consumed.compareAndSet(false,true)) throw NativeVaultFailure("ACCESS_DENIED")
        val expected = if(operation.binding.localCode) 3..4 else 32..32
        if (operation.encrypt != (plaintext != null) || plaintext != null && (plaintext.size !in expected || operation.binding.localCode && plaintext.any { it.toInt() !in 48..57 }))
            throw NativeVaultFailure("INVALID_REQUEST")
        var result: ByteArray? = null
        try {
            returned.updateAAD(operation.binding.aad())
            result = returned.doFinal(plaintext ?: operation.sealed?.ciphertext ?: throw NativeVaultFailure("KEY_INVALIDATED"))
            if (!operation.encrypt) {
                if (result.size !in expected || operation.binding.localCode && result.any { it.toInt() !in 48..57 }) throw NativeVaultFailure("KEY_INVALIDATED")
                return result.also { result = null }
            }
            val nonce = returned.iv
            if (nonce.size != 12 || result.size !in (expected.first+16)..(expected.last+16)) throw NativeVaultFailure("KEY_INVALIDATED")
            val record = byteArrayOf(1) + nonce + result
            try {
                val target = file(operation.binding); val output = target.startWrite()
                try { output.write(record); target.finishWrite(output) }
                catch (_: Exception) { target.failWrite(output); throw NativeVaultFailure("KEY_INVALIDATED") }
            } finally { record.fill(0) }
            return null
        } catch (failure: NativeVaultFailure) { throw failure }
        catch (_: Exception) { throw NativeVaultFailure("KEY_INVALIDATED") }
        finally { result?.fill(0); operation.sealed?.discard() }
    }
}
