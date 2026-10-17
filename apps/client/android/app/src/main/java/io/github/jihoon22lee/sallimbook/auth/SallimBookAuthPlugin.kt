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
    private val lockedAllowed = mutableSetOf<PluginCall>()
    private val cancelled = mutableSetOf<PluginCall>()
    private var uiCall: PluginCall? = null
    private var uiMode: String? = null
    private var uiOutcome: AuthOutcome? = null
    private var lastUiLaunch = Long.MIN_VALUE
    private val auth get() = NativeAuthSession.get(context)
    private val appLock get() = AppLockController.get(context)
    private var lockEventPending = true
    private val lockChanged: () -> Unit = {
        lockEventPending = true
        if (appLock.locked) pending.forEach { (call, gate) ->
            if (call !in lockedAllowed) { gate.cancel(); cancelled.add(call) }
        }
        flushCancelled(); flushLockEvent()
    }
    override fun load() { appLock.addListener(lockChanged) }

    private fun flushLockEvent() {
        if (lockEventPending && trustedForeground()) {
            lockEventPending = false
            notifyListeners("appLockChanged", JSObject().put("locked", appLock.locked), true)
        }
    }

    @PluginMethod fun getAppLock(call: PluginCall) { main.post {
        if (!emptyOptions(call)) failure(call, AuthCode.INVALID_REQUEST)
        else if (!trustedForeground()) failure(call, AuthCode.ACCESS_DENIED)
        else resolve(call, AuthOutcome.success(mapOf("locked" to appLock.locked)))
    } }
    @PluginMethod fun lockApp(call: PluginCall) { main.post {
        if (!emptyOptions(call)) failure(call, AuthCode.INVALID_REQUEST)
        else if (!trustedForeground()) failure(call, AuthCode.ACCESS_DENIED)
        else { appLock.lock(); resolve(call, AuthOutcome.success(mapOf("locked" to true))) }
    } }

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

    private fun begin(call: PluginCall, allowLocked: Boolean = false, action: (ForegroundRequest, (AuthOutcome) -> Unit) -> Unit) {
        if (!trustedForeground()) { failure(call, AuthCode.ACCESS_DENIED); return }
        if (appLock.locked && !allowLocked) { failure(call, AuthCode.APP_LOCKED); return }
        if (pending.size >= 8 || uiCall != null) { failure(call, AuthCode.AUTH_UNAVAILABLE); return }
        val gate = ForegroundRequest()
        pending[call] = gate
        if (allowLocked) lockedAllowed.add(call)
        action(gate) { outcome ->
            main.post {
                if (pending[call] !== gate) return@post
                val loggedOut = allowLocked && outcome.value?.get("status") == "signedOut"
                if ((gate.isActive() || loggedOut) && trustedForeground() && (!appLock.locked || allowLocked)) {
                    pending.remove(call)
                    lockedAllowed.remove(call)
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
        else begin(call, allowLocked = true) { gate, callback -> auth.logout(gate, callback) }
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

    private fun finance(call: PluginCall, operation: FinanceOperation) { main.post {
        begin(call) { gate, callback -> auth.finance(operation, call.data, gate, callback) }
    } }
    @PluginMethod fun listAssets(call: PluginCall) = finance(call, FinanceOperation.LIST_ASSETS)
    @PluginMethod fun getAsset(call: PluginCall) = finance(call, FinanceOperation.GET_ASSET)
    @PluginMethod fun createAsset(call: PluginCall) = finance(call, FinanceOperation.CREATE_ASSET)
    @PluginMethod fun updateAsset(call: PluginCall) = finance(call, FinanceOperation.UPDATE_ASSET)
    @PluginMethod fun archiveAsset(call: PluginCall) = finance(call, FinanceOperation.ARCHIVE_ASSET)
    @PluginMethod fun deleteAsset(call: PluginCall) = finance(call, FinanceOperation.DELETE_ASSET)
    @PluginMethod fun listAccounts(call: PluginCall) = finance(call, FinanceOperation.LIST_ACCOUNTS)
    @PluginMethod fun getAccount(call: PluginCall) = finance(call, FinanceOperation.GET_ACCOUNT)
    @PluginMethod fun createAccount(call: PluginCall) = finance(call, FinanceOperation.CREATE_ACCOUNT)
    @PluginMethod fun updateAccount(call: PluginCall) = finance(call, FinanceOperation.UPDATE_ACCOUNT)

    @PluginMethod fun getAssetMonth(call: PluginCall) = finance(call, FinanceOperation.GET_ASSET_MONTH)
    @PluginMethod fun getAssetMonthRevision(call: PluginCall) = finance(call, FinanceOperation.GET_ASSET_MONTH_REVISION)
    @PluginMethod fun listAssetMonthRevisions(call: PluginCall) = finance(call, FinanceOperation.LIST_ASSET_MONTH_REVISIONS)
    @PluginMethod fun createAssetMonthDraft(call: PluginCall) = finance(call, FinanceOperation.CREATE_ASSET_MONTH_DRAFT)
    @PluginMethod fun updateAssetMonthValue(call: PluginCall) = finance(call, FinanceOperation.UPDATE_ASSET_MONTH_VALUE)
    @PluginMethod fun synchronizeAssetMonthScope(call: PluginCall) = finance(call, FinanceOperation.SYNCHRONIZE_ASSET_MONTH_SCOPE)
    @PluginMethod fun confirmAssetMonth(call: PluginCall) = finance(call, FinanceOperation.CONFIRM_ASSET_MONTH)
    @PluginMethod fun reopenAssetMonth(call: PluginCall) = finance(call, FinanceOperation.REOPEN_ASSET_MONTH)

    @PluginMethod fun listIncome(call: PluginCall) = finance(call, FinanceOperation.LIST_INCOME)
    @PluginMethod fun incomeSummary(call: PluginCall) = finance(call, FinanceOperation.INCOME_SUMMARY)
    @PluginMethod fun incomeDuplicateCandidates(call: PluginCall) = finance(call, FinanceOperation.INCOME_DUPLICATE_CANDIDATES)
    @PluginMethod fun getIncome(call: PluginCall) = finance(call, FinanceOperation.GET_INCOME)
    @PluginMethod fun incomeHistory(call: PluginCall) = finance(call, FinanceOperation.INCOME_HISTORY)
    @PluginMethod fun createIncome(call: PluginCall) = finance(call, FinanceOperation.CREATE_INCOME)
    @PluginMethod fun correctIncome(call: PluginCall) = finance(call, FinanceOperation.CORRECT_INCOME)
    @PluginMethod fun voidIncome(call: PluginCall) = finance(call, FinanceOperation.VOID_INCOME)
    @PluginMethod fun returnIncome(call: PluginCall) = finance(call, FinanceOperation.RETURN_INCOME)
    @PluginMethod fun convertIncomePrecision(call: PluginCall) = finance(call, FinanceOperation.CONVERT_INCOME_PRECISION)

    @PluginMethod fun listCards(call: PluginCall) = finance(call, FinanceOperation.LIST_CARDS)
    @PluginMethod fun getCard(call: PluginCall) = finance(call, FinanceOperation.GET_CARD)
    @PluginMethod fun createCard(call: PluginCall) = finance(call, FinanceOperation.CREATE_CARD)
    @PluginMethod fun updateCard(call: PluginCall) = finance(call, FinanceOperation.UPDATE_CARD)
    @PluginMethod fun archiveCard(call: PluginCall) = finance(call, FinanceOperation.ARCHIVE_CARD)
    @PluginMethod fun deleteCard(call: PluginCall) = finance(call, FinanceOperation.DELETE_CARD)

    @PluginMethod fun loginUI(call: PluginCall) { main.post { launchForm(call, NativeAuthActivity.LOGIN) } }
    @PluginMethod fun reauthenticateUI(call: PluginCall) { main.post { launchForm(call, NativeAuthActivity.REAUTHENTICATE) } }
    @PluginMethod fun acceptInvitationUI(call: PluginCall) { main.post { launchForm(call, NativeAuthActivity.INVITATION) } }
    @PluginMethod fun createInvitationUI(call: PluginCall) { main.post { launchForm(call, NativeAuthActivity.CREATE_INVITATION) } }
    @PluginMethod fun passkeyLoginUI(call: PluginCall) { main.post { launchForm(call, NativePasskeyActivity.LOGIN) } }
    @PluginMethod fun registerPasskeyUI(call: PluginCall) { main.post { launchForm(call, NativePasskeyActivity.REGISTER) } }
    @PluginMethod fun createInvitationWithPasskeyUI(call: PluginCall) { main.post { launchForm(call, NativePasskeyActivity.INVITE) } }
    @PluginMethod fun revokePasskeyUI(call: PluginCall) { main.post { launchTargetForm(call, NativePasskeyActivity.REVOKE, "credentialId") } }
    @PluginMethod fun revokeDeviceUI(call: PluginCall) { main.post { launchTargetForm(call, NativePasskeyActivity.DEVICE, "deviceId") } }
    @PluginMethod fun editAccountNumberUI(call: PluginCall) { main.post { launchAccountForm(call, NativeAccountNumberActivity.EDIT) } }
    @PluginMethod fun showAccountNumberUI(call: PluginCall) { main.post { launchAccountForm(call, NativeAccountNumberActivity.SHOW) } }
    @PluginMethod fun showAccountNumberWithPasskeyUI(call: PluginCall) { main.post { launchAccountForm(call, NativePasskeyActivity.ACCOUNT) } }

    private fun launchAccountForm(call: PluginCall, mode: String) {
        val fields = call.data.keys().asSequence().toSet()
        val id = call.data.opt("accountId") as? String
        val tag = call.data.opt("ifMatch") as? String
        val expected = if (mode == NativeAccountNumberActivity.EDIT) setOf("accountId", "ifMatch") else setOf("accountId")
        if (fields != expected || id == null || !PasskeyPolicy.uuid.matches(id) ||
            mode == NativeAccountNumberActivity.EDIT && !PasskeyPolicy.target(id, tag)) {
            failure(call, AuthCode.INVALID_REQUEST); return
        }
        launchForm(call, mode, id, tag)
    }

    private fun launchTargetForm(call: PluginCall, mode: String, idKey: String) {
        val names = call.data.keys().asSequence().toSet()
        val id = call.data.opt(idKey) as? String
        val ifMatch = call.data.opt("ifMatch") as? String
        if (names != setOf(idKey, "ifMatch") || !PasskeyPolicy.target(id, ifMatch)) {
            failure(call, AuthCode.INVALID_REQUEST); return
        }
        launchForm(call, mode, id, ifMatch)
    }

    private fun launchForm(call: PluginCall, mode: String, targetId: String? = null, ifMatch: String? = null) {
        if (targetId == null && !emptyOptions(call)) { failure(call, AuthCode.INVALID_REQUEST); return }
        if (!trustedForeground() || !activity.hasWindowFocus()) { failure(call, AuthCode.ACCESS_DENIED); return }
        if (appLock.locked) { failure(call, AuthCode.APP_LOCKED); return }
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
            val passkey = mode in setOf(NativePasskeyActivity.LOGIN, NativePasskeyActivity.REGISTER,
                NativePasskeyActivity.REVOKE, NativePasskeyActivity.DEVICE, NativePasskeyActivity.INVITE, NativePasskeyActivity.ACCOUNT)
            val component = when {
                passkey -> NativePasskeyActivity::class.java
                mode in setOf(NativeAccountNumberActivity.EDIT, NativeAccountNumberActivity.SHOW) -> NativeAccountNumberActivity::class.java
                else -> NativeAuthActivity::class.java
            }
            val intent = Intent(activity, component)
                .putExtra(NativeAuthActivity.EXTRA_MODE, mode)
            if (targetId != null) intent.putExtra(NativePasskeyActivity.EXTRA_ID, targetId)
            if (ifMatch != null) intent.putExtra(NativePasskeyActivity.EXTRA_VERSION, ifMatch)
            startActivityForResult(call, intent, "authActivityResult")
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
            NativeAuthActivity.LOGIN, NativeAuthActivity.REAUTHENTICATE, NativePasskeyActivity.LOGIN -> "authenticated"
            NativeAuthActivity.CREATE_INVITATION, NativePasskeyActivity.INVITE -> "created"
            NativePasskeyActivity.REGISTER -> "registered"
            NativePasskeyActivity.REVOKE, NativePasskeyActivity.DEVICE -> "revoked"
            NativeAccountNumberActivity.EDIT -> "saved"
            NativeAccountNumberActivity.SHOW, NativePasskeyActivity.ACCOUNT -> "completed"
            else -> "accepted"
        }
        val status = result.data?.getStringExtra(NativeAuthActivity.EXTRA_STATUS)
        uiOutcome = if (result.resultCode == Activity.RESULT_OK &&
            (status == expected || uiMode == NativeAccountNumberActivity.EDIT && status == "deleted")) {
            AuthOutcome.success(mapOf("status" to status))
        } else if (result.data?.getStringExtra(NativeAuthActivity.EXTRA_ERROR) != null) {
            val code = AuthCode.entries.firstOrNull { it.name == result.data?.getStringExtra(NativeAuthActivity.EXTRA_ERROR) }
            AuthOutcome.failure(code ?: AuthCode.AUTH_UNAVAILABLE)
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
        resolve(call, if (appLock.locked) AuthOutcome.failure(AuthCode.APP_LOCKED) else outcome)
    }

    private fun flushCancelled() {
        if (!trustedForeground()) return
        cancelled.toList().forEach { call ->
            cancelled.remove(call)
            pending.remove(call)
            lockedAllowed.remove(call)
            failure(call, if (appLock.locked) AuthCode.APP_LOCKED else AuthCode.AUTH_CANCELLED)
        }
    }

    override fun handleOnResume() {
        resumed = true
        main.post { flushLockEvent(); flushCancelled(); flushUiResult() }
    }

    override fun handleOnPause() {
        resumed = false
        pending.forEach { (call, gate) -> gate.cancel(); cancelled.add(call) }
    }

    override fun handleOnDestroy() {
        appLock.removeListener(lockChanged)
        resumed = false
        pending.forEach { (call, gate) -> gate.cancel(); call.release(bridge) }
        pending.clear()
        lockedAllowed.clear()
        cancelled.clear()
        uiCall?.release(bridge)
        uiCall = null
        uiMode = null
        uiOutcome = null
    }
}
