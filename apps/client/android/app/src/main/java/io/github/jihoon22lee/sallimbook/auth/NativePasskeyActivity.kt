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
        internal const val EXTRA_ID = "sallimbook.auth.target"
        internal const val EXTRA_VERSION = "sallimbook.auth.version"
    }

    private val auth by lazy { NativeAuthSession.get(applicationContext) }
    private val keyguard by lazy { getSystemService(KeyguardManager::class.java) }
    private val credentials by lazy { CredentialManager.create(applicationContext) }
    private val handler = Handler(Looper.getMainLooper())
    private var resumed = false
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
    private lateinit var status: TextView
    private lateinit var field: EditText
    private lateinit var code: TextView
    private lateinit var submit: Button
    private val finishWhenReady = Runnable { finishProviderResponse() }
    private val expire = Runnable { cancelPending(); showFailure(AuthCode.PASSKEY_CANCELLED) }
    private val hideInvitation = Runnable { clearInvitation(); status.text = "초대 코드를 지웠어요. 필요하면 다시 만들어 주세요." }
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
        mode = intent.getStringExtra(NativeAuthActivity.EXTRA_MODE) ?: ""
        targetId = intent.getStringExtra(EXTRA_ID)
        ifMatch = intent.getStringExtra(EXTRA_VERSION)
        val targetMode = mode in setOf(REVOKE, DEVICE)
        val allowedExtras = setOf(NativeAuthActivity.EXTRA_MODE) + if (targetMode) setOf(EXTRA_ID, EXTRA_VERSION) else emptySet()
        val internal = try { !packageManager.getActivityInfo(ComponentName(this, NativePasskeyActivity::class.java), 0).exported }
            catch (_: Exception) { false }
        if (savedInstanceState != null || !internal || !auth.available ||
            mode !in setOf(LOGIN, REGISTER, REVOKE, DEVICE, INVITE) || intent.extras?.keySet() != allowedExtras ||
            targetMode && !PasskeyPolicy.target(targetId, ifMatch)) {
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
            else -> "SallimBook · 패스키로 구성원 초대"
        }).textSize = 24f
        label(when (mode) {
            REGISTER -> "최근 로그인한 계정에 패스키를 등록합니다. 저장할 인증 제공자는 시스템 화면에서 선택해 주세요."
            REVOKE -> "현재 계정에서 이 패스키를 더 이상 로그인에 사용하지 못하게 합니다. 인증 제공자의 저장 항목은 별도로 관리해 주세요."
            DEVICE -> "표시된 기기의 연결만 해제하도록 패스키로 인증합니다."
            INVITE -> "현재 가계의 구성원 초대에만 사용할 인증을 진행합니다."
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
            if (mode in setOf(REVOKE, DEVICE)) visibility = View.GONE
            column.addView(this)
        }
        code = label("").apply { setTextIsSelectable(false); isLongClickable = false }
        status = label(if (mode in setOf(REVOKE, DEVICE)) "대상을 확인하고 있어요." else "")
        submit = Button(this).apply {
            text = when (mode) { REVOKE -> "이 패스키 삭제"; DEVICE -> "인증하고 기기 연결 해제"; INVITE -> "인증하고 초대 만들기"; REGISTER -> "패스키 등록"; else -> "패스키 로그인" }
            minimumHeight = 48.dp()
            filterTouchesWhenObscured = true
            isEnabled = mode !in setOf(REVOKE, DEVICE)
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

    private fun loadTarget() {
        if (!ready() || gate != null || targetLoaded || mode !in setOf(REVOKE, DEVICE)) return
        val request = ForegroundRequest().also { gate = it }
        loadTargetPage(request, PasskeyTargetPages(mode == REVOKE, targetId!!, ifMatch!!))
    }

    private fun loadTargetPage(request: ForegroundRequest, pages: PasskeyTargetPages) {
        if (gate !== request || !request.isActive() || !ready()) { request.cancel(); return }
        val path = pages.nextPath ?: return
        auth.request("GET", path, null, request) { outcome -> runOnUiThread {
            if (gate !== request || !request.isActive() || !ready()) { request.cancel(); return@runOnUiThread }
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

    private fun submitNativePasskey() {
        if (!ready() || gate != null || providerOwner != null) return
        invitation?.let {
            val value = it.reveal(SystemClock.elapsedRealtime(), resumed, hasWindowFocus(), !keyguard.isDeviceLocked)
            if (value == null) clearInvitation() else { code.text = value; submit.isEnabled = false }
            return
        }
        if (mode in setOf(REVOKE, DEVICE) && !targetLoaded) return
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
        val operation = when (mode) { LOGIN -> PasskeyOperation.LOGIN; REGISTER -> PasskeyOperation.REGISTER; INVITE -> PasskeyOperation.INVITE; else -> PasskeyOperation.DEVICE_REVOKE }
        auth.beginPasskey(operation, text, targetId, ifMatch, request) { result, pending -> runOnUiThread {
            if (gate !== request || !request.isActive() || !ready()) {
                pending?.discard(); request.cancel(); return@runOnUiThread
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
        auth.finishPasskey(pending, result, request) { outcome, invitation -> runOnUiThread { complete(request, outcome, invitation) } }
    }

    private fun complete(request: ForegroundRequest, outcome: AuthOutcome, received: NativeInvitation?) {
        try {
            if (gate !== request || !request.isActive() || !ready()) { request.cancel(); return }
            cancelPending()
            if (outcome.code != null) { showFailure(outcome.code); return }
            if (mode == INVITE && received != null) {
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
        } finally { received?.discard() }
    }

    private fun providerFailure(owner: NativePasskeyCeremony, code: AuthCode) {
        if (providerOwner !== owner) return
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
        gate?.cancel(); gate = null
        ceremony?.discard(); ceremony = null
        response?.fill('\u0000'); response = null
        val signal = cancellation; cancellation = null; signal?.cancel()
    }

    private fun clearInvitation() {
        handler.removeCallbacks(hideInvitation)
        invitation?.discard(); invitation = null
        if (::code.isInitialized) code.text = ""
        if (createdInvitation && ::submit.isInitialized) submit.isEnabled = false
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
        submit.isEnabled = providerOwner == null && (mode !in setOf(REVOKE, DEVICE) || targetLoaded)
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
            if (gate != null && lifetime?.mayWaitForPresentation() != true) {
                cancelPending(); showFailure(AuthCode.PASSKEY_CANCELLED)
            }
        }
    }

    override fun onPause() {
        resumed = false
        clearInvitation()
        // Credential Manager can temporarily pause this Activity. No response is used until
        // resumed, unlocked and focused; a stopped Activity always cancels the ceremony.
        if (lifetime?.mayWaitForPresentation() != true) close()
        super.onPause()
    }

    override fun onStop() { close(); super.onStop() }
    override fun onSaveInstanceState(outState: Bundle) { cancelPending(); clearInvitation(); super.onSaveInstanceState(outState); outState.clear() }
    override fun onDestroy() {
        cancelPending(); clearInvitation()
        providerOwner = null
        if (::field.isInitialized) field.text.clear()
        if (receiverRegistered) unregisterReceiver(screenReceiver)
        receiverRegistered = false
        super.onDestroy()
    }
    private fun Int.dp(): Int = (this * resources.displayMetrics.density).toInt()
}
