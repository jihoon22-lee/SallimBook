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
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/** The device row this install signs in on again, proven by the key the server issued for it. */
internal class InstallClaim(val deviceId: String, val key: String) {
    override fun toString() = "InstallClaim(redacted)"
}

internal interface InstallClaimStore {
    /** Null when nothing is stored; throws [AuthFailure] AUTH_UNAVAILABLE on a transient failure. */
    fun read(): InstallClaim?
    fun save(claim: InstallClaim)
    fun clear()
}

/**
 * One device row per install. A sign-in presents the stored claim, or an empty one to ask for a
 * key. The claim outlives sign-out and session ends; only the server decides whether it still
 * proves the row (same user and household, row not revoked) and otherwise issues a new one.
 */
internal object NativeInstallDevice {
    private val uuid = Regex("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
    private val key = Regex("[A-Za-z0-9_-]{32,128}")

    /** The request field, or null to send none after a transient read failure (the claim stays). */
    fun claim(store: InstallClaimStore): Map<String, String>? {
        val stored = try { store.read() } catch (_: AuthFailure) { return null }
        return stored?.let { mapOf("device_id" to it.deviceId, "key" to it.key) } ?: emptyMap()
    }

    /** A new row's key replaces the stored claim; a reused row keeps it. */
    fun accept(store: InstallClaimStore, sent: Map<String, String>?, body: Any?) {
        if (sent == null) return
        val install = (body as? Map<*, *>)?.get("install") as? Map<*, *> ?: return
        val id = install["device_id"] as? String ?: return
        if (!uuid.matches(id)) return
        val issued = install["key"] as? String
        when {
            issued != null -> if (key.matches(issued)) store.save(InstallClaim(id, issued))
            sent["device_id"] == id -> Unit
            // A different row without a key cannot be claimed later.
            else -> store.clear()
        }
    }
}

/** Keystore-encrypted like the refresh token, but in its own file and key, so ending a session leaves it. */
internal class InstallDeviceStore(context: Context, origin: String) : InstallClaimStore {
    private val app = context.applicationContext
    private val alias = app.packageName + ".auth.install-device.v1"
    private val file = AtomicFile(File(app.noBackupFilesDir, "sallimbook-install-device-v1.bin"))
    private val aad = (app.packageName + "\n" + origin + "\nSallimBook/install-device/v1").toByteArray(Charsets.UTF_8)
    private val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    init {
        if ((app.applicationInfo.flags and ApplicationInfo.FLAG_ALLOW_BACKUP) != 0) throw AuthFailure(AuthCode.AUTH_UNAVAILABLE)
    }

    private fun stored(): Boolean = file.baseFile.exists() || File(file.baseFile.path + ".bak").exists() ||
        File(file.baseFile.path + ".new").exists()

    private fun key(create: Boolean): SecretKey {
        val existing = keyStore.getKey(alias, null)
        if (existing is SecretKey) return existing
        if (!create || keyStore.containsAlias(alias)) throw AuthFailure(AuthCode.KEY_INVALIDATED)
        val specification = KeyGenParameterSpec.Builder(alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setKeySize(256)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setRandomizedEncryptionRequired(true)
            .setUserAuthenticationRequired(false)
            .apply { if (Build.VERSION.SDK_INT >= 35) setUnlockedDeviceRequired(true) }
            .build()
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply { init(specification) }.generateKey()
    }

    override fun read(): InstallClaim? {
        if (!stored()) return null
        var plaintext: ByteArray? = null
        try {
            val envelope = file.openRead().use { input ->
                val buffer = ByteArray(513)
                var size = 0
                while (size < buffer.size) {
                    val count = input.read(buffer, size, buffer.size - size)
                    if (count < 0) break
                    size += count
                }
                if (size !in 30..512) throw AuthFailure(AuthCode.KEY_INVALIDATED)
                buffer.copyOf(size).also { buffer.fill(0) }
            }
            if (envelope[0] != 1.toByte()) throw AuthFailure(AuthCode.KEY_INVALIDATED)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, key(create = false), GCMParameterSpec(128, envelope.copyOfRange(1, 13)))
            cipher.updateAAD(aad)
            plaintext = cipher.doFinal(envelope.copyOfRange(13, envelope.size))
            val parts = plaintext.toString(Charsets.UTF_8).split('\n')
            if (parts.size != 2 || !Regex("[0-9a-f-]{36}").matches(parts[0]) ||
                !Regex("[A-Za-z0-9_-]{32,128}").matches(parts[1])) throw AuthFailure(AuthCode.KEY_INVALIDATED)
            return InstallClaim(parts[0], parts[1])
        } catch (failure: Exception) {
            // As for the refresh token: only a broken envelope or key drops the claim.
            if (!RefreshDecryptFailure.permanent(failure)) throw AuthFailure(AuthCode.AUTH_UNAVAILABLE)
            clear()
            return null
        } finally {
            plaintext?.fill(0)
        }
    }

    override fun save(claim: InstallClaim) {
        val plaintext = (claim.deviceId + "\n" + claim.key).toByteArray(Charsets.UTF_8)
        try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, key(create = true))
            cipher.updateAAD(aad)
            val iv = cipher.iv
            if (iv.size != 12) throw AuthFailure(AuthCode.KEY_INVALIDATED)
            val ciphertext = cipher.doFinal(plaintext)
            val envelope = ByteBuffer.allocate(1 + iv.size + ciphertext.size).put(1.toByte()).put(iv).put(ciphertext).array()
            val output = file.startWrite()
            try {
                output.write(envelope)
                file.finishWrite(output)
            } catch (_: Exception) {
                file.failWrite(output)
                throw AuthFailure(AuthCode.KEY_INVALIDATED)
            } finally {
                envelope.fill(0)
                ciphertext.fill(0)
            }
        } catch (failure: Exception) {
            clear()
            throw failure as? AuthFailure ?: AuthFailure(AuthCode.KEY_INVALIDATED)
        } finally {
            plaintext.fill(0)
        }
    }

    override fun clear() {
        try { file.delete() } catch (_: Exception) { }
        try { keyStore.deleteEntry(alias) } catch (_: Exception) { }
    }
}
