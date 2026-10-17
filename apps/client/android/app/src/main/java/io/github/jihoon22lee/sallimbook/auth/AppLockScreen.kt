package io.github.jihoon22lee.sallimbook.auth

import android.content.Intent
import android.hardware.biometrics.BiometricManager
import android.hardware.biometrics.BiometricPrompt
import android.os.CancellationSignal
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.text.InputType
import android.view.View
import android.view.ViewGroup
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.OnBackPressedCallback
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import io.github.jihoon22lee.sallimbook.MainActivity

/** Native curtain and password field; no Intent result or JS value can unlock it. */
internal class AppLockScreen(private val activity: MainActivity) {
    private val lock = AppLockController.get(activity)
    private val auth = NativeAuthSession.get(activity)
    private val handler = Handler(Looper.getMainLooper())
    private var resumed = false
    private var gate: ForegroundRequest? = null
    private var password: CharArray? = null
    private var signal: CancellationSignal? = null
    private var attempt: AppLockTicket? = null
    private var success: AppLockTicket? = null
    private var deadline = 0L
    private val timeout = Runnable { cancelPrompt(); status.text = "인증 시간이 끝났어요. 다시 시도해 주세요." }
    private val column = LinearLayout(activity).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(24.dp(), 24.dp(), 24.dp(), 24.dp())
        isSaveEnabled = false
        importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
        importantForContentCapture = View.IMPORTANT_FOR_CONTENT_CAPTURE_NO_EXCLUDE_DESCENDANTS
    }
    private fun label(text: String) = TextView(activity).apply {
        this.text = text; textSize = 18f; isSaveEnabled = false
        setPadding(0, 12, 0, 12); column.addView(this)
    }
    private val title = label("SallimBook · 앱 잠금")
    private val status = label("기기에 등록된 인증수단 또는 현재 계정 비밀번호로 다시 열어 주세요.")
    private fun button(text: String, action: () -> Unit) = Button(activity).apply {
        this.text = text; minimumHeight = 48.dp(); filterTouchesWhenObscured = true
        setOnClickListener { action() }; column.addView(this)
    }
    private val unlock = button("기기 인증으로 잠금 해제", ::startPrompt)
    private val input = object : EditText(activity) {
        override fun onTextContextMenuItem(id: Int): Boolean = false
    }.apply {
        hint = "현재 계정 비밀번호"
        inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        imeOptions = EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING
        isSaveEnabled = false; isSaveFromParentEnabled = false; freezesText = false
        importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO
        importantForContentCapture = View.IMPORTANT_FOR_CONTENT_CAPTURE_NO
        isLongClickable = false; filterTouchesWhenObscured = true; setSingleLine(true)
        column.addView(this)
    }
    private val reauthenticate = button("비밀번호로 다시 인증하고 열기", ::passwordUnlock)
    private val login = button("계정 로그인") { launch(NativeAuthActivity.LOGIN) }
    private val passkey = button("패스키로 계정 로그인") { launch(NativePasskeyActivity.LOGIN, true) }
    private val invitation = button("초대 수락") { launch(NativeAuthActivity.INVITATION) }
    private val logoutButton = button("이 기기에서 로그아웃", ::logout)
    private val explanation = label("기기 인증은 서버의 최근 로그인을 갱신하거나 카드 보관함을 열지 않습니다. 비밀번호 재인증은 서버에서 현재 계정을 확인합니다.")
    private val close = button("닫기") { activity.finish() }
    private val curtain = ScrollView(activity).apply {
        isClickable = true; isFocusable = true; isSaveEnabled = false
        setBackgroundColor(0xfffaf8f3.toInt()); addView(column)
    }
    private val back = object : OnBackPressedCallback(true) {
        override fun handleOnBackPressed() { if (curtain.visibility == View.VISIBLE) activity.finish() }
    }
    private val changed: () -> Unit = { render() }

    init {
        (activity.findViewById<View>(android.R.id.content) as ViewGroup).addView(curtain,
            ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT))
        activity.onBackPressedDispatcher.addCallback(activity, back)
        ViewCompat.setOnApplyWindowInsetsListener(curtain) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
            insets
        }
        lock.addListener(changed)
        render()
    }
    private fun ready() = resumed && activity.hasWindowFocus() && !activity.isFinishing && !activity.isDestroyed
    private fun render() {
        val covered = lock.locked || !resumed
        activity.setAppContentVisible(!covered)
        curtain.visibility = if (covered) View.VISIBLE else View.GONE
        back.isEnabled = covered
        if (!lock.locked) { clearInput(); cancelPrompt(); return }
        if (attempt?.let { !lock.isCurrent(it) } == true) cancelPrompt()
        val session = auth.hasLocalSession()
        listOf(unlock, input, reauthenticate, logoutButton).forEach { it.visibility = if (session) View.VISIBLE else View.GONE }
        listOf(login, passkey, invitation).forEach { it.visibility = if (session) View.GONE else View.VISIBLE }
        title.text = if (session) "SallimBook · 앱 잠금" else "SallimBook · 로그인"
        listOf(unlock, reauthenticate, login, passkey, invitation, logoutButton).forEach {
            it.isEnabled = resumed && auth.available && gate == null && signal == null
        }
        if (!auth.available) status.text = "앱 인증 서버 설정을 확인할 수 없어요. 올바른 앱 빌드를 사용해 주세요."
    }
    private fun launch(mode: String, usePasskey: Boolean = false) {
        if (!ready() || auth.hasLocalSession() || !auth.available || gate != null || signal != null) return
        clearInput()
        success = null
        activity.startActivity(Intent(activity, if (usePasskey) NativePasskeyActivity::class.java else NativeAuthActivity::class.java)
            .putExtra(NativeAuthActivity.EXTRA_MODE, mode))
    }
    private fun startPrompt() {
        if (!ready() || !auth.hasLocalSession() || gate != null || signal != null) return
        val types = BiometricManager.Authenticators.BIOMETRIC_STRONG or BiometricManager.Authenticators.DEVICE_CREDENTIAL
        if (activity.getSystemService(BiometricManager::class.java).canAuthenticate(types) != BiometricManager.BIOMETRIC_SUCCESS) {
            status.text = "기기 인증을 사용할 수 없어요. 현재 계정 비밀번호로 다시 인증해 주세요."; return
        }
        clearInput()
        val owner = lock.newUnlockAttempt().also { attempt = it }
        success = null
        val cancellation = CancellationSignal().also { signal = it }
        deadline = SystemClock.elapsedRealtime() + 60_000
        handler.postDelayed(timeout, 60_000)
        render()
        try {
            BiometricPrompt.Builder(activity).setTitle("SallimBook 앱 잠금 해제")
                .setSubtitle("기기에 등록된 인증수단을 확인합니다")
                .setAllowedAuthenticators(types).build()
                .authenticate(cancellation, activity.mainExecutor, object : BiometricPrompt.AuthenticationCallback() {
                    override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                        if (attempt !== owner || signal !== cancellation) return
                        signal = null; success = owner
                        finishPrompt()
                    }
                    override fun onAuthenticationError(errorCode: Int, errString: CharSequence?) {
                        if (attempt !== owner) return
                        cancelPrompt()
                        status.text = "기기 인증을 완료하지 못했어요. 다시 시도하거나 현재 계정 비밀번호를 입력해 주세요."
                        render()
                    }
                })
        } catch (_: Exception) {
            cancelPrompt(); status.text = "기기 인증을 시작할 수 없어요. 비밀번호로 다시 인증해 주세요."; render()
        }
    }
    private fun finishPrompt() {
        val owner = success ?: return
        if (SystemClock.elapsedRealtime() >= deadline) { cancelPrompt(); render(); return }
        if (!ready()) return
        if (!lock.finishOsAuthentication(owner, activity)) {
            status.text = "앱 상태가 바뀌었어요. 다시 인증해 주세요."
        }
        cancelPrompt(); render()
    }
    private fun passwordUnlock() {
        if (!ready() || gate != null || signal != null || !auth.hasLocalSession()) return
        val characters = CharArray(input.length()).also { input.text.getChars(0, input.length(), it, 0) }
        input.text.clear()
        if (characters.isEmpty() || characters.size > 1024) { characters.fill('\u0000'); return }
        password = characters
        val request = ForegroundRequest().also { gate = it }
        render()
        auth.reauthenticate(characters, request) { outcome -> activity.runOnUiThread {
            if (gate !== request) return@runOnUiThread
            gate = null; clearInput()
            status.text = when (outcome.code) {
                null -> "현재 계정을 확인했어요."
                AuthCode.SESSION_EXPIRED -> "로그인이 만료됐어요. 다시 로그인해 주세요."
                AuthCode.APP_LOCKED, AuthCode.AUTH_CANCELLED -> "인증을 중단했어요. 다시 시도해 주세요."
                else -> "비밀번호 인증을 완료하지 못했어요. 입력과 연결 상태를 확인해 주세요."
            }
            render()
        } }
    }
    private fun logout() {
        if (!ready() || gate != null || signal != null) return
        clearInput()
        val request = ForegroundRequest().also { gate = it }; render()
        auth.logout(request) { outcome -> activity.runOnUiThread {
            if (gate !== request) return@runOnUiThread
            gate = null
            status.text = if (outcome.value?.get("serverRevoked") == true) "로그아웃했어요." else
                "이 기기에서 로그아웃했어요. 서버의 연결 해제 여부는 다른 기기에서 확인해 주세요."
            render()
        } }
    }
    private fun clearInput() { input.text.clear(); password?.fill('\u0000'); password = null }
    private fun cancelPrompt() {
        handler.removeCallbacks(timeout)
        attempt = null; success = null
        val old = signal; signal = null; old?.cancel()
    }
    fun onResume() { resumed = true; render(); finishPrompt() }
    fun onFocusChanged(focused: Boolean) { if (focused) finishPrompt() else clearInput() }
    fun onPause() { resumed = false; clearInput(); gate?.cancel(); gate = null; render() }
    fun onStop() { cancelPrompt() }
    fun onDestroy() { onPause(); cancelPrompt(); lock.removeListener(changed) }
    private fun Int.dp(): Int = (this * activity.resources.displayMetrics.density).toInt()
}
