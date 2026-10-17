package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test
import java.util.UUID

class PasskeyTargetPagesTest {
    private val target = UUID(0, 1).toString()
    private val cursor = UUID(0, 2).toString()
    private val row = mapOf("id" to target, "version" to 3, "label" to "합성 대상")
    private fun rejected(action: () -> Unit) {
        try { action(); fail("Invalid target page was accepted") }
        catch (failure: AuthFailure) { assertEquals(AuthCode.ACCESS_DENIED, failure.code) }
    }

    @Test fun targetBeyondFirstTwoHundredRowsIsFoundForBothNativeLists() {
        for (passkey in listOf(true, false)) {
            val pages = PasskeyTargetPages(passkey, target, "\"3\"")
            val base = if (passkey) "/api/v1/auth/passkeys?limit=200" else "/api/v1/devices?limit=200"
            assertEquals(base, pages.nextPath)
            val first = (2L..201L).map { mapOf("id" to UUID(0, it).toString(), "version" to 1) }
            assertNull(pages.accept(mapOf("items" to first, "next_cursor" to cursor)))
            assertEquals("$base&cursor=$cursor", pages.nextPath)
            assertEquals(row, pages.accept(mapOf("items" to listOf(row), "next_cursor" to null)))
            assertNull(pages.nextPath)
        }
    }

    @Test fun exhaustedListAndStaleOrDuplicateTargetsNeverAuthorizeRevoke() {
        val pages = PasskeyTargetPages(true, target, "\"3\"")
        assertNull(pages.accept(mapOf("items" to emptyList<Any>(), "next_cursor" to null)))
        assertNull(pages.nextPath)
        rejected { pages.accept(mapOf("items" to listOf(row), "next_cursor" to null)) }
        rejected { PasskeyTargetPages(false, target, "\"2\"").accept(mapOf("items" to listOf(row), "next_cursor" to null)) }
        rejected { PasskeyTargetPages(false, target, "\"3\"").accept(mapOf("items" to listOf(row, row), "next_cursor" to null)) }
    }

    @Test fun repeatedOrMalformedCursorsCannotLoopOrAddArbitraryRequests() {
        val first = listOf(mapOf("id" to cursor, "version" to 1))
        val pages = PasskeyTargetPages(false, target, "\"3\"")
        pages.accept(mapOf("items" to first, "next_cursor" to cursor))
        rejected { pages.accept(mapOf("items" to first, "next_cursor" to cursor)) }
        rejected { PasskeyTargetPages(true, target, "\"3\"").accept(mapOf("items" to first, "next_cursor" to "../auth")) }
        rejected { PasskeyTargetPages(true, target, "\"3\"").accept(mapOf("items" to emptyList<Any>(), "next_cursor" to cursor)) }
    }
}
