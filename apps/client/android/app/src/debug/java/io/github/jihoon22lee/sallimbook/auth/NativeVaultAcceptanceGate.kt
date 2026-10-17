package io.github.jihoon22lee.sallimbook.auth

import android.content.Context
import android.content.pm.ApplicationInfo
import android.os.SystemClock
import io.github.jihoon22lee.sallimbook.debugproof.CvcAcceptanceActivity
import io.github.jihoon22lee.sallimbook.debugproof.CvcAcceptanceFixtures
import java.io.IOException
import java.lang.ref.WeakReference

/** Debug-only, single foreground Activity owner; never an application preference or JS switch. */
internal object NativeVaultAcceptanceGate {
    private class Owner(activity: CvcAcceptanceActivity) {
        val activity = WeakReference(activity)
        val began = SystemClock.elapsedRealtime()
        var failWrite = false
    }
    private var owner: Owner? = null
    @Synchronized fun beginSyntheticCvcAcceptance(activity: CvcAcceptanceActivity): Boolean {
        if (!activity.syntheticOwnerPresented() || !debugApplication(activity)) return false
        owner = Owner(activity)
        return true
    }
    @Synchronized fun end(activity: CvcAcceptanceActivity) {
        if (owner?.activity?.get() === activity) owner = null
    }
    @Synchronized fun active(activity: CvcAcceptanceActivity): Boolean {
        val current = owner ?: return false
        val live = SystemClock.elapsedRealtime() - current.began in 0 until 180_000L
        if (!live || current.activity.get() == null) { owner = null; return false }
        return current.activity.get() === activity
    }
    private fun debugApplication(context: Context) =
        context.packageName == "io.github.jihoon22lee.sallimbook.debug" &&
            (context.applicationInfo.flags and ApplicationInfo.FLAG_DEBUGGABLE) != 0
    @Synchronized fun allows(context: Context, binding: NativeVaultBinding, namespace: String): Boolean {
        val activity = owner?.activity?.get() ?: return false
        return debugApplication(context) && active(activity) && activity.syntheticOwnerPresented() &&
            namespace == CvcAcceptanceFixtures.NAMESPACE && binding.localCode &&
            binding.aad().contentEquals(CvcAcceptanceFixtures.binding(context).aad())
    }
    @Synchronized fun armSyntheticCvcWriteFailure(activity: CvcAcceptanceActivity): Boolean {
        if (!active(activity) || !activity.syntheticOwnerPresented()) return false
        owner?.failWrite = true
        return true
    }
    @Synchronized fun beforeCommit(context: Context, binding: NativeVaultBinding, namespace: String) {
        if (namespace != CvcAcceptanceFixtures.NAMESPACE || !binding.localCode) return
        val activity = owner?.activity?.get()
        if (!allows(context, binding, namespace) || activity?.syntheticCommitActive() != true)
            throw IOException("Synthetic request no longer permits commit")
        if (owner?.failWrite == true) {
            owner?.failWrite = false
            throw IOException("Synthetic AtomicFile acceptance failure")
        }
    }
}
