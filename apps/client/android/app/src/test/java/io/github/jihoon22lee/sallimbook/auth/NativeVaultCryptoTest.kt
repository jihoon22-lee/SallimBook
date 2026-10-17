package io.github.jihoon22lee.sallimbook.auth

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import java.io.File
import java.security.SecureRandom
import org.junit.Assert.*
import org.junit.Test

/** Only the committed, explicitly public synthetic vectors are read. No production default secrets. */
class NativeVaultCryptoTest {
    private val vector = JsonParser.parseString(File("../../../../packages/test-fixtures/vault-v1.json").readText()).asJsonObject
    private val household = vector["household_id"].asString
    private val keyVersion = vector["key_version"].asLong
    private val hvk = hex(vector["hvk_hex"].asString)
    private val card = vector["card"].asJsonObject
    private fun hex(text: String) = text.chunked(2).map { it.toInt(16).toByte() }.toByteArray()
    private fun bytes(record: JsonObject, name: String, size: Int) = NativeVaultCrypto.decode(record[name].asString, size)
    private fun sealed(record: JsonObject, name: String, size: Int) = VaultSealed(bytes(record, "nonce", 12), bytes(record, name, size))
    private fun fixed(nonce: ByteArray) = NativeVaultCrypto(object : SecureRandom() {
        override fun nextBytes(bytes: ByteArray) { check(bytes.size == nonce.size); nonce.copyInto(bytes) }
    })
    private fun rejected(code: VaultCryptoCode? = null, action: () -> Unit) {
        try { action(); fail("Invalid synthetic vault input accepted") }
        catch (failure: VaultCryptoFailure) { if (code != null) assertEquals(code, failure.code); assertNull(failure.message); assertNull(failure.cause) }
    }
    @Test fun cardBinaryAndAadMatchSharedVectorAndDecryptIndependently() {
        val secret = VaultCardSecret(card["pan"].asString.toCharArray(), card["expiry_year"].asInt, card["expiry_month"].asInt)
        val aad = NativeVaultCrypto.cardAad(household, card["card_id"].asString, keyVersion)
        assertArrayEquals(hex(card["payload_hex"].asString), NativeVaultCrypto.cardPayload(secret))
        assertArrayEquals(hex(card["aad_hex"].asString), aad)
        val expected = sealed(card, "ciphertext", 43)
        val actual = fixed(expected.nonce).sealCard(hvk, secret, household, card["card_id"].asString, keyVersion)
        assertArrayEquals(expected.ciphertext, actual.ciphertext)
        val opened = NativeVaultCrypto.openCard(hvk, expected, household, card["card_id"].asString, keyVersion)
        assertArrayEquals(secret.pan, opened.pan); assertEquals(secret.expiryYear, opened.expiryYear); assertEquals(secret.expiryMonth, opened.expiryMonth)
        assertFalse(opened.toString().contains(card["pan"].asString)); opened.discard(); assertTrue(opened.pan.all { it == '\u0000' })
        secret.discard(); actual.discard(); expected.discard()
    }
    @Test fun twoIndependentPasswordsIncludingUnicodeMatchSharedPbkdfAndWrappingVectors() {
        for (value in vector["members"].asJsonArray) {
            val member = value.asJsonObject
            val password = member["password"].asString.toCharArray()
            val salt = bytes(member, "salt", 16); val count = member["iterations"].asInt
            assertArrayEquals(hex(member["password_utf8_hex"].asString), NativeVaultCrypto.passwordUtf8(password))
            val key = NativeVaultCrypto.deriveMemberKey(password, salt, count)
            assertArrayEquals(hex(member["derived_kek_hex"].asString), key)
            val memberId = member["member_id"].asString; val generation = member["generation"].asLong
            assertArrayEquals(hex(member["aad_hex"].asString), NativeVaultCrypto.memberAad(household, memberId, keyVersion, generation, count, salt))
            val expected = sealed(member, "wrapped_hvk", 48)
            val actual = fixed(expected.nonce).wrapMember(key, hvk, household, memberId, keyVersion, generation, count, salt)
            assertArrayEquals(expected.ciphertext, actual.ciphertext)
            assertArrayEquals(hvk, NativeVaultCrypto.unwrapMember(key, expected, household, memberId, keyVersion, generation, count, salt))
            key.fill(0); password.fill('\u0000'); actual.discard(); expected.discard()
        }
    }
    @Test fun tinkRecoveryHkdfAndWrappingMatchSharedVector() {
        val record = vector["recovery"].asJsonObject
        val salt = bytes(record, "salt", 16); val generation = record["generation"].asLong
        val code = bytes(record, "code", 32)
        val key = NativeVaultCrypto.deriveRecoveryKey(code, salt)
        assertArrayEquals(hex(record["derived_kek_hex"].asString), key)
        assertArrayEquals(hex(record["aad_hex"].asString), NativeVaultCrypto.recoveryAad(household, keyVersion, generation, salt))
        val expected = sealed(record, "wrapped_hvk", 48)
        val actual = fixed(expected.nonce).wrapRecovery(key, hvk, household, keyVersion, generation, salt)
        assertArrayEquals(expected.ciphertext, actual.ciphertext)
        assertArrayEquals(hvk, NativeVaultCrypto.unwrapRecovery(key, expected, household, keyVersion, generation, salt))
        code.fill(0); key.fill(0); actual.discard(); expected.discard()
    }
    @Test fun emptyVaultKeyCheckMatchesSharedVectorAndRejectsWrongKey() {
        val record = vector["key_check"].asJsonObject
        assertArrayEquals(hex(record["aad_hex"].asString), NativeVaultCrypto.keyCheckAad(household, keyVersion))
        val expected = sealed(record, "ciphertext", 45)
        val actual = fixed(expected.nonce).sealKeyCheck(hvk, household, keyVersion)
        assertArrayEquals(expected.ciphertext, actual.ciphertext)
        NativeVaultCrypto.verifyKey(hvk, expected, household, keyVersion)
        rejected(VaultCryptoCode.DECRYPTION_FAILED) { NativeVaultCrypto.verifyKey(ByteArray(32), expected, household, keyVersion) }
        actual.discard(); expected.discard()
    }
    @Test fun tamperingEveryCiphertextAndNonceByteOrBindingFailsClosed() {
        val original = sealed(card, "ciphertext", 43); val cardId = card["card_id"].asString
        for (index in original.ciphertext.indices) {
            val altered = original.ciphertext.copyOf().also { it[index] = (it[index].toInt() xor 1).toByte() }
            rejected(VaultCryptoCode.DECRYPTION_FAILED) { NativeVaultCrypto.openCard(hvk, VaultSealed(original.nonce, altered), household, cardId, keyVersion) }
        }
        for (index in original.nonce.indices) {
            val altered = original.nonce.copyOf().also { it[index] = (it[index].toInt() xor 1).toByte() }
            rejected(VaultCryptoCode.DECRYPTION_FAILED) { NativeVaultCrypto.openCard(hvk, VaultSealed(altered, original.ciphertext), household, cardId, keyVersion) }
        }
        for ((hh, id, version) in listOf(Triple(cardId, cardId, keyVersion), Triple(household, household, keyVersion), Triple(household, cardId, keyVersion + 1)))
            rejected(VaultCryptoCode.DECRYPTION_FAILED) { NativeVaultCrypto.openCard(hvk, original, hh, id, version) }
    }
    @Test fun memberAadRejectsOtherMemberGenerationIterationsSaltAndPassword() {
        val member = vector["members"].asJsonArray[0].asJsonObject
        val key = hex(member["derived_kek_hex"].asString); val salt = bytes(member, "salt", 16)
        val expected = sealed(member, "wrapped_hvk", 48); val id = member["member_id"].asString
        val generation = member["generation"].asLong; val count = member["iterations"].asInt
        for ((otherId, otherGeneration, otherCount) in listOf(Triple(household, generation, count), Triple(id, generation + 1, count), Triple(id, generation, count + 1)))
            rejected(VaultCryptoCode.DECRYPTION_FAILED) { NativeVaultCrypto.unwrapMember(key, expected, household, otherId, keyVersion, otherGeneration, otherCount, salt) }
        rejected(VaultCryptoCode.DECRYPTION_FAILED) { NativeVaultCrypto.unwrapMember(key, expected, household, id, keyVersion, generation, count, ByteArray(16)) }
        val wrong = NativeVaultCrypto.deriveMemberKey("synthetic-wrong-password".toCharArray(), salt, count)
        rejected(VaultCryptoCode.DECRYPTION_FAILED) { NativeVaultCrypto.unwrapMember(wrong, expected, household, id, keyVersion, generation, count, salt) }
        wrong.fill(0); key.fill(0)
    }
    @Test fun base64IsCanonicalUnpaddedAndSizeBounded() {
        val valid = NativeVaultCrypto.encode(ByteArray(32))
        for (bad in listOf(valid + "=", valid.dropLast(1), valid.dropLast(1) + "B", " " + valid, valid.replace('A', '+'), "A".repeat(10000)))
            rejected(VaultCryptoCode.INVALID_FORMAT) { NativeVaultCrypto.decode(bad, 32) }
        rejected { NativeVaultCrypto.decode(valid, 31) }
    }
    @Test fun malformedUnicodeCannotBeReplacedAndWhitespaceNormalizationIsNotApplied() {
        for (password in listOf(charArrayOf('\uD800'), charArrayOf('\uDC00'), charArrayOf('a','\uD800','b'), charArrayOf(), CharArray(1025) { 'a' }, CharArray(400) { '한' }))
            rejected(VaultCryptoCode.INVALID_FORMAT) { NativeVaultCrypto.passwordUtf8(password) }
        assertArrayEquals(byteArrayOf(32, 101, -52, -127, 32), NativeVaultCrypto.passwordUtf8(" e\u0301 ".toCharArray()))
        assertFalse(NativeVaultCrypto.passwordUtf8("é".toCharArray()).contentEquals(NativeVaultCrypto.passwordUtf8("e\u0301".toCharArray())))
    }
    @Test fun hostileKdfVersionsUuidsAndEnvelopeLengthsAreRejectedBeforeCrypto() {
        for (count in listOf(-1, 0, 599999, 2000001, Int.MAX_VALUE)) rejected { NativeVaultCrypto.deriveMemberKey("synthetic-password".toCharArray(), ByteArray(16), count) }
        for (size in listOf(0, 15, 17, 1024)) rejected { NativeVaultCrypto.deriveRecoveryKey(ByteArray(32), ByteArray(size)) }
        rejected { NativeVaultCrypto.deriveRecoveryKey(ByteArray(31), ByteArray(16)) }
        for (version in listOf(-1L, 0L, NativeVaultCrypto.MAX_VERSION + 1, Long.MAX_VALUE)) rejected { NativeVaultCrypto.keyCheckAad(household, version) }
        for (id in listOf("1-1-1-1-1", household + "x", "../$household", household.replace('a','A').uppercase() + "A")) rejected { NativeVaultCrypto.keyCheckAad(id, 1) }
        val expected = sealed(card, "ciphertext", 43)
        rejected { NativeVaultCrypto.openCard(ByteArray(31), expected, household, card["card_id"].asString, keyVersion) }
        rejected { NativeVaultCrypto.openCard(hvk, VaultSealed(ByteArray(13), expected.ciphertext), household, card["card_id"].asString, keyVersion) }
        rejected { NativeVaultCrypto.openCard(hvk, VaultSealed(expected.nonce, ByteArray(44)), household, card["card_id"].asString, keyVersion) }
    }
    @Test fun payloadRejectsInvalidDigitsLuhnPaddingMagicDateAndExtraFields() {
        val good = hex(card["payload_hex"].asString)
        for (index in listOf(0, 4, 5, 23, 24, 25, 26)) {
            val bad = good.copyOf().also { it[index] = 0x7f }
            rejected { NativeVaultCrypto.readCardPayload(bad) }
        }
        rejected { NativeVaultCrypto.readCardPayload(good + byteArrayOf(0)) }
        for (pan in listOf("4242424242424243", "0000000000000000", "4242 4242 4242 4242", "424242424242"))
            rejected { NativeVaultCrypto.cardPayload(VaultCardSecret(pan.toCharArray(), 2032, 12)) }
        for ((year, month) in listOf(1999 to 12, 2200 to 1, 2032 to 0, 2032 to 13))
            rejected { NativeVaultCrypto.cardPayload(VaultCardSecret(card["pan"].asString.toCharArray(), year, month)) }
    }
    @Test fun runtimeUsesFreshRandomKeysSaltsAndNoncesAndRedactsObjects() {
        val crypto = NativeVaultCrypto()
        assertEquals(32, crypto.newKey().size); assertFalse(crypto.newKey().contentEquals(crypto.newKey()))
        assertEquals(16, crypto.newSalt().size); assertFalse(crypto.newSalt().contentEquals(crypto.newSalt()))
        val first = crypto.sealKeyCheck(hvk, household, keyVersion); val second = crypto.sealKeyCheck(hvk, household, keyVersion)
        assertFalse(first.nonce.contentEquals(second.nonce)); assertEquals("VaultSealed(redacted)", first.toString())
        NativeVaultCrypto.verifyKey(hvk, first, household, keyVersion)
        first.discard(); assertTrue(first.nonce.all { it == 0.toByte() }); assertTrue(first.ciphertext.all { it == 0.toByte() }); second.discard()
    }
}
