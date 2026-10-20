package io.github.jihoon22lee.sallimbook.auth

import android.app.Activity
import android.app.KeyguardManager
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Bundle
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
import java.time.Instant

/** Must be registered exported=false. No credential is an Intent extra or Activity result.
 * Background/recreation cancels the form; JVM/build checks do not prove physical UI privacy.
 */
class NativeAuthActivity : AppCompatActivity() {
    companion object {
        internal const val EXTRA_MODE = "sallimbook.auth.mode"
        internal const val EXTRA_STATUS = "sallimbook.auth.status"
        internal const val EXTRA_ERROR = "sallimbook.auth.error"
        internal const val LOGIN = "login"
        internal const val REAUTHENTICATE = "reauthenticate"
        internal const val INVITATION = "invitation"
        internal const val CREATE_INVITATION = "create-invitation"
        internal const val CHANGE_PASSWORD = "change-password"
        internal const val SIGN_OUT_OTHERS = "sign-out-others"
    }

    private val auth by lazy { NativeAuthSession.get(applicationContext) }
    private val keyguard by lazy { getSystemService(KeyguardManager::class.java) }
    private var foreground = false
    private var pending: ForegroundRequest? = null
    private var mode = LOGIN
    private val inputs = mutableListOf<EditText>()
    private val secretInputs = mutableListOf<EditText>()
    private val pendingSecrets = mutableListOf<CharArray>()
    private lateinit var identity: EditText
    private lateinit var password: EditText
    private lateinit var newPassword: EditText
    private lateinit var passwordConfirmation: EditText
    private lateinit var displayName: EditText
    private lateinit var status: TextView
    private lateinit var submit: Button
    private lateinit var close: Button
    private var invitationText: TextView? = null
    private var createdInvitation = false
    private var invitationDisplay: InvitationDisplay? = null
    private val handler = Handler(Looper.getMainLooper())
    private val expireInvitation = Runnable { clearInvitationDisplay(true) }
    private var screenReceiverRegistered = false
    private val screenReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action == Intent.ACTION_SCREEN_OFF) cancelAndFinish()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(null)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        setResult(Activity.RESULT_CANCELED)
        val notExported = try {
            !packageManager.getActivityInfo(ComponentName(this, NativeAuthActivity::class.java), 0).exported
        } catch (_: Exception) { false }
        mode = intent.getStringExtra(EXTRA_MODE) ?: ""
        if (savedInstanceState != null || !notExported || !auth.available ||
            mode !in setOf(LOGIN, REAUTHENTICATE, INVITATION, CREATE_INVITATION, CHANGE_PASSWORD, SIGN_OUT_OTHERS) || intent.extras?.keySet() != setOf(EXTRA_MODE)) {
            setResult(Activity.RESULT_CANCELED, Intent().putExtra(EXTRA_ERROR, AuthCode.AUTH_UNAVAILABLE.name))
            finish()
            return
        }
        buildUi()
        ContextCompat.registerReceiver(this, screenReceiver, IntentFilter(Intent.ACTION_SCREEN_OFF),
            ContextCompat.RECEIVER_NOT_EXPORTED)
        screenReceiverRegistered = true
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() { cancelAndFinish() }
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
        fun label(text: String, size: Float = 16f) = TextView(this).apply {
            this.text = text
            textSize = size
            isSaveEnabled = false
            setPadding(0, 12.dp(), 0, 8.dp())
            column.addView(this)
        }
        fun field(caption: String, secret: Boolean, maxLength: Int): EditText {
            val title = label(caption)
            return EditText(this).apply {
                id = View.generateViewId()
                title.labelFor = id
                setSingleLine(true)
                inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS or
                    if (secret) InputType.TYPE_TEXT_VARIATION_PASSWORD else InputType.TYPE_TEXT_VARIATION_NORMAL
                imeOptions = EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING or EditorInfo.IME_ACTION_NEXT
                filters = arrayOf(InputFilter.LengthFilter(maxLength))
                isSaveEnabled = false
                isSaveFromParentEnabled = false
                freezesText = false
                isLongClickable = false
                filterTouchesWhenObscured = true
                importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO
                importantForContentCapture = View.IMPORTANT_FOR_CONTENT_CAPTURE_NO
                minimumHeight = 48.dp()
                inputs.add(this)
                if (secret) secretInputs.add(this)
                column.addView(this)
            }
        }
        label(when (mode) {
            LOGIN -> "SallimBook · 로그인"
            REAUTHENTICATE -> "SallimBook · 현재 계정 다시 인증"
            CREATE_INVITATION -> "SallimBook · 구성원 초대"
            CHANGE_PASSWORD -> "SallimBook · 비밀번호 변경"
            SIGN_OUT_OTHERS -> "SallimBook · 다른 기기 모두 로그아웃"
            else -> "SallimBook · 초대 수락"
        }, 24f)
        label("이 화면을 벗어나면 입력한 비밀번호와 초대 코드를 지웁니다.")
        if (mode in setOf(CHANGE_PASSWORD, SIGN_OUT_OTHERS)) {
            label("이 기기를 뺀 내 다른 기기는 모두 로그아웃돼요. 등록한 패스키는 그대로 유지돼요.")
        }
        if (mode == LOGIN) {
            label("처음 시작에서 만든 계정은 아래에서 선택하세요. 기존 계정은 로그인 이름을 직접 입력할 수 있어요.")
            column.addView(LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                for ((caption, login) in listOf("처음 시작한 사람" to "owner", "연결한 배우자" to "partner")) {
                    addView(Button(this@NativeAuthActivity).apply {
                        text = caption; minimumHeight = 48.dp(); filterTouchesWhenObscured = true
                        setOnClickListener {
                            if (this@NativeAuthActivity.foreground && this@NativeAuthActivity.hasWindowFocus() && pending == null) {
                                identity.setText(login); password.requestFocus()
                            }
                        }
                    }, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
                }
            })
        }
        if (mode !in setOf(REAUTHENTICATE, CHANGE_PASSWORD, SIGN_OUT_OTHERS)) identity = field(when (mode) {
            LOGIN -> "로그인 이름"
            CREATE_INVITATION -> "초대할 구성원의 로그인 이름"
            else -> "초대 코드"
        }, mode == INVITATION, if (mode == INVITATION) 128 else 64)
        if (mode != CREATE_INVITATION) {
            password = field(when (mode) {
                LOGIN, REAUTHENTICATE, SIGN_OUT_OTHERS -> "비밀번호"
                CHANGE_PASSWORD -> "현재 비밀번호"
                else -> "새 비밀번호 · 15자 이상"
            }, true, 128)
        }
        if (mode == CHANGE_PASSWORD) newPassword = field("새 비밀번호 · 15자 이상", true, 128)
        if (mode in setOf(INVITATION, CHANGE_PASSWORD)) passwordConfirmation = field("새 비밀번호 확인", true, 128)
        if (mode == INVITATION) displayName = field("표시 이름", false, 80)
        if (mode == CREATE_INVITATION) {
            invitationText = NativeSecretViews.sensitive(label("")).apply { setTextIsSelectable(false); isLongClickable = false; freezesText = false }
        }
        status = label("")
        submit = Button(this).apply {
            text = when (mode) {
                LOGIN -> "로그인"; REAUTHENTICATE -> "다시 인증"; CREATE_INVITATION -> "초대 만들기"
                CHANGE_PASSWORD -> "비밀번호 변경"; SIGN_OUT_OTHERS -> "다른 기기 로그아웃"; else -> "초대 수락"
            }
            minimumHeight = 48.dp()
            filterTouchesWhenObscured = true
            setOnClickListener { submitNative() }
            column.addView(this)
        }
        close = Button(this).apply {
            text = "취소"
            minimumHeight = 48.dp()
            filterTouchesWhenObscured = true
            setOnClickListener { cancelAndFinish() }
            column.addView(this)
        }
        val scroll = ScrollView(this).apply { isSaveEnabled = false; addView(column) }
        ViewCompat.setOnApplyWindowInsetsListener(scroll) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            view.setPadding(bars.left + 20.dp(), bars.top + 12.dp(), bars.right + 20.dp(), bars.bottom + 20.dp())
            insets
        }
        setContentView(scroll)
    }

    private fun submitNative() {
        if (!foreground || !hasWindowFocus() || keyguard.isDeviceLocked || pending != null) return
        if (mode == CREATE_INVITATION && invitationDisplay != null) {
            val code = invitationDisplay?.reveal(SystemClock.elapsedRealtime(), foreground,
                hasWindowFocus(), !keyguard.isDeviceLocked)
            if (code == null) clearInvitationDisplay(true)
            else {
                invitationText?.text = code
                submit.isEnabled = false
                status.text = "받는 사람이 자신의 네이티브 초대 수락 화면에 직접 입력해 주세요.\n최대 30초 후 또는 화면에서 벗어나면 코드를 지웁니다."
            }
            return
        }
        if (mode in setOf(CHANGE_PASSWORD, SIGN_OUT_OTHERS)) { submitAccount(); return }
        val identifier = if (mode == REAUTHENTICATE) "" else identity.text.toString().trim()
        if (mode == CREATE_INVITATION) { createNativeInvitation(identifier); return }
        val secret = CharArray(password.length()).also { password.text.getChars(0, password.length(), it, 0) }
        val confirmation = if (mode == INVITATION) CharArray(passwordConfirmation.length()).also {
            passwordConfirmation.text.getChars(0, passwordConfirmation.length(), it, 0)
            passwordConfirmation.text.clear()
        } else null
        val passwordsMatch = confirmation == null || secret.contentEquals(confirmation)
        confirmation?.fill('\u0000')
        val name = if (mode == INVITATION) displayName.text.toString().trim() else ""
        val valid = if (mode == REAUTHENTICATE) secret.isNotEmpty() else if (mode == LOGIN) {
            Regex("[A-Za-z][A-Za-z0-9_.-]{2,63}").matches(identifier) && secret.isNotEmpty()
        } else {
            Regex("[A-Za-z0-9_-]{32,128}").matches(identifier) && secret.size >= 15 && name.isNotEmpty() && passwordsMatch
        }
        if (!valid) {
            secret.fill('\u0000')
            password.text.clear()
            status.text = "입력 항목을 확인해 주세요."
            return
        }
        val gate = ForegroundRequest()
        pending = gate
        pendingSecrets.add(secret)
        password.text.clear()
        if (mode == INVITATION) identity.text.clear()
        submit.isEnabled = false
        status.text = "확인하고 있어요."
        val completion = completion(gate, if (mode in setOf(LOGIN, REAUTHENTICATE)) "authenticated" else "accepted",
            NativeAuthMessages::message)
        if (mode == LOGIN) auth.login(identifier, secret, "Android", gate, completion)
        else if (mode == REAUTHENTICATE) auth.reauthenticate(secret, gate, completion)
        else {
            val invitation = identifier.toCharArray()
            pendingSecrets.add(invitation)
            auth.acceptInvitation(invitation, secret, name, gate, completion)
        }
    }

    private fun completion(gate: ForegroundRequest, success: String, failure: (AuthCode) -> String): (AuthOutcome) -> Unit = { outcome ->
        runOnUiThread {
            if (pending === gate && gate.isActive() && foreground && hasWindowFocus() && !keyguard.isDeviceLocked &&
                !isFinishing && !isDestroyed) {
                pending = null
                clearSecretBuffers()
                submit.isEnabled = true
                if (outcome.code == null) {
                    setResult(Activity.RESULT_OK, Intent().putExtra(EXTRA_STATUS, success))
                    clearInputs()
                    finish()
                } else status.text = failure(outcome.code)
            } else gate.cancel()
        }
    }

    private fun submitAccount() {
        fun read(input: EditText) = CharArray(input.length()).also { input.text.getChars(0, input.length(), it, 0) }
        val current = read(password)
        val next = if (mode == CHANGE_PASSWORD) read(newPassword) else null
        val confirmation = if (mode == CHANGE_PASSWORD) read(passwordConfirmation) else null
        inputs.forEach { it.text.clear() }
        val problem = when {
            current.isEmpty() -> "현재 비밀번호를 입력해 주세요."
            next == null -> null
            Character.codePointCount(next, 0, next.size) < 15 -> "새 비밀번호는 15자 이상으로 정해 주세요."
            !next.contentEquals(confirmation) -> "새 비밀번호와 확인 입력이 달라요."
            next.contentEquals(current) -> "현재 비밀번호와 다른 새 비밀번호를 입력해 주세요."
            else -> null
        }
        confirmation?.fill('\u0000')
        if (problem != null) {
            current.fill('\u0000'); next?.fill('\u0000')
            status.text = problem
            return
        }
        val gate = ForegroundRequest()
        pending = gate
        pendingSecrets.add(current); next?.let(pendingSecrets::add)
        submit.isEnabled = false
        status.text = "확인하고 있어요."
        val done = completion(gate, if (next == null) "revoked" else "changed") {
            NativeAuthMessages.accountMessage(it, next != null)
        }
        if (next == null) auth.revokeOtherDevices(current, gate, done) else auth.changePassword(current, next, gate, done)
    }

    private fun createNativeInvitation(identifier: String) {
        if (!Regex("[A-Za-z][A-Za-z0-9_.-]{2,63}").matches(identifier)) {
            status.text = "초대할 구성원의 로그인 이름을 확인해 주세요."
            return
        }
        val gate = ForegroundRequest()
        pending = gate
        submit.isEnabled = false
        status.text = "초대를 만들고 있어요."
        auth.createInvitation(identifier, gate) { outcome, invitation ->
            runOnUiThread {
                try {
                    if (pending === gate && gate.isActive() && foreground && hasWindowFocus() && !keyguard.isDeviceLocked &&
                        !isFinishing && !isDestroyed) {
                        pending = null
                        if (outcome.code == null && invitation != null) {
                            createdInvitation = true
                            identity.isEnabled = false
                            val now = Instant.now()
                            val expiry = java.time.OffsetDateTime.parse(invitation.expiresAt).toInstant()
                            val remaining = when {
                                expiry <= now -> 0L
                                expiry >= now.plusSeconds(30) -> 30_000L
                                else -> java.time.Duration.between(now, expiry).toMillis()
                            }
                            invitationDisplay = InvitationDisplay(invitation.token.copyOf(),
                                SystemClock.elapsedRealtime(), remaining)
                            submit.text = "초대 코드 보기"
                            submit.isEnabled = remaining > 0
                            status.text = "초대 코드는 최대 30초 동안 이 화면에서 확인할 수 있어요."
                            handler.postDelayed(expireInvitation, remaining)
                            close.text = "닫기"
                        } else {
                            submit.isEnabled = true
                            status.text = NativeAuthMessages.message(outcome.code ?: AuthCode.AUTH_UNAVAILABLE)
                        }
                    } else {
                        gate.cancel()
                        if (!isFinishing && !isDestroyed) {
                            status.text = "화면을 벗어나 초대 코드를 지웠어요. 다시 초대를 만들어 주세요."
                        }
                    }
                } finally { invitation?.discard() }
            }
        }
    }

    private fun clearSecretBuffers() { pendingSecrets.forEach { it.fill('\u0000') }; pendingSecrets.clear() }
    private fun clearInvitationDisplay(expired: Boolean = false) {
        handler.removeCallbacks(expireInvitation)
        invitationDisplay?.discard()
        invitationDisplay = null
        invitationText?.text = ""
        if (expired && ::status.isInitialized) {
            status.text = "초대 코드를 지웠어요. 필요하면 다시 초대를 만들어 주세요."
            submit.text = "초대 다시 만들기"
            submit.isEnabled = true
            identity.isEnabled = true
        }
    }

    private fun clearInputs() { inputs.forEach { it.text.clear() }; clearInvitationDisplay(); clearSecretBuffers() }

    private fun cancelAndFinish() {
        pending?.cancel()
        pending = null
        clearInputs()
        if (createdInvitation) setResult(Activity.RESULT_OK, Intent().putExtra(EXTRA_STATUS, "created"))
        else setResult(Activity.RESULT_CANCELED)
        if (!isFinishing) finish()
    }

    override fun onResume() {
        super.onResume()
        foreground = true
        if (keyguard.isDeviceLocked) cancelAndFinish()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (!hasFocus) {
            val interrupted = pending != null
            pending?.cancel()
            pending = null
            clearSecretBuffers()
            // Every secret field (current, new and confirmation passwords, invitation code).
            secretInputs.forEach { it.text.clear() }
            clearInvitationDisplay(createdInvitation)
            if (::submit.isInitialized) submit.isEnabled = true
            if (interrupted && ::status.isInitialized) status.text = "화면을 벗어나 요청을 중단했어요. 결과를 확인한 후 다시 진행해 주세요."
        }
    }

    override fun onPause() {
        foreground = false
        pending?.cancel()
        pending = null
        clearInputs()
        if (!isFinishing) cancelAndFinish()
        super.onPause()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        clearInputs()
        super.onSaveInstanceState(outState)
        outState.clear()
    }

    override fun onDestroy() {
        pending?.cancel()
        clearInputs()
        if (screenReceiverRegistered) unregisterReceiver(screenReceiver)
        screenReceiverRegistered = false
        super.onDestroy()
    }

    private fun Int.dp(): Int = (this * resources.displayMetrics.density).toInt()
}
