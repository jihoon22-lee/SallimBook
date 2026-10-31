package io.github.jihoon22lee.sallimbook.auth

/** Never returned through AuthOutcome, Intents, logs or the bridge. */
internal class NativeStoredCard(val pan: CharArray, val year: Int, val month: Int, val cvc: CharArray?, val checksumValid: Boolean, val version: Long = 0) {
    fun discard() { pan.fill('\u0000'); cvc?.fill('\u0000') }
    override fun toString() = "NativeStoredCard(redacted)"
}

internal object NativeStoredCardPolicy {
    fun entry(value: Map<String, Any?>): Boolean = value.keys == setOf("action", "cardId") &&
        value["action"] in setOf("view", "edit", "delete") &&
        (value["cardId"] as? String)?.let { PasskeyPolicy.uuid.matches(it) } == true
    private fun invalid(): Nothing = throw AuthFailure(AuthCode.INVALID_REQUEST)
    fun panValid(value: CharArray) = value.size in 13..19 && value.all { it in '0'..'9' }
    fun checksum(pan: CharArray): Boolean {
        var total = 0
        for (index in pan.indices) {
            var digit = pan[pan.lastIndex - index] - '0'
            if (index % 2 == 1) { digit *= 2; if (digit > 9) digit -= 9 }
            total += digit
        }
        return total % 10 == 0
    }
    fun input(number: CharArray, year: String, month: String, code: CharArray): NativeStoredCard {
        if (number.size > 64 || code.size > 4) invalid()
        val pan = number.filter { it != ' ' && it != '-' }.toCharArray()
        try {
            val y = year.toIntOrNull() ?: invalid(); val m = month.toIntOrNull() ?: invalid()
            if (!panValid(pan) || y !in 2000..2199 || m !in 1..12 ||
                code.isNotEmpty() && (code.size !in 3..4 || code.any { it !in '0'..'9' })) invalid()
            return NativeStoredCard(pan.copyOf(), y, m, code.takeIf { it.isNotEmpty() }?.copyOf(), checksum(pan))
        } finally { pan.fill('\u0000') }
    }
    fun reveal(value: Any?, cardId: String): NativeStoredCard {
        val row = value as? Map<*, *> ?: invalid()
        if (row.keys != setOf("card_id", "household_id", "pan", "expiry_year", "expiry_month", "cvc", "checksum_valid", "version") || row["card_id"] != cardId) invalid()
        FinancePolicy.id(row["household_id"])
        val pan = (row["pan"] as? String)?.toCharArray() ?: invalid()
        val cvc = when (val value = row["cvc"]) { null -> null; is String -> value.toCharArray(); else -> invalid() }
        try {
            fun integer(key: String): Long = when (val n = row[key]) { is Long -> n; is Int -> n.toLong(); else -> invalid() }
            val year = integer("expiry_year"); val month = integer("expiry_month"); val version = integer("version")
            if (!panValid(pan) || year !in 2000..2199 || month !in 1..12 || version !in 1..9_007_199_254_740_991L ||
                cvc != null && (cvc.size !in 3..4 || cvc.any { it !in '0'..'9' }) || row["checksum_valid"] != checksum(pan)) invalid()
            return NativeStoredCard(pan.copyOf(), year.toInt(), month.toInt(), cvc?.copyOf(), checksum(pan), version)
        } finally { pan.fill('\u0000'); cvc?.fill('\u0000') }
    }
}
