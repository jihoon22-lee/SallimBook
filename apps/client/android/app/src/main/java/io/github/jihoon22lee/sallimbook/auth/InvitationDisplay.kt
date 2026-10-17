package io.github.jihoon22lee.sallimbook.auth

/** Owns the supplied buffer. Losing eligibility permanently destroys this display session. */
internal class InvitationDisplay(
    private val token: CharArray,
    private val receivedAtMillis: Long,
    remainingServerValidityMillis: Long,
) {
    val durationMillis = remainingServerValidityMillis.coerceIn(0L, 30_000L)
    private var discarded = false

    fun reveal(nowMillis: Long, resumed: Boolean, focused: Boolean, unlocked: Boolean): String? {
        if (!resumed || !focused || !unlocked || nowMillis < receivedAtMillis ||
            nowMillis - receivedAtMillis >= durationMillis) discard()
        return if (discarded) null else String(token)
    }

    fun discard() { token.fill('\u0000'); discarded = true }
    override fun toString() = "InvitationDisplay(redacted)"
}
