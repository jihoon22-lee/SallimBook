package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class NativeResponseShapeTest {
    private class Invalid : RuntimeException()
    private val invalid: () -> Nothing = { throw Invalid() }
    private val known = setOf("id", "note")
    private fun check(row: Map<String, Any?>, fields: Set<String> = known, required: Set<String> = setOf("id")) =
        NativeResponseShape.accept(row, row.keys, fields, required, invalid)
    private fun rejected(action: () -> Unit) {
        try { action(); fail("Synthetic response accepted") } catch (_: Invalid) {}
    }

    @Test fun outsideResponsesUnknownKeysStayRejected() {
        assertFalse(NativeResponseShape.tolerant)
        check(mapOf("id" to "a"))
        rejected { check(mapOf("id" to "a", "added_note" to "x")) }
        rejected { check(mapOf("note" to "x")) }
    }

    @Test fun responsesDropAddedFieldsAtEveryLevelButKeepRequiredOnes() {
        val child = mapOf("id" to "c", "added_note" to "x")
        val parent = mapOf("id" to "p", "child" to child, "items" to listOf(child), "added_note" to "x")
        val result = NativeResponseShape.project {
            check(child)
            check(parent, setOf("id", "child", "items"))
            assertTrue(NativeResponseShape.tolerant)
            assertEquals(mapOf("id" to "c"), NativeResponseShape.known(child))
            parent
        }
        assertEquals(mapOf("id" to "p", "child" to mapOf("id" to "c"), "items" to listOf(mapOf("id" to "c"))), result)
        assertFalse(NativeResponseShape.tolerant)
        rejected { NativeResponseShape.project { check(mapOf("note" to "missing id")) } }
    }

    @Test fun flatRepliesKeepTheirKnownFieldsWhenTheServerAddsSafeOnes() {
        val nested = mapOf("challenge" to "c", "added" to "kept inside")
        val reply = mapOf("id" to "a", "note" to nested, "added_note" to "x")
        assertEquals(mapOf("id" to "a", "note" to nested), NativeResponseShape.fields(reply, known, invalid))
        assertFalse(NativeResponseShape.tolerant)
        rejected { NativeResponseShape.fields(mapOf("id" to "a"), known, invalid) }
        rejected { NativeResponseShape.fields(reply + ("refresh_token" to "synthetic"), known, invalid) }
        rejected { NativeResponseShape.fields(mapOf(1 to "a", "id" to "a", "note" to "n"), known, invalid) }
        rejected { NativeResponseShape.fields(listOf("id"), known, invalid) }
    }

    @Test fun addedFieldsNamedLikeSecretsAreRefused() {
        for (name in listOf("refresh_token", "card_number_pan", "account_number", "policyNumber", "ciphertext", "cvc"))
            rejected { NativeResponseShape.project { check(mapOf("id" to "a", name to "synthetic")) } }
        assertFalse(NativeResponseShape.tolerant)
    }

    @Test fun nestedProjectionUsesTheOuterResponse() {
        val inner = mapOf("id" to "i", "added_note" to "x")
        val result = NativeResponseShape.project {
            NativeResponseShape.project { check(inner); inner }
        }
        assertEquals(mapOf("id" to "i"), result)
    }
}
