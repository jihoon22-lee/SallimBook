package io.github.jihoon22lee.sallimbook.auth

/** Presentation/cancellation bookkeeping, never authentication or authorization to decrypt.
 * A native caller must match the actual CryptoObject Cipher and finish doFinal before completion.
 * No key, password, token or plaintext is held here. New screens always start locked.
 */
internal class NativeVaultLifetime(private val now: () -> Long) {
    companion object {
        const val DISPLAY_MILLIS = 30_000L
        const val REQUEST_MILLIS = 60_000L
        const val FOCUS_MILLIS = 1_000L
    }
    private enum class Phase { IDLE, WORK, PROMPT, CANCELLING, READY, CRYPTO }
    private var phase = Phase.IDLE
    private var sequence = 0L
    private var request: Long? = null
    private var cancellation: Long? = null
    private var began = 0L
    private var focusBegan = 0L
    private var displayed: Long? = null
    private var resumed = false
    private var focused = false
    private var deviceUnlocked = false
    private var appUnlocked = false
    private fun presented() = resumed && focused && deviceUnlocked && appUnlocked
    private fun live(start: Long, duration: Long): Boolean { val elapsed = now() - start; return elapsed in 0 until duration }

    /** Returns the prompt to cancel once. WORK results become stale immediately. */
    fun presentation(resumed: Boolean, focused: Boolean, deviceUnlocked: Boolean, appUnlocked: Boolean): Long? {
        this.resumed = resumed; this.focused = focused
        this.deviceUnlocked = deviceUnlocked; this.appUnlocked = appUnlocked
        if (!resumed || !deviceUnlocked || !appUnlocked) return lock()
        if (!focused) {
            displayed = null
            if (phase == Phase.WORK || phase == Phase.CRYPTO) return lock()
        }
        return expire()
    }
    fun canBegin(): Boolean { checkExpiry(); return phase == Phase.IDLE && presented() }
    fun beginWork(): Long? = begin(Phase.WORK)
    fun beginPrompt(): Long? = begin(Phase.PROMPT)
    private fun begin(next: Phase): Long? {
        if (!canBegin()) return null
        displayed = null
        sequence += 1; request = sequence; began = now(); phase = next
        return request
    }
    /** Worker result gate only. Successful PBKDF2 alone is not evidence of the correct password. */
    fun workActive(id: Long): Boolean { checkExpiry(); return request == id && phase == Phase.WORK && presented() }
    fun finishWork(id: Long, displayAfterVerifiedDecryption: Boolean): Boolean {
        if (!workActive(id)) return false
        retire()
        if (displayAfterVerifiedDecryption) displayed = now()
        return true
    }
    /** Call only for the same Cipher returned by this request's CryptoObject, on its terminal callback. */
    fun promptSucceeded(id: Long): Boolean {
        checkExpiry()
        if (request != id) return false
        if (phase == Phase.CANCELLING) { retire(); return false }
        if (phase != Phase.PROMPT || !resumed || !deviceUnlocked || !appUnlocked) return false
        phase = Phase.READY; focusBegan = now()
        return true
    }
    fun promptEnded(id: Long): Boolean {
        if (request != id || phase !in setOf(Phase.PROMPT, Phase.CANCELLING)) return false
        retire(); return true
    }
    fun focusRemaining(id: Long): Long {
        checkExpiry()
        if (request != id || phase != Phase.READY) return 0
        val elapsed = now() - focusBegan
        if (elapsed !in 0 until FOCUS_MILLIS) { invalidate(); return 0 }
        return FOCUS_MILLIS - elapsed
    }
    fun claimCipher(id: Long): Boolean {
        checkExpiry()
        if (request != id || phase != Phase.READY || !presented() || !live(focusBegan, FOCUS_MILLIS)) { checkExpiry(); return false }
        phase = Phase.CRYPTO; return true
    }
    /** Call after actual authenticated doFinal and payload/key-check validation, never on prompt success. */
    fun finishCipher(id: Long, displayAfterVerifiedDecryption: Boolean): Boolean {
        checkExpiry()
        if (request != id || phase != Phase.CRYPTO || !presented()) return false
        retire()
        if (displayAfterVerifiedDecryption) displayed = now()
        return true
    }
    fun displayRemaining(): Long {
        val started = displayed ?: return 0
        val elapsed = now() - started
        if (!presented() || elapsed !in 0 until DISPLAY_MILLIS) { displayed = null; return 0 }
        return DISPLAY_MILLIS - elapsed
    }
    /** Drain the cancellation even when an earlier predicate detected timeout. */
    fun expire(): Long? { checkExpiry(); return takeCancellation() }
    private fun checkExpiry() {
        if (phase == Phase.READY && !live(focusBegan, FOCUS_MILLIS)) invalidate()
        if (phase !in setOf(Phase.IDLE, Phase.CANCELLING) && !live(began, REQUEST_MILLIS)) invalidate()
    }
    fun lock(): Long? { invalidate(); return takeCancellation() }
    private fun invalidate() {
        displayed = null
        when (phase) {
            Phase.PROMPT -> { phase = Phase.CANCELLING; cancellation = request }
            Phase.CANCELLING -> Unit
            else -> retire()
        }
    }
    private fun takeCancellation(): Long? = cancellation.also { cancellation = null }
    private fun retire() { phase = Phase.IDLE; request = null; cancellation = null; began = 0; focusBegan = 0 }
}
