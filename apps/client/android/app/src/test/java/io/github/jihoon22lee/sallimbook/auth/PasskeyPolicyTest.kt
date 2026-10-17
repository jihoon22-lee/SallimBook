package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test
import java.time.Instant
import java.util.Base64

class PasskeyPolicyTest {
    @Test fun rejectedProofPreservesSessionButExpiredSessionClearsIt() {
        for (code in listOf("PASSKEY_VERIFICATION_FAILED", "UNAUTHENTICATED", "SESSION_EXPIRED", null)) {
            var clearCount = 0
            val expected = if (code == "PASSKEY_VERIFICATION_FAILED") AuthCode.PASSKEY_FAILED else AuthCode.SESSION_EXPIRED
            try {
                PasskeyPolicy.reject(401, mapOf("error" to mapOf("code" to code)), false) { clearCount++ }
            } catch (failure: AuthFailure) {
                assertEquals(expected, failure.code)
            }
            assertEquals(if (expected == AuthCode.SESSION_EXPIRED) 1 else 0, clearCount)
        }
    }

    @Test fun loginProofFailureNeverClearsAnotherSessionAndKnownErrorsRemainSpecific() {
        for ((status, code, expected) in listOf(
            Triple(401, "PASSKEY_VERIFICATION_FAILED", AuthCode.PASSKEY_FAILED),
            Triple(401, "UNAUTHENTICATED", AuthCode.PASSKEY_FAILED),
            Triple(403, "REAUTHENTICATION_REQUIRED", AuthCode.REAUTHENTICATION_REQUIRED),
            Triple(409, "PASSKEY_REQUIRED", AuthCode.PASSKEY_REQUIRED),
            Triple(503, "PASSKEYS_DISABLED", AuthCode.PASSKEYS_DISABLED),
        )) {
            try {
                PasskeyPolicy.reject(status, mapOf("error" to mapOf("code" to code)), true) {
                    fail("A proof failure cleared the account session")
                }
            } catch (failure: AuthFailure) { assertEquals(expected, failure.code) }
        }
    }

    private val id = "00000000-0000-4000-8000-000000000001"
    private val other = "00000000-0000-4000-8000-000000000002"
    private val challenge = Base64.getUrlEncoder().withoutPadding().encodeToString(ByteArray(32) { 7 })
    private val origin = "android:apk-key-hash:" + Base64.getUrlEncoder().withoutPadding().encodeToString(ByteArray(32) { 8 })
    private val now = Instant.parse("2026-01-01T00:00:00Z")
    private fun assertionOptions() = mapOf<String, Any?>("challenge" to challenge, "rpId" to "synthetic.invalid",
        "timeout" to 300_000, "userVerification" to "required", "allowCredentials" to emptyList<Any>())
    private fun registrationOptions() = mapOf<String, Any?>("challenge" to challenge,
        "rp" to mapOf("id" to "synthetic.invalid", "name" to "SallimBook"),
        "user" to mapOf("id" to "AQ", "name" to "synthetic", "displayName" to "합성"),
        "timeout" to 300_000, "attestation" to "none", "excludeCredentials" to emptyList<Any>(),
        "pubKeyCredParams" to listOf(mapOf("type" to "public-key", "alg" to -7)),
        "authenticatorSelection" to mapOf("residentKey" to "required", "requireResidentKey" to true, "userVerification" to "required"))
    private fun credential() = mapOf<String, Any?>("id" to "AQ", "rawId" to "AQ", "type" to "public-key",
        "response" to mapOf("clientDataJSON" to "AQ", "authenticatorData" to "AQ", "signature" to "AQ", "userHandle" to null),
        "clientExtensionResults" to emptyMap<String, Any>())
    private fun fails(action: () -> Unit) {
        try { action(); fail("Unsafe passkey input was accepted") } catch (failure: AuthFailure) {
            assertEquals(AuthCode.PASSKEY_FAILED, failure.code)
            assertNull(failure.message)
        }
    }

    @Test fun configurationRequiresFixedHttpsRelatedRpAndMatchingActualSigningCertificate() {
        val cert = "ab".repeat(32)
        assertTrue(PasskeyPolicy.configuration("https://synthetic.invalid", "synthetic.invalid", cert, cert))
        assertTrue(PasskeyPolicy.configuration("https://api.synthetic.invalid:8443", "synthetic.invalid", "AB:".repeat(31)+"AB", cert))
        for ((api, rp, configured, actual) in listOf(
            listOf("", "synthetic.invalid", cert, cert), listOf("http://synthetic.invalid", "synthetic.invalid", cert, cert),
            listOf("https://synthetic.invalid", "", cert, cert), listOf("https://synthetic.invalid", "localhost", cert, cert),
            listOf("https://synthetic.invalid", "other.invalid", cert, cert), listOf("https://synthetic.invalid", "synthetic.invalid", "", cert),
            listOf("https://synthetic.invalid", "synthetic.invalid", cert, "cd".repeat(32)),
            listOf("https://synthetic.invalid", "Synthetic.invalid", cert, cert),
        )) assertFalse(PasskeyPolicy.configuration(api, rp, configured, actual))
    }

    @Test fun optionsRequireExactRpRequiredVerificationAndNoPrfOrArbitraryExtensions() {
        assertEquals(assertionOptions(), PasskeyPolicy.options(assertionOptions(), false, "synthetic.invalid"))
        assertEquals(registrationOptions(), PasskeyPolicy.options(registrationOptions(), true, "synthetic.invalid"))
        for (options in listOf(assertionOptions()+mapOf("rpId" to "other.invalid"),
            assertionOptions()+mapOf("userVerification" to "preferred"), assertionOptions()+mapOf("timeout" to 300_001),
            assertionOptions()+mapOf("extensions" to mapOf("prf" to emptyMap<String, Any>())),
            assertionOptions()+mapOf("challenge" to "not-a-valid-challenge"))) {
            fails { PasskeyPolicy.options(options, false, "synthetic.invalid") }
        }
        fails { PasskeyPolicy.options(registrationOptions()+mapOf("attestation" to "direct"), true, "synthetic.invalid") }
        fails { PasskeyPolicy.options(registrationOptions()+mapOf("authenticatorSelection" to mapOf("userVerification" to "preferred")), true, "synthetic.invalid") }
    }

    @Test fun nativeResponseOnlyAcceptsPublicKeyShapeWithoutSecretExtensions() {
        assertEquals(credential(), PasskeyPolicy.credential(credential(), false))
        for (response in listOf(credential()+mapOf("type" to "password"), credential()+mapOf("rawId" to "Ag"),
            credential()+mapOf("password" to "synthetic"),
            credential()+mapOf("clientExtensionResults" to mapOf("prf" to mapOf("results" to "synthetic"))),
            credential()+mapOf("response" to mapOf("clientDataJSON" to "AQ", "signature" to "AQ")))) {
            fails { PasskeyPolicy.credential(response, false) }
        }
        fails { PasskeyPolicy.encoded("AQ==") }
        fails { PasskeyPolicy.encoded("AR") }
    }

    @Test fun clientDataMustMatchCeremonyChallengeAndroidOriginAndOperation() {
        val data = mapOf("type" to "webauthn.get", "challenge" to challenge, "origin" to origin, "crossOrigin" to false)
        assertTrue(PasskeyPolicy.clientData(data, false, challenge, origin))
        assertFalse(PasskeyPolicy.clientData(data, true, challenge, origin))
        assertFalse(PasskeyPolicy.clientData(data, false, "another", origin))
        assertFalse(PasskeyPolicy.clientData(data+mapOf("origin" to "https://synthetic.invalid"), false, challenge, origin))
        assertFalse(PasskeyPolicy.clientData(data+mapOf("crossOrigin" to true), false, challenge, origin))
        assertTrue(PasskeyPolicy.clientData(data+mapOf("type" to "webauthn.create"), true, challenge, origin))
    }

    @Test fun grantsAreBoundToSupportedPurposeTargetAndExpiryAndNeverGenericHeaders() {
        val grant = mapOf("grant_token" to challenge, "purpose" to "device.revoke", "target_id" to id, "expires_at" to "2026-01-01T00:02:00Z")
        assertEquals(challenge, PasskeyPolicy.grant(grant, "device.revoke", id, now))
        fails { PasskeyPolicy.grant(grant, "household.invite", id, now) }
        fails { PasskeyPolicy.grant(grant, "device.revoke", other, now) }
        fails { PasskeyPolicy.grant(grant, "device.revoke", id, now.plusSeconds(120)) }
        fails { PasskeyPolicy.grant(grant+mapOf("key" to "synthetic"), "device.revoke", id, now) }
        fails { PasskeyPolicy.grant(grant+mapOf("purpose" to "vault.membership"), "vault.membership", id, now) }
        assertTrue(PasskeyPolicy.stepUpHeaderAllowed("DELETE", "/api/v1/devices/$id", "\"1\"", challenge))
        assertTrue(PasskeyPolicy.stepUpHeaderAllowed("POST", "/api/v1/household/invitations", null, challenge))
        for (path in listOf("/api/v1/me", "/api/v1/auth/passkeys/$id", "/api/v1/auth/step-up/verify", "/api/v1/devices/$id?x=1")) {
            assertFalse(PasskeyPolicy.stepUpHeaderAllowed("DELETE", path, "\"1\"", challenge))
        }
        assertFalse(PasskeyPolicy.stepUpHeaderAllowed("DELETE", "/api/v1/devices/$id", null, challenge))
    }

    @Test fun passkeyListingUsesSafeMetadataWhileCeremoniesAndRevokeAreNotGenericBridgeRequests() {
        assertTrue(AuthPolicy.requestAllowed("GET", "/api/v1/auth/passkeys?limit=200&cursor=$id", null))
        assertFalse(AuthPolicy.requestAllowed("DELETE", "/api/v1/auth/passkeys/$id", "\"1\""))
        for (path in listOf("/api/v1/auth/native/passkeys/options", "/api/v1/auth/native/passkeys/verify",
            "/api/v1/auth/passkeys/register/options", "/api/v1/auth/passkeys/register/verify", "/api/v1/auth/step-up/options", "/api/v1/auth/step-up/verify")) {
            assertFalse(AuthPolicy.requestAllowed("POST", path, null))
        }
        val row = mapOf("id" to id, "label" to "합성 패스키", "created_at" to "2026-01-01T00:00:00Z", "last_used_at" to null,
            "backed_up" to true, "device_type" to "multi_device", "version" to 1)
        val list = mapOf("items" to listOf(row), "next_cursor" to null)
        assertEquals(list, AuthPolicy.metadataBody("GET", "/api/v1/auth/passkeys", 200, list))
        for (field in listOf("challenge", "device_binding", "assertion", "attestationObject", "grant_token", "clientDataJSON", "signature")) {
            assertFalse(AuthPolicy.safeJson(mapOf(field to "synthetic")))
            try { AuthPolicy.passkey(row+mapOf(field to "synthetic")); fail("Secret-bearing metadata accepted") }
            catch (failure: AuthFailure) { assertEquals(AuthCode.ACCESS_DENIED, failure.code) }
        }
    }
}
