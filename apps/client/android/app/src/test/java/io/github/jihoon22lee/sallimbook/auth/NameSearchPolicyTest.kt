package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class NameSearchPolicyTest {
    private val operations = listOf(
        FinanceOperation.LIST_ASSETS, FinanceOperation.LIST_ACCOUNTS, FinanceOperation.LIST_CARDS,
        FinanceOperation.LIST_INSURANCE_POLICIES, FinanceOperation.LIST_INSURANCE_CASES,
        FinanceOperation.LIST_APPLIANCES, FinanceOperation.LIST_CONSUMABLES, FinanceOperation.LIST_RECURRING_RULES,
    )
    private fun invalid(action: () -> Unit) {
        try { action(); fail("Unsafe query accepted") } catch (failure: AuthFailure) {
            assertEquals(AuthCode.INVALID_REQUEST, failure.code)
        }
    }
    @Test fun eightListsEncodeLiteralUnicodeAndKeepFixedRoutes() {
        for (operation in operations) {
            val request = FinancePolicy.prepare(operation, mapOf("query" to mapOf("q" to "합성 A%_\\ &+?=#", "limit" to 50)))
            assertTrue(request.path.endsWith("?limit=50&q=%ED%95%A9%EC%84%B1+A%25_%5C+%26%2B%3F%3D%23"))
            assertTrue(FinancePolicy.metadataHttpAllowed("GET", request.path, null, null))
            assertFalse(FinancePolicy.metadataHttpAllowed("GET", request.path + "&q=again", null, null))
            assertFalse(FinancePolicy.metadataHttpAllowed("GET", request.path + "&account_number=synthetic", null, null))
            assertFalse(FinancePolicy.metadataHttpAllowed("GET", request.path.replace("/api/", "/%61pi/"), null, null))
        }
    }
    @Test fun lengthControlsNullAndUnicodeCodePointsMatchTheApi() {
        for (operation in operations) {
            for (value in listOf("가".repeat(121), "검색\n어", "검색\u0000어", "검색\u007f어", 42, mapOf("name" to "bad")))
                invalid { FinancePolicy.prepare(operation, mapOf("query" to mapOf("q" to value))) }
            for (value in listOf("", "  ", "가".repeat(120), "😀".repeat(120))) {
                val request = FinancePolicy.prepare(operation, mapOf("query" to mapOf("q" to value)))
                assertTrue(FinancePolicy.metadataHttpAllowed("GET", request.path, null, null))
            }
            val omitted = FinancePolicy.prepare(operation, mapOf("query" to mapOf("q" to null)))
            assertFalse(omitted.path.contains('?'))
        }
    }
    @Test fun encodedQueryDoesNotOpenOtherRoutesOrAllowControls() {
        for (operation in operations) {
            val base = FinancePolicy.prepare(operation, emptyMap<String, Any?>()).path
            for (suffix in listOf("?q=%00", "?q=%0A", "?q=%7F", "?q=%", "?q=a&unknown=x", "?q=%61", "?q=a%20b"))
                assertFalse(FinancePolicy.metadataHttpAllowed("GET", base + suffix, null, null))
            assertFalse(FinancePolicy.metadataHttpAllowed("GET", base + "/00000000-0000-4000-8000-000000000001?q=a", null, null))
        }
    }
}
