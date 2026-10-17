package io.github.jihoon22lee.sallimbook.auth

/** Local screen authorization only. No server freshness, credentials, or vault keys. */
internal enum class AppRequestKind { PROTECTED, LOGIN, INVITATION, REAUTHENTICATE, LOGOUT }
internal data class AppLockTicket(val generation: Long, val kind: AppRequestKind)

/** Installed by Application, never by a bridge call. Tests can exercise policies without Android. */
internal object AppLockRequests {
    @Volatile var register: ((ForegroundRequest) -> Unit)? = null
}

internal class AppLockPolicy {
    var locked = true; private set
    var generation = 0L; private set
    private var backgroundAt: Long? = null
    private var foreground = false

    @Synchronized fun resume(now: Long, deviceLocked: Boolean) {
        val away = backgroundAt
        if (deviceLocked || away != null && (now < away || now - away >= 60_000)) lock()
        backgroundAt = null
        foreground = true
    }
    @Synchronized fun pause() { foreground = false }
    @Synchronized fun background(now: Long) { if (backgroundAt == null) backgroundAt = now }
    @Synchronized fun expire(now: Long): Boolean {
        val away = backgroundAt ?: return false
        if (!locked && (now < away || now - away >= 60_000)) { lock(); return true }
        return false
    }
    @Synchronized fun lock() { locked = true; generation++ }
    @Synchronized fun ticket(kind: AppRequestKind): AppLockTicket = AppLockTicket(generation, kind)
    @Synchronized fun allowed(ticket: AppLockTicket): Boolean =
        foreground && ticket.generation == generation && (!locked || ticket.kind != AppRequestKind.PROTECTED)
    @Synchronized fun unlock(ticket: AppLockTicket): Boolean {
        if (ticket.kind !in setOf(AppRequestKind.LOGIN, AppRequestKind.REAUTHENTICATE) || !allowed(ticket)) return false
        locked = false
        return true
    }
    @Synchronized fun isLocked(): Boolean = locked

    /** Cancellation and the final unlock decision share the request's monitor. */
    fun unlockAfterServerProof(gate: ForegroundRequest, deviceUnlocked: () -> Boolean): Boolean = gate.whileActive {
        val ticket = gate.appLockTicket()
        ticket != null && deviceUnlocked() && unlock(ticket)
    }

    fun httpAllowed(ticket: AppLockTicket, method: String, path: String): Boolean {
        if (!allowed(ticket)) return false
        if (ticket.kind == AppRequestKind.PROTECTED) return true
        if (method != "POST") return false
        val names = when (ticket.kind) {
            AppRequestKind.LOGIN -> setOf("/api/v1/auth/native/login", "/api/v1/auth/native/passkeys/options", "/api/v1/auth/native/passkeys/verify")
            AppRequestKind.INVITATION -> setOf("/api/v1/auth/invitations/accept")
            AppRequestKind.REAUTHENTICATE -> setOf("/api/v1/auth/native/refresh", "/api/v1/auth/native/reauthenticate")
            AppRequestKind.LOGOUT -> setOf("/api/v1/auth/native/refresh", "/api/v1/auth/native/logout")
            else -> emptySet()
        }
        return path in names
    }
}
