package io.github.jihoon22lee.sallimbook.auth

import android.app.Activity
import android.app.Application
import android.app.KeyguardManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.ComponentName
import android.content.Intent
import android.content.IntentFilter
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import androidx.core.content.ContextCompat
import java.util.WeakHashMap

/** Process lifetime is the longest possible unlock lifetime; nothing is restored from disk. */
internal class AppLockController private constructor(private val app: Application) : Application.ActivityLifecycleCallbacks {
    companion object {
        @Volatile private var instance: AppLockController? = null
        fun get(context: Context): AppLockController = instance ?: synchronized(this) {
            instance ?: AppLockController(context.applicationContext as Application).also { instance = it }
        }
    }
    private val policy = AppLockPolicy()
    private val main = Handler(Looper.getMainLooper())
    private val keyguard = app.getSystemService(KeyguardManager::class.java)
    private val started = mutableSetOf<Activity>()
    private val resumed = mutableSetOf<Activity>()
    private val passkeyOwners = mutableSetOf<NativePasskeyActivity>()
    private val gates = WeakHashMap<ForegroundRequest, Boolean>()
    private val listeners = mutableSetOf<() -> Unit>()
    private val expiry = Runnable {
        if (policy.expire(SystemClock.elapsedRealtime())) changed()
    }
    val locked: Boolean get() = policy.isLocked()
    fun addListener(listener: () -> Unit) { listeners.add(listener) }
    fun removeListener(listener: () -> Unit) { listeners.remove(listener) }

    init {
        AppLockRequests.register = { gate ->
            gate.captureAppLock(policy, policy.ticket(AppRequestKind.PROTECTED)) { !keyguard.isDeviceLocked }
            synchronized(gates) { gates[gate] = true }
        }
        app.registerActivityLifecycleCallbacks(this)
        ContextCompat.registerReceiver(app, object : BroadcastReceiver() {
            override fun onReceive(context: Context?, intent: Intent?) { if (intent?.action == Intent.ACTION_SCREEN_OFF) lock() }
        }, IntentFilter(Intent.ACTION_SCREEN_OFF), ContextCompat.RECEIVER_NOT_EXPORTED)
    }
    fun lock() { policy.lock(); changed() }
    private fun changed() {
        if (locked) synchronized(gates) { gates.keys.toList() }.forEach { it.cancel() }
        val notify = Runnable { listeners.toList().forEach { it() } }
        if (Looper.myLooper() == Looper.getMainLooper()) notify.run() else main.post(notify)
    }
    fun bind(gate: ForegroundRequest, kind: AppRequestKind) {
        gate.bindAppLock(policy, policy.ticket(kind)) { !keyguard.isDeviceLocked }
        synchronized(gates) { gates[gate] = true }
        gate.check()
    }
    fun newUnlockAttempt(): AppLockTicket = policy.ticket(AppRequestKind.REAUTHENTICATE)
    fun isCurrent(ticket: AppLockTicket): Boolean = policy.ticket(ticket.kind).generation == ticket.generation
    /** Called only by the native system prompt owner, after focus has returned. */
    fun finishOsAuthentication(ticket: AppLockTicket, activity: Activity): Boolean {
        if (!activity.hasWindowFocus() || activity !in resumed || keyguard.isDeviceLocked ||
            !NativeAuthSession.get(app).hasLocalSession()) return false
        if (!policy.unlock(ticket)) return false
        changed()
        return true
    }
    /** A session service calls this only after validating a real server authentication response. */
    fun finishServerAuthentication(gate: ForegroundRequest) {
        val wasLocked = locked
        if (!policy.unlockAfterServerProof(gate) { !keyguard.isDeviceLocked }) throw AuthFailure(AuthCode.APP_LOCKED)
        if (wasLocked) changed()
    }

    override fun onActivityCreated(activity: Activity, state: Bundle?) {
        if (activity is NativePasskeyActivity) passkeyOwners.add(activity)
    }
    override fun onActivityStarted(activity: Activity) { started.add(activity); main.removeCallbacks(expiry) }
    override fun onActivityResumed(activity: Activity) {
        resumed.add(activity)
        val previous = policy.ticket(AppRequestKind.PROTECTED).generation
        policy.resume(SystemClock.elapsedRealtime(), keyguard.isDeviceLocked)
        if (previous != policy.ticket(AppRequestKind.PROTECTED).generation) changed()
        val debugProof = io.github.jihoon22lee.sallimbook.BuildConfig.DEBUG &&
            activity.javaClass.name in setOf("io.github.jihoon22lee.sallimbook.debugproof.SecurityProofActivity",
                "io.github.jihoon22lee.sallimbook.debugproof.CvcAcceptanceActivity")
        if (locked && activity !is io.github.jihoon22lee.sallimbook.MainActivity && !debugProof) {
            val mode = activity.intent.getStringExtra(NativeAuthActivity.EXTRA_MODE)
            val bootstrap = !NativeAuthSession.get(app).hasLocalSession() &&
                (activity is NativeAuthActivity && mode in setOf(NativeAuthActivity.LOGIN, NativeAuthActivity.INVITATION) ||
                    activity is NativeOnboardingActivity && NativeOnboardingActivity.enrollment(mode) ||
                    activity is NativePasskeyActivity && mode == NativePasskeyActivity.LOGIN)
            // AndroidX launches a non-exported trampoline while Credential Manager owns the
            // ceremony. This permits that screen only; it grants no unlock or HTTP privilege.
            val provider = passkeyOwners.any { owner ->
                val exported = try { app.packageManager.getActivityInfo(ComponentName(app, activity.javaClass), 0).exported }
                    catch (_: Exception) { true }
                PasskeyProviderActivityPolicy.permits(activity.javaClass.name, exported, activity.taskId == owner.taskId,
                    owner.ownsCredentialProvider())
            }
            if (!bootstrap && !provider) activity.finish()
        }
    }
    override fun onActivityPaused(activity: Activity) {
        resumed.remove(activity)
        if (resumed.isEmpty()) policy.pause()
    }
    override fun onActivityStopped(activity: Activity) {
        started.remove(activity)
        if (started.isEmpty()) {
            policy.background(SystemClock.elapsedRealtime())
            main.postDelayed(expiry, 60_000)
        }
    }
    override fun onActivitySaveInstanceState(activity: Activity, outState: Bundle) = Unit
    override fun onActivityDestroyed(activity: Activity) {
        resumed.remove(activity); started.remove(activity)
        if (activity is NativePasskeyActivity) passkeyOwners.remove(activity)
    }
}

/** Install before any Activity can expose a WebView or dispatch an auth request. */
class SallimBookApplication : Application() {
    override fun onCreate() { super.onCreate(); AppLockController.get(this) }
}
