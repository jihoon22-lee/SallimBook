package io.github.jihoon22lee.sallimbook.auth

/** Native callback value only. Neither the number nor its encrypted representation is bridged. */
internal class NativeAccountNumber(val number: CharArray) {
    fun discard() { number.fill('\u0000') }
    override fun toString() = "NativeAccountNumber(redacted)"
}

/** Reuses the audited monotonic 30-second/focus/pause/lock display policy. */
internal class AccountNumberDisplay(number: CharArray, receivedAtMillis: Long) {
    private val display = InvitationDisplay(number, receivedAtMillis, 30_000)
    fun reveal(nowMillis: Long, resumed: Boolean, focused: Boolean, unlocked: Boolean): String? =
        display.reveal(nowMillis, resumed, focused, unlocked)
    fun discard() = display.discard()
    override fun toString() = "AccountNumberDisplay(redacted)"
}
