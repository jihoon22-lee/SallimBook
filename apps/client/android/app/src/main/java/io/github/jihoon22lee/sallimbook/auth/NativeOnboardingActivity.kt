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
import java.time.Duration
import java.time.Instant
import java.time.OffsetDateTime

/** First household and partner enrollment. All names/passwords/codes stay in this native
 * form/transport; Activity results contain only authenticated/created/cancelled status. */
class NativeOnboardingActivity : AppCompatActivity() {
    companion object {
        internal const val SETUP = "household-setup"
        internal const val CONNECT = "household-connect"
        internal const val CREATE_CODE = "household-connection-code"
        internal fun enrollment(mode: String?) = mode in setOf(SETUP, CONNECT)
    }
    private val auth by lazy { NativeAuthSession.get(applicationContext) }
    private val appLock by lazy { AppLockController.get(applicationContext) }
    private val keyguard by lazy { getSystemService(KeyguardManager::class.java) }
    private val handler = Handler(Looper.getMainLooper())
    private val fields = mutableListOf<EditText>()
    private val secrets = mutableListOf<CharArray>()
    private var mode = ""
    private var foreground = false
    private var pending: ForegroundRequest? = null
    private var registeredReceiver = false
    private var needsReauthentication = false
    private var createdCode = false
    private var displayedCode: InvitationDisplay? = null
    private lateinit var name: EditText
    private lateinit var password: EditText
    private lateinit var passwordLabel: TextView
    private lateinit var confirmation: EditText
    private lateinit var code: EditText
    private lateinit var codeText: TextView
    private lateinit var status: TextView
    private lateinit var submit: Button
    private val timeout = Runnable { cancelAndFinish() }
    private val hideCode = Runnable { clearCode(true) }
    private val screenOff = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action == Intent.ACTION_SCREEN_OFF) cancelAndFinish()
        }
    }
    private fun ready() = foreground && hasWindowFocus() && !isFinishing && !isDestroyed && !keyguard.isDeviceLocked

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(null)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        setResult(Activity.RESULT_CANCELED)
        val valid = try {
            mode = intent.getStringExtra(NativeAuthActivity.EXTRA_MODE) ?: ""
            !packageManager.getActivityInfo(ComponentName(this, NativeOnboardingActivity::class.java), 0).exported &&
                savedInstanceState == null && auth.available && mode in setOf(SETUP, CONNECT, CREATE_CODE) &&
                intent.extras?.keySet() == setOf(NativeAuthActivity.EXTRA_MODE) && intent.data == null &&
                intent.clipData == null && intent.selector == null && intent.action == null && intent.categories.isNullOrEmpty() &&
                (if (enrollment(mode)) !auth.hasLocalSession() else !appLock.locked && auth.hasLocalSession())
        } catch (_: Exception) { false }
        if (!valid) {
            setResult(Activity.RESULT_CANCELED, Intent().putExtra(NativeAuthActivity.EXTRA_ERROR, AuthCode.ACCESS_DENIED.name))
            finish(); return
        }
        buildUi()
        ContextCompat.registerReceiver(this, screenOff, IntentFilter(Intent.ACTION_SCREEN_OFF), ContextCompat.RECEIVER_NOT_EXPORTED)
        registeredReceiver = true
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() = cancelAndFinish()
        })
    }
    private fun buildUi() {
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; isSaveEnabled = false; filterTouchesWhenObscured = true
            importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
            importantForContentCapture = View.IMPORTANT_FOR_CONTENT_CAPTURE_NO_EXCLUDE_DESCENDANTS
        }
        fun label(text: String) = TextView(this).apply {
            this.text = text; textSize = 17f; isSaveEnabled = false; setPadding(0, 12.dp(), 0, 8.dp())
            column.addView(this)
        }
        fun field(caption: String, secret: Boolean, numeric: Boolean = false, limit: Int = 256): Pair<TextView, EditText> {
            val title = label(caption)
            val input = object : EditText(this) {
                override fun onTextContextMenuItem(id: Int): Boolean = false
            }.apply {
                id = View.generateViewId(); title.labelFor = id; setSingleLine(true)
                inputType = if (numeric) InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_VARIATION_PASSWORD
                    else InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS or
                        if (secret) InputType.TYPE_TEXT_VARIATION_PASSWORD else InputType.TYPE_TEXT_VARIATION_NORMAL
                imeOptions = EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING or EditorInfo.IME_ACTION_NEXT
                filters = arrayOf(InputFilter.LengthFilter(limit))
                isSaveEnabled = false; isSaveFromParentEnabled = false; freezesText = false; isLongClickable = false
                filterTouchesWhenObscured = true; minimumHeight = 48.dp()
                importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO
                importantForContentCapture = View.IMPORTANT_FOR_CONTENT_CAPTURE_NO
                fields.add(this); column.addView(this)
            }
            return title to input
        }
        label(when (mode) { SETUP -> "SallimBook · 처음 시작"; CONNECT -> "SallimBook · 배우자 연결"; else -> "SallimBook · 배우자 연결 코드" }).textSize = 24f
        label(if (mode == CREATE_CODE) "배우자의 시작 화면에 입력할 코드를 만듭니다. 코드는 15분 동안 유효하며 이 화면에서는 최대 30초 표시합니다."
            else "이름과 비밀번호를 정하면 바로 시작합니다. 화면을 벗어나면 비밀번호와 연결 코드를 지웁니다.")
        if (enrollment(mode)) name = field("표시 이름", false, limit = 160).second
        if (mode == CONNECT) code = field("연결 코드 · 숫자 8자리", true, true, 8).second
        val passwordField = field(if (mode == CREATE_CODE) "현재 계정 비밀번호" else "새 비밀번호 · 15~128자", true)
        passwordLabel = passwordField.first; password = passwordField.second
        if (enrollment(mode)) confirmation = field("새 비밀번호 확인", true).second
        else { passwordLabel.visibility = View.GONE; password.visibility = View.GONE }
        codeText = NativeSecretViews.sensitive(label("")).apply { setTextIsSelectable(false); isLongClickable = false; freezesText = false }
        status = label("")
        submit = Button(this).apply {
            text = when (mode) { SETUP -> "가계 만들고 시작"; CONNECT -> "연결하고 시작"; else -> "연결 코드 만들기" }
            minimumHeight = 48.dp(); filterTouchesWhenObscured = true
            setOnClickListener { submitNative() }; column.addView(this)
        }
        column.addView(Button(this).apply {
            text = "닫기"; minimumHeight = 48.dp(); filterTouchesWhenObscured = true
            setOnClickListener { cancelAndFinish() }
        })
        val scroll = ScrollView(this).apply { isSaveEnabled = false; addView(column) }
        ViewCompat.setOnApplyWindowInsetsListener(scroll) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            view.setPadding(bars.left + 20.dp(), bars.top + 12.dp(), bars.right + 20.dp(), bars.bottom + 20.dp()); insets
        }
        setContentView(scroll)
    }
    private fun characters(field: EditText): CharArray = CharArray(field.length()).also {
        field.text.getChars(0, field.length(), it, 0); field.text.clear()
    }
    private fun startRequest(): ForegroundRequest {
        val gate = ForegroundRequest(); pending = gate
        submit.isEnabled = false; status.text = "확인하고 있어요."
        handler.postDelayed(timeout, 60_000)
        return gate
    }
    private fun consume(gate: ForegroundRequest): Boolean {
        val accepted = pending === gate && ready() && try { gate.check(); true } catch (_: Exception) { false }
        if (!accepted) {
            gate.cancel()
            if (pending === gate) {
                pending = null; handler.removeCallbacks(timeout); clearSecrets()
                if (ready()) {
                    submit.isEnabled = true
                    status.text = "요청 상태가 바뀌어 완료 결과를 사용하지 않았어요. 이미 가입했다면 로그인해 주세요."
                }
            }
            return false
        }
        pending = null; handler.removeCallbacks(timeout); clearSecrets(); submit.isEnabled = true
        return true
    }
    private fun submitNative() {
        if (!ready() || pending != null) return
        if (mode == CREATE_CODE) {
            displayedCode?.let {
                codeText.text = it.reveal(SystemClock.elapsedRealtime(), foreground, hasWindowFocus(), !keyguard.isDeviceLocked) ?: ""
                submit.isEnabled = false
                return
            }
            if (needsReauthentication) reauthenticate() else createCode()
            return
        }
        val displayName = name.text.toString().trim()
        val secret = characters(password)
        val confirmed = characters(confirmation)
        val connection = if (mode == CONNECT) characters(code) else null
        val valid = NativeOnboardingPolicy.name(displayName) && NativeOnboardingPolicy.password(secret) &&
            secret.contentEquals(confirmed) && (connection == null || NativeOnboardingPolicy.code(connection))
        confirmed.fill('\u0000')
        if (!valid) {
            secret.fill('\u0000'); connection?.fill('\u0000')
            status.text = "이름, 비밀번호 길이와 확인, 연결 코드를 확인해 주세요."; return
        }
        val gate = startRequest(); secrets.add(secret); connection?.let(secrets::add)
        auth.enrollHousehold(displayName, secret, connection, gate) { outcome -> runOnUiThread {
            if (consume(gate)) {
                if (outcome.code == null) {
                    setResult(Activity.RESULT_OK, Intent().putExtra(NativeAuthActivity.EXTRA_STATUS, "authenticated"))
                    clearInputs(); finish()
                } else status.text = message(outcome.code)
            }
        } }
    }
    private fun reauthenticate() {
        val secret = characters(password)
        if (secret.isEmpty()) { status.text = "현재 비밀번호를 입력해 주세요."; return }
        val gate = startRequest(); secrets.add(secret)
        auth.reauthenticate(secret, gate) { outcome -> runOnUiThread {
            if (consume(gate)) {
                if (outcome.code == null) {
                    needsReauthentication = false
                    password.visibility = View.GONE; passwordLabel.visibility = View.GONE
                    createCode()
                } else status.text = message(outcome.code)
            }
        } }
    }
    private fun createCode() {
        if (!ready() || pending != null || appLock.locked) return
        val gate = startRequest()
        auth.createConnectionCode(gate) { outcome, received -> runOnUiThread {
            try {
                if (consume(gate)) {
                    if (outcome.code == null && received != null) {
                        createdCode = true
                        val now = Instant.now()
                        val expiry = OffsetDateTime.parse(received.expiresAt).toInstant()
                        val remaining = when {
                            expiry <= now -> 0L
                            expiry >= now.plusSeconds(30) -> 30_000L
                            else -> Duration.between(now, expiry).toMillis()
                        }
                        displayedCode = InvitationDisplay(received.code.copyOf(), SystemClock.elapsedRealtime(), remaining)
                        submit.text = "연결 코드 보기"; submit.isEnabled = remaining > 0
                        status.text = "배우자의 연결 화면에 직접 입력해 주세요. 화면을 벗어나면 코드를 지웁니다."
                        handler.postDelayed(hideCode, remaining)
                    } else if (outcome.code == AuthCode.REAUTHENTICATION_REQUIRED) {
                        needsReauthentication = true
                        passwordLabel.visibility = View.VISIBLE; password.visibility = View.VISIBLE
                        submit.text = "비밀번호 확인 후 코드 만들기"; status.text = message(outcome.code)
                    } else status.text = message(outcome.code ?: AuthCode.AUTH_UNAVAILABLE)
                }
            } finally { received?.discard() }
        } }
    }
    private fun clearSecrets() { secrets.forEach { it.fill('\u0000') }; secrets.clear() }
    private fun clearCode(expired: Boolean = false) {
        handler.removeCallbacks(hideCode); displayedCode?.discard(); displayedCode = null
        if (::codeText.isInitialized) codeText.text = ""
        if (expired && ::submit.isInitialized) {
            submit.text = "연결 코드 다시 만들기"; submit.isEnabled = pending == null
            status.text = "코드를 지웠어요. 필요하면 새 코드를 만들어 주세요."
        }
    }
    private fun clearInputs() { fields.forEach { it.text.clear() }; clearSecrets(); clearCode() }
    private fun cancelAndFinish() {
        pending?.cancel(); pending = null; handler.removeCallbacks(timeout); clearInputs()
        if (createdCode) setResult(Activity.RESULT_OK, Intent().putExtra(NativeAuthActivity.EXTRA_STATUS, "created"))
        else setResult(Activity.RESULT_CANCELED)
        if (!isFinishing) finish()
    }
    override fun onResume() { super.onResume(); foreground = true; if (keyguard.isDeviceLocked) cancelAndFinish() }
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (!hasFocus) {
            val interrupted = pending != null
            pending?.cancel(); pending = null; handler.removeCallbacks(timeout)
            fields.forEach { it.text.clear() }; clearSecrets(); clearCode(createdCode)
            if (::submit.isInitialized) submit.isEnabled = true
            if (interrupted && ::status.isInitialized) status.text = "요청을 중단했어요. 이미 가입됐다면 로그인 화면에서 다시 확인해 주세요."
        }
    }
    override fun onPause() {
        foreground = false; pending?.cancel(); pending = null; clearInputs(); handler.removeCallbacks(timeout)
        if (!isFinishing) cancelAndFinish()
        super.onPause()
    }
    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); cancelAndFinish() }
    override fun onSaveInstanceState(outState: Bundle) { clearInputs(); super.onSaveInstanceState(outState); outState.clear() }
    override fun onDestroy() {
        pending?.cancel(); clearInputs(); handler.removeCallbacksAndMessages(null)
        if (registeredReceiver) unregisterReceiver(screenOff)
        super.onDestroy()
    }
    private fun message(code: AuthCode): String = when (code) {
        AuthCode.SETUP_UNAVAILABLE -> "이 연결에서는 처음 시작할 수 없어요. 허용된 사설 연결을 확인해 주세요."
        AuthCode.SETUP_COMPLETE -> "이미 시작한 가계가 있어요. 로그인하거나 배우자 연결을 이용해 주세요."
        AuthCode.INVALID_CONNECTION_CODE -> "연결 코드가 올바르지 않거나 만료됐어요. 새 코드를 확인해 주세요."
        AuthCode.HOUSEHOLD_FULL -> "이미 두 사람이 연결되어 있어요. 기존 계정으로 로그인해 주세요."
        AuthCode.REGISTRATION_CONFLICT, AuthCode.LOGIN_UNAVAILABLE -> "가입 상태가 변경됐어요. 이미 가입했다면 로그인해 주세요."
        AuthCode.RATE_LIMITED -> "요청이 많아요. 잠시 후 다시 시도해 주세요."
        AuthCode.REAUTHENTICATION_REQUIRED -> "연결 코드를 만들려면 현재 계정 비밀번호를 다시 확인해 주세요."
        AuthCode.AUTH_FAILED -> "현재 비밀번호를 확인해 주세요."
        AuthCode.VALIDATION_ERROR, AuthCode.INVALID_REQUEST -> "입력 항목을 확인해 주세요."
        AuthCode.NETWORK_UNAVAILABLE -> "연결을 확인하지 못했어요. 이미 가입됐다면 로그인해 주세요. 자동 재전송은 하지 않았어요."
        AuthCode.SESSION_EXPIRED -> "로그인이 만료됐어요. 화면을 닫고 다시 로그인해 주세요."
        AuthCode.KEY_INVALIDATED -> "기기에 로그인을 안전하게 저장하지 못했어요. 로그인 화면에서 다시 확인해 주세요."
        AuthCode.AUTH_CANCELLED, AuthCode.APP_LOCKED -> "요청이 취소됐어요. 결과를 확인한 후 다시 진행해 주세요."
        else -> "요청을 완료하지 못했어요. 연결과 현재 가계 상태를 확인해 주세요."
    }
    private fun Int.dp() = (this * resources.displayMetrics.density).toInt()
}
