package io.github.jihoon22lee.sallimbook.auth

import android.app.Activity
import android.app.KeyguardManager
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Bundle
import android.os.CancellationSignal
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.text.InputFilter
import android.text.InputType
import android.view.View
import android.view.WindowManager
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.credentials.CreateCredentialResponse
import androidx.credentials.CreatePublicKeyCredentialRequest
import androidx.credentials.CreatePublicKeyCredentialResponse
import androidx.credentials.CredentialManager
import androidx.credentials.CredentialManagerCallback
import androidx.credentials.GetCredentialRequest
import androidx.credentials.GetCredentialResponse
import androidx.credentials.GetPublicKeyCredentialOption
import androidx.credentials.PublicKeyCredential
import androidx.credentials.exceptions.CreateCredentialCancellationException
import androidx.credentials.exceptions.CreateCredentialException
import androidx.credentials.exceptions.GetCredentialCancellationException
import androidx.credentials.exceptions.GetCredentialException
import androidx.credentials.exceptions.NoCredentialException
import java.time.Instant

/** Credential Manager is account authentication, never vault key derivation or decryption. */
class NativePasskeyActivity : AppCompatActivity() {
    companion object {
        internal const val LOGIN = "passkey-login"
        internal const val REGISTER = "passkey-register"
        internal const val REVOKE = "passkey-revoke"
        internal const val DEVICE = "device-revoke"
        internal const val INVITE = "passkey-invite"
        internal const val ACCOUNT = "account-number-passkey"
        internal const val EXTRA_ID = "sallimbook.auth.target"
        internal const val EXTRA_VERSION = "sallimbook.auth.version"
    }

    private val auth by lazy { NativeAuthSession.get(applicationContext) }
    private val appLock by lazy { AppLockController.get(applicationContext) }
    private val keyguard by lazy { getSystemService(KeyguardManager::class.java) }
    private val credentials by lazy { CredentialManager.create(applicationContext) }
    private val handler = Handler(Looper.getMainLooper())
    private var resumed = false
    private var startedSignedIn = false
    private var mode = ""
    private var targetId: String? = null
    private var ifMatch: String? = null
    private var targetLoaded = false
    private var gate: ForegroundRequest? = null
    private var cancellation: CancellationSignal? = null
    private var providerOwner: NativePasskeyCeremony? = null
    private var ceremony: NativePasskeyCeremony? = null
    private var lifetime: PasskeyPresentationPolicy? = null
    private var response: CharArray? = null
    private var invitation: InvitationDisplay? = null
    private var createdInvitation = false
    private var accountDisplay: AccountNumberDisplay? = null
    private var shownAccountNumber = false
    private lateinit var status: TextView
    private lateinit var field: EditText
    private lateinit var code: TextView
    private lateinit var submit: Button
    private val finishWhenReady = Runnable { finishProviderResponse() }
    private val expire = Runnable { cancelPending(); showFailure(AuthCode.PASSKEY_CANCELLED) }
    private val hideInvitation = Runnable { clearInvitation(); status.text = "초대 코드를 지웠어요. 필요하면 다시 만들어 주세요." }
    private val hideAccount = Runnable { clearInvitation(); status.text = "계좌번호 표시 시간이 끝났어요. 다시 보려면 새로 인증해 주세요." }
    private var receiverRegistered = false
    private val screenReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action == Intent.ACTION_SCREEN_OFF) close()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(null)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        setResult(Activity.RESULT_CANCELED)
        startedSignedIn = auth.hasLocalSession()
        mode = intent.getStringExtra(NativeAuthActivity.EXTRA_MODE) ?: ""
        targetId = intent.getStringExtra(EXTRA_ID)
        ifMatch = intent.getStringExtra(EXTRA_VERSION)
        val targetMode = mode in setOf(REVOKE, DEVICE)
        val allowedExtras = setOf(NativeAuthActivity.EXTRA_MODE) + when {
            targetMode -> setOf(EXTRA_ID, EXTRA_VERSION)
            mode == ACCOUNT -> setOf(EXTRA_ID)
            else -> emptySet()
        }
        val internal = try { !packageManager.getActivityInfo(ComponentName(this, NativePasskeyActivity::class.java), 0).exported }
            catch (_: Exception) { false }
        if (savedInstanceState != null || !internal || !auth.available ||
            mode !in setOf(LOGIN, REGISTER, REVOKE, DEVICE, INVITE, ACCOUNT) || intent.extras?.keySet() != allowedExtras ||
            targetMode && !PasskeyPolicy.target(targetId, ifMatch) ||
            mode == ACCOUNT && (targetId == null || !PasskeyPolicy.uuid.matches(targetId!!))) {
            failAndFinish(AuthCode.AUTH_UNAVAILABLE)
            return
        }
        if (mode != REVOKE && PasskeyConfiguration.read(this) == null) {
            failAndFinish(AuthCode.PASSKEYS_DISABLED)
            return
        }
        buildUi()
        ContextCompat.registerReceiver(this, screenReceiver, IntentFilter(Intent.ACTION_SCREEN_OFF), ContextCompat.RECEIVER_NOT_EXPORTED)
        receiverRegistered = true
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() { close() }
        })
    }

    private fun buildUi() {
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            isSaveEnabled = false
            filterTouchesWhenObscured = true
            importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
            importantForContentCapture = View.IMPORTANT_FOR_CONTENT_CAPTURE_NO_EXCLUDE_DESCENDANTS
        }
        fun label(text: String) = TextView(this).apply {
            this.text = text
            textSize = 17f
            isSaveEnabled = false
            freezesText = false
            setPadding(0, 12.dp(), 0, 12.dp())
            column.addView(this)
        }
        label(when (mode) {
            LOGIN -> "SallimBook · 패스키 로그인"
            REGISTER -> "SallimBook · 패스키 등록"
            REVOKE -> "SallimBook · 패스키 삭제"
            DEVICE -> "SallimBook · 기기 연결 해제"
            ACCOUNT -> "SallimBook · 패스키로 계좌번호 보기"
            else -> "SallimBook · 패스키로 구성원 초대"
        }).textSize = 24f
        label(when (mode) {
            REGISTER -> "최근 로그인한 계정에 패스키를 등록합니다. 저장할 인증 제공자는 시스템 화면에서 선택해 주세요."
            REVOKE -> "현재 계정에서 이 패스키를 더 이상 로그인에 사용하지 못하게 합니다. 인증 제공자의 저장 항목은 별도로 관리해 주세요."
            DEVICE -> "표시된 기기의 연결만 해제하도록 패스키로 인증합니다."
            INVITE -> "현재 가계의 구성원 초대에만 사용할 인증을 진행합니다."
            ACCOUNT -> "표시된 계좌의 번호를 최대 30초 동안 볼 수 있도록 인증합니다."
            else -> "로그인 이름을 입력한 뒤 시스템 화면에서 사용할 패스키를 선택해 주세요."
        })
        field = EditText(this).apply {
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            imeOptions = EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING
            isSaveEnabled = false
            isSaveFromParentEnabled = false
            freezesText = false
            importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO
            importantForContentCapture = View.IMPORTANT_FOR_CONTENT_CAPTURE_NO
            filterTouchesWhenObscured = true
            isLongClickable = false
            setSingleLine(true)
            filters = arrayOf(InputFilter.LengthFilter(if (mode == REGISTER) 80 else 64))
            hint = when (mode) { REGISTER -> "패스키 이름"; INVITE -> "초대할 구성원의 로그인 이름"; else -> "로그인 이름" }
            minimumHeight = 48.dp()
            if (mode in setOf(REVOKE, DEVICE, ACCOUNT)) visibility = View.GONE
            column.addView(this)
        }
        code = NativeSecretViews.sensitive(label("")).apply { setTextIsSelectable(false); isLongClickable = false }
        status = label(if (mode in setOf(REVOKE, DEVICE, ACCOUNT)) "대상을 확인하고 있어요." else "")
        submit = Button(this).apply {
            text = when (mode) { REVOKE -> "이 패스키 삭제"; DEVICE -> "인증하고 기기 연결 해제"; INVITE -> "인증하고 초대 만들기"; REGISTER -> "패스키 등록"; ACCOUNT -> "인증하고 계좌번호 표시"; else -> "패스키 로그인" }
            minimumHeight = 48.dp()
            filterTouchesWhenObscured = true
            isEnabled = mode !in setOf(REVOKE, DEVICE, ACCOUNT)
            setOnClickListener { submitNativePasskey() }
            column.addView(this)
        }
        Button(this).apply {
            text = "닫기"
            minimumHeight = 48.dp()
            filterTouchesWhenObscured = true
            setOnClickListener { close() }
            column.addView(this)
        }
        val scroll = ScrollView(this).apply { isSaveEnabled = false; addView(column) }
        ViewCompat.setOnApplyWindowInsetsListener(scroll) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            view.setPadding(bars.left + 20.dp(), bars.top + 12.dp(), bars.right + 20.dp(), bars.bottom + 12.dp())
            insets
        }
        setContentView(scroll)
    }

    private fun ready() = resumed && hasWindowFocus() && !keyguard.isDeviceLocked && !isFinishing && !isDestroyed

    private fun closeIfSignedOut(current: Boolean) {
        if (!NativeSessionEnd.ended(current, ready(), startedSignedIn, auth.hasLocalSession())) return
        cancelPending()
        NativeSessionEnd.close(this)
    }

    private fun loadTarget() {
        if (!ready() || gate != null || targetLoaded || mode !in setOf(REVOKE, DEVICE, ACCOUNT)) return
        val request = ForegroundRequest().also { gate = it }
        if (mode == ACCOUNT) { loadAccountTarget(request); return }
        loadTargetPage(request, PasskeyTargetPages(mode == REVOKE, targetId!!, ifMatch!!))
    }

    private fun loadTargetPage(request: ForegroundRequest, pages: PasskeyTargetPages) {
        if (gate !== request || !request.isActive() || !ready()) {
            request.cancel(); closeIfSignedOut(gate === request); return
        }
        val path = pages.nextPath ?: return
        auth.request("GET", path, null, request) { outcome -> runOnUiThread {
            if (gate !== request || !request.isActive() || !ready()) {
                request.cancel(); closeIfSignedOut(gate === request); return@runOnUiThread
            }
            if (outcome.code != null || outcome.value?.get("status") != 200) {
                gate = null
                showFailure(outcome.code ?: AuthCode.ACCESS_DENIED)
                return@runOnUiThread
            }
            val row = try { pages.accept(outcome.value["body"]) } catch (failure: AuthFailure) {
                gate = null
                showFailure(failure.code)
                return@runOnUiThread
            }
            if (row != null) {
                gate = null
                targetLoaded = true
                status.text = "대상: ${row["label"]}\n아래 버튼으로 이 항목의 해제를 확인해 주세요."
                submit.isEnabled = true
            } else if (pages.nextPath != null) {
                loadTargetPage(request, pages)
            } else {
                gate = null
                showFailure(AuthCode.ACCESS_DENIED)
            }
        } }
    }

    private fun loadAccountTarget(request: ForegroundRequest) {
        auth.finance(FinanceOperation.GET_ACCOUNT, org.json.JSONObject().put("accountId", targetId), request) { outcome -> runOnUiThread {
            if (gate !== request || !request.isActive() || !ready()) {
                request.cancel(); closeIfSignedOut(gate === request); return@runOnUiThread
            }
            gate = null
            val row = outcome.value?.get("body") as? Map<*, *>
            if (outcome.code != null || outcome.value?.get("status") != 200 || row == null || row["has_number"] != true) {
                showFailure(outcome.code ?: AuthCode.ACCESS_DENIED)
            } else {
                targetLoaded = true
                val asset = row["asset"] as Map<*, *>
                status.text = "${asset["name"]} · ${row["institution_name"]}\n${row["masked_number"]}\n이 계좌의 전체 번호를 확인합니다."
                submit.isEnabled = true
            }
        } }
    }

    private fun submitNativePasskey() {
        if (!ready() || gate != null || providerOwner != null) return
        invitation?.let {
            val value = it.reveal(SystemClock.elapsedRealtime(), resumed, hasWindowFocus(), !keyguard.isDeviceLocked)
            if (value == null) clearInvitation() else { code.text = value; submit.isEnabled = false }
            return
        }
        if (shownAccountNumber || mode in setOf(REVOKE, DEVICE, ACCOUNT) && !targetLoaded) return
        val text = field.text.toString().trim()
        if (mode in setOf(LOGIN, INVITE) && !Regex("[A-Za-z][A-Za-z0-9_.-]{2,63}").matches(text) ||
            mode == REGISTER && text.isBlank()) { status.text = "입력 항목을 확인해 주세요."; return }
        submit.isEnabled = false
        field.isEnabled = false
        status.text = "요청을 확인하고 있어요."
        val request = ForegroundRequest().also { gate = it }
        if (mode == REVOKE) {
            auth.revokePasskey(targetId!!, ifMatch!!, request) { result -> runOnUiThread { complete(request, result, null) } }
            return
        }
        val operation = when (mode) { LOGIN -> PasskeyOperation.LOGIN; REGISTER -> PasskeyOperation.REGISTER; INVITE -> PasskeyOperation.INVITE; ACCOUNT -> PasskeyOperation.ACCOUNT_REVEAL; else -> PasskeyOperation.DEVICE_REVOKE }
        auth.beginPasskey(operation, text, targetId, ifMatch, request) { result, pending -> runOnUiThread {
            if (gate !== request || !request.isActive() || !ready()) {
                pending?.discard(); request.cancel(); closeIfSignedOut(gate === request); return@runOnUiThread
            }
            if (result.code != null || pending == null) { cancelPending(); showFailure(result.code ?: AuthCode.PASSKEY_FAILED); return@runOnUiThread }
            ceremony = pending
            lifetime = PasskeyPresentationPolicy(SystemClock::elapsedRealtime, pending.expiresAtMillis)
            handler.postDelayed(expire, (pending.expiresAtMillis - SystemClock.elapsedRealtime()).coerceAtLeast(0))
            launchProvider(pending)
        } }
    }

    private fun launchProvider(pending: NativePasskeyCeremony) {
        if (!ready() || lifetime?.startProvider() != true) { cancelPending(); return }
        val signal = CancellationSignal().also { cancellation = it }
        providerOwner = pending
        val request = gate ?: run { cancelPending(); return }
        // App-lock cancellation must also revoke an outstanding provider operation, even if
        // the SDK never delivers its cancellation callback while our Activity is stopped.
        request.bindNetworkCancellation { handler.post {
            if (gate === request && ceremony === pending) close() else signal.cancel()
        } }
        val executor = ContextCompat.getMainExecutor(this)
        try {
            val json = String(pending.options)
            pending.options.fill('\u0000')
            if (pending.operation == PasskeyOperation.REGISTER) {
                credentials.createCredentialAsync(this,
                    CreatePublicKeyCredentialRequest(requestJson = json, origin = null,
                        isAutoSelectAllowed = false, isConditional = false), signal, executor,
                    object : CredentialManagerCallback<CreateCredentialResponse, CreateCredentialException> {
                        override fun onResult(result: CreateCredentialResponse) {
                            if (result !is CreatePublicKeyCredentialResponse) providerFailure(pending, AuthCode.PASSKEY_FAILED)
                            else providerResult(pending, result.registrationResponseJson)
                        }
                        override fun onError(e: CreateCredentialException) {
                            providerFailure(pending, if (e is CreateCredentialCancellationException) AuthCode.PASSKEY_CANCELLED else AuthCode.PASSKEY_FAILED)
                        }
                    })
            } else {
                credentials.getCredentialAsync(this,
                    GetCredentialRequest(listOf(GetPublicKeyCredentialOption(json)), origin = null), signal, executor,
                    object : CredentialManagerCallback<GetCredentialResponse, GetCredentialException> {
                        override fun onResult(result: GetCredentialResponse) {
                            val credential = result.credential
                            if (credential !is PublicKeyCredential) providerFailure(pending, AuthCode.PASSKEY_FAILED)
                            else providerResult(pending, credential.authenticationResponseJson)
                        }
                        override fun onError(e: GetCredentialException) {
                            providerFailure(pending, when (e) { is GetCredentialCancellationException -> AuthCode.PASSKEY_CANCELLED; is NoCredentialException -> AuthCode.PASSKEY_REQUIRED; else -> AuthCode.PASSKEY_FAILED })
                        }
                    })
            }
        } catch (_: Exception) { providerFailure(pending, AuthCode.PASSKEY_FAILED) }
    }

    private fun providerResult(owner: NativePasskeyCeremony, json: String) {
        if (providerOwner !== owner) return
        gate?.releaseNetworkCancellation()
        providerOwner = null
        cancellation = null
        if (ceremony !== owner) { if (ready()) showFailure(AuthCode.PASSKEY_CANCELLED); return }
        if (gate?.isActive() != true || lifetime?.providerReturned() != true || json.length !in 1..100_000 || isFinishing || isDestroyed) {
            cancelPending(); return
        }
        response = json.toCharArray()
        finishProviderResponse()
    }

    private fun finishProviderResponse() {
        val pending = ceremony ?: return
        val policy = lifetime ?: return
        val result = response ?: return
        if (!policy.waitingForPresentation()) return
        if (!policy.canWait()) { cancelPending(); showFailure(AuthCode.PASSKEY_CANCELLED); return }
        if (!policy.claimVerification(resumed, hasWindowFocus(), !keyguard.isDeviceLocked)) {
            handler.removeCallbacks(finishWhenReady)
            handler.postDelayed(finishWhenReady, 50)
            return
        }
        val request = gate ?: run { cancelPending(); return }
        handler.removeCallbacks(finishWhenReady)
        status.text = "서버에서 인증을 확인하고 있어요."
        auth.finishPasskey(pending, result, request) { outcome, invitation, number -> runOnUiThread { complete(request, outcome, invitation, number) } }
    }

    private fun complete(request: ForegroundRequest, outcome: AuthOutcome, received: NativeInvitation?, number: NativeAccountNumber? = null) {
        try {
            if (gate !== request || !request.isActive() || !ready()) {
                request.cancel(); closeIfSignedOut(gate === request); return
            }
            cancelPending()
            if (outcome.code != null) { showFailure(outcome.code); return }
            if (mode == ACCOUNT) {
                if (number == null) { showFailure(AuthCode.ACCESS_DENIED); return }
                val now = SystemClock.elapsedRealtime()
                accountDisplay = AccountNumberDisplay(number.number.copyOf(), now)
                code.text = accountDisplay?.reveal(now, resumed, hasWindowFocus(), !keyguard.isDeviceLocked) ?: ""
                shownAccountNumber = true
                submit.isEnabled = false
                status.text = "최대 30초 동안 표시합니다. 화면을 벗어나면 즉시 지웁니다."
                handler.postDelayed(hideAccount, 30_000)
            } else if (mode == INVITE && received != null) {
                createdInvitation = true
                val remaining = PasskeyPolicy.remaining(received.expiresAt, Instant.now(), 30_000)
                invitation = InvitationDisplay(received.token.copyOf(), SystemClock.elapsedRealtime(), remaining)
                submit.text = "초대 코드 보기"
                submit.isEnabled = remaining > 0
                status.text = "초대 코드를 최대 30초 동안 확인할 수 있어요. 받는 사람이 자신의 네이티브 화면에 직접 입력해 주세요."
                handler.postDelayed(hideInvitation, remaining)
            } else {
                val status = when (mode) { LOGIN -> "authenticated"; REGISTER -> "registered"; else -> "revoked" }
                setResult(Activity.RESULT_OK, Intent().putExtra(NativeAuthActivity.EXTRA_STATUS, status))
                finish()
            }
        } finally { received?.discard(); number?.discard() }
    }

    private fun providerFailure(owner: NativePasskeyCeremony, code: AuthCode) {
        if (providerOwner !== owner) return
        gate?.releaseNetworkCancellation()
        providerOwner = null
        cancellation = null
        if (ceremony !== owner) { if (ready()) showFailure(AuthCode.PASSKEY_CANCELLED); return }
        if (gate == null || isFinishing || isDestroyed) return
        cancelPending()
        if (code == AuthCode.PASSKEY_CANCELLED) close() else showFailure(code)
    }

    private fun cancelPending() {
        handler.removeCallbacks(finishWhenReady)
        handler.removeCallbacks(expire)
        lifetime?.cancel(); lifetime = null
        // Invalidate ownership before CancellationSignal can synchronously invoke a callback.
        providerOwner = null
        if (cancellation != null) gate?.releaseNetworkCancellation()
        gate?.cancel(); gate = null
        ceremony?.discard(); ceremony = null
        response?.fill('\u0000'); response = null
        val signal = cancellation; cancellation = null; signal?.cancel()
    }

    private fun clearInvitation() {
        handler.removeCallbacks(hideInvitation)
        handler.removeCallbacks(hideAccount)
        accountDisplay?.discard(); accountDisplay = null
        invitation?.discard(); invitation = null
        if (::code.isInitialized) code.text = ""
        if ((createdInvitation || shownAccountNumber) && ::submit.isInitialized) submit.isEnabled = false
    }

    private fun showFailure(code: AuthCode) {
        if (!::status.isInitialized || isFinishing || isDestroyed) return
        status.text = when (code) {
            AuthCode.PASSKEYS_DISABLED -> "패스키 연결 설정이 아직 준비되지 않았어요."
            AuthCode.PASSKEY_REQUIRED -> "사용할 수 있는 패스키가 없어요. 로그인 후 패스키를 등록해 주세요."
            AuthCode.REAUTHENTICATION_REQUIRED, AuthCode.SESSION_EXPIRED -> "이 화면을 닫고 다시 로그인한 후 진행해 주세요."
            AuthCode.PASSKEY_CANCELLED, AuthCode.AUTH_CANCELLED -> "인증을 중단했어요. 다시 진행하려면 버튼을 눌러 주세요."
            AuthCode.NETWORK_UNAVAILABLE -> "연결을 확인할 수 없어요. 자동으로 다시 전송하지 않았어요."
            else -> "요청을 완료하지 못했어요. 대상과 계정 상태를 확인해 주세요."
        }
        submit.isEnabled = !shownAccountNumber && providerOwner == null && (mode !in setOf(REVOKE, DEVICE, ACCOUNT) || targetLoaded)
        field.isEnabled = true
    }

    private fun failAndFinish(code: AuthCode) {
        setResult(Activity.RESULT_CANCELED, Intent().putExtra(NativeAuthActivity.EXTRA_ERROR, code.name))
        finish()
    }

    private fun close() {
        cancelPending(); clearInvitation()
        if (::field.isInitialized) field.text.clear()
        if (createdInvitation) setResult(Activity.RESULT_OK, Intent().putExtra(NativeAuthActivity.EXTRA_STATUS, "created"))
        if (shownAccountNumber) setResult(Activity.RESULT_OK, Intent().putExtra(NativeAuthActivity.EXTRA_STATUS, "completed"))
        if (!isFinishing) finish()
    }

    override fun onResume() {
        super.onResume(); resumed = true
        if (keyguard.isDeviceLocked) close() else finishProviderResponse()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) { finishProviderResponse(); loadTarget() }
        else {
            clearInvitation()
            if (gate != null && !keepProviderTransition()) {
                cancelPending(); showFailure(AuthCode.PASSKEY_CANCELLED)
            }
        }
    }

    override fun onPause() {
        resumed = false
        clearInvitation()
        // Only the current provider (or its bounded return) may cover this Activity.
        if (!keepProviderTransition()) close()
        super.onPause()
    }

    override fun onStop() { if (!keepProviderTransition()) close(); super.onStop() }
    override fun onSaveInstanceState(outState: Bundle) {
        if (!keepProviderTransition()) cancelPending()
        clearInvitation()
        super.onSaveInstanceState(outState)
        // Provider state remains in this Activity instance only; recreation is still rejected.
        outState.clear()
    }
    override fun onDestroy() {
        cancelPending(); clearInvitation()
        providerOwner = null
        if (::field.isInitialized) field.text.clear()
        if (receiverRegistered) unregisterReceiver(screenReceiver)
        receiverRegistered = false
        super.onDestroy()
    }
    private fun Int.dp(): Int = (this * resources.displayMetrics.density).toInt()

    /** Used only by the process controller for the pinned SDK trampoline during cold login. */
    internal fun ownsCredentialProvider(): Boolean {
        val request = gate ?: return false
        val ticket = request.appLockTicket() ?: return false
        return providerOwner != null && providerOwner === ceremony && cancellation?.isCanceled == false &&
            request.isActive() && appLock.isCurrent(ticket) && !keyguard.isDeviceLocked &&
            !isFinishing && !isDestroyed && lifetime?.providerWaitValid() == true
    }

    private fun keepProviderTransition(): Boolean {
        val policy = lifetime ?: return false
        val request = gate
        val ticket = request?.appLockTicket()
        val active = request?.isActive() == true && ticket != null && appLock.isCurrent(ticket) && !isFinishing && !isDestroyed
        if (!policy.keepPendingInBackground(ownsCredentialProvider(), active, !keyguard.isDeviceLocked)) return false
        handler.removeCallbacks(expire)
        handler.postDelayed(expire, policy.remainingPresentationMillis())
        return true
    }
}
