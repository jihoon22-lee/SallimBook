package io.github.jihoon22lee.sallimbook.auth

import java.net.URI
import java.time.Duration
import java.time.Instant
import java.time.OffsetDateTime
import java.util.Base64

/** Validates the native boundary; the server remains responsible for WebAuthn verification. */
internal object PasskeyPolicy {
    val uuid = Regex("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
    private val version = Regex("\"[1-9][0-9]{0,18}\"")
    private val domainLabel = Regex("[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
    private val base64Url = Regex("[A-Za-z0-9_-]+")

    fun reject(status: Int, body: Any?, unauthenticatedLogin: Boolean, clearSession: () -> Unit): Nothing {
        val code = ((body as? Map<*, *>)?.get("error") as? Map<*, *>)?.get("code")
        if (status == 401) {
            // A consumed/rejected ceremony does not revoke the existing account session.
            if (unauthenticatedLogin || code == "PASSKEY_VERIFICATION_FAILED") {
                throw AuthFailure(AuthCode.PASSKEY_FAILED)
            }
            clearSession()
            throw AuthFailure(AuthCode.SESSION_EXPIRED)
        }
        throw AuthFailure(when (code) {
            "PASSKEYS_DISABLED", "PASSKEY_CONFIGURATION_INVALID" -> AuthCode.PASSKEYS_DISABLED
            "PASSKEY_REQUIRED" -> AuthCode.PASSKEY_REQUIRED
            "REAUTHENTICATION_REQUIRED" -> AuthCode.REAUTHENTICATION_REQUIRED
            else -> AuthCode.PASSKEY_FAILED
        })
    }

    fun configuration(apiOrigin: String, rpId: String, configuredCertificate: String, actualCertificate: String): Boolean {
        if (AuthPolicy.apiOrigin(apiOrigin) == null || rpId.length !in 3..253 ||
            rpId.split('.').size < 2 || rpId.split('.').any { !domainLabel.matches(it) }) return false
        val host = URI(apiOrigin).host
        val configured = configuredCertificate.replace(":", "").lowercase()
        return (host == rpId || host.endsWith(".$rpId")) && Regex("[0-9a-f]{64}").matches(configured) &&
            configured == actualCertificate.lowercase()
    }

    fun target(id: String?, ifMatch: String?): Boolean = id != null && uuid.matches(id) &&
        ifMatch != null && version.matches(ifMatch)

    fun revokePath(path: String): Boolean = path.startsWith("/api/v1/auth/passkeys/") &&
        uuid.matches(path.removePrefix("/api/v1/auth/passkeys/"))

    fun stepUpHeaderAllowed(method: String, path: String, ifMatch: String?, token: String): Boolean =
        Regex("[A-Za-z0-9_-]{32,128}").matches(token) &&
            (method == "POST" && path == "/api/v1/household/invitations" && ifMatch == null ||
                method == "POST" && FinancePolicy.numberPath(path, true) && ifMatch == null ||
                method == "DELETE" && AuthPolicy.requestAllowed(method, path, ifMatch))

    fun grant(value: Any?, purpose: String, targetId: String?, now: Instant): String {
        val result = value as? Map<*, *> ?: throw AuthFailure(AuthCode.PASSKEY_FAILED)
        if (purpose !in setOf("household.invite", "device.revoke", "account.reveal") || targetId == null || !uuid.matches(targetId) ||
            result.keys != setOf("grant_token", "purpose", "target_id", "expires_at") ||
            result["purpose"] != purpose || result["target_id"] != targetId ||
            remaining(result["expires_at"] as? String ?: "", now, 120_000) == 0L) {
            throw AuthFailure(AuthCode.PASSKEY_FAILED)
        }
        return encoded(result["grant_token"], 32, 128)
    }

    fun remaining(expiresAt: String, now: Instant, maximumMillis: Long): Long = try {
        val expiry = OffsetDateTime.parse(expiresAt).toInstant()
        when {
            expiry <= now -> 0L
            expiry >= now.plusMillis(maximumMillis) -> maximumMillis
            else -> Duration.between(now, expiry).toMillis()
        }
    } catch (_: Exception) { 0L }

    fun encoded(value: Any?, minimum: Int = 1, maximum: Int = 1364): String {
        val text = value as? String ?: throw AuthFailure(AuthCode.PASSKEY_FAILED)
        if (text.length !in minimum..maximum || !base64Url.matches(text)) throw AuthFailure(AuthCode.PASSKEY_FAILED)
        try {
            val bytes = Base64.getUrlDecoder().decode(text)
            if (Base64.getUrlEncoder().withoutPadding().encodeToString(bytes) != text) throw AuthFailure(AuthCode.PASSKEY_FAILED)
        } catch (_: Exception) { throw AuthFailure(AuthCode.PASSKEY_FAILED) }
        return text
    }

    fun options(value: Any?, registration: Boolean, rpId: String): Map<*, *> {
        val options = value as? Map<*, *> ?: throw AuthFailure(AuthCode.PASSKEY_FAILED)
        val permitted = if (registration) setOf("rp", "user", "challenge", "pubKeyCredParams", "timeout",
            "excludeCredentials", "authenticatorSelection", "attestation")
        else setOf("challenge", "timeout", "rpId", "allowCredentials", "userVerification")
        if (!permitted.containsAll(options.keys)) throw AuthFailure(AuthCode.PASSKEY_FAILED)
        encoded(options["challenge"], 43, 43)
        val timeout = options["timeout"]
        if (!(timeout is Int && timeout in 1..300_000 || timeout is Long && timeout in 1..300_000L)) {
            throw AuthFailure(AuthCode.PASSKEY_FAILED)
        }
        if (registration) {
            val rp = options["rp"] as? Map<*, *> ?: throw AuthFailure(AuthCode.PASSKEY_FAILED)
            val user = options["user"] as? Map<*, *> ?: throw AuthFailure(AuthCode.PASSKEY_FAILED)
            val selection = options["authenticatorSelection"] as? Map<*, *> ?: throw AuthFailure(AuthCode.PASSKEY_FAILED)
            if (rp["id"] != rpId || rp["name"] != "SallimBook" || options["attestation"] != "none" ||
                selection["userVerification"] != "required" || selection["residentKey"] != "required" ||
                selection["requireResidentKey"] != true || user["name"] !is String || user["displayName"] !is String) {
                throw AuthFailure(AuthCode.PASSKEY_FAILED)
            }
            encoded(user["id"], 1, 86)
            val algorithms = options["pubKeyCredParams"] as? List<*> ?: throw AuthFailure(AuthCode.PASSKEY_FAILED)
            if (algorithms.isEmpty() || algorithms.size > 20 || algorithms.any {
                    val row = it as? Map<*, *>
                    row?.get("type") != "public-key" || row?.get("alg") !is Int
                }) throw AuthFailure(AuthCode.PASSKEY_FAILED)
        } else if (options["rpId"] != rpId || options["userVerification"] != "required") {
            throw AuthFailure(AuthCode.PASSKEY_FAILED)
        }
        val descriptors = options[if (registration) "excludeCredentials" else "allowCredentials"] as? List<*>
            ?: throw AuthFailure(AuthCode.PASSKEY_FAILED)
        if (descriptors.size > 200) throw AuthFailure(AuthCode.PASSKEY_FAILED)
        descriptors.forEach {
            val row = it as? Map<*, *> ?: throw AuthFailure(AuthCode.PASSKEY_FAILED)
            if (row["type"] != "public-key") throw AuthFailure(AuthCode.PASSKEY_FAILED)
            encoded(row["id"])
        }
        return options
    }

    fun credential(value: Any?, registration: Boolean): Map<*, *> {
        val result = value as? Map<*, *> ?: throw AuthFailure(AuthCode.PASSKEY_FAILED)
        if (!setOf("id", "rawId", "type", "response", "authenticatorAttachment", "clientExtensionResults")
                .containsAll(result.keys) || result["type"] != "public-key" || result["id"] != result["rawId"]) {
            throw AuthFailure(AuthCode.PASSKEY_FAILED)
        }
        encoded(result["id"])
        val response = result["response"] as? Map<*, *> ?: throw AuthFailure(AuthCode.PASSKEY_FAILED)
        val permitted = if (registration) setOf("clientDataJSON", "attestationObject", "transports", "authenticatorData", "publicKey", "publicKeyAlgorithm")
            else setOf("clientDataJSON", "authenticatorData", "signature", "userHandle")
        if (!permitted.containsAll(response.keys)) throw AuthFailure(AuthCode.PASSKEY_FAILED)
        encoded(response["clientDataJSON"], 1, 8192)
        if (registration) encoded(response["attestationObject"], 1, 65536)
        else {
            encoded(response["authenticatorData"], 1, 4096)
            encoded(response["signature"], 1, 2048)
            response["userHandle"]?.let { encoded(it, 1, 128) }
        }
        val extensions = result["clientExtensionResults"]
        if (extensions != null && (extensions !is Map<*, *> || !setOf("credProps").containsAll(extensions.keys))) {
            throw AuthFailure(AuthCode.PASSKEY_FAILED)
        }
        return result
    }

    fun clientData(value: Any?, registration: Boolean, challenge: String, androidOrigin: String): Boolean {
        val data = value as? Map<*, *> ?: return false
        return data["type"] == (if (registration) "webauthn.create" else "webauthn.get") &&
            data["challenge"] == challenge && data["origin"] == androidOrigin &&
            (data["crossOrigin"] == null || data["crossOrigin"] == false)
    }
}

/** One ceremony, one verification, never a reusable authentication grant. */
internal class PasskeyPresentationPolicy(private val clock: () -> Long, private val expiresAt: Long) {
    private enum class Phase { FETCHED, PROVIDER, WAITING, VERIFYING, CANCELLED }
    private var phase = Phase.FETCHED
    private var returnedAt = 0L
    fun awaitingProvider(): Boolean = phase == Phase.PROVIDER
    fun waitingForPresentation(): Boolean = phase == Phase.WAITING
    fun mayWaitForPresentation(): Boolean = phase in setOf(Phase.PROVIDER, Phase.WAITING)
    fun startProvider(): Boolean {
        if (phase != Phase.FETCHED || clock() >= expiresAt) { cancel(); return false }
        phase = Phase.PROVIDER
        return true
    }
    fun providerReturned(): Boolean {
        if (phase != Phase.PROVIDER || clock() >= expiresAt) { cancel(); return false }
        phase = Phase.WAITING
        returnedAt = clock()
        return true
    }
    fun canWait(): Boolean = phase == Phase.WAITING && clock() >= returnedAt &&
        clock() - returnedAt < 1_000L && clock() < expiresAt
    fun claimVerification(resumed: Boolean, focused: Boolean, unlocked: Boolean): Boolean {
        if (!canWait()) { cancel(); return false }
        if (!resumed || !focused || !unlocked) return false
        phase = Phase.VERIFYING
        return true
    }
    fun cancel() { phase = Phase.CANCELLED }
}
