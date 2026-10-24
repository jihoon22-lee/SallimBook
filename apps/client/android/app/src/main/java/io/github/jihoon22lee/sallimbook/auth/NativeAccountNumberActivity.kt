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
import android.widget.CheckBox
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import org.json.JSONObject

/** Number forms and plaintext display have no JS, Intent-result or saved-state representation. */
class NativeAccountNumberActivity : AppCompatActivity() {
    companion object {
        internal const val EDIT = "account-number-edit"
        internal const val SHOW = "account-number-show"
    }
    private val auth by lazy { NativeAuthSession.get(applicationContext) }
    private val keyguard by lazy { getSystemService(KeyguardManager::class.java) }
    private val handler = Handler(Looper.getMainLooper())
    private var mode = ""
    private var startedSignedIn = false
    private var accountId = ""
    private var ifMatch: String? = null
    private var resumed = false
    private var hadFocus = false
    private var loaded = false
    private var gate: ForegroundRequest? = null
    private var pendingNumber: CharArray? = null
    private var display: AccountNumberDisplay? = null
    private var shown = false
    private lateinit var status: TextView
    private lateinit var output: TextView
    private lateinit var input: EditText
    private lateinit var action: Button
    private lateinit var delete: Button
    private lateinit var confirmDelete: CheckBox
    private var receiverRegistered = false
    private val expire = Runnable { clearNumber(); status.text = "표시 시간이 끝났어요. 다시 보려면 화면을 닫고 새로 요청해 주세요." }
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
        accountId = intent.getStringExtra(NativePasskeyActivity.EXTRA_ID) ?: ""
        ifMatch = intent.getStringExtra(NativePasskeyActivity.EXTRA_VERSION)
        val internal = try { !packageManager.getActivityInfo(ComponentName(this, NativeAccountNumberActivity::class.java), 0).exported }
            catch (_: Exception) { false }
        val fields = setOf(NativeAuthActivity.EXTRA_MODE, NativePasskeyActivity.EXTRA_ID) +
            if (mode == EDIT) setOf(NativePasskeyActivity.EXTRA_VERSION) else emptySet()
        if (!internal || savedInstanceState != null || !auth.available || mode !in setOf(EDIT, SHOW) ||
            !PasskeyPolicy.uuid.matches(accountId) || mode == EDIT && !PasskeyPolicy.target(accountId, ifMatch) ||
            intent.extras?.keySet() != fields) {
            setResult(Activity.RESULT_CANCELED, Intent().putExtra(NativeAuthActivity.EXTRA_ERROR, AuthCode.AUTH_UNAVAILABLE.name))
            finish(); return
        }
        buildUi()
        ContextCompat.registerReceiver(this, screenReceiver, IntentFilter(Intent.ACTION_SCREEN_OFF), ContextCompat.RECEIVER_NOT_EXPORTED)
        receiverRegistered = true
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) {
            override fun handleOnBackPressed() = close()
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
            this.text = text; textSize = 17f; isSaveEnabled = false; freezesText = false
            setTextIsSelectable(false); isLongClickable = false
            setPadding(0, 12.dp(), 0, 12.dp()); column.addView(this)
        }
        label(if (mode == EDIT) "SallimBook · 계좌번호 입력" else "SallimBook · 계좌번호 보기").textSize = 24f
        label("이 화면을 벗어나면 입력과 표시를 지웁니다. 계좌번호는 서버에서 암호화하여 보관합니다.")
        status = label("계좌를 확인하고 있어요.")
        output = NativeSecretViews.sensitive(label(""))
        input = object : EditText(this) {
            override fun onTextContextMenuItem(id: Int): Boolean = false
        }.apply {
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            imeOptions = EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING
            isSaveEnabled = false; isSaveFromParentEnabled = false; freezesText = false
            importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO
            importantForContentCapture = View.IMPORTANT_FOR_CONTENT_CAPTURE_NO
            isLongClickable = false; filterTouchesWhenObscured = true
            filters = arrayOf(InputFilter.LengthFilter(64)); setSingleLine(true)
            hint = "새 계좌번호 · 영문/숫자, 공백·하이픈 가능"
            minimumHeight = 48.dp()
            if (mode != EDIT) visibility = View.GONE
            column.addView(this)
        }
        fun button(text: String, click: () -> Unit) = Button(this).apply {
            this.text = text; minimumHeight = 48.dp(); filterTouchesWhenObscured = true
            setOnClickListener { click() }; column.addView(this)
        }
        action = button(if (mode == EDIT) "번호 저장" else "최대 30초 표시") {
            if (mode == EDIT) writeNumber(false) else reveal()
        }.apply { isEnabled = false }
        confirmDelete = CheckBox(this).apply {
            text = "저장된 계좌번호를 삭제할게요"
            isSaveEnabled = false; filterTouchesWhenObscured = true
            if (mode != EDIT) visibility = View.GONE
            column.addView(this)
        }
        delete = button("계좌번호 삭제") { writeNumber(true) }.apply {
            isEnabled = false; if (mode != EDIT) visibility = View.GONE
        }
        button("닫기", ::close)
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
        gate = null; pendingNumber?.fill('\u0000'); pendingNumber = null
        NativeSessionEnd.close(this)
    }

    private fun load() {
        if (!ready() || loaded || gate != null) return
        val request = ForegroundRequest().also { gate = it }
        auth.finance(FinanceOperation.GET_ACCOUNT, JSONObject().put("accountId", accountId), request) { outcome -> runOnUiThread {
            if (gate !== request || !request.isActive() || !ready()) {
                request.cancel(); closeIfSignedOut(gate === request); return@runOnUiThread
            }
            gate = null
            val account = outcome.value?.get("body") as? Map<*, *>
            if (outcome.code != null || outcome.value?.get("status") != 200 || account == null) {
                failure(outcome.code ?: AuthCode.ACCESS_DENIED); return@runOnUiThread
            }
            if (mode == EDIT && "\"${account["version"]}\"" != ifMatch) {
                failure(AuthCode.VERSION_CONFLICT); return@runOnUiThread
            }
            loaded = true
            val asset = account["asset"] as Map<*, *>
            status.text = "${asset["name"]} · ${account["institution_name"]}\n${account["masked_number"] ?: "등록된 번호 없음"}"
            action.isEnabled = mode == EDIT || account["has_number"] == true
            delete.isEnabled = mode == EDIT && account["has_number"] == true
        } }
    }

    private fun writeNumber(remove: Boolean) {
        if (!ready() || !loaded || gate != null) return
        if (remove && !confirmDelete.isChecked) { status.text = "삭제 확인 항목에 표시한 뒤 진행해 주세요."; return }
        val number = if (remove) null else CharArray(input.length()).also { input.text.getChars(0, input.length(), it, 0) }
        if (number != null && !FinancePolicy.number(number)) {
            number.fill('\u0000'); input.text.clear(); status.text = "계좌번호 형식과 길이를 확인해 주세요."; return
        }
        input.text.clear(); pendingNumber = number
        action.isEnabled = false; delete.isEnabled = false
        val request = ForegroundRequest().also { gate = it }
        status.text = "요청을 처리하고 있어요."
        auth.editAccountNumber(accountId, ifMatch!!, number, request) { outcome -> runOnUiThread {
            if (gate !== request || !request.isActive() || !ready()) {
                request.cancel(); closeIfSignedOut(gate === request); return@runOnUiThread
            }
            gate = null; pendingNumber?.fill('\u0000'); pendingNumber = null
            if (outcome.code != null) { failure(outcome.code); return@runOnUiThread }
            setResult(Activity.RESULT_OK, Intent().putExtra(NativeAuthActivity.EXTRA_STATUS, if (remove) "deleted" else "saved"))
            finish()
        } }
    }

    private fun reveal() {
        if (!ready() || !loaded || gate != null || shown) return
        action.isEnabled = false
        val request = ForegroundRequest().also { gate = it }
        auth.revealAccountNumber(accountId, request) { outcome, number -> runOnUiThread {
            try {
                if (gate !== request || !request.isActive() || !ready()) {
                    request.cancel(); closeIfSignedOut(gate === request); return@runOnUiThread
                }
                gate = null
                if (outcome.code != null || number == null) { failure(outcome.code ?: AuthCode.ACCESS_DENIED); return@runOnUiThread }
                val now = SystemClock.elapsedRealtime()
                display = AccountNumberDisplay(number.number.copyOf(), now)
                output.text = display?.reveal(now, resumed, hasWindowFocus(), !keyguard.isDeviceLocked) ?: ""
                shown = true
                status.text = "최대 30초 동안 표시합니다. 화면을 벗어나면 즉시 지웁니다."
                handler.postDelayed(expire, 30_000)
            } finally { number?.discard() }
        } }
    }

    private fun failure(code: AuthCode) {
        if (!::status.isInitialized) return
        setResult(Activity.RESULT_CANCELED, Intent().putExtra(NativeAuthActivity.EXTRA_ERROR, code.name))
        status.text = when (code) {
            AuthCode.VERSION_CONFLICT -> "다른 기기에서 계좌를 수정했어요. 이 화면을 닫고 최신 내용을 다시 확인해 주세요."
            AuthCode.REAUTHENTICATION_REQUIRED, AuthCode.SESSION_EXPIRED -> "현재 계정을 다시 인증한 뒤 열어 주세요. 패스키 인증으로도 번호를 볼 수 있어요."
            AuthCode.NETWORK_UNAVAILABLE, AuthCode.AUTH_CANCELLED -> "처리 결과를 확인할 수 없어요. 자동 재전송하지 않았으니 화면을 닫고 계좌를 새로 조회해 주세요."
            else -> "계좌번호를 처리할 수 없어요. 화면을 닫고 계좌 상태와 서버 보호 설정을 확인해 주세요."
        }
        action.isEnabled = false; delete.isEnabled = false
    }

    private fun clearNumber() {
        handler.removeCallbacks(expire)
        pendingNumber?.fill('\u0000'); pendingNumber = null
        display?.discard(); display = null
        if (::input.isInitialized) input.text.clear()
        if (::output.isInitialized) output.text = ""
    }
    private fun close() {
        gate?.cancel(); gate = null; clearNumber()
        if (shown) setResult(Activity.RESULT_OK, Intent().putExtra(NativeAuthActivity.EXTRA_STATUS, "completed"))
        if (!isFinishing) finish()
    }
    override fun onResume() { super.onResume(); resumed = true; if (keyguard.isDeviceLocked) close() }
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) { hadFocus = true; load() } else if (hadFocus) close() else clearNumber()
    }
    override fun onPause() { resumed = false; close(); super.onPause() }
    override fun onSaveInstanceState(outState: Bundle) { clearNumber(); gate?.cancel(); super.onSaveInstanceState(outState); outState.clear() }
    override fun onDestroy() {
        gate?.cancel(); clearNumber()
        if (receiverRegistered) unregisterReceiver(screenReceiver)
        receiverRegistered = false; super.onDestroy()
    }
    private fun Int.dp(): Int = (this * resources.displayMetrics.density).toInt()
}
