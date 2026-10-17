package io.github.jihoon22lee.sallimbook.auth

/** Preparing a prompt never replaces an existing key or commits a new encrypted record. */
internal object NativeVaultKeyPreparation {
    fun <K : Any, C> encryption(existing: () -> K?, create: () -> K, initialize: (K) -> C): C =
        initialize(existing() ?: create())

    /** The adapter must positively identify permanent invalidation; transient errors propagate. */
    fun clearInvalidated(confirmed: Boolean, permanentlyInvalidated: () -> Boolean, remove: () -> Unit) {
        if (!confirmed || !permanentlyInvalidated()) throw NativeVaultFailure("KEY_INVALIDATED")
        remove()
    }
}
