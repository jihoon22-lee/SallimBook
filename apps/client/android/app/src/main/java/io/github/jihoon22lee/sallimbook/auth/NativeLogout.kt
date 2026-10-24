package io.github.jihoon22lee.sallimbook.auth

/**
 * Logout reaches the server before local state goes: clearing locks the app, which cancels
 * every gate including this one. Local state is cleared whatever the server answers.
 */
internal object NativeLogout {
    fun run(token: String?, active: () -> Boolean, post: (String) -> Boolean, clearLocal: () -> Unit): Boolean {
        try {
            return token != null && active() && try { post(token) } catch (_: Exception) { false }
        } finally {
            clearLocal()
        }
    }
}
