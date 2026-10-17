package io.github.jihoon22lee.sallimbook.auth

/** Native callback value only. Neither the number nor its encrypted representation is bridged. */
internal class NativePolicyNumber(val number: CharArray) {
    fun discard() { number.fill('\u0000') }
    override fun toString() = "NativePolicyNumber(redacted)"
}

