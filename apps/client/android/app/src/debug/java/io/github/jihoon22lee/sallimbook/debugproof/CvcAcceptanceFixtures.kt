package io.github.jihoon22lee.sallimbook.debugproof

import android.content.Context
import io.github.jihoon22lee.sallimbook.auth.NativeVaultBinding
import io.github.jihoon22lee.sallimbook.auth.NativeVaultScope

/** Public synthetic values only; never accept identities or secrets from an Intent or bridge. */
internal object CvcAcceptanceFixtures {
    const val NAMESPACE = "debug-cvc-acceptance-v1"
    const val MARKER = "SALLIMBOOK DEBUG CVC ACCEPTANCE V1"
    fun binding(context: Context) = NativeVaultBinding(NativeVaultScope(
        context.packageName, "https://localhost", "10000000-0000-4000-8000-000000000001",
        "10000000-0000-4000-8000-000000000002", "10000000-0000-4000-8000-000000000003",
        "10000000-0000-4000-8000-000000000004", 1),
        "10000000-0000-4000-8000-000000000005", "10000000-0000-4000-8000-000000000006", 1)
    fun value(fourDigits: Boolean): ByteArray = if (fourDigits) byteArrayOf(52, 53, 54, 55) else byteArrayOf(49, 50, 51)
}
