package io.github.jihoon22lee.sallimbook.auth

import android.app.Activity
import android.app.KeyguardManager
import android.content.BroadcastReceiver
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.Uri
import android.os.Bundle
import android.os.CancellationSignal
import android.os.Handler
import android.os.Looper
import android.os.ParcelFileDescriptor
import android.os.SystemClock
import android.provider.DocumentsContract
import android.provider.OpenableColumns
import android.view.View
import android.view.WindowManager
import android.widget.Button
import android.widget.CheckBox
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.OnBackPressedCallback
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import java.util.concurrent.Executors
import org.json.JSONObject

/** File selection, bytes and destination URI never enter the WebView or an Activity result. */
class NativeDocumentActivity : AppCompatActivity() {
    companion object {
        internal const val UPLOAD = "document-upload"
        internal const val DOWNLOAD = "document-download"
        internal const val EXTRA_KIND = "sallimbook.document.kind"
    }
    private class Selection(val uri: Uri, val name: String, val mime: String, val size: Long?) {
        override fun toString() = "DocumentSelection(redacted)"
    }
    private val auth by lazy { NativeAuthSession.get(applicationContext) }
    private val appLock by lazy { AppLockController.get(applicationContext) }
    private val keyguard by lazy { getSystemService(KeyguardManager::class.java) }
    private val main = Handler(Looper.getMainLooper())
    private val io = Executors.newSingleThreadExecutor { task -> Thread(task, "sallimbook-document-io").apply { isDaemon = true } }
    private val flow = NativeDocumentFlow(SystemClock::elapsedRealtime)
    private var gate: ForegroundRequest? = null
    private var mode = ""
    private var targetId = ""
    private var targetKind = ""
    private var resumed = false
    private var hadFocus = false
    private var closing = false
    private var busy = false
    private var loaded = false
    private var completed = false
    private var receiverRegistered = false
    private var pendingUri: Uri? = null
    private var selected: Selection? = null
    private var destination: Uri? = null
    private var downloadInfo: NativeDocumentInfo? = null
    private lateinit var status: TextView
    private lateinit var fileLabel: TextView
    private lateinit var choose: Button
    private lateinit var submit: Button
    private lateinit var confirmation: CheckBox
    private val pickerExpired = Runnable { close(AuthCode.AUTH_CANCELLED) }
    private val transferExpired = Runnable { failure(AuthCode.NETWORK_UNAVAILABLE) }
    private val lockChanged: () -> Unit = { if (appLock.locked) close(AuthCode.APP_LOCKED) }
    private val screenReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) { if (intent?.action == Intent.ACTION_SCREEN_OFF) close(AuthCode.APP_LOCKED) }
    }
    private val picker = registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if (closing || result.resultCode != Activity.RESULT_OK) { close(); return@registerForActivityResult }
        val uri = result.data?.data
        val flags = result.data?.flags ?: 0
        val required = if (mode == UPLOAD) Intent.FLAG_GRANT_READ_URI_PERMISSION else Intent.FLAG_GRANT_WRITE_URI_PERMISSION
        val clips = result.data?.clipData
        if (uri == null || uri.scheme != "content" || uri.authority.isNullOrBlank() ||
            !DocumentsContract.isDocumentUri(this, uri) || flags and required == 0 ||
            clips != null && (clips.itemCount != 1 || clips.getItemAt(0).uri != uri) || !current() || !flow.pickerReturned()) {
            close(AuthCode.ACCESS_DENIED); return@registerForActivityResult
        }
        pendingUri = uri
        main.removeCallbacks(pickerExpired)
        main.postDelayed(pickerExpired, 1000)
        main.post { finishPicker() }
    }
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(null)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        setResult(Activity.RESULT_CANCELED)
        mode = intent.getStringExtra(NativeAuthActivity.EXTRA_MODE) ?: ""
        targetId = intent.getStringExtra(NativePasskeyActivity.EXTRA_ID) ?: ""
        targetKind = intent.getStringExtra(EXTRA_KIND) ?: ""
        val internal = try { !packageManager.getActivityInfo(ComponentName(this, NativeDocumentActivity::class.java), 0).exported }
            catch (_: Exception) { false }
        val expected = setOf(NativeAuthActivity.EXTRA_MODE, NativePasskeyActivity.EXTRA_ID) + if (mode == UPLOAD) setOf(EXTRA_KIND) else emptySet()
        val valid = try {
            FinancePolicy.id(targetId)
            if (mode == UPLOAD) NativeDocumentPolicy.target(mapOf("kind" to targetKind, "id" to targetId))
            true
        } catch (_: Exception) { false }
        if (savedInstanceState != null || !internal || !auth.available || mode !in setOf(UPLOAD, DOWNLOAD) ||
            intent.extras?.keySet() != expected || !valid || appLock.locked) {
            close(AuthCode.AUTH_UNAVAILABLE); return
        }
        gate = ForegroundRequest()
        buildUi()
        appLock.addListener(lockChanged)
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
            this.text = text; textSize = 17f; isSaveEnabled = false; freezesText = false
            setTextIsSelectable(false); isLongClickable = false; setPadding(0, 12.dp(), 0, 12.dp()); column.addView(this)
        }
        label(if (mode == UPLOAD) "SallimBook · 문서 첨부" else "SallimBook · 문서 사본 저장").textSize = 24f
        label(if (mode == UPLOAD) "PDF·JPEG·PNG 한 개를 첨부할 수 있어요. 최대 20MiB, PDF는 최대 ${NativeDocumentPolicy.MAX_PDF_PAGES}쪽이며 카드 사진·전체 카드번호·보안코드가 포함된 파일은 첨부할 수 없어요. JPEG 사진은 방향을 맞추고 긴 변을 ${NativeDocumentImage.MAX_LONG_EDGE}px 이하로 줄이며 위치 등 사진 정보를 뺀 사본으로 올려요."
            else "선택한 저장 위치에 문서 사본을 만들어요. 이 사본은 앱 밖에 남으며 서버에서 문서를 삭제해도 함께 지워지지 않아요. 중단되면 빈 파일이나 일부 내용이 남을 수 있어요.")
        label("파일 선택 중 1분이 지나거나 화면을 잠그면 작업을 취소해요. 처리 중 이 화면을 벗어나도 취소합니다.")
        status = label(if (mode == UPLOAD) "첨부할 파일을 선택해 주세요." else "현재 문서를 확인하고 있어요.")
        fileLabel = label("")
        fun button(text: String, action: () -> Unit) = Button(this).apply {
            this.text = text; minimumHeight = 48.dp(); isSaveEnabled = false; filterTouchesWhenObscured = true
            setOnClickListener { action() }; column.addView(this)
        }
        choose = button(if (mode == UPLOAD) "파일 선택" else "사본 저장 위치 선택", ::launchPicker).apply { isEnabled = mode == UPLOAD }
        confirmation = CheckBox(this).apply {
            text = "선택한 파일을 확인했고, 카드 사진·전체 카드번호·보안코드가 없어요."
            isSaveEnabled = false; filterTouchesWhenObscured = true; isEnabled = false
            if (mode != UPLOAD) visibility = View.GONE
            setOnCheckedChangeListener { _, checked -> if (::submit.isInitialized) submit.isEnabled = checked && selected != null && !busy && current() }
            column.addView(this)
        }
        submit = button("확인한 파일 첨부", ::upload).apply { isEnabled = false; if (mode != UPLOAD) visibility = View.GONE }
        button("취소하고 닫기") { close() }
        val scroll = ScrollView(this).apply { isSaveEnabled = false; addView(column) }
        ViewCompat.setOnApplyWindowInsetsListener(scroll) { view, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            view.setPadding(bars.left + 20.dp(), bars.top + 12.dp(), bars.right + 20.dp(), bars.bottom + 12.dp()); insets
        }
        setContentView(scroll)
    }
    private fun current(): Boolean {
        val request = gate ?: return false
        val ticket = request.appLockTicket() ?: return false
        return request.isActive() && appLock.isCurrent(ticket) && !appLock.locked && !keyguard.isDeviceLocked && !closing && !isFinishing && !isDestroyed
    }
    private fun ready() = current() && resumed && hasWindowFocus()
    private fun keepPicker() = current() && flow.keepPicker()
    private fun load() {
        if (mode != DOWNLOAD || loaded || !ready()) return
        loaded = true; busy = true
        val request = gate ?: return
        auth.finance(FinanceOperation.GET_DOCUMENT, JSONObject().put("documentId", targetId), request) { result -> main.post {
            if (!ready()) { close(); return@post }
            if (result.code != null) { failure(result.code); return@post }
            try {
                val value = result.value ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
                if (value["status"] != 200) {
                    val code = ((value["body"] as? Map<*, *>)?.get("error") as? Map<*, *>)?.get("code") as? String
                    failure(AuthCode.ACCESS_DENIED, code); return@post
                }
                val info = NativeDocumentPolicy.info(value["body"], targetId)
                downloadInfo = info; busy = false
                fileLabel.text = "${info.name}\n${info.mime} · ${info.size} bytes"
                status.text = "저장 위치를 직접 선택해 주세요."
                choose.isEnabled = true
            } catch (_: Exception) { failure(AuthCode.ACCESS_DENIED) }
        } }
    }
    private fun launchPicker() {
        if (!ready() || busy || mode == DOWNLOAD && downloadInfo == null || !flow.beginPicker()) return
        selected = null; confirmation.isChecked = false; confirmation.isEnabled = false; submit.isEnabled = false; choose.isEnabled = false
        val intent = Intent(if (mode == UPLOAD) Intent.ACTION_OPEN_DOCUMENT else Intent.ACTION_CREATE_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            if (mode == UPLOAD) {
                type = "*/*"; putExtra(Intent.EXTRA_MIME_TYPES, arrayOf("application/pdf", "image/jpeg", "image/png"))
                putExtra(Intent.EXTRA_ALLOW_MULTIPLE, false)
            } else {
                type = downloadInfo!!.mime; putExtra(Intent.EXTRA_TITLE, downloadInfo!!.name)
            }
        }
        main.postDelayed(pickerExpired, 60_000)
        try { picker.launch(intent) } catch (_: Exception) { failure(AuthCode.AUTH_UNAVAILABLE) }
    }
    private fun finishPicker() {
        val uri = pendingUri ?: return
        if (!ready()) return
        if (!flow.resumePicker()) { close(); return }
        pendingUri = null; main.removeCallbacks(pickerExpired)
        busy = true; startDeadline()
        if (mode == UPLOAD) readSelection(uri) else {
            destination = uri
            download()
        }
    }
    private fun startDeadline() { main.removeCallbacks(transferExpired); main.postDelayed(transferExpired, NativeDocumentBytes.TRANSFER_MILLIS) }
    private fun cancelAsync(action: () -> Unit) {
        Thread({ try { action() } catch (_: Exception) { } }, "sallimbook-document-cancel").apply { isDaemon = true; start() }
    }
    private fun <T> provider(request: ForegroundRequest, action: (CancellationSignal) -> T): T {
        val signal = CancellationSignal(); val owner = Any()
        request.bindCancellation(owner) { cancelAsync(signal::cancel) }
        try { request.check(); return action(signal) }
        finally { request.releaseCancellation(owner) }
    }
    private fun readSelection(uri: Uri) {
        val request = gate ?: return
        io.execute {
            try {
                val selection = provider(request) { signal ->
                    val mime = contentResolver.getType(uri) ?: throw AuthFailure(AuthCode.INVALID_REQUEST)
                    request.check()
                    val cursor = contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null, signal)
                        ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
                    cursor.use {
                        if (!it.moveToFirst()) throw AuthFailure(AuthCode.ACCESS_DENIED)
                        val nameIndex = it.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                        val sizeIndex = it.getColumnIndex(OpenableColumns.SIZE)
                        val name = if (nameIndex >= 0 && !it.isNull(nameIndex)) it.getString(nameIndex) else null
                        if (name == null) throw AuthFailure(AuthCode.INVALID_REQUEST)
                        NativeDocumentPolicy.filename(name, mime)
                        val size = if (sizeIndex >= 0 && !it.isNull(sizeIndex)) it.getLong(sizeIndex) else null
                        if (size != null && size !in 1..NativeDocumentBytes.MAX_BYTES.toLong()) throw AuthFailure(AuthCode.INVALID_REQUEST)
                        Selection(uri, name, mime, size)
                    }
                }
                main.post {
                    if (!ready()) { close(); return@post }
                    main.removeCallbacks(transferExpired); busy = false; selected = selection
                    fileLabel.text = "${selection.name}\n${selection.mime} · ${selection.size?.let { "$it bytes" } ?: "읽은 뒤 크기 확인"}"
                    status.text = "선택한 파일의 내용을 확인한 뒤 첨부해 주세요."
                    confirmation.isEnabled = true; choose.isEnabled = true
                }
            } catch (error: AuthFailure) { main.post { failure(error.code) } }
            catch (_: Exception) { main.post { failure(AuthCode.NETWORK_UNAVAILABLE) } }
        }
    }
    private fun upload() {
        val selection = selected ?: return
        val request = gate ?: return
        if (!ready() || busy || !confirmation.isChecked) return
        busy = true; choose.isEnabled = false; submit.isEnabled = false; confirmation.isEnabled = false; startDeadline()
        status.text = "파일을 확인하고 첨부하고 있어요. 보안 검사까지 기다려 주세요."
        io.execute {
            var content: NativeDocumentBytes? = null
            try {
                content = provider(request) { signal ->
                    val descriptor = contentResolver.openAssetFileDescriptor(selection.uri, "r", signal) ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
                    val owner = Any()
                    request.bindCancellation(owner) { cancelAsync(descriptor::close) }
                    try { descriptor.use { it.createInputStream().use { stream -> NativeDocumentBytes.read(stream, selection.size) { request.check() } } } }
                    finally { request.releaseCancellation(owner) }
                }
                request.check()
                if (selection.mime == "image/jpeg") {
                    main.post { status.text = "사진 방향을 맞추고 크기를 줄여 첨부하고 있어요. 보안 검사까지 기다려 주세요." }
                    NativeDocumentImage.normalizeJpeg(content!!) { request.check() }?.let { normalized ->
                        content?.close()
                        content = normalized
                    }
                }
                val owned = content!!
                auth.uploadDocument(selection.name, selection.mime, mapOf("kind" to targetKind, "id" to targetId), true, owned, request) { outcome ->
                    main.post { complete(outcome, "uploaded") }
                }
                content = null // The session closes the buffer even when the queued request was cancelled.
            } catch (error: AuthFailure) { main.post { failure(error.code) } }
            catch (_: Exception) { main.post { failure(AuthCode.NETWORK_UNAVAILABLE) } }
            finally { content?.close() }
        }
    }
    private fun download() {
        val request = gate ?: return
        val info = downloadInfo ?: return
        status.text = "문서 권한과 내용을 다시 확인하고 있어요."
        auth.downloadDocument(info, request) { outcome, content ->
            if (content == null) { main.post { complete(outcome, "downloaded") }; return@downloadDocument }
            main.post {
                if (!ready()) { content.close(); close(); return@post }
                status.text = "선택한 위치에 문서 사본을 저장하고 있어요."
                try { io.execute { writeDestination(content, request) } }
                catch (_: Exception) { content.close(); failure(AuthCode.NETWORK_UNAVAILABLE) }
            }
        }
    }
    private fun writeDestination(content: NativeDocumentBytes, request: ForegroundRequest) {
        try {
            val uri = destination ?: throw AuthFailure(AuthCode.AUTH_CANCELLED)
            provider(request) { signal ->
                val descriptor = contentResolver.openFileDescriptor(uri, "wt", signal) ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
                val owner = Any()
                request.bindCancellation(owner) { cancelAsync { descriptor.closeWithError("Document transfer cancelled") } }
                try {
                    ParcelFileDescriptor.AutoCloseOutputStream(descriptor).use { stream ->
                        content.writeTo(stream) { request.check() }
                        stream.flush(); request.check()
                    }
                } finally { request.releaseCancellation(owner); try { descriptor.close() } catch (_: Exception) { } }
            }
            main.post { complete(AuthOutcome.success(mapOf("status" to "downloaded")), "downloaded") }
        } catch (error: AuthFailure) { main.post { failure(error.code) } }
        catch (_: Exception) { main.post { failure(AuthCode.NETWORK_UNAVAILABLE) } }
        finally { content.close() }
    }
    private fun complete(outcome: AuthOutcome, expected: String) {
        if (!ready()) { close(); return }
        if (outcome.code != null) { failure(outcome.code); return }
        if (outcome.value?.get("status") != expected) { failure(AuthCode.ACCESS_DENIED, outcome.value?.get("error_code") as? String); return }
        main.removeCallbacks(transferExpired)
        completed = true
        setResult(Activity.RESULT_OK, Intent().putExtra(NativeAuthActivity.EXTRA_STATUS, expected))
        close()
    }
    private fun cleanupDestination() {
        val uri = destination ?: return
        destination = null
        if (!completed) cancelAsync { DocumentsContract.deleteDocument(contentResolver, uri) }
    }
    private fun failure(code: AuthCode, documentCode: String? = null) {
        if (closing) return
        gate?.cancel(); flow.cancel(); selected = null; pendingUri = null
        main.removeCallbacks(pickerExpired); main.removeCallbacks(transferExpired); cleanupDestination()
        setResult(Activity.RESULT_CANCELED, Intent().putExtra(NativeAuthActivity.EXTRA_ERROR, code.name))
        if (!::status.isInitialized) { close(code); return }
        fileLabel.text = ""; confirmation.isChecked = false; confirmation.isEnabled = false; choose.isEnabled = false; submit.isEnabled = false
        status.text = when {
            documentCode != null -> NativeDocumentPolicy.errorMessage(documentCode)
            code == AuthCode.INVALID_REQUEST -> "파일 형식·이름·크기를 확인해 주세요. PDF·JPEG·PNG, 20MiB 이하만 첨부할 수 있어요."
            code in setOf(AuthCode.APP_LOCKED, AuthCode.SESSION_EXPIRED, AuthCode.REAUTHENTICATION_REQUIRED) -> "화면을 닫고 앱 잠금과 로그인 상태를 확인한 뒤 다시 진행해 주세요."
            else -> "파일 처리를 완료하지 못했어요. 자동 재전송하지 않았으니 목록을 다시 확인해 주세요. 저장 중이었다면 선택한 위치의 불완전한 사본을 확인해 주세요."
        }
    }
    private fun close(code: AuthCode? = null) {
        if (closing) return
        closing = true; flow.cancel(); gate?.cancel(); selected = null; pendingUri = null; downloadInfo = null
        main.removeCallbacks(pickerExpired); main.removeCallbacks(transferExpired); cleanupDestination()
        if (::fileLabel.isInitialized) fileLabel.text = ""
        if (code != null && !completed) setResult(Activity.RESULT_CANCELED, Intent().putExtra(NativeAuthActivity.EXTRA_ERROR, code.name))
        if (!isFinishing) finish()
    }
    override fun onResume() { super.onResume(); resumed = true; if (keyguard.isDeviceLocked) close(AuthCode.APP_LOCKED) else main.post { finishPicker(); load() } }
    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if (hasFocus) { hadFocus = true; main.post { finishPicker(); load() } }
        else if (hadFocus && !keepPicker()) close()
    }
    override fun onPause() { resumed = false; if (!keepPicker()) close(); super.onPause() }
    override fun onStop() { if (!keepPicker()) close(); super.onStop() }
    override fun onSaveInstanceState(outState: Bundle) { if (!keepPicker()) close(); super.onSaveInstanceState(outState); outState.clear() }
    override fun onDestroy() {
        close(); gate?.cancel(); appLock.removeListener(lockChanged); io.shutdownNow()
        if (receiverRegistered) unregisterReceiver(screenReceiver)
        receiverRegistered = false; super.onDestroy()
    }
    private fun Int.dp(): Int = (this * resources.displayMetrics.density).toInt()
}
