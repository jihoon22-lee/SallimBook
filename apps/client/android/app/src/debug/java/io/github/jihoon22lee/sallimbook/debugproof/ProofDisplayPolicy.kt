package io.github.jihoon22lee.sallimbook.debugproof

/**
 * Request/presentation lifetime only, NOT authentication or permission to use a key.
 * The Activity supplies actual lifecycle/window/lock state, keeps the returned CryptoObject,
 * and must perform real Cipher.doFinal before recording encryption/decryption completion.
 */
internal class ProofDisplayPolicy(private val elapsedRealtime: () -> Long) {
    companion object {
        const val MAX_DISPLAY_MILLIS = 30_000L
        const val MAX_FOCUS_SETTLE_MILLIS = 1_000L
    }

    private enum class Phase { IDLE, AUTHENTICATING, CANCELLING, READY_FOR_CRYPTO, USING_CRYPTO }
    private var phase = Phase.IDLE
    private var sequence = 0L
    private var activeRequest: Long? = null
    private var readySince: Long? = null
    private var displayStartedAt: Long? = null
    private var resumed = false
    private var focused = false
    private var unlocked = false

    /** Returns a request whose native cancellation must be dispatched, at most once. */
    fun updatePresentation(resumed: Boolean, focused: Boolean, unlocked: Boolean): Long? {
        this.resumed = resumed
        this.focused = focused
        this.unlocked = unlocked
        if (!resumed || !unlocked) return lock()
        // A system biometric prompt can take focus while authentication is still pending.
        // No value may remain visible or be newly decrypted while focus is absent.
        if (!focused) displayStartedAt = null
        return null
    }

    fun canAcceptAction(): Boolean = phase == Phase.IDLE && resumed && focused && unlocked

    fun beginRequest(): Long? {
        if (!canAcceptAction() || remainingDisplayMillis() > 0) return null
        sequence += 1
        activeRequest = sequence
        phase = Phase.AUTHENTICATING
        return sequence
    }

    fun ownsRequest(request: Long): Boolean = activeRequest == request
    fun isAuthenticating(request: Long): Boolean = ownsRequest(request) && phase == Phase.AUTHENTICATING
    fun isWaitingForFocus(request: Long): Boolean = ownsRequest(request) && phase == Phase.READY_FOR_CRYPTO

    /** Called only after matching the actual returned Cipher to this request's Cipher. */
    fun authenticationSucceeded(request: Long): Boolean {
        if (!ownsRequest(request)) return false
        if (phase == Phase.CANCELLING) {
            retireRequest()
            return false
        }
        if (phase != Phase.AUTHENTICATING) return false
        if (!resumed || !unlocked) {
            retireRequest()
            return false
        }
        phase = Phase.READY_FOR_CRYPTO
        readySince = elapsedRealtime()
        return true
    }

    /** The slot stays occupied after lock() until this terminal callback (or success) arrives. */
    fun authenticationEnded(request: Long): Boolean {
        if (!ownsRequest(request) || phase !in setOf(Phase.AUTHENTICATING, Phase.CANCELLING)) return false
        retireRequest()
        return true
    }

    fun remainingFocusWaitMillis(request: Long): Long {
        if (!isWaitingForFocus(request)) return 0
        val elapsed = elapsedRealtime() - (readySince ?: return 0)
        if (elapsed < 0 || elapsed >= MAX_FOCUS_SETTLE_MILLIS) {
            retireRequest()
            return 0
        }
        return MAX_FOCUS_SETTLE_MILLIS - elapsed
    }

    /** Presentation gate only; a successful result cannot substitute for Cipher.doFinal. */
    fun claimCipherForUse(request: Long): Boolean {
        if (remainingFocusWaitMillis(request) == 0L || !resumed || !focused || !unlocked) return false
        phase = Phase.USING_CRYPTO
        readySince = null
        return true
    }

    fun finishEncryption(request: Long): Boolean {
        if (!ownsRequest(request) || phase != Phase.USING_CRYPTO) return false
        val allowed = resumed && focused && unlocked
        retireRequest()
        return allowed
    }

    fun showAfterDecryption(request: Long): Boolean {
        if (!ownsRequest(request) || phase != Phase.USING_CRYPTO) return false
        val allowed = resumed && focused && unlocked
        retireRequest()
        if (allowed) displayStartedAt = elapsedRealtime()
        return allowed
    }

    fun remainingDisplayMillis(): Long {
        val startedAt = displayStartedAt ?: return 0
        val elapsed = elapsedRealtime() - startedAt
        if (!resumed || !focused || !unlocked || elapsed < 0 || elapsed >= MAX_DISPLAY_MILLIS) {
            displayStartedAt = null
            return 0
        }
        return MAX_DISPLAY_MILLIS - elapsed
    }

    /** Clears display immediately; it does not release an unfinished native prompt's slot. */
    fun lock(): Long? {
        displayStartedAt = null
        return when (phase) {
            Phase.AUTHENTICATING -> {
                phase = Phase.CANCELLING
                activeRequest
            }
            Phase.CANCELLING -> null
            else -> { retireRequest(); null }
        }
    }

    private fun retireRequest() {
        phase = Phase.IDLE
        activeRequest = null
        readySince = null
    }
}
