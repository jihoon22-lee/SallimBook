package io.github.jihoon22lee.sallimbook.auth

import android.content.Context

/** Release has no activation state, owner, synthetic fixture or fault injection. */
internal object NativeVaultAcceptanceGate {
    @Suppress("UNUSED_PARAMETER")
    fun allows(context: Context, binding: NativeVaultBinding, namespace: String): Boolean = false
    @Suppress("UNUSED_PARAMETER")
    fun beforeCommit(context: Context, binding: NativeVaultBinding, namespace: String) = Unit
}
