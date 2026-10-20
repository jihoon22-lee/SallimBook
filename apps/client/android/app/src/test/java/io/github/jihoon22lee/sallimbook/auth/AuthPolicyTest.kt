package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class AuthPolicyTest {
    private val uuid = "00000000-0000-4000-8000-000000000001"

    @Test fun apiOriginRequiresExplicitHttpsWithoutOtherUrlParts() {
        for (origin in listOf("https://synthetic.invalid", "https://synthetic.invalid:8443")) {
            assertEquals(origin, AuthPolicy.apiOrigin(origin))
        }
        for (origin in listOf(
            "", "http://synthetic.invalid", "//synthetic.invalid", "https://",
            "https://user:password@synthetic.invalid", "https://synthetic.invalid/",
            "https://synthetic.invalid/api", "https://synthetic.invalid?x=1",
            "https://synthetic.invalid#fragment", "https://synthetic.invalid:",
            "https://synthetic.invalid:0", "https://synthetic.invalid:65536",
            "https://synthetic.invalid:0443", " https://synthetic.invalid",
            "https://synthetic.invalid\n", "https://synthetic.invalid%2f.example",
            "https://synthetic.invalid\\.example",
        )) assertNull(origin, AuthPolicy.apiOrigin(origin))
    }

    @Test fun bridgeRequiresTheBundledLocalHttpsOrigin() {
        assertTrue(AuthPolicy.trustedBridgeUrl("https://localhost/assets"))
        assertTrue(AuthPolicy.trustedBridgeUrl("https://localhost/#/settings"))
        for (url in listOf(null, "", "http://localhost", "https://localhost:443",
            "https://localhost.synthetic.invalid", "https://synthetic.invalid",
            "https://user@localhost", "file:///android_asset/index.html")) {
            assertFalse(url, AuthPolicy.trustedBridgeUrl(url))
        }
    }

    @Test fun requestsAllowOnlyTheCurrentMetadataEndpointsAndBoundedDeviceQueries() {
        for (path in listOf("/api/v1/me", "/api/v1/household/members", "/api/v1/devices",
            "/api/v1/devices?limit=200", "/api/v1/devices?cursor=$uuid&limit=1",
            "/api/v1/devices?limit=50&cursor=$uuid")) {
            assertTrue(path, AuthPolicy.requestAllowed("GET", path, null))
        }
        assertTrue(AuthPolicy.requestAllowed("DELETE", "/api/v1/devices/$uuid", "\"1\""))
        for (path in listOf(
            "/api/v1/devices?limit=201", "/api/v1/devices?limit=0",
            "/api/v1/devices?limit=01", "/api/v1/devices?limit=1&limit=2",
            "/api/v1/devices?cursor=1-1-1-1-1", "/api/v1/devices?password=synthetic",
            "/api/v1/me?anything=1", "/api/v1/devices?", "/api/v1/devices/$uuid",
        )) assertFalse(path, AuthPolicy.requestAllowed("GET", path, null))
    }

    @Test fun credentialsVaultRevealDocumentsAndPathBypassesAreNeverAllowed() {
        for (path in listOf(
            "https://synthetic.invalid/api/v1/me", "//synthetic.invalid/api/v1/me",
            "/api/v1/../auth/native/login", "/api/v1/%6de", "/api/v1/me#fragment",
            "/api/v1//me", "/api/v1/me/", "/api/v1/me\\", "/api/v1/me\n",
            "/api/v1/auth/native/login", "/api/v1/auth/native/refresh", "/api/v1/auth/web/csrf",
            "/api/v1/vault/status", "/api/v1/cards/$uuid/secret-envelope",
            "/api/v1/accounts/$uuid/reveal", "/api/v1/documents/$uuid/download",
            "/api/v1/documents/download", "/api/v1/household/invitations", "/api/v1/assets",
        )) {
            for (method in listOf("GET", "POST", "DELETE")) {
                assertFalse("$method $path", AuthPolicy.requestAllowed(method, path, null))
            }
        }
    }

    @Test fun deviceDeletionRequiresOnlyAStrongVersionTag() {
        for (tag in listOf(null, "1", "\"0\"", "W/\"1\"", "*", "\"-1\"", "\"1\"\r\nCookie:synthetic")) {
            assertFalse(AuthPolicy.requestAllowed("DELETE", "/api/v1/devices/$uuid", tag))
        }
        assertFalse(AuthPolicy.requestAllowed("GET", "/api/v1/me", "\"1\""))
        assertFalse(AuthPolicy.requestAllowed("delete", "/api/v1/devices/$uuid", "\"1\""))
    }

    @Test fun safeJsonRejectsCredentialFieldsAtEveryDepthAndFormat() {
        assertTrue(AuthPolicy.safeJson(mapOf("items" to listOf(mapOf(
            "id" to uuid, "label" to "합성 Android", "current" to true, "version" to 1,
        )), "next_cursor" to null)))
        for (key in listOf("password", "access_token", "refreshToken", "token_type", "Authorization",
            "Set-Cookie", "csrf_token", "private_key", "wrappedKey", "account_number", "pan",
            "cvc", "cvv", "recovery_code", "session_hash", "api_key", "salt",
            "pa\u200bssword", "ｐａｓｓｗｏｒｄ")) {
            assertFalse(key, AuthPolicy.safeJson(mapOf("items" to listOf(mapOf(key to "synthetic")))))
        }
        assertFalse(AuthPolicy.safeJson(mapOf("version" to 1.5)))
        assertFalse(AuthPolicy.safeJson(mapOf("version" to Double.NaN)))
        assertFalse(AuthPolicy.safeJson(List(201) { null }))
        var nested: Any? = null
        repeat(18) { nested = listOf(nested) }
        assertFalse(AuthPolicy.safeJson(nested))
    }

    @Test fun cancelledForegroundRequestCannotApplyALateResult() {
        val request = ForegroundRequest()
        var applied = false
        var cancelledCalls = 0
        request.bindNetworkCancellation { cancelledCalls++ }
        request.cancel()
        request.cancel()
        assertEquals(1, cancelledCalls)
        request.bindNetworkCancellation { cancelledCalls++ }
        assertEquals(2, cancelledCalls)
        assertFalse(request.isActive())
        try {
            request.whileActive { applied = true }
            fail("Cancelled request applied a result")
        } catch (failure: AuthFailure) {
            assertEquals(AuthCode.AUTH_CANCELLED, failure.code)
        }
        assertFalse(applied)
    }

    @Test fun assetMonthAndAccountErrorsKeepTheirCode() {
        for ((status, code) in listOf(
            422 to "ASSET_END_IN_FUTURE", 422 to "MONTH_IN_FUTURE", 409 to "PREVIOUS_MONTH_UNCONFIRMED", 409 to "ACCOUNT_IN_USE",
        )) {
            val error = AuthPolicy.safeError(
                status, mapOf("error" to mapOf("code" to code, "message" to "synthetic")), uuid,
            )!!["error"] as Map<*, *>
            assertEquals(code, error["code"])
            assertFalse(error["message"].toString().contains("synthetic"))
        }
    }

    @Test fun errorResponsesKeepOnlyRecognizedCodeCorrelationAndPositiveConflictVersion() {
        val input = mapOf("error" to mapOf(
            "code" to "REAUTHENTICATION_REQUIRED", "message" to "synthetic-sensitive-input",
            "request_id" to "ignored-untrusted-body-id", "password" to "synthetic",
        ))
        val result = AuthPolicy.safeError(403, input, uuid)!!["error"] as Map<*, *>
        assertEquals("REAUTHENTICATION_REQUIRED", result["code"])
        assertEquals(uuid, result["request_id"])
        assertEquals("다시 로그인한 후 진행해 주세요.", result["message"])
        assertEquals(setOf("code", "message", "request_id"), result.keys)
        assertNull(AuthPolicy.safeError(403, input, "synthetic-sensitive-input"))
        val unknown = mapOf("error" to mapOf("code" to "SYNTHETIC_SECRET_VALUE", "current_version" to 8))
        val conflict = AuthPolicy.safeError(409, unknown, uuid)!!["error"] as Map<*, *>
        assertEquals("VERSION_CONFLICT", conflict["code"])
        assertEquals(8, conflict["current_version"])
        val invalidVersion = mapOf("error" to mapOf("current_version" to "synthetic-sensitive-input"))
        assertFalse((AuthPolicy.safeError(409, invalidVersion, uuid)!!["error"] as Map<*, *>).containsKey("current_version"))
    }

    @Test fun assetKindRestrictionIsNotAStaleVersionConflict() {
        val body = mapOf("error" to mapOf("code" to "ASSET_KIND_IN_USE", "message" to "synthetic"))
        val error = AuthPolicy.safeError(409, body, uuid)!!["error"] as Map<*, *>
        assertEquals("ASSET_KIND_IN_USE", error["code"])
        val unavailable = mapOf("error" to mapOf("code" to "ASSET_UNAVAILABLE"))
        assertEquals("ASSET_UNAVAILABLE", (AuthPolicy.safeError(422, unavailable, uuid)!!["error"] as Map<*, *>)["code"])
        assertEquals("월별 금액 기록이 있어 자산·부채 구분을 바꿀 수 없습니다.", error["message"])
    }

    @Test fun metadataProjectionMatchesTheGeneratedMemberAndDeviceContractsOnly() {
        val member = mapOf("user_id" to uuid, "member_id" to uuid, "household_id" to uuid,
            "display_name" to "합성 구성원", "role" to "owner")
        assertEquals(member, AuthPolicy.metadataBody("GET", "/api/v1/me", 200, member))
        assertEquals(listOf(member), AuthPolicy.metadataBody("GET", "/api/v1/household/members", 200, listOf(member)))
        val device = mapOf("id" to uuid, "label" to "합성 Android", "platform" to "android",
            "status" to "active", "last_seen_at" to "2026-10-17T00:00:00Z", "version" to 1, "current" to true)
        val page = mapOf("items" to listOf(device), "next_cursor" to uuid)
        assertEquals(page, AuthPolicy.metadataBody("GET", "/api/v1/devices?limit=50&cursor=$uuid", 200, page))
        assertNull(AuthPolicy.metadataBody("DELETE", "/api/v1/devices/$uuid", 204, null))
    }

    @Test fun metadataProjectionRejectsAdditionalCredentialsUnknownFieldsAndWrongTypes() {
        val member = mapOf("user_id" to uuid, "member_id" to uuid, "household_id" to uuid,
            "display_name" to "합성 구성원", "role" to "owner")
        for (payload in listOf(
            member + ("refresh_token" to "synthetic"), member + ("unreviewed" to "synthetic"),
            member - "role", member + ("role" to "admin"), member + ("member_id" to "not-a-uuid"),
            member + ("display_name" to mapOf("token" to "synthetic")),
        )) {
            try { AuthPolicy.metadataBody("GET", "/api/v1/me", 200, payload); fail("Unsafe member response") }
            catch (failure: AuthFailure) { assertEquals(AuthCode.ACCESS_DENIED, failure.code) }
        }
        val device = mapOf("id" to uuid, "label" to "합성 Android", "platform" to "android",
            "status" to "active", "last_seen_at" to "2026-10-17T00:00:00Z", "version" to 1, "current" to true)
        for (row in listOf(device + ("version" to 1.5), device + ("current" to "true"),
            device + ("last_seen_at" to "not-a-timestamp"), device + ("secret" to "synthetic"))) {
            try {
                AuthPolicy.metadataBody("GET", "/api/v1/devices", 200, mapOf("items" to listOf(row), "next_cursor" to null))
                fail("Unsafe device response")
            } catch (failure: AuthFailure) { assertEquals(AuthCode.ACCESS_DENIED, failure.code) }
        }
    }

    @Test fun credentialFailuresSeparateRateLimitAndOutageFromWrongCredentials() {
        assertEquals(AuthCode.RATE_LIMITED, AuthPolicy.credentialFailure(429))
        for (status in listOf(500, 502, 503)) assertEquals(AuthCode.NETWORK_UNAVAILABLE, AuthPolicy.credentialFailure(status))
        for (status in listOf(400, 401, 403, 422)) assertEquals(AuthCode.AUTH_FAILED, AuthPolicy.credentialFailure(status))
    }
}
