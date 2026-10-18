package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class NativeOnboardingPolicyTest {
    private val setup = mapOf("display_name" to "합성 구성원", "password" to "synthetic password only", "device_label" to "Android")
    private val connect = setup + ("code" to "01234567")
    private val tokens = mapOf("access_token" to "a".repeat(32), "refresh_token" to "r".repeat(32),
        "token_type" to "Bearer", "expires_in" to 600, "refresh_expires_at" to "2026-11-18T00:00:00Z")
    private fun rejected(action: () -> Unit) {
        try { action(); fail("Malformed native onboarding response accepted") } catch (_: AuthFailure) { }
    }
    private fun allowed(method: String, path: String, body: Any? = null, authenticated: Boolean = false,
        ifMatch: String? = null, stepUp: String? = null, idempotency: String? = null) =
        NativeOnboardingPolicy.httpAllowed(method, path, body, authenticated, ifMatch, stepUp, idempotency)

    @Test fun displayNamesCountUnicodeScalarsAndRequireTrimmedNonemptyInput() {
        assertTrue(NativeOnboardingPolicy.name("합성 이름")); assertTrue(NativeOnboardingPolicy.name("😀".repeat(80)))
        for (value in listOf("", " ", " name", "name ", "😀".repeat(81), "x\ud800", "\udc00x"))
            assertFalse(NativeOnboardingPolicy.name(value))
    }
    @Test fun passwordsUseServerScalarLengthWithoutTrimmingOrNormalization() {
        for (value in listOf("😀".repeat(15), "😀".repeat(128), " ".repeat(15), "e\u0301".repeat(8)))
            assertTrue(NativeOnboardingPolicy.password(value.toCharArray()))
        for (value in listOf("😀".repeat(14), "x".repeat(129), " ".repeat(14), "x".repeat(15) + "\ud800"))
            assertFalse(NativeOnboardingPolicy.password(value.toCharArray()))
    }
    @Test fun connectionCodeIsExactlyEightAsciiDigitsIncludingLeadingZero() {
        assertTrue(NativeOnboardingPolicy.code("01234567".toCharArray()))
        for (value in listOf("1234567", "123456789", "1234-5678", "1234 5678", "１２３４５６７８", "1234567\n"))
            assertFalse(NativeOnboardingPolicy.code(value.toCharArray()))
    }
    @Test fun fixedTransportShapesDoNotAllowCredentialsQueriesOverridesOrExtraJson() {
        assertTrue(allowed("GET", NativeOnboardingPolicy.STATUS_PATH))
        assertTrue(allowed("POST", NativeOnboardingPolicy.SETUP_PATH, setup))
        assertTrue(allowed("POST", NativeOnboardingPolicy.CONNECT_PATH, connect))
        assertTrue(allowed("POST", NativeOnboardingPolicy.CODE_PATH, authenticated = true))
        assertFalse(AuthPolicy.requestAllowed("GET", NativeOnboardingPolicy.STATUS_PATH, null))
        for (path in listOf(NativeOnboardingPolicy.SETUP_PATH, NativeOnboardingPolicy.CONNECT_PATH, NativeOnboardingPolicy.CODE_PATH))
            assertFalse(AuthPolicy.requestAllowed("POST", path, null))
        assertFalse(allowed("GET", NativeOnboardingPolicy.STATUS_PATH, authenticated = true))
        assertFalse(allowed("POST", NativeOnboardingPolicy.SETUP_PATH, setup, true))
        assertFalse(allowed("POST", NativeOnboardingPolicy.CODE_PATH))
        assertFalse(allowed("POST", NativeOnboardingPolicy.CODE_PATH, emptyMap<String, Any>(), true))
        for (path in listOf(NativeOnboardingPolicy.STATUS_PATH + "?available=true", "https://synthetic.invalid/api/v1/household/setup",
            "/api/v1/household/%73etup", "/api/v1/household/setup/", "/api/v1/me")) assertFalse(allowed("GET", path))
        for (method in listOf("PUT", "DELETE", "PATCH", "get")) assertFalse(allowed(method, NativeOnboardingPolicy.STATUS_PATH))
        assertFalse(allowed("POST", NativeOnboardingPolicy.SETUP_PATH, setup, ifMatch = "\"1\""))
        assertFalse(allowed("POST", NativeOnboardingPolicy.SETUP_PATH, setup, stepUp = "synthetic"))
        assertFalse(allowed("POST", NativeOnboardingPolicy.SETUP_PATH, setup, idempotency = "synthetic"))
    }
    @Test fun enrollmentRejectsUnexpectedIdentityAndSecretFieldsOrMalformedValues() {
        for (key in listOf("login_name", "role", "household_id", "access_token", "code"))
            assertFalse(allowed("POST", NativeOnboardingPolicy.SETUP_PATH, setup + (key to "synthetic")))
        for (body in listOf(setup - "display_name", setup + ("password" to true), setup + ("device_label" to ""),
            setup + ("display_name" to " padded "), connect + ("code" to 12345678), connect + ("code" to "1234-5678")))
            assertFalse(allowed("POST", NativeOnboardingPolicy.CONNECT_PATH, body))
    }
    @Test fun publicSetupProjectionCannotReturnCredentialsOrNonBooleanAvailability() {
        assertEquals(mapOf("available" to true), NativeOnboardingPolicy.setupStatus(200, mapOf("available" to true)))
        assertEquals(mapOf("available" to false), NativeOnboardingPolicy.setupStatus(200, mapOf("available" to false)))
        for (value in listOf(null, mapOf("available" to 1), mapOf("available" to true, "token" to "synthetic")))
            rejected { NativeOnboardingPolicy.setupStatus(200, value) }
        rejected { NativeOnboardingPolicy.setupStatus(201, mapOf("available" to true)) }
    }
    @Test fun tokenResponseIsExactAndBoundedBeforeAnyCredentialInstallation() {
        assertEquals("a".repeat(32), NativeOnboardingPolicy.enrollmentAccess(201, tokens))
        for (body in listOf(tokens + ("member" to emptyMap<String, Any>()), tokens - "refresh_token",
            tokens + ("expires_in" to 600L), tokens + ("expires_in" to 0), tokens + ("expires_in" to 601),
            tokens + ("token_type" to "Basic"), tokens + ("access_token" to "short"), tokens + ("refresh_expires_at" to "not-a-date")))
            rejected { NativeOnboardingPolicy.enrollmentAccess(201, body) }
        rejected { NativeOnboardingPolicy.enrollmentAccess(200, tokens) }
    }
    @Test fun connectionResponseStaysRedactedAndOwnedBufferCanBeDestroyed() {
        val response = mapOf("code" to "01234567", "expires_at" to "2026-10-18T00:15:00Z")
        val result = NativeOnboardingPolicy.connectionCode(201, response)
        assertArrayEquals("01234567".toCharArray(), result.code); assertFalse(result.toString().contains("01234567"))
        result.discard(); assertTrue(result.code.all { it == '\u0000' })
        for (body in listOf(response + ("token" to "synthetic"), response + ("code" to 12345678),
            response + ("code" to "1234-5678"), response + ("expires_at" to "tomorrow")))
            rejected { NativeOnboardingPolicy.connectionCode(201, body) }
    }
    @Test fun onlyRecognizedStatusMatchedErrorsAreReturnedAndRawMessagesAreDiscarded() {
        val expected = mapOf(403 to listOf("SETUP_UNAVAILABLE", "REAUTHENTICATION_REQUIRED"),
            409 to listOf("SETUP_COMPLETE", "REGISTRATION_CONFLICT", "HOUSEHOLD_FULL", "LOGIN_UNAVAILABLE"),
            400 to listOf("INVALID_CONNECTION_CODE"), 429 to listOf("RATE_LIMITED"), 422 to listOf("VALIDATION_ERROR"))
        for ((status, codes) in expected) for (code in codes) {
            val error = mapOf("error" to mapOf("code" to code, "message" to "synthetic private detail", "token" to "synthetic"))
            assertEquals(AuthCode.valueOf(code), NativeOnboardingPolicy.error(status, error))
            assertEquals(AuthCode.AUTH_UNAVAILABLE, NativeOnboardingPolicy.error(500, error))
        }
        assertEquals(AuthCode.ACCESS_DENIED, NativeOnboardingPolicy.error(403, mapOf("error" to mapOf("code" to "UNRECOGNIZED"))))
    }
}
