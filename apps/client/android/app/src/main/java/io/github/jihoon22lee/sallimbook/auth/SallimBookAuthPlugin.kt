package io.github.jihoon22lee.sallimbook.auth

import android.app.Activity
import android.app.KeyguardManager
import android.content.Intent
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import androidx.activity.result.ActivityResult
import com.getcapacitor.JSObject
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.ActivityCallback
import com.getcapacitor.annotation.CapacitorPlugin
import io.github.jihoon22lee.sallimbook.MainActivity
import org.json.JSONObject

/** Tokens and password/invitation input have no bridge method, argument or return value. */
@CapacitorPlugin(name = "SallimBookAuth")
class SallimBookAuthPlugin : Plugin() {
    private val main = Handler(Looper.getMainLooper())
    private var resumed = false
    private val pending = mutableMapOf<PluginCall, ForegroundRequest>()
    private val cancelled = mutableSetOf<PluginCall>()
    private var uiCall: PluginCall? = null
    private var uiMode: String? = null
    private var uiOutcome: AuthOutcome? = null
    private var lastUiLaunch = Long.MIN_VALUE
    private val auth get() = NativeAuthSession.get(context)

    private fun trustedForeground(): Boolean = resumed && !activity.isFinishing && !activity.isDestroyed &&
        (activity as? MainActivity)?.secureBridgeReady == true &&
        !context.getSystemService(KeyguardManager::class.java).isDeviceLocked &&
        AuthPolicy.trustedBridgeUrl(bridge.webView.url)

    private fun emptyOptions(call: PluginCall): Boolean = call.data.length() == 0

    private fun resolve(call: PluginCall, outcome: AuthOutcome) {
        val response = JSObject().put("ok", outcome.code == null)
        if (outcome.code != null) response.put("code", outcome.code.name)
        else response.put("value", JSONObject(outcome.value ?: emptyMap<String, Any?>()))
        call.resolve(response)
    }

    private fun failure(call: PluginCall, code: AuthCode) = resolve(call, AuthOutcome.failure(code))

    private fun begin(call: PluginCall, action: (ForegroundRequest, (AuthOutcome) -> Unit) -> Unit) {
        if (!trustedForeground()) { failure(call, AuthCode.ACCESS_DENIED); return }
        if (pending.size >= 8 || uiCall != null) { failure(call, AuthCode.AUTH_UNAVAILABLE); return }
        val gate = ForegroundRequest()
        pending[call] = gate
        action(gate) { outcome ->
            main.post {
                if (pending[call] !== gate) return@post
                if (gate.isActive() && trustedForeground()) {
                    pending.remove(call)
                    resolve(call, outcome)
                } else {
                    gate.cancel()
                    cancelled.add(call)
                    flushCancelled()
                }
            }
        }
    }

    @PluginMethod fun getSession(call: PluginCall) { main.post {
        if (!emptyOptions(call)) failure(call, AuthCode.INVALID_REQUEST)
        else begin(call) { gate, callback -> auth.getSession(gate, callback) }
    } }

    @PluginMethod fun logout(call: PluginCall) { main.post {
        if (!emptyOptions(call)) failure(call, AuthCode.INVALID_REQUEST)
        else begin(call) { gate, callback -> auth.logout(gate, callback) }
    } }

    @PluginMethod fun request(call: PluginCall) { main.post {
        val names = call.data.keys().asSequence().toSet()
        val method = call.data.opt("method") as? String
        val path = call.data.opt("path") as? String
        val ifMatch = if ("ifMatch" in names) call.data.opt("ifMatch") as? String else null
        if (names != setOf("method", "path") && names != setOf("method", "path", "ifMatch") ||
            method == null || path == null || "ifMatch" in names && ifMatch == null ||
            !AuthPolicy.requestAllowed(method, path, ifMatch)) {
            failure(call, AuthCode.INVALID_REQUEST)
        } else begin(call) { gate, callback -> auth.request(method, path, ifMatch, gate, callback) }
    } }

    @PluginMethod fun loginUI(call: PluginCall) { main.post { launchForm(call, NativeAuthActivity.LOGIN) } }
    @PluginMethod fun acceptInvitationUI(call: PluginCall) { main.post { launchForm(call, NativeAuthActivity.INVITATION) } }
    @PluginMethod fun createInvitationUI(call: PluginCall) { main.post { launchForm(call, NativeAuthActivity.CREATE_INVITATION) } }

    private fun launchForm(call: PluginCall, mode: String) {
        if (!emptyOptions(call)) { failure(call, AuthCode.INVALID_REQUEST); return }
        if (!trustedForeground() || !activity.hasWindowFocus()) { failure(call, AuthCode.ACCESS_DENIED); return }
        val now = SystemClock.elapsedRealtime()
        if (!auth.available || uiCall != null || pending.isNotEmpty() ||
            lastUiLaunch != Long.MIN_VALUE && now - lastUiLaunch < 1000) {
            failure(call, AuthCode.AUTH_UNAVAILABLE)
            return
        }
        lastUiLaunch = now
        uiCall = call
        uiMode = mode
        try {
            startActivityForResult(call, Intent(activity, NativeAuthActivity::class.java)
                .putExtra(NativeAuthActivity.EXTRA_MODE, mode), "authActivityResult")
        } catch (_: Exception) {
            uiCall = null
            uiMode = null
            failure(call, AuthCode.AUTH_UNAVAILABLE)
        }
    }

    @ActivityCallback
    private fun authActivityResult(call: PluginCall?, result: ActivityResult) {
        if (call == null || call !== uiCall) return
        val expected = when (uiMode) {
            NativeAuthActivity.LOGIN -> "authenticated"
            NativeAuthActivity.CREATE_INVITATION -> "created"
            else -> "accepted"
        }
        val status = result.data?.getStringExtra(NativeAuthActivity.EXTRA_STATUS)
        uiOutcome = if (result.resultCode == Activity.RESULT_OK && status == expected) {
            AuthOutcome.success(mapOf("status" to expected))
        } else if (result.data?.getStringExtra(NativeAuthActivity.EXTRA_ERROR) == AuthCode.AUTH_UNAVAILABLE.name) {
            AuthOutcome.failure(AuthCode.AUTH_UNAVAILABLE)
        } else AuthOutcome.success(mapOf("status" to "cancelled"))
        flushUiResult()
    }

    private fun flushUiResult() {
        if (!trustedForeground()) return
        val call = uiCall ?: return
        val outcome = uiOutcome ?: return
        uiCall = null
        uiMode = null
        uiOutcome = null
        resolve(call, outcome)
    }

    private fun flushCancelled() {
        if (!trustedForeground()) return
        cancelled.toList().forEach { call ->
            cancelled.remove(call)
            pending.remove(call)
            failure(call, AuthCode.AUTH_CANCELLED)
        }
    }

    override fun handleOnResume() {
        resumed = true
        main.post { flushCancelled(); flushUiResult() }
    }

    override fun handleOnPause() {
        resumed = false
        pending.forEach { (call, gate) -> gate.cancel(); cancelled.add(call) }
    }

    override fun handleOnDestroy() {
        resumed = false
        pending.forEach { (call, gate) -> gate.cancel(); call.release(bridge) }
        pending.clear()
        cancelled.clear()
        uiCall?.release(bridge)
        uiCall = null
        uiMode = null
        uiOutcome = null
    }
}
