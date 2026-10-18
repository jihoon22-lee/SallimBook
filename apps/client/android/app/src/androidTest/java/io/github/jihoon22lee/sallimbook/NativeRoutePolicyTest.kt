package io.github.jihoon22lee.sallimbook

import androidx.test.ext.junit.runners.AndroidJUnit4
import io.github.jihoon22lee.sallimbook.auth.AuthCode
import io.github.jihoon22lee.sallimbook.auth.AuthFailure
import io.github.jihoon22lee.sallimbook.auth.FinanceOperation
import io.github.jihoon22lee.sallimbook.auth.FinancePolicy
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Android uses ICU regex, which rejects an unescaped literal closing brace.
 * Exercise the actual policies on-device; host JVM unit tests cannot catch that difference.
 * No network, credentials, real data, Activity or device state is needed.
 */
@RunWith(AndroidJUnit4::class)
class NativeRoutePolicyTest {
    private val id = "00000000-0000-4000-8000-000000000010"
    private val secondId = "00000000-0000-4000-8000-000000000020"
    private data class Read(val operation: FinanceOperation, val args: Map<String, Any?>, val path: String)
    private fun lists() = listOf(
        Read(FinanceOperation.LIST_INCOME, mapOf("query" to mapOf("month" to "2026-10", "limit" to 200)), "/api/v1/income?limit=200&month=2026-10"),
        Read(FinanceOperation.LIST_OBLIGATIONS, mapOf("query" to mapOf("month" to "2026-10", "limit" to 200)), "/api/v1/obligations?limit=200&month=2026-10"),
        Read(FinanceOperation.LIST_DOCUMENTS, mapOf("query" to mapOf("limit" to 200)), "/api/v1/documents?limit=200"),
        Read(FinanceOperation.LIST_INSURANCE_CASES, mapOf("query" to mapOf("limit" to 200)), "/api/v1/insurance/cases?limit=200"),
        Read(FinanceOperation.LIST_INSURANCE_CLAIMS, mapOf("query" to mapOf("limit" to 200)), "/api/v1/insurance/claims?limit=200"),
        Read(FinanceOperation.GET_HOMECARE_STATUS, mapOf("query" to mapOf("limit" to 200)), "/api/v1/homecare/status?limit=200")
    )
    private fun details() = listOf(
        Read(FinanceOperation.GET_ASSET_MONTH_REVISION, mapOf("month" to "2026-10", "revisionNo" to 2), "/api/v1/asset-months/2026-10/revisions/2"),
        Read(FinanceOperation.GET_OBLIGATION, mapOf("obligationId" to id), "/api/v1/obligations/$id"),
        Read(FinanceOperation.GET_DOCUMENT, mapOf("documentId" to id), "/api/v1/documents/$id"),
        Read(FinanceOperation.GET_INSURANCE_POLICY, mapOf("policyId" to id), "/api/v1/insurance/policies/$id"),
        Read(FinanceOperation.GET_INSURANCE_CLAIM, mapOf("claimId" to id), "/api/v1/insurance/claims/$id"),
        Read(FinanceOperation.GET_STOCK_MOVEMENT, mapOf("consumableId" to id, "movementId" to secondId), "/api/v1/consumables/$id/stock-movements/$secondId")
    )
    private fun check(read: Read) {
        val request = FinancePolicy.prepare(read.operation, read.args)
        assertEquals(read.path, request.path)
        assertEquals("GET", request.method)
        assertNull(request.body); assertNull(request.ifMatch); assertNull(request.idempotencyKey)
        assertTrue(FinancePolicy.metadataHttpAllowed(request.method, request.path, null, null, null))
    }
    private fun invalid(operation: FinanceOperation, args: Map<String, Any?>) {
        try { FinancePolicy.prepare(operation, args); fail("Invalid synthetic route accepted") }
        catch (failure: AuthFailure) { assertEquals(AuthCode.INVALID_REQUEST, failure.code) }
    }
    @Test fun allSixDomainListRoutesAndFreshHomeResponseWorkOnAndroid() {
        lists().forEach(::check)
        val read = lists().last()
        val request = FinancePolicy.prepare(read.operation, read.args)
        val body = mapOf("as_of" to "2026-10-18", "items" to emptyList<Any>(), "next_cursor" to null)
        assertEquals(body, FinancePolicy.response(read.operation, request, 200, body))
    }
    @Test fun allSixDomainRouteTemplatesBindIdsAndMultipleParametersOnAndroid() {
        details().forEach(::check)
    }
    @Test fun correctedTemplatesStillRejectInvalidIdsAndExtraArgumentsOnAndroid() {
        for (read in lists() + details()) {
            invalid(read.operation, read.args + ("url" to "https://synthetic.invalid/"))
            assertFalse(FinancePolicy.metadataHttpAllowed("GET", read.path + "#fragment", null, null, null))
        }
        for (read in details()) {
            for (key in read.args.keys) {
                invalid(read.operation, read.args - key)
                invalid(read.operation, read.args + (key to "../synthetic"))
            }
        }
    }
}
