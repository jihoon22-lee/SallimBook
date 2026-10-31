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
import android.text.InputFilter
import android.text.InputType
import android.text.Editable
import android.text.TextWatcher
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

/** A foreground native form, independent of the legacy client-encrypted vault. */
class NativeCardDetailsActivity : AppCompatActivity() {
    companion object { internal const val MODE = "stored-card-details"; internal const val EXTRA_ACTION = "stored-card-action" }
    private val auth by lazy { NativeAuthSession.get(applicationContext) }
    private val appLock by lazy { AppLockController.get(applicationContext) }
    private val keyguard by lazy { getSystemService(KeyguardManager::class.java) }
    private val handler = Handler(Looper.getMainLooper())
    private var action = ""
    private var cardId = ""
    private var resumed = false
    private var hadFocus = false
    private var loaded = false
    private var receiverRegistered = false
    private var version: Long? = null
    private var gate: ForegroundRequest? = null
    private var pending: NativeStoredCard? = null
    private var completed = false
    private lateinit var status: TextView
    private lateinit var output: TextView
    private lateinit var pan: EditText
    private lateinit var year: EditText
    private lateinit var month: EditText
    private lateinit var cvc: EditText
    private lateinit var submit: Button
    private lateinit var confirm: CheckBox
    private val expire = Runnable { close() }
    private val screenReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) { if (intent?.action == Intent.ACTION_SCREEN_OFF) close() }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(null)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        setResult(Activity.RESULT_CANCELED)
        action = intent.getStringExtra(EXTRA_ACTION) ?: ""
        cardId = intent.getStringExtra(NativePasskeyActivity.EXTRA_ID) ?: ""
        val internal = try { !packageManager.getActivityInfo(ComponentName(this, NativeCardDetailsActivity::class.java), 0).exported } catch (_: Exception) { false }
        if (!internal || savedInstanceState != null || !auth.available || !auth.hasLocalSession() || appLock.locked ||
            !NativeStoredCardPolicy.entry(mapOf("action" to action, "cardId" to cardId)) ||
            intent.getStringExtra(NativeAuthActivity.EXTRA_MODE) != MODE ||
            intent.extras?.keySet() != setOf(NativeAuthActivity.EXTRA_MODE, NativePasskeyActivity.EXTRA_ID, EXTRA_ACTION)) {
            finish(); return
        }
        buildUi()
        ContextCompat.registerReceiver(this, screenReceiver, IntentFilter(Intent.ACTION_SCREEN_OFF), ContextCompat.RECEIVER_NOT_EXPORTED)
        receiverRegistered = true
        onBackPressedDispatcher.addCallback(this, object : OnBackPressedCallback(true) { override fun handleOnBackPressed() = close() })
    }
    private fun buildUi() {
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL; isSaveEnabled = false; filterTouchesWhenObscured = true
            importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
            importantForContentCapture = View.IMPORTANT_FOR_CONTENT_CAPTURE_NO_EXCLUDE_DESCENDANTS
        }
        fun label(text: String) = TextView(this).apply {
            this.text = text; textSize = 17f; isSaveEnabled = false; isSaveFromParentEnabled = false; freezesText = false
            setTextIsSelectable(false); isLongClickable = false; setPadding(0, 12.dp(), 0, 12.dp()); column.addView(this)
        }
        label(when(action) { "edit" -> "카드 정보 입력"; "delete" -> "저장된 카드 정보 삭제"; else -> "카드 정보 보기" }).textSize = 24f
        label("별도 보관함 암호 없이 로그인한 부부가 조회합니다. 서버에서 암호화하여 저장하며, 화면을 벗어나면 입력과 표시를 지웁니다.")
        status = label("카드를 확인하고 있어요.")
        output = NativeSecretViews.sensitive(label(""))
        fun field(hint: String, maximum: Int): EditText = NativeSecretViews.sensitive(object : EditText(this) {
            override fun onTextContextMenuItem(id: Int): Boolean = false
        }.apply {
            this.hint = hint
            isEnabled = false
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            imeOptions = EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING
            isSaveEnabled = false; isSaveFromParentEnabled = false; freezesText = false
            importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO; importantForContentCapture = View.IMPORTANT_FOR_CONTENT_CAPTURE_NO
            isLongClickable = false; filterTouchesWhenObscured = true; setSingleLine(true)
            filters = arrayOf(InputFilter.LengthFilter(maximum)); minimumHeight = 48.dp()
            if (action != "edit") visibility = View.GONE
            column.addView(this)
        })
        pan = field("카드번호 · 공백·하이픈 가능", 64)
        year = field("유효기간 연도 · 예: 2030", 4)
        month = field("유효기간 월 · 1~12", 2)
        cvc = field("CVC/CVV · 선택 · 비워 두면 저장하지 않음", 4)
        val checksumWarning = label("")
        pan.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) = Unit
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) = Unit
            override fun afterTextChanged(s: Editable?) {
                val raw = characters(pan)
                val number = raw.filter { it != ' ' && it != '-' }.toCharArray()
                try {
                    checksumWarning.text = if (NativeStoredCardPolicy.panValid(number) && !NativeStoredCardPolicy.checksum(number))
                        "카드번호 검사 결과가 맞지 않아요. 번호를 확인해 주세요. 입력한 값으로 저장할 수 있어요." else ""
                } finally { raw.fill('\u0000'); number.fill('\u0000') }
            }
        })
        confirm = CheckBox(this).apply {
            text = "카드번호·유효기간·CVC를 삭제할게요"
            isSaveEnabled = false; filterTouchesWhenObscured = true
            if (action != "delete") visibility = View.GONE
            column.addView(this)
        }
        fun button(text: String, click: () -> Unit) = Button(this).apply {
            this.text = text; minimumHeight = 48.dp(); filterTouchesWhenObscured = true
            setOnClickListener { click() }; column.addView(this)
        }
        submit = button(if (action == "delete") "카드 정보 삭제" else "카드 정보 저장") { mutate() }.apply {
            isEnabled = false; if (action == "view") visibility = View.GONE
        }
        button("닫기", ::close)
        val scroll = ScrollView(this).apply { isSaveEnabled = false; addView(column) }
        ViewCompat.setOnApplyWindowInsetsListener(scroll) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            view.setPadding(bars.left + 20.dp(), bars.top + 12.dp(), bars.right + 20.dp(), bars.bottom + 12.dp()); insets
        }
        setContentView(scroll)
    }
    private fun ready() = resumed && hasWindowFocus() && !keyguard.isDeviceLocked && !appLock.locked &&
        auth.hasLocalSession() && !isFinishing && !isDestroyed
    private fun current(request: ForegroundRequest): Boolean {
        if (gate === request && request.isActive() && ready()) return true
        request.cancel()
        if (!auth.hasLocalSession()) NativeSessionEnd.close(this)
        else if (gate === request) close()
        return false
    }
    private fun load() {
        if (!ready() || loaded || gate != null) return
        val request = ForegroundRequest().also { gate = it }
        auth.finance(FinanceOperation.GET_CARD, JSONObject().put("cardId", cardId), request) { outcome -> runOnUiThread {
            if (!current(request)) return@runOnUiThread
            gate = null
            val card = outcome.value?.get("body") as? Map<*, *>
            if (outcome.code != null || outcome.value?.get("status") != 200 || card == null || card["id"] != cardId) {
                failure(outcome.code ?: AuthCode.ACCESS_DENIED); return@runOnUiThread
            }
            version = (card["version"] as? Number)?.toLong()
            loaded = true
            status.text = "${card["issuer_name"]} · ${card["product_name"]}"
            val exists = card["has_stored_details"] == true
            if (action == "view" || action == "edit" && exists) reveal()
            else {
                enableEditing(action == "edit")
                submit.isEnabled = action == "edit" || exists
                if (action == "delete" && !exists) status.text = "저장된 카드 정보가 없어요."
            }
        } }
    }
    private fun reveal() {
        if (!ready() || gate != null) return
        val request = ForegroundRequest().also { gate = it }
        auth.storedCard("view", cardId, null, null, request) { outcome, details -> runOnUiThread {
            try {
                if (!current(request)) return@runOnUiThread
                gate = null
                if (outcome.code != null || details == null) { failure(outcome.code ?: AuthCode.ACCESS_DENIED); return@runOnUiThread }
                if (details.version != version) { failure(AuthCode.VERSION_CONFLICT); return@runOnUiThread }
                if (action == "edit") {
                    pan.setText(details.pan, 0, details.pan.size); year.setText(details.year.toString()); month.setText(details.month.toString())
                    details.cvc?.let { cvc.setText(it, 0, it.size) }
                    enableEditing(true)
                    submit.isEnabled = true
                } else {
                    output.text = "카드번호: ${String(details.pan)}\n유효기간: ${details.year}/${details.month}\nCVC/CVV: ${details.cvc?.let(::String) ?: "저장 안 함"}"
                    completed = true
                }
                status.text = "30초 후 화면을 닫습니다." + if (!details.checksumValid) " 카드번호 검사 결과를 확인해 주세요. 직접 입력한 값은 저장할 수 있어요." else ""
                handler.postDelayed(expire, 30_000)
            } finally { details?.discard() }
        } }
    }
    private fun characters(field: EditText) = CharArray(field.length()).also { field.text.getChars(0, field.length(), it, 0) }
    private fun mutate() {
        if (!ready() || !loaded || gate != null || version == null) return
        if (action == "delete" && !confirm.isChecked) { status.text = "삭제 확인에 표시해 주세요."; return }
        var details: NativeStoredCard? = null
        if (action == "edit") {
            val number = characters(pan); val code = characters(cvc)
            try {
                val y = year.text.toString(); val m = month.text.toString()
                val normalized = number.filter { it != ' ' && it != '-' }.toCharArray()
                val validPan = try { NativeStoredCardPolicy.panValid(normalized) } finally { normalized.fill('\u0000') }
                pan.error = if (!validPan) "13~19자리 숫자를 입력해 주세요." else null
                year.error = if (y.toIntOrNull() !in 2000..2199) "2000~2199년을 입력해 주세요." else null
                month.error = if (m.toIntOrNull() !in 1..12) "1~12월을 입력해 주세요." else null
                cvc.error = if (code.isNotEmpty() && (code.size !in 3..4 || code.any { it !in '0'..'9' })) "3~4자리 숫자 또는 빈칸으로 입력해 주세요." else null
                if (listOf(pan, year, month, cvc).any { it.error != null }) return
                details = NativeStoredCardPolicy.input(number, y, m, code)
            } catch (_: AuthFailure) { status.text = "입력 형식을 확인해 주세요."; return }
            finally { number.fill('\u0000'); code.fill('\u0000') }
        }
        enableEditing(false)
        clearSecrets(); pending = details
        submit.isEnabled = false
        val request = ForegroundRequest().also { gate = it }
        status.text = "요청을 처리하고 있어요."
        auth.storedCard(action, cardId, version, details, request) { outcome, ignored -> runOnUiThread {
            ignored?.discard()
            if (!current(request)) return@runOnUiThread
            gate = null; pending?.discard(); pending = null
            if (outcome.code != null) { failure(outcome.code); return@runOnUiThread }
            completed = true; close()
        } }
    }
    private fun failure(code: AuthCode) {
        enableEditing(false)
        clearSecrets(); submit.isEnabled = false
        status.text = when(code) {
            AuthCode.VERSION_CONFLICT -> "다른 기기에서 카드가 바뀌었어요. 닫고 최신 정보를 다시 열어 주세요."
            AuthCode.INVALID_REQUEST -> "입력 형식을 확인할 수 없어요. 닫고 다시 입력해 주세요."
            AuthCode.SESSION_EXPIRED, AuthCode.REAUTHENTICATION_REQUIRED -> "로그인 상태를 다시 확인한 뒤 열어 주세요."
            AuthCode.NETWORK_UNAVAILABLE, AuthCode.AUTH_CANCELLED -> "처리 결과를 확인할 수 없어요. 닫고 카드를 새로 조회해 주세요. 자동으로 재전송하지 않았습니다."
            else -> "카드 정보를 처리할 수 없어요. 닫고 카드 상태를 확인해 주세요."
        }
    }
    private fun enableEditing(enabled: Boolean) {
        for (field in listOf(pan, year, month, cvc)) field.isEnabled = enabled
    }
    private fun clearSecrets() {
        handler.removeCallbacks(expire); pending?.discard(); pending = null
        if (::pan.isInitialized) for (field in listOf(pan, year, month, cvc)) { field.text.clear(); field.error = null }
        if (::output.isInitialized) output.text = ""
    }
    private fun close() {
        gate?.cancel(); gate = null; clearSecrets()
        if (completed) setResult(Activity.RESULT_OK, Intent().putExtra(NativeAuthActivity.EXTRA_STATUS, "completed"))
        if (!isFinishing) finish()
    }
    override fun onResume() { super.onResume(); resumed = true; if (keyguard.isDeviceLocked || appLock.locked) close() }
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) { hadFocus = true; load() } else if (hadFocus) close() else clearSecrets()
    }
    override fun onPause() { resumed = false; close(); super.onPause() }
    override fun onSaveInstanceState(outState: Bundle) { close(); super.onSaveInstanceState(outState); outState.clear() }
    override fun onDestroy() { gate?.cancel(); clearSecrets(); if (receiverRegistered) unregisterReceiver(screenReceiver); receiverRegistered = false; super.onDestroy() }
    private fun Int.dp() = (this * resources.displayMetrics.density).toInt()
}
