package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class HouseholdPeoplePolicyTest {
    private fun id(n: Int) = "00000000-0000-4000-8000-${n.toString().padStart(12, '0')}"
    private fun bad(action: () -> Unit) {
        try { action(); fail("invalid family metadata accepted") } catch (_: AuthFailure) { }
    }
    private fun person(n: Int = 7) = mapOf<String, Any?>(
        "id" to id(n), "household_id" to id(3), "member_id" to null,
        "display_name" to "합성 자녀", "relation" to "child", "active" to true,
        "archived_at" to null, "version" to 1, "created_by_member_id" to id(2),
        "updated_by_member_id" to id(2), "created_at" to "2026-10-24T00:00:00Z",
        "updated_at" to "2026-10-24T00:00:00Z",
    )
    @Test fun namedRequestsRejectIdentityAndCredentialFields() {
        val input = mapOf("display_name" to "합성 자녀", "relation" to "child")
        val args = mapOf("input" to input, "idempotencyKey" to "synthetic-people")
        val request = FinancePolicy.prepare(FinanceOperation.CREATE_HOUSEHOLD_PERSON, args)
        assertEquals("POST", request.method)
        assertTrue(FinancePolicy.metadataHttpAllowed(request.method, request.path, request.body, request.ifMatch, request.idempotencyKey))
        for (field in listOf("member_id", "household_id", "user_id", "token", "cvc")) {
            bad { FinancePolicy.prepare(FinanceOperation.CREATE_HOUSEHOLD_PERSON, args + ("input" to (input + (field to id(2))))) }
        }
        bad { FinancePolicy.prepare(FinanceOperation.CREATE_HOUSEHOLD_PERSON, args + ("input" to (input + ("relation" to "member")))) }
        bad { FinancePolicy.prepare(FinanceOperation.CREATE_HOUSEHOLD_PERSON, args - "idempotencyKey") }
        assertFalse(HouseholdPeoplePolicy.httpAllowed("DELETE", request.path + "/" + id(7), null, "\"1\"", null))
    }
    @Test fun archiveRequestsRequireVersionAndStrictBoolean() {
        val args = mapOf("personId" to id(7), "input" to mapOf("active" to false), "ifMatch" to "\"2\"")
        val request = FinancePolicy.prepare(FinanceOperation.UPDATE_HOUSEHOLD_PERSON, args)
        assertTrue(HouseholdPeoplePolicy.httpAllowed("PATCH", request.path, request.body, request.ifMatch, null))
        bad { FinancePolicy.prepare(FinanceOperation.UPDATE_HOUSEHOLD_PERSON, args - "ifMatch") }
        bad { FinancePolicy.prepare(FinanceOperation.UPDATE_HOUSEHOLD_PERSON, args + ("input" to mapOf("active" to "false"))) }
    }
    @Test fun pagedPeopleAcceptCreationOrderAndPreserveIdentityKinds() {
        val operation = FinanceOperation.LIST_HOUSEHOLD_PEOPLE
        val request = FinancePolicy.prepare(operation, mapOf("query" to mapOf("limit" to 2)))
        val member = person(2) + mapOf("member_id" to id(2), "relation" to "member")
        val page = mapOf("items" to listOf(member, person(7)), "next_cursor" to id(7))
        assertEquals(page, FinancePolicy.response(operation, request, 200, page))
        bad { FinancePolicy.response(operation, request, 200, page + ("next_cursor" to id(2))) }
        bad { FinancePolicy.response(operation, request, 200, page + ("items" to listOf(person(), person()))) }
        bad { FinancePolicy.response(operation, request, 200, page + ("items" to listOf(member, person() + ("household_id" to id(99))))) }
        bad { FinancePolicy.response(operation, request, 200, page + ("items" to listOf(person() + ("member_id" to id(2))))) }
        bad { FinancePolicy.prepare(operation, mapOf("query" to mapOf("limit" to 201))) }
        assertFalse(HouseholdPeoplePolicy.httpAllowed("GET", request.path + "&limit=2", null, null, null))
    }
    @Test fun archivedPeopleRemainVisibleAndAddedFieldsAreDropped() {
        val operation = FinanceOperation.UPDATE_HOUSEHOLD_PERSON
        val request = FinancePolicy.prepare(operation, mapOf("personId" to id(7), "input" to mapOf("active" to false), "ifMatch" to "\"1\""))
        val archived = person() + mapOf("active" to false, "archived_at" to "2026-10-24T00:00:00Z")
        assertEquals(archived, FinancePolicy.response(operation, request, 200, archived + ("future_metadata" to "discard")))
        bad { FinancePolicy.response(operation, request, 200, archived + ("id" to id(8))) }
        bad { FinancePolicy.response(operation, request, 200, archived + ("active" to true)) }
    }
    @Test fun creationReplayIsOnlyAnImmutableReference() {
        val operation = FinanceOperation.CREATE_HOUSEHOLD_PERSON
        val request = FinancePolicy.prepare(operation, mapOf("input" to mapOf("display_name" to "합성 자녀", "relation" to "child"), "idempotencyKey" to "synthetic-key"))
        val reference = mapOf("id" to id(7), "version" to 1)
        assertEquals(reference, FinancePolicy.response(operation, request, 201, reference))
        bad { FinancePolicy.response(operation, request, 201, reference + ("version" to 0)) }
        assertTrue("household_person" in NativeAuditWire.entityTypes)
        assertTrue("relation" in NativeAuditWire.knownFields)
    }
}
