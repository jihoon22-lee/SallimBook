package io.github.jihoon22lee.sallimbook.auth

/** Owner-authorized release option; availability does not claim physical-device acceptance.
 * Synthetic stores still require their debug Activity owner. No bridge/server setting enables them.
 */
internal object NativeVaultCvcPolicy {
    fun available(namespace: String) = namespace == "vault.v1"

    /** Explicit per-save consent; callers own and wipe the returned native-only bytes. */
    fun input(confirmed: Boolean, chars: CharArray): ByteArray = try {
        if (!confirmed) throw NativeVaultFailure("CVC_CONSENT_REQUIRED")
        if (chars.size !in 3..4 || chars.any { it !in '0'..'9' }) throw NativeVaultFailure("INVALID_FORMAT")
        ByteArray(chars.size) { chars[it].code.toByte() }
    } finally { chars.fill('\u0000') }
}
