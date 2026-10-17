package io.github.jihoon22lee.sallimbook.auth

internal enum class PasskeyOperation { LOGIN, REGISTER, INVITE, DEVICE_REVOKE, ACCOUNT_REVEAL }

/** Never placed in an Intent, saved state, bridge response, cache or log. */
internal class NativePasskeyCeremony(
    val operation: PasskeyOperation,
    val challengeId: String,
    val challenge: String,
    val options: CharArray,
    val binding: CharArray?,
    val targetId: String?,
    val ifMatch: String?,
    val intendedLogin: String?,
    val expiresAtMillis: Long,
    val configuration: PasskeyConfiguration,
) {
    private var consumed = false
    @Synchronized fun claim(nowMillis: Long): Boolean {
        if (consumed || nowMillis >= expiresAtMillis) { discard(); return false }
        consumed = true
        return true
    }
    @Synchronized fun discard() { options.fill('\u0000'); binding?.fill('\u0000'); consumed = true }
    override fun toString() = "NativePasskeyCeremony(redacted)"
}
