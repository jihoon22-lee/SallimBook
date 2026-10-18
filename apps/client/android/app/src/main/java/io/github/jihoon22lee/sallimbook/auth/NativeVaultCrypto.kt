package io.github.jihoon22lee.sallimbook.auth

import com.google.crypto.tink.subtle.Hkdf
import java.nio.ByteBuffer
import java.nio.CharBuffer
import java.nio.charset.CodingErrorAction
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64
import java.util.UUID
import javax.crypto.Cipher
import javax.crypto.SecretKeyFactory
import javax.crypto.spec.GCMParameterSpec
import javax.crypto.spec.PBEKeySpec
import javax.crypto.spec.SecretKeySpec

internal enum class VaultCryptoCode { INVALID_FORMAT, DECRYPTION_FAILED }
/** Never attach a key, password, submitted value, provider message or cause. */
internal class VaultCryptoFailure(val code: VaultCryptoCode) : Exception()

internal class VaultSealed(val nonce: ByteArray, val ciphertext: ByteArray) {
    fun discard() { nonce.fill(0); ciphertext.fill(0) }
    override fun toString() = "VaultSealed(redacted)"
}

/** Owned by a native protected screen; never place in AuthOutcome, Intent or saved state. */
internal class VaultCardSecret(val pan: CharArray, val expiryYear: Int, val expiryMonth: Int) {
    fun discard() = pan.fill('\u0000')
    override fun toString() = "VaultCardSecret(redacted)"
}

/** Binary protocol only. No network, bridge, persistence, authentication or permission decisions. */
internal class NativeVaultCrypto(private val random: SecureRandom = SecureRandom()) {
    companion object {
        const val MAX_VERSION = 9_007_199_254_740_991L
        const val MIN_ITERATIONS = 600_000
        const val MAX_ITERATIONS = 2_000_000
        private const val MAX_PASSWORD_BYTES = 1024
        private val uuidPattern = Regex("[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
        private val encodedPattern = Regex("[A-Za-z0-9_-]+")
        private val recoveryInfo = "SallimBook/vault/recovery-kek/v1".toByteArray(Charsets.UTF_8)
        private val checkPlaintext = "SallimBook vault key check v1".toByteArray(Charsets.US_ASCII)
        private fun invalid(): Nothing = throw VaultCryptoFailure(VaultCryptoCode.INVALID_FORMAT)

        fun decode(value: String, size: Int): ByteArray {
            if (size !in setOf(12, 16, 32, 43, 45, 48) || value.length != (size * 8 + 5) / 6 || !encodedPattern.matches(value)) invalid()
            val bytes = try { Base64.getUrlDecoder().decode(value) } catch (_: IllegalArgumentException) { invalid() }
            if (bytes.size != size || encode(bytes) != value) { bytes.fill(0); invalid() }
            return bytes
        }
        fun encode(bytes: ByteArray): String = Base64.getUrlEncoder().withoutPadding().encodeToString(bytes)
        private fun version(value: Long): Long { if (value !in 1..MAX_VERSION) invalid(); return value }
        private fun iterations(value: Int): Int { if (value !in MIN_ITERATIONS..MAX_ITERATIONS) invalid(); return value }
        private fun sized(value: ByteArray, size: Int): ByteArray { if (value.size != size) invalid(); return value }
        private fun uuid(value: String): ByteArray {
            if (!uuidPattern.matches(value)) invalid()
            val id = try { UUID.fromString(value) } catch (_: IllegalArgumentException) { invalid() }
            return ByteBuffer.allocate(16).putLong(id.mostSignificantBits).putLong(id.leastSignificantBits).array()
        }
        private fun prefix(purpose: String) = "SallimBook/vault/$purpose/v1\u0000".toByteArray(Charsets.US_ASCII)
        fun cardAad(householdId: String, cardId: String, keyVersion: Long): ByteArray =
            prefix("card") + uuid(householdId) + uuid(cardId) + ByteBuffer.allocate(12).putLong(version(keyVersion)).putInt(1).array()
        fun memberAad(householdId: String, memberId: String, keyVersion: Long, generation: Long, count: Int, salt: ByteArray): ByteArray =
            prefix("member") + uuid(householdId) + uuid(memberId) + ByteBuffer.allocate(20).putLong(version(keyVersion))
                .putLong(version(generation)).putInt(iterations(count)).array() + sized(salt, 16)
        fun recoveryAad(householdId: String, keyVersion: Long, generation: Long, salt: ByteArray): ByteArray =
            prefix("recovery") + uuid(householdId) + ByteBuffer.allocate(16).putLong(version(keyVersion)).putLong(version(generation)).array() + sized(salt, 16)
        fun keyCheckAad(householdId: String, keyVersion: Long): ByteArray =
            prefix("key-check") + uuid(householdId) + ByteBuffer.allocate(8).putLong(version(keyVersion)).array()

        /** Validate original Unicode before JCA's UTF-8 PBKDF2 provider conversion. No String copy. */
        fun passwordUtf8(password: CharArray): ByteArray {
            if (password.isEmpty() || password.size > MAX_PASSWORD_BYTES) invalid()
            val buffer = ByteBuffer.allocate(MAX_PASSWORD_BYTES)
            try {
                val encoder = Charsets.UTF_8.newEncoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT)
                val result = encoder.encode(CharBuffer.wrap(password), buffer, true)
                if (result.isError || result.isOverflow) invalid()
                val end = encoder.flush(buffer)
                if (end.isError || end.isOverflow || buffer.position() == 0) invalid()
                return buffer.array().copyOf(buffer.position())
            } finally { buffer.array().fill(0) }
        }
        fun deriveMemberKey(password: CharArray, salt: ByteArray, count: Int): ByteArray {
            sized(salt, 16); iterations(count)
            passwordUtf8(password).fill(0)
            val specification = PBEKeySpec(password, salt, count, 256)
            try {
                // Android PBKDF2WithHmacSHA256 uses PKCS5S2_UTF8; vectors also exercise the JDK provider.
                return SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256").generateSecret(specification).encoded.also { sized(it, 32) }
            } catch (_: Exception) { throw VaultCryptoFailure(VaultCryptoCode.INVALID_FORMAT) }
            finally { specification.clearPassword() }
        }
        fun deriveRecoveryKey(code: ByteArray, salt: ByteArray): ByteArray {
            sized(code, 32); sized(salt, 16)
            return try { Hkdf.computeHkdf("HmacSHA256", code, salt, recoveryInfo, 32) }
            catch (_: Exception) { throw VaultCryptoFailure(VaultCryptoCode.INVALID_FORMAT) }
        }
        private fun validPan(pan: CharArray): Boolean {
            if (pan.size !in 13..19 || pan.any { it !in '0'..'9' }) return false
            var total = 0
            for (index in pan.indices.reversed()) {
                var digit = pan[index] - '0'
                if ((pan.lastIndex - index) % 2 == 1) { digit *= 2; if (digit > 9) digit -= 9 }
                total += digit
            }
            return total % 10 == 0 && pan.any { it != '0' }
        }
        fun cardPayload(secret: VaultCardSecret): ByteArray {
            if (!validPan(secret.pan) || secret.expiryYear !in 2000..2199 || secret.expiryMonth !in 1..12) invalid()
            val bytes = ByteBuffer.allocate(27).put(byteArrayOf(83, 66, 86, 49)).put(secret.pan.size.toByte())
            for (index in 0 until 19) bytes.put(if (index < secret.pan.size) secret.pan[index].code.toByte() else 0)
            return bytes.putShort(secret.expiryYear.toShort()).put(secret.expiryMonth.toByte()).array()
        }
        fun readCardPayload(bytes: ByteArray): VaultCardSecret {
            sized(bytes, 27)
            if (!bytes.copyOfRange(0, 4).contentEquals(byteArrayOf(83, 66, 86, 49))) invalid()
            val length = bytes[4].toInt() and 255
            if (length !in 13..19 || (5 + length until 24).any { bytes[it] != 0.toByte() }) invalid()
            val pan = CharArray(length) { (bytes[5 + it].toInt() and 255).toChar() }
            val year = ((bytes[24].toInt() and 255) shl 8) or (bytes[25].toInt() and 255)
            val month = bytes[26].toInt() and 255
            if (!validPan(pan) || year !in 2000..2199 || month !in 1..12) { pan.fill('\u0000'); invalid() }
            return VaultCardSecret(pan, year, month)
        }
        private fun decrypt(key: ByteArray, sealed: VaultSealed, aad: ByteArray, expected: Int): ByteArray {
            sized(key, 32); sized(sealed.nonce, 12); sized(sealed.ciphertext, expected + 16)
            try {
                val cipher = Cipher.getInstance("AES/GCM/NoPadding")
                cipher.init(Cipher.DECRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, sealed.nonce))
                cipher.updateAAD(aad)
                return cipher.doFinal(sealed.ciphertext).also { if (it.size != expected) { it.fill(0); invalid() } }
            } catch (_: Exception) { throw VaultCryptoFailure(VaultCryptoCode.DECRYPTION_FAILED) }
        }
        fun openCard(key: ByteArray, sealed: VaultSealed, householdId: String, cardId: String, keyVersion: Long): VaultCardSecret {
            val bytes = decrypt(key, sealed, cardAad(householdId, cardId, keyVersion), 27)
            return try { readCardPayload(bytes) } finally { bytes.fill(0) }
        }
        fun unwrapMember(key: ByteArray, sealed: VaultSealed, householdId: String, memberId: String, keyVersion: Long,
            generation: Long, count: Int, salt: ByteArray): ByteArray =
            decrypt(key, sealed, memberAad(householdId, memberId, keyVersion, generation, count, salt), 32)
        fun unwrapRecovery(key: ByteArray, sealed: VaultSealed, householdId: String, keyVersion: Long, generation: Long, salt: ByteArray): ByteArray =
            decrypt(key, sealed, recoveryAad(householdId, keyVersion, generation, salt), 32)
        fun verifyKey(key: ByteArray, sealed: VaultSealed, householdId: String, keyVersion: Long) {
            val bytes = decrypt(key, sealed, keyCheckAad(householdId, keyVersion), checkPlaintext.size)
            try { if (!MessageDigest.isEqual(bytes, checkPlaintext)) throw VaultCryptoFailure(VaultCryptoCode.DECRYPTION_FAILED) }
            finally { bytes.fill(0) }
        }
    }
    fun newKey(): ByteArray = ByteArray(32).also(random::nextBytes)
    fun newSalt(): ByteArray = ByteArray(16).also(random::nextBytes)
    private fun encrypt(key: ByteArray, bytes: ByteArray, aad: ByteArray): VaultSealed {
        sized(key, 32)
        val nonce = ByteArray(12).also(random::nextBytes)
        return try {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.ENCRYPT_MODE, SecretKeySpec(key, "AES"), GCMParameterSpec(128, nonce))
            cipher.updateAAD(aad)
            VaultSealed(nonce, cipher.doFinal(bytes))
        } catch (_: Exception) { nonce.fill(0); throw VaultCryptoFailure(VaultCryptoCode.INVALID_FORMAT) }
    }
    fun sealCard(key: ByteArray, secret: VaultCardSecret, householdId: String, cardId: String, keyVersion: Long): VaultSealed {
        val bytes = cardPayload(secret)
        return try { encrypt(key, bytes, cardAad(householdId, cardId, keyVersion)) } finally { bytes.fill(0) }
    }
    fun wrapMember(key: ByteArray, hvk: ByteArray, householdId: String, memberId: String, keyVersion: Long,
        generation: Long, count: Int, salt: ByteArray): VaultSealed =
        encrypt(key, sized(hvk, 32), memberAad(householdId, memberId, keyVersion, generation, count, salt))
    fun wrapRecovery(key: ByteArray, hvk: ByteArray, householdId: String, keyVersion: Long, generation: Long, salt: ByteArray): VaultSealed =
        encrypt(key, sized(hvk, 32), recoveryAad(householdId, keyVersion, generation, salt))
    fun sealKeyCheck(key: ByteArray, householdId: String, keyVersion: Long): VaultSealed =
        encrypt(key, checkPlaintext, keyCheckAad(householdId, keyVersion))
}
