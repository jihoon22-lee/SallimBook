package io.github.jihoon22lee.sallimbook.debugproof

import android.app.KeyguardManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyPermanentlyInvalidatedException
import android.security.keystore.KeyProperties
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.biometric.BiometricManager
import androidx.biometric.BiometricPrompt
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import java.security.KeyStore
import java.security.MessageDigest
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * SB-008 DEBUG-ONLY physical-device proof; not a vault, login, or CVC implementation.
 * Public synthetic payload only. No extras, input fields, bridge, network, file persistence,
 * clipboard, logs or arbitrary decrypt method. The dedicated proof key remains in Keystore
 * until explicit deletion/uninstall so enrollment invalidation can be exercised.
 * Ciphertext is Activity-local memory only and is intentionally lost after recreation.
 *
 * Unexecuted physical acceptance scenarios (Galaxy S25 Ultra / S24 Ultra Android 16):
 * 1. Create proof key, encrypt with strong biometric, then separately authenticate decryption.
 *    A prompt success alone must never display data: the returned Cipher must finish doFinal.
 * 2. Cancel/reject/lock out authentication: text remains locked; no weaker credential fallback.
 * 3. While awaiting auth and while visible: Home, screen lock, rotation, another activity,
 *    force-stop and relaunch. No restored plaintext or late callback may display anything.
 * 4. Observe the 30-second limit; change wall time and repeat. Monotonic expiry must persist.
 * 5. Add/remove enrolled biometrics or remove device lock, return and try existing proof key.
 *    Report key invalidation/unavailability; never regenerate automatically. Explicitly delete
 *    the disposable proof key before creating a replacement.
 * 6. Screenshot/screen-record/recents and inspect logs/bridge/network/backup artifacts.
 *    FLAG_SECURE is a mitigation to verify, not a claim about cameras or compromised devices.
 * 7. Verify release APK has neither this component/class nor its biometric dependency.
 * JVM policy tests and successful builds do not establish any of these physical results.
 */
class SecurityProofActivity : AppCompatActivity() {
    companion object {
        // Deliberately public test content; never replace this with actual card/customer data.
        private const val PUBLIC_SYNTHETIC_TEXT = "SALLIMBOOK PUBLIC SYNTHETIC PROOF V1 - NOT A CARD SECRET"
        private const val PROOF_KEY_ALIAS = "sallimbook.debug.sb008.disposable-proof.v1"
        private const val PUBLIC_AAD = "SallimBook/SB-008/debug-proof/v1"
        private const val LOCKED_TEXT = "잠김 · 합성 문자열을 표시하지 않음"
    }

    private enum class Operation { ENCRYPT, DECRYPT }
    private class PendingOperation(val request: Long, val operation: Operation, val cipher: Cipher) {
        // Only the exact Cipher returned by this request's CryptoObject may be used.
        var authenticatedCipher: Cipher? = null
    }
    private data class SealedProof(val nonce: ByteArray, val ciphertext: ByteArray) {
        fun discard() {
            nonce.fill(0)
            ciphertext.fill(0)
        }
    }

    private val policy = ProofDisplayPolicy(SystemClock::elapsedRealtime)
    private val handler = Handler(Looper.getMainLooper())
    private val keyStore by lazy { KeyStore.getInstance("AndroidKeyStore").apply { load(null) } }
    private val keyguard by lazy { getSystemService(KeyguardManager::class.java) }
    private lateinit var prompt: BiometricPrompt
    private lateinit var status: TextView
    private lateinit var proofText: TextView
    private lateinit var createButton: Button
    private lateinit var encryptButton: Button
    private lateinit var decryptButton: Button
    private lateinit var deleteButton: Button
    private var pending: PendingOperation? = null
    private var sealedProof: SealedProof? = null
    // Lifecycle guard only: it never authorizes cryptographic key use.
    private var foreground = false
    private var screenReceiverRegistered = false

    private val expiry = object : Runnable {
        override fun run() {
            synchronizePresentation()
            val remaining = policy.remainingDisplayMillis()
            if (remaining == 0L) {
                lock("표시가 끝났어요. 다시 보려면 별도로 인증해 주세요.")
            } else {
                handler.postDelayed(this, minOf(remaining, 250L))
            }
        }
    }

    private val focusSettlement = Runnable { finishCryptographicOperation() }

    private val screenOffReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action == Intent.ACTION_SCREEN_OFF) lock("화면이 잠겨 합성 문자열을 가렸어요.")
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        buildProofUi()
        prompt = BiometricPrompt(this, ContextCompat.getMainExecutor(this), object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult) {
                val operation = pending ?: return
                synchronizePresentation()
                val cipher = result.cryptoObject?.cipher
                if (cipher == null || cipher !== operation.cipher) {
                    // This is a terminal callback, but never a usable cryptographic result.
                    if (policy.authenticationEnded(operation.request)) {
                        pending = null
                        lock("현재 요청에 연결된 키 연산을 확인하지 못해 중단했어요.")
                    }
                    return
                }
                if (!policy.authenticationSucceeded(operation.request)) {
                    if (!policy.ownsRequest(operation.request)) pending = null
                    updateActions()
                    return
                }
                operation.authenticatedCipher = cipher
                // A successful prompt can deliver its callback before window focus returns.
                // Keep only its Cipher for a bounded wait; do not decrypt any bytes yet.
                finishCryptographicOperation()
            }

            override fun onAuthenticationError(errorCode: Int, errString: CharSequence) {
                val operation = pending ?: return
                // lock() retains this request's slot until the terminal callback is consumed.
                // A new prompt cannot start while cancellation of this prompt is outstanding.
                if (!policy.authenticationEnded(operation.request)) return
                pending = null
                val message = when (errorCode) {
                    BiometricPrompt.ERROR_NEGATIVE_BUTTON, BiometricPrompt.ERROR_USER_CANCELED,
                    BiometricPrompt.ERROR_CANCELED -> "인증을 취소했어요. 합성 문자열은 잠겨 있어요."
                    BiometricPrompt.ERROR_LOCKOUT, BiometricPrompt.ERROR_LOCKOUT_PERMANENT ->
                        "기기 인증이 잠겼어요. 이 검증에서는 다른 인증으로 우회하지 않아요."
                    else -> "기기 인증을 완료할 수 없어요. 보호 수준을 낮추지 않고 중단했어요."
                }
                lock(message)
            }

            override fun onAuthenticationFailed() {
                if (pending?.let { policy.isAuthenticating(it.request) } == true) status.text = "생체 인증이 일치하지 않아요. 합성 문자열은 표시하지 않았어요."
            }
        })
        ContextCompat.registerReceiver(this, screenOffReceiver, IntentFilter(Intent.ACTION_SCREEN_OFF), ContextCompat.RECEIVER_NOT_EXPORTED)
        screenReceiverRegistered = true
        updateActions()
    }

    private fun buildProofUi() {
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
            setPadding(0, 12.dp(), 0, 12.dp())
            column.addView(this)
        }
        label("SallimBook · 합성 보안 검증", 24f)
        label("DEBUG 전용 · 실제 카드·CVC·계정 정보 입력 불가\n공개 합성 문자열만 암호화합니다. 서버 로그인이나 실제 보관함과 연결되지 않습니다.")
        status = label("먼저 검증 키를 만든 뒤 암호화와 복호화를 각각 인증해 주세요.")
        proofText = label(LOCKED_TEXT, 20f).apply {
            setTextIsSelectable(false)
            isLongClickable = false
            freezesText = false
        }
        fun action(text: String, onClick: () -> Unit) = Button(this).apply {
            this.text = text
            minimumHeight = 48.dp()
            filterTouchesWhenObscured = true
            setOnClickListener { onClick() }
            column.addView(this)
        }
        createButton = action("1. 검증 키 생성", ::createProofKey)
        encryptButton = action("2. 인증 후 합성 문자열 암호화") { beginOperation(Operation.ENCRYPT) }
        decryptButton = action("3. 인증 후 최대 30초 표시") { beginOperation(Operation.DECRYPT) }
        action("지금 가리기") { lock("합성 문자열을 가렸어요.") }
        deleteButton = action("검증 키와 합성 암호문 삭제", ::deleteProofKey)
        label("기기에 등록된 강력한 생체 인증수단을 확인합니다. 특정 사람의 손가락을 식별하는 검증이 아닙니다.\n화면 보호·키 무효화 등 실기기 시나리오를 아직 통과한 제품으로 간주하면 안 됩니다.", 14f)
        val scroll = ScrollView(this).apply { isSaveEnabled = false; addView(column) }
        ViewCompat.setOnApplyWindowInsetsListener(scroll) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.displayCutout())
            view.setPadding(bars.left + 20.dp(), bars.top + 12.dp(), bars.right + 20.dp(), bars.bottom + 20.dp())
            insets
        }
        setContentView(scroll)
    }

    private fun createProofKey() {
        lock("검증 키를 확인하고 있어요.")
        if (!strongBiometricReady()) return
        try {
            if (keyStore.containsAlias(PROOF_KEY_ALIAS)) {
                status.text = "기존 검증 키가 있어요. 무효화된 키도 자동 재생성하지 않아요. 새 검증은 삭제 버튼으로 시작해 주세요."
                return
            }
            val specification = KeyGenParameterSpec.Builder(PROOF_KEY_ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setKeySize(256)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setRandomizedEncryptionRequired(true)
                .setUserAuthenticationRequired(true)
                .setUserAuthenticationParameters(0, KeyProperties.AUTH_BIOMETRIC_STRONG)
                .setInvalidatedByBiometricEnrollment(true)
                .build()
            KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply { init(specification); generateKey() }
            status.text = "검증 키를 만들었어요. 암호화와 복호화에 각각 강력한 생체 인증이 필요해요."
        } catch (failure: Exception) {
            handleCryptoFailure(failure)
        } finally {
            updateActions()
        }
    }

    private fun strongBiometricReady(): Boolean {
        synchronizePresentation()
        if (!policy.canAcceptAction() || !keyguard.isDeviceSecure) {
            lock("기기 잠금과 현재 화면 상태를 확인해 주세요.")
            return false
        }
        if (BiometricManager.from(this).canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_STRONG) != BiometricManager.BIOMETRIC_SUCCESS) {
            lock("사용 가능한 강력한 생체 인증이 없어요. 약한 생체 인증이나 PIN으로 우회하지 않아요.")
            return false
        }
        return true
    }

    private fun beginOperation(operation: Operation) {
        if (pending != null) return
        lock("인증을 준비하고 있어요.")
        if (!strongBiometricReady()) return
        try {
            val key = keyStore.getKey(PROOF_KEY_ALIAS, null) as? SecretKey
            if (key == null) {
                lock("먼저 검증 키를 만들어 주세요. 키가 없거나 무효해도 자동으로 대체하지 않아요.")
                return
            }
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            when (operation) {
                Operation.ENCRYPT -> cipher.init(Cipher.ENCRYPT_MODE, key)
                Operation.DECRYPT -> {
                    val sealed = sealedProof ?: run { lock("먼저 합성 문자열을 암호화해 주세요."); return }
                    cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, sealed.nonce))
                }
            }
            val request = policy.beginRequest() ?: return
            pending = PendingOperation(request, operation, cipher)
            updateActions()
            status.text = "생체 인증을 기다리고 있어요. 아직 키 연산을 완료하지 않았어요."
            val info = BiometricPrompt.PromptInfo.Builder()
                .setTitle("합성 보안 검증")
                .setSubtitle(if (operation == Operation.ENCRYPT) "공개 합성 문자열 암호화" else "합성 암호문 복호화 · 최대 30초")
                .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG)
                .setNegativeButtonText("취소")
                .build()
            prompt.authenticate(info, BiometricPrompt.CryptoObject(cipher))
        } catch (failure: Exception) {
            handleCryptoFailure(failure)
        }
    }

    private fun finishCryptographicOperation() {
        val operation = pending ?: return
        synchronizePresentation()
        if (!policy.isWaitingForFocus(operation.request)) return
        val remaining = policy.remainingFocusWaitMillis(operation.request)
        if (remaining == 0L) {
            lock("화면 초점 복귀를 확인하지 못했어요. 다시 인증해 주세요.")
            return
        }
        if (!policy.claimCipherForUse(operation.request)) {
            handler.removeCallbacks(focusSettlement)
            handler.postDelayed(focusSettlement, minOf(remaining, 50L))
            return
        }
        handler.removeCallbacks(focusSettlement)
        val cipher = operation.authenticatedCipher ?: run {
            lock("현재 요청에 연결된 키 연산을 확인하지 못해 중단했어요.")
            return
        }
        try {
            cipher.updateAAD(PUBLIC_AAD.toByteArray(Charsets.UTF_8))
            when (operation.operation) {
                Operation.ENCRYPT -> {
                    val plaintext = PUBLIC_SYNTHETIC_TEXT.toByteArray(Charsets.UTF_8)
                    val ciphertext = try { cipher.doFinal(plaintext) } finally { plaintext.fill(0) }
                    val nonce = cipher.iv.copyOf()
                    synchronizePresentation()
                    if (nonce.size != 12 || !policy.finishEncryption(operation.request)) {
                        ciphertext.fill(0)
                        nonce.fill(0)
                        lock("합성 암호문의 형식을 확인하지 못해 중단했어요.")
                        return
                    }
                    sealedProof?.discard()
                    sealedProof = SealedProof(nonce, ciphertext)
                    pending = null
                    status.text = "인증된 키 연산으로 합성 암호문을 만들었어요. 표시는 별도 인증이 필요해요."
                }
                Operation.DECRYPT -> {
                    val sealed = sealedProof ?: run { lock("합성 암호문이 없어요."); return }
                    val plaintext = cipher.doFinal(sealed.ciphertext)
                    val expected = PUBLIC_SYNTHETIC_TEXT.toByteArray(Charsets.UTF_8)
                    try {
                        synchronizePresentation()
                        if (!MessageDigest.isEqual(plaintext, expected) || !policy.showAfterDecryption(operation.request)) {
                            lock("합성 문자열 검증에 실패해 표시하지 않았어요.")
                            return
                        }
                        pending = null
                        // Only the bytes returned by authenticated doFinal reach the native TextView.
                        // JVM/Android string and rendering memory erasure is best-effort, not guaranteed.
                        proofText.text = plaintext.toString(Charsets.UTF_8)
                        status.text = "복호화한 공개 합성 문자열 · 최대 30초 표시"
                        handler.post(expiry)
                    } finally {
                        plaintext.fill(0)
                        expected.fill(0)
                    }
                }
            }
            updateActions()
        } catch (failure: Exception) {
            handleCryptoFailure(failure)
        }
    }

    private fun handleCryptoFailure(failure: Exception) {
        var cause: Throwable? = failure
        var invalidated = false
        repeat(8) {
            if (cause is KeyPermanentlyInvalidatedException) invalidated = true
            cause = cause?.cause
        }
        lock(if (invalidated) "검증 키가 무효화됐어요. 자동 재생성하지 않아요. 검증 키 삭제 후 명시적으로 다시 만들어 주세요."
             else "키 연산을 완료하지 못했어요. 합성 문자열을 표시하지 않고 중단했어요.")
    }

    private fun deleteProofKey() {
        lock("검증 자료를 삭제하고 있어요.")
        sealedProof?.discard()
        sealedProof = null
        try {
            keyStore.deleteEntry(PROOF_KEY_ALIAS)
            status.text = "이 화면의 검증 키와 메모리의 합성 암호문을 삭제했어요. 실제 보관함과는 별개예요."
        } catch (failure: Exception) {
            handleCryptoFailure(failure)
        }
        updateActions()
    }

    private fun lock(message: String) {
        val cancellation = policy.lock()
        pending?.authenticatedCipher = null
        if (pending?.let { !policy.ownsRequest(it.request) } == true) pending = null
        handler.removeCallbacks(expiry)
        handler.removeCallbacks(focusSettlement)
        if (::proofText.isInitialized) proofText.text = LOCKED_TEXT
        if (::status.isInitialized) status.text = message
        if (::prompt.isInitialized && cancellation != null) prompt.cancelAuthentication()
        updateActions()
    }

    private fun synchronizePresentation() {
        val cancellation = policy.updatePresentation(
            resumed = foreground,
            focused = hasWindowFocus(),
            unlocked = !keyguard.isDeviceLocked,
        )
        if (policy.remainingDisplayMillis() == 0L && ::proofText.isInitialized) proofText.text = LOCKED_TEXT
        if (pending?.let { !policy.ownsRequest(it.request) } == true) pending = null
        if (::prompt.isInitialized && cancellation != null) prompt.cancelAuthentication()
    }

    private fun updateActions() {
        if (!::createButton.isInitialized) return
        val idle = policy.canAcceptAction() && pending == null
        createButton.isEnabled = idle
        encryptButton.isEnabled = idle
        decryptButton.isEnabled = idle && sealedProof != null
        deleteButton.isEnabled = idle
    }

    override fun onResume() {
        super.onResume()
        foreground = true
        synchronizePresentation()
        if (keyguard.isDeviceLocked) lock("기기 잠금을 해제한 뒤 다시 시작해 주세요.")
        updateActions()
    }

    override fun onPause() {
        foreground = false
        synchronizePresentation()
        lock("화면을 벗어나 합성 문자열을 가렸어요.")
        super.onPause()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        synchronizePresentation()
        // Focus loss clears any displayed value in policy, even before an expiry callback runs.
        // A still-pending biometric prompt may itself own focus; only its terminal callback
        // can release the request slot, and a returned Cipher cannot run while unfocused.
        if (hasFocus) finishCryptographicOperation()
        updateActions()
    }

    override fun onSaveInstanceState(outState: Bundle) {
        lock("화면이 다시 만들어져 합성 문자열을 가렸어요.")
        super.onSaveInstanceState(outState)
    }

    override fun onDestroy() {
        foreground = false
        synchronizePresentation()
        lock("검증 화면이 종료됐어요.")
        sealedProof?.discard()
        sealedProof = null
        if (screenReceiverRegistered) unregisterReceiver(screenOffReceiver)
        super.onDestroy()
    }

    private fun Int.dp(): Int = (this * resources.displayMetrics.density).toInt()
}
