package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class NativeStoredCardTest {
    private val id = "00000000-0000-0000-0000-000000000001"
    private fun bad(action: () -> Unit) {
        try { action(); fail("Invalid synthetic card accepted") } catch (e: AuthFailure) { assertNull(e.message) }
    }
    @Test fun entryAcceptsOnlyActionAndCardUuid() {
        for (action in listOf("view", "edit", "delete")) assertTrue(NativeStoredCardPolicy.entry(mapOf("action" to action, "cardId" to id)))
        for (input in listOf(mapOf("action" to "edit", "cardId" to id, "pan" to "synthetic"), mapOf("action" to "setup", "cardId" to id), mapOf("action" to "edit", "cardId" to "../bad"))) assertFalse(NativeStoredCardPolicy.entry(input))
    }
    @Test fun normalizationAndChecksumWarningDoNotBlockManualSave() {
        val details = NativeStoredCardPolicy.input("4111-1111 1111-1112".toCharArray(), "2030", "12", "123".toCharArray())
        assertArrayEquals("4111111111111112".toCharArray(), details.pan)
        assertFalse(details.checksumValid)
        details.discard(); assertTrue(details.pan.all { it == '\u0000' }); assertTrue(details.cvc!!.all { it == '\u0000' })
        assertEquals("NativeStoredCard(redacted)", details.toString())
    }
    @Test fun invalidInputAndMalformedRevealFailClosed() {
        for (number in listOf("", "123456789012", "41111111111111111111", "４１１１１１１１１１１１１１１１")) bad { NativeStoredCardPolicy.input(number.toCharArray(), "2030", "12", charArrayOf()) }
        bad { NativeStoredCardPolicy.input("4111111111111111".toCharArray(), "2030", "13", charArrayOf()) }
        bad { NativeStoredCardPolicy.input("4111111111111111".toCharArray(), "2030", "12", "12".toCharArray()) }
        val valid = mapOf("card_id" to id, "household_id" to id, "pan" to "4111111111111111", "expiry_year" to 2030L, "expiry_month" to 12L, "cvc" to null, "checksum_valid" to true, "version" to 3L)
        val revealed = NativeStoredCardPolicy.reveal(valid, id); assertEquals(3L, revealed.version); revealed.discard()
        bad { NativeStoredCardPolicy.reveal(valid + ("card_id" to "00000000-0000-0000-0000-000000000002"), id) }
        bad { NativeStoredCardPolicy.reveal(valid + ("access_token" to "synthetic"), id) }
        bad { NativeStoredCardPolicy.reveal(valid + ("checksum_valid" to false), id) }
    }
    @Test fun genericFinanceRejectsAllProtectedRoutesAndFields() {
        for (method in listOf("GET", "POST", "PUT", "DELETE")) for (suffix in listOf("stored-details", "stored-details/reveal"))
            assertFalse(FinancePolicy.metadataHttpAllowed(method, "/api/v1/cards/$id/$suffix", null, "\"1\"", null))
        for (field in listOf("pan", "cvc", "expiry_year", "expiry_month")) bad {
            FinancePolicy.prepare(FinanceOperation.UPDATE_CARD, mapOf("cardId" to id, "ifMatch" to "\"1\"", "input" to mapOf(field to "synthetic")))
        }
    }
}
