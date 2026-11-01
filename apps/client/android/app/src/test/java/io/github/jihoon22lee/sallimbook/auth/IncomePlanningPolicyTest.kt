package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class IncomePlanningPolicyTest {
    private val member = "00000000-0000-4000-8000-000000000002"
    private val record = "00000000-0000-4000-8000-000000000004"
    private fun rejected(action: () -> Unit) { try { action(); fail("accepted invalid input") } catch (_: AuthFailure) {} }
    @Test fun exactMoneyForecastAndBonusRemainDistinct() {
        val forecast=CashflowPolicy.prepare(FinanceOperation.CREATE_EXPECTED_INCOME,mapOf("input" to mapOf("member_id" to member,"label" to "합성 월급","amount_krw" to "9007199254740993"),"idempotencyKey" to "synthetic-forecast"))
        assertEquals("/api/v1/income-planning/expected",forecast.path)
        assertEquals("9007199254740993",forecast.body?.get("amount_krw"))
        val input=mapOf("member_id" to member,"performance_year" to 2022,"award_kind" to "opi","payment_month" to "2023-01","gross_krw" to "5000000","net_cash_krw" to "3000000","stock_grant_value_krw" to "1000000","payout_rate_percent" to "37.5","received" to true,"active" to true,"note" to null)
        val args=mapOf("input" to input,"idempotencyKey" to "synthetic-bonus")
        val request=CashflowPolicy.prepare(FinanceOperation.CREATE_BONUS_AWARD,args)
        assertEquals("POST",request.method)
        assertEquals("/api/v1/income-planning/bonuses",request.path)
        for (bad in listOf(37.5, "-1", "1e2", "1.234")) rejected { CashflowPolicy.prepare(FinanceOperation.CREATE_BONUS_AWARD,args+mapOf("input" to input+mapOf("payout_rate_percent" to bad))) }
        rejected { CashflowPolicy.prepare(FinanceOperation.CREATE_BONUS_AWARD,args+mapOf("input" to input+mapOf("net_cash_krw" to 3000000))) }
        val response=input+mapOf("id" to record,"household_id" to member,"version" to 1,"created_by_member_id" to member,"updated_by_member_id" to member,"created_at" to "2026-01-01T00:00:00Z","updated_at" to "2026-01-01T00:00:00Z","cash_record_id" to member)
        assertEquals(response,CashflowPolicy.response(FinanceOperation.CREATE_BONUS_AWARD,request,201,response))
        val change=CashflowPolicy.prepare(FinanceOperation.CHANGE_BONUS_AWARD,mapOf("recordId" to record,"input" to input+mapOf("reason" to "합성 정정"),"ifMatch" to "\"1\"","idempotencyKey" to "synthetic-change"))
        rejected { CashflowPolicy.response(FinanceOperation.CHANGE_BONUS_AWARD,change,200,response+mapOf("id" to member)) }
    }
    @Test fun bonusSummaryKeepsServerYearTotalsAndUnknownCounts() {
        val op = FinanceOperation.BONUS_AWARD_SUMMARY
        val request = FinancePolicy.prepare(op, emptyMap<String, Any?>())
        assertEquals("GET", request.method)
        assertEquals("/api/v1/income-planning/bonus-summary", request.path)
        assertTrue(FinancePolicy.metadataHttpAllowed("GET", request.path, null, null))
        assertFalse(FinancePolicy.metadataHttpAllowed("GET", request.path + "?year=2025", null, null))
        assertFalse(FinancePolicy.metadataHttpAllowed("POST", request.path, emptyMap<String, Any>(), null, "synthetic"))
        rejected { FinancePolicy.prepare(op, mapOf("query" to mapOf("year" to 2025))) }
        val year = mapOf<String, Any?>("performance_year" to 2025, "record_count" to 2, "net_cash_known_krw" to "9007199254740993",
            "net_cash_unknown_count" to 1, "stock_grant_known_krw" to "3", "stock_grant_unknown_count" to 0, "known_total_krw" to "9007199254740996")
        val response = mapOf("years" to listOf(year, year + mapOf("performance_year" to 2024, "record_count" to 1)))
        assertEquals(response, FinancePolicy.response(op, request, 200, response))
        assertEquals(response, FinancePolicy.response(op, request, 200, withAddedFields(response)))
        for (change in listOf(mapOf("net_cash_known_krw" to 3000000), mapOf("known_total_krw" to "-1"), mapOf("record_count" to 0),
            mapOf("performance_year" to 1899), mapOf("stock_grant_unknown_count" to -1), mapOf("cvc" to "synthetic"))) rejected {
            FinancePolicy.response(op, request, 200, mapOf("years" to listOf(year + change)))
        }
        rejected { FinancePolicy.response(op, request, 201, response) }
    }
}
