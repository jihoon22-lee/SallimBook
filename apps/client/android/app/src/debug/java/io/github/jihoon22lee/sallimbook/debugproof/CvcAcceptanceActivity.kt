package io.github.jihoon22lee.sallimbook.debugproof

import android.app.Activity
import android.app.KeyguardManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.hardware.biometrics.BiometricManager
import android.hardware.biometrics.BiometricPrompt
import android.os.Bundle
import android.os.CancellationSignal
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import io.github.jihoon22lee.sallimbook.auth.NativeVaultAcceptanceGate
import io.github.jihoon22lee.sallimbook.auth.NativeVaultFailure
import io.github.jihoon22lee.sallimbook.auth.NativeVaultKeyOperation
import io.github.jihoon22lee.sallimbook.auth.NativeVaultLifetime
import io.github.jihoon22lee.sallimbook.auth.NativeVaultStore
import javax.crypto.Cipher

/** Offline, public synthetic CVC acceptance using the production store and platform prompt.
 * There is no input, bridge, network, credential fallback or persisted activation flag.
 * Process restart preserves only this namespace's encrypted record and requires a new owner.
 */
class CvcAcceptanceActivity : Activity() {
    private class Pending(val id: Long, val operation: NativeVaultKeyOperation, val value: ByteArray?) {
        val cancellation = CancellationSignal()
        var returned: Cipher? = null
        fun discard() { value?.fill(0); operation.discard(); returned = null }
    }
    private val handler = Handler(Looper.getMainLooper())
    private val life = NativeVaultLifetime(SystemClock::elapsedRealtime)
    private val keyguard by lazy { getSystemService(KeyguardManager::class.java) }
    private val store by lazy { NativeVaultStore(this, CvcAcceptanceFixtures.NAMESPACE) }
    private val binding by lazy { CvcAcceptanceFixtures.binding(this) }
    private lateinit var status: TextView
    private lateinit var visibleValue: TextView
    private var resumed = false
    private var receiverRegistered = false
    private var ownerStarted = false
    private var pending: Pending? = null

    internal fun syntheticOwnerPresented(): Boolean = resumed && hasWindowFocus() && !isFinishing && !isDestroyed &&
        keyguard?.isDeviceLocked == false

    /** Called by the debug gate after doFinal/write and immediately before AtomicFile commit.
     * Owner lifetime alone is insufficient: this exact request may have expired in blocking IO. */
    internal fun syntheticCommitActive(): Boolean {
        val current = pending ?: return false
        return current.operation.encrypt && current.returned === current.operation.cipher &&
            syntheticOwnerPresented() && life.cipherActive(current.id)
    }

    private val screenOff = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action == Intent.ACTION_SCREEN_OFF) stopSession("화면 잠금 · 세션 종료")
        }
    }
    private val tick = object : Runnable {
        override fun run() {
            synchronize()
            if (ownerStarted && !NativeVaultAcceptanceGate.active(this@CvcAcceptanceActivity)) stopSession("세션 종료 · 시작 버튼으로 다시 시작")
            else finishCipher()
            if (life.displayRemaining() == 0L) visibleValue.text = "잠김"
            handler.postDelayed(this, 100)
        }
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        if (!validIntent(intent)) { finish(); return }
        val column = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(24, 40, 24, 24)
            isSaveEnabled = false
            filterTouchesWhenObscured = true
            importantForAutofill = View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
            importantForContentCapture = View.IMPORTANT_FOR_CONTENT_CAPTURE_NO_EXCLUDE_DESCENDANTS
        }
        ViewCompat.setOnApplyWindowInsetsListener(column) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            view.setPadding(24 + bars.left, 40 + bars.top, 24 + bars.right, 24 + bars.bottom)
            insets
        }
        fun label(value: String) = TextView(this).apply {
            text = value; textSize = 16f; isSaveEnabled = false; setTextIsSelectable(false)
            column.addView(this)
        }
        fun button(value: String, action: () -> Unit) {
            column.addView(Button(this).apply {
                text = value; isSaveEnabled = false; filterTouchesWhenObscured = true
                setOnClickListener { if (syntheticOwnerPresented()) action() }
            })
        }
        label(CvcAcceptanceFixtures.MARKER)
        label("공개 합성 3/4자리만 사용. 일반 보관함은 열지 않습니다. 세션 180초 · 인증 60초 · 표시 30초.")
        status = label("시작 전 · CVC 검증 gate 닫힘")
        visibleValue = label("잠김")
        button("합성 세션 시작") {
            if (pending == null && NativeVaultAcceptanceGate.beginSyntheticCvcAcceptance(this)) {
                ownerStarted = true
                synchronize(); status.text = "합성 세션 시작 · 저장과 읽기마다 별도 강한 생체 인증"
            }
        }
        button("합성 3자리 저장") { begin(true, false) }
        button("합성 4자리로 덮어쓰기") { begin(true, true) }
        button("저장된 합성 값 읽기") { begin(false, false) }
        button("다음 쓰기 실패 예약") {
            if (pending == null && NativeVaultAcceptanceGate.armSyntheticCvcWriteFailure(this))
                status.text = "다음 실제 AtomicFile 쓰기 직후 실패 · 기존 값 보존 확인 필요"
        }
        button("세션 취소 · 암호문 보존") { stopSession("취소 · 암호문 보존") }
        button("합성 저장소만 초기화") { eraseSyntheticStore(false) }
        button("종료 · 합성 저장소 삭제") { eraseSyntheticStore(true) }
        setContentView(ScrollView(this).apply { isSaveEnabled = false; addView(column) })
        ContextCompat.registerReceiver(this, screenOff, IntentFilter(Intent.ACTION_SCREEN_OFF), ContextCompat.RECEIVER_NOT_EXPORTED)
        receiverRegistered = true
    }
    private fun validIntent(value: Intent): Boolean = value.data == null && value.clipData == null &&
        value.selector == null && value.action == null && value.categories.isNullOrEmpty() && value.extras?.isEmpty != false
    override fun onNewIntent(intent: Intent) { super.onNewIntent(intent); stopSession("새 Intent 거절"); finish() }
    private fun synchronize() {
        val cancel = life.presentation(resumed, hasWindowFocus(), keyguard?.isDeviceLocked == false,
            NativeVaultAcceptanceGate.active(this))
        if (cancel != null) pending?.takeIf { it.id == cancel }?.cancellation?.cancel()
    }
    private fun begin(encrypt: Boolean, fourDigits: Boolean) {
        synchronize()
        if (pending != null || !life.canBegin() || !NativeVaultAcceptanceGate.allows(this, binding, CvcAcceptanceFixtures.NAMESPACE)) return
        visibleValue.text = "잠김"
        var operation: NativeVaultKeyOperation? = null
        try {
            operation = if (encrypt) store.prepareEncryption(binding) else store.prepareDecryption(binding)
            val id = life.beginPrompt() ?: run { operation.discard(); return }
            val current = Pending(id, operation, if (encrypt) CvcAcceptanceFixtures.value(fourDigits) else null)
            pending = current
            status.text = "인증 대기 · 성공 콜백만으로는 저장/표시하지 않음"
            BiometricPrompt.Builder(this)
                .setTitle("공개 합성 CVC 검증")
                .setSubtitle(if (encrypt) "합성 값 저장" else "합성 값 읽기")
                .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG)
                // Platform onDialogDismissed dispatches this as a terminal event, without
                // also requiring AuthenticationCallback.onAuthenticationError.
                .setNegativeButton("취소", mainExecutor) { _, _ -> terminal(current, "인증 취소 · 암호문 보존") }
                .build().authenticate(BiometricPrompt.CryptoObject(operation.cipher), current.cancellation, mainExecutor,
                    object : BiometricPrompt.AuthenticationCallback() {
                        override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                            if (pending !== current) { current.discard(); return }
                            synchronize()
                            val cipher = result.cryptoObject?.cipher
                            if (cipher !== current.operation.cipher || !life.promptSucceeded(current.id)) {
                                terminal(current, "유효하지 않은 완료 · 세션 종료"); return
                            }
                            current.returned = cipher
                            finishCipher()
                        }
                        override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                            terminal(current, "인증 취소/오류 · 암호문 보존")
                        }
                        override fun onAuthenticationFailed() {
                            if (pending === current) status.text = "생체 인증 불일치 · 합성 값 잠김"
                        }
                    })
        } catch (_: Exception) {
            // A synchronous authenticate failure may still produce a terminal callback. Keep
            // its slot until that callback or Activity destruction; do not overlap prompts.
            if (pending == null) operation?.discard()
            stopSession("키 사용 불가/요청 실패 · 자동 키 교체 없음")
        }
    }
    private fun terminal(current: Pending, message: String) {
        if (pending !== current) { current.discard(); return }
        life.promptEnded(current.id)
        pending = null
        current.discard()
        stopSession(message)
    }
    private fun finishCipher() {
        val current = pending ?: return
        val returned = current.returned ?: return
        if (!syntheticOwnerPresented()) {
            if (life.focusRemaining(current.id) == 0L) terminal(current, "초점 복귀 시간 초과")
            return
        }
        if (!life.claimCipher(current.id)) { terminal(current, "완료 시한 만료"); return }
        var result: ByteArray? = null
        var committed = false
        try {
            result = store.finish(current.operation, returned, current.value)
            committed = current.operation.encrypt
            if (!life.finishCipher(current.id, result != null) || !syntheticOwnerPresented() || !NativeVaultAcceptanceGate.active(this))
                throw NativeVaultFailure("ACCESS_DENIED")
            // Deliberately only the fixed public fixture reaches this native TextView.
            if (result != null) {
                val three = CvcAcceptanceFixtures.value(false); val four = CvcAcceptanceFixtures.value(true)
                try {
                    if (!result.contentEquals(three) && !result.contentEquals(four)) throw NativeVaultFailure("KEY_INVALIDATED")
                    visibleValue.text = String(result, Charsets.US_ASCII)
                } finally { three.fill(0); four.fill(0) }
            }
            status.text = if (current.operation.encrypt) "실제 AtomicFile 저장 완료 · 읽기는 별도 인증" else "실제 복호화 완료 · 30초 이내 가림"
            pending = null
        } catch (_: Exception) {
            pending = null
            // A finishWrite that began in time can return after the deadline. Never describe
            // that durable write as a failed save merely because its UI completion is stale.
            stopSession(if (committed) "저장 완료 · 완료 시한/화면 상태 변경으로 세션 종료 · 새 세션에서 읽기로 확인"
                else "키/저장/검증 실패 · 자동 교체 없음 · 기존 값 별도 읽기로 확인")
        } finally { result?.fill(0); current.discard() }
    }
    private fun stopSession(message: String) {
        ownerStarted = false
        NativeVaultAcceptanceGate.end(this)
        life.lock()?.let { id -> pending?.takeIf { it.id == id }?.cancellation?.cancel() }
        pending?.value?.fill(0)
        // READY has already received its terminal callback; no cancellation slot is needed.
        pending?.takeIf { it.returned != null }?.let { it.discard(); pending = null }
        if (::visibleValue.isInitialized) visibleValue.text = "잠김"
        if (::status.isInitialized) status.text = message
    }
    private fun eraseSyntheticStore(close: Boolean) {
        stopSession("합성 저장소 초기화")
        if (pending != null) { status.text = "인증 종료 콜백 뒤 초기화를 다시 선택하세요"; return }
        try { store.clearAll(); status.text = "합성 namespace 삭제 완료"; if (close) finish() }
        catch (_: Exception) { status.text = "합성 저장소 삭제 실패 · 기기 확인 필요" }
    }
    override fun onResume() {
        super.onResume(); resumed = true
        if (::status.isInitialized) { synchronize(); handler.post(tick) }
    }
    override fun onPause() { resumed = false; stopSession("백그라운드 · 세션 종료"); handler.removeCallbacks(tick); super.onPause() }
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (!::status.isInitialized) return
        if (!hasFocus) {
            visibleValue.text = "잠김"
            if (pending == null) stopSession("초점 이탈 · 세션 종료")
        }
        synchronize()
        if (hasFocus) finishCipher()
    }
    override fun onDestroy() {
        resumed = false; stopSession("종료")
        pending?.cancellation?.cancel(); pending?.discard(); pending = null
        handler.removeCallbacksAndMessages(null)
        if (receiverRegistered) unregisterReceiver(screenOff)
        super.onDestroy()
    }
}
