package io.github.jihoon22lee.sallimbook.auth

internal object NativeAccessLifetime {
    fun usable(now: Long, expiresAt: Long, requiredMillis: Long): Boolean =
        requiredMillis >= 0 && expiresAt > now && expiresAt - now > requiredMillis
}

/** Called on the account executor immediately before each HTTP call. Never retries a response. */
internal class NativeVaultAccess(private val gate: ForegroundRequest, private val token: (Long) -> String) {
    companion object { const val REQUIRED_MILLIS = 20_000L } // 15s HTTP deadline + scheduling margin.
    fun <T> send(request: (String) -> T): T {
        gate.check()
        val current = token(REQUIRED_MILLIS)
        gate.check()
        return request(current)
    }
}
