package io.github.jihoon22lee.sallimbook.auth

import android.content.Context
import android.content.pm.ApplicationInfo
import android.os.Build
import android.security.keystore.KeyPermanentlyInvalidatedException
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import java.io.File
import java.nio.ByteBuffer
import java.security.KeyStore
import javax.crypto.AEADBadTagException
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Only a malformed envelope, a failed tag or a key the platform invalidated ends the stored
 * session; a locked keystore or a vendor quirk is retried with the token kept.
 */
internal object RefreshDecryptFailure {
    fun permanent(failure: Throwable): Boolean =
        failure is AuthFailure || failure is AEADBadTagException || failure is KeyPermanentlyInvalidatedException
}

/** Only an encrypted refresh token is persisted. Access tokens never enter this store.
 * Hardware backing and vendor backup/transfer behavior still require physical-device tests.
 */
internal class RefreshStore(context: Context, origin: String) : RefreshTokenStore {
    private val app = context.applicationContext
    private val alias = app.packageName + ".auth.refresh.v1"
    private val file = AtomicFile(File(app.noBackupFilesDir, "sallimbook-auth-refresh-v1.bin"))
    private val aad = (app.packageName + "\n" + origin + "\nSallimBook/account-refresh/v1")
        .toByteArray(Charsets.UTF_8)
    private val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }

    init {
        if ((app.applicationInfo.flags and ApplicationInfo.FLAG_ALLOW_BACKUP) != 0) {
            throw AuthFailure(AuthCode.AUTH_UNAVAILABLE)
        }
    }

    fun hasRefresh(): Boolean = file.baseFile.exists() || File(file.baseFile.path + ".bak").exists() ||
        File(file.baseFile.path + ".new").exists()

    private fun key(create: Boolean): SecretKey {
        val existing = keyStore.getKey(alias, null)
        if (existing is SecretKey) return existing
        if (!create || keyStore.containsAlias(alias)) throw AuthFailure(AuthCode.KEY_INVALIDATED)
        val specification = KeyGenParameterSpec.Builder(
            alias, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT,
        )
            .setKeySize(256)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setRandomizedEncryptionRequired(true)
            .setUserAuthenticationRequired(false)
            // As in the vault: before SDK 35, face unlock and trust agents do not unlock such keys.
            .apply { if (Build.VERSION.SDK_INT >= 35) setUnlockedDeviceRequired(true) }
            .build()
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
            .apply { init(specification) }.generateKey()
    }

    override fun save(refresh: String) {
        val plaintext = refresh.toByteArray(Charsets.UTF_8)
        try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, key(create = true))
            cipher.updateAAD(aad)
            val iv = cipher.iv
            if (iv.size != 12) throw AuthFailure(AuthCode.KEY_INVALIDATED)
            val ciphertext = cipher.doFinal(plaintext)
            val envelope = ByteBuffer.allocate(1 + iv.size + ciphertext.size)
                .put(1.toByte()).put(iv).put(ciphertext).array()
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
        } catch (failure: AuthFailure) {
            clear()
            throw failure
        } catch (_: Exception) {
            clear()
            throw AuthFailure(AuthCode.KEY_INVALIDATED)
        } finally {
            plaintext.fill(0)
        }
    }

    /** Decrypts the stored token; the ciphertext stays until [consume]. */
    override fun readForRotation(): String? {
        if (!hasRefresh()) return null
        var plaintext: ByteArray? = null
        try {
            val envelope = file.openRead().use { input ->
                val buffer = ByteArray(1025)
                var size = 0
                while (size < buffer.size) {
                    val count = input.read(buffer, size, buffer.size - size)
                    if (count < 0) break
                    size += count
                }
                if (size !in 30..1024) throw AuthFailure(AuthCode.KEY_INVALIDATED)
                buffer.copyOf(size).also { buffer.fill(0) }
            }
            if (envelope[0] != 1.toByte()) throw AuthFailure(AuthCode.KEY_INVALIDATED)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, key(create = false), GCMParameterSpec(128, envelope.copyOfRange(1, 13)))
            cipher.updateAAD(aad)
            plaintext = cipher.doFinal(envelope.copyOfRange(13, envelope.size))
            val refresh = plaintext.toString(Charsets.UTF_8)
            if (!Regex("[A-Za-z0-9_-]{32,128}").matches(refresh)) throw AuthFailure(AuthCode.KEY_INVALIDATED)
            return refresh
        } catch (failure: Exception) {
            if (!RefreshDecryptFailure.permanent(failure)) throw AuthFailure(AuthCode.AUTH_UNAVAILABLE)
            clear()
            throw AuthFailure(AuthCode.KEY_INVALIDATED)
        } finally {
            plaintext?.fill(0)
        }
    }

    /** Called only from the refresh body write; a crash afterwards cannot replay the old token. */
    override fun consume() {
        try {
            file.delete()
            if (hasRefresh()) throw AuthFailure(AuthCode.KEY_INVALIDATED)
        } catch (_: Exception) {
            clear()
            throw AuthFailure(AuthCode.KEY_INVALIDATED)
        }
    }

    fun clear() {
        // Deleting the key also invalidates any stale ciphertext if file deletion fails.
        val fileGone = try { file.delete(); !hasRefresh() } catch (_: Exception) { false }
        val keyGone = try { keyStore.deleteEntry(alias); !keyStore.containsAlias(alias) }
            catch (_: Exception) { false }
        if (!fileGone && !keyGone) throw AuthFailure(AuthCode.KEY_INVALIDATED)
    }
}
