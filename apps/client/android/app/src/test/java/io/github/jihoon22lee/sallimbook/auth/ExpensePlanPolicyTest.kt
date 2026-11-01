package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class ExpensePlanPolicyTest {
    private val id = "00000000-0000-4000-8000-000000000002"
    private val terms = mapOf("title" to "합성 계획", "category" to "합성", "amount_mode" to "variable", "economic_type" to "expense", "frequency" to "monthly", "tracking_mode" to "plan_only", "plan_kind" to "recurring", "budget_treatment" to "included", "interval_count" to 1, "expected_amount_krw" to null)
    private fun rejected(action: () -> Unit) { try { action(); fail("accepted invalid input") } catch (_: AuthFailure) {} }
    @Test fun optionalDayAndExactMoneyAreAcceptedWithoutSecrets() {
        val args = mapOf("input" to terms, "idempotencyKey" to "synthetic-plan")
        val request = FinancePolicy.prepare(FinanceOperation.CREATE_EXPENSE_PLAN,args)
        assertEquals("/api/v1/expense-plans",request.path)
        assertTrue(ExpensePlanPolicy.httpAllowed(request.method,request.path,request.body,request.ifMatch,request.idempotencyKey))
        for (bad in listOf(mapOf("cvc" to "123"),mapOf("token" to "secret"),mapOf("anchor_date" to "2026-02-30"),mapOf("expected_amount_krw" to 100),mapOf("tracking_mode" to "scheduled"),mapOf("annual_month" to 6),mapOf("subject_member_id" to "other"),mapOf("plan_kind" to "budget","frequency" to "annual"))) {
            rejected { ExpensePlanPolicy.prepare(FinanceOperation.CREATE_EXPENSE_PLAN,args+mapOf("input" to terms+bad)) }
        }
        val precise=ExpensePlanPolicy.prepare(FinanceOperation.CREATE_EXPENSE_PLAN,args+mapOf("input" to terms+mapOf("expected_amount_krw" to "9007199254740993")))
        assertEquals("9007199254740993",precise.body?.get("expected_amount_krw"))
    }
    @Test fun detailAcceptsRevokedPlanHistoryAndChecksTarget() {
        val v=terms+mapOf("id" to id,"account_id" to null,"card_id" to null,"loan_asset_id" to null,"currency_reference" to null,"foreign_amount_reference" to null,"note" to null,"anchor_date" to null,"subject_member_id" to null,"annual_month" to null,"effective_from" to "2026-02-01","effective_until" to null,"reason" to null,"created_at" to "2026-02-01T00:00:00Z","revoked_at" to "2026-02-01T01:00:00Z","monthly_equivalent_krw" to null)
        val response=mapOf("id" to id,"household_id" to id,"version" to 2,"ended_on" to "2026-02-01","end_reason" to "합성 종료","versions" to emptyList<Any>(),"history" to listOf(v))
        val request=ExpensePlanPolicy.prepare(FinanceOperation.GET_EXPENSE_PLAN,mapOf("planId" to id))
        assertEquals(response,ExpensePlanPolicy.response(FinanceOperation.GET_EXPENSE_PLAN,request,200,response))
        rejected { ExpensePlanPolicy.response(FinanceOperation.GET_EXPENSE_PLAN,request,200,response+mapOf("id" to "00000000-0000-4000-8000-000000000003")) }
        rejected { ExpensePlanPolicy.response(FinanceOperation.GET_EXPENSE_PLAN,request,200,response+mapOf("secret" to "no")) }
    }
}
