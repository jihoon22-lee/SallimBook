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
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import java.util.concurrent.Executors

/** Export plaintext, destination URI and login password never enter the bridge or a disk cache. */
class NativeExportActivity:AppCompatActivity() {
    companion object {
        internal const val MODE="data-export"
        internal const val EXTRA_INPUT="sallimbook.export.input"
    }
    private val auth by lazy { NativeAuthSession.get(applicationContext) }
    private val appLock by lazy { AppLockController.get(applicationContext) }
    private val keyguard by lazy { getSystemService(KeyguardManager::class.java) }
    private val main=Handler(Looper.getMainLooper())
    private val io=Executors.newSingleThreadExecutor { task -> Thread(task,"sallimbook-export-io").apply { isDaemon=true } }
    private val pickerFlow=NativeDocumentFlow(SystemClock::elapsedRealtime)
    private val flow=NativeExportFlow(SystemClock::elapsedRealtime)
    private var gate:ForegroundRequest?=null
    private var authGate:ForegroundRequest?=null
    private var sessionGeneration=0L
    private var selection:NativeExportSelection?=null
    private var destination:Uri?=null
    private var pendingUri:Uri?=null
    @Volatile private var pendingArchive:NativeExportArchive?=null
    private var resumed=false; private var hadFocus=false; private var closing=false; private var busy=false
    private var completed=false; private var receiverRegistered=false
    private lateinit var status:TextView
    private lateinit var password:EditText
    private lateinit var confirmation:CheckBox
    private lateinit var submit:Button
    private val expired=Runnable { failure("EXPORT_TIMEOUT") }
    private val pickerExpired=Runnable { close(AuthCode.AUTH_CANCELLED) }
    private val lockChanged:()->Unit={ if(appLock.locked) close(AuthCode.APP_LOCKED) }
    private val screenReceiver=object:BroadcastReceiver() {
        override fun onReceive(context:Context?,intent:Intent?) { if(intent?.action==Intent.ACTION_SCREEN_OFF) close(AuthCode.APP_LOCKED) }
    }
    private val picker=registerForActivityResult(ActivityResultContracts.StartActivityForResult()) { result ->
        if(closing || result.resultCode!=Activity.RESULT_OK) { close(); return@registerForActivityResult }
        val uri=result.data?.data; val flags=result.data?.flags ?: 0; val clips=result.data?.clipData
        if(uri==null || uri.scheme!="content" || uri.authority.isNullOrBlank() || !DocumentsContract.isDocumentUri(this,uri) ||
            flags and Intent.FLAG_GRANT_WRITE_URI_PERMISSION==0 || clips!=null && (clips.itemCount!=1 || clips.getItemAt(0).uri!=uri) ||
            !current() || !pickerFlow.pickerReturned()) { close(AuthCode.ACCESS_DENIED); return@registerForActivityResult }
        try { flow.check(NativeExportFlow.Phase.PICKER) } catch(_:Exception) { close(AuthCode.AUTH_CANCELLED); return@registerForActivityResult }
        destination=uri; pendingUri=uri; main.removeCallbacks(pickerExpired); main.postDelayed(pickerExpired,1000); main.post { finishPicker() }
    }
    override fun onCreate(state:Bundle?) {
        super.onCreate(null); window.addFlags(WindowManager.LayoutParams.FLAG_SECURE); setResult(Activity.RESULT_CANCELED)
        val internal=try { !packageManager.getActivityInfo(ComponentName(this,NativeExportActivity::class.java),0).exported } catch(_:Exception) { false }
        try {
            if(state!=null || !internal || !auth.available || appLock.locked || intent.getStringExtra(NativeAuthActivity.EXTRA_MODE)!=MODE ||
                intent.extras?.keySet()!=setOf(NativeAuthActivity.EXTRA_MODE,EXTRA_INPUT)) throw AuthFailure(AuthCode.ACCESS_DENIED)
            val input=intent.getStringExtra(EXTRA_INPUT) ?: throw AuthFailure(AuthCode.INVALID_REQUEST)
            if(input.length>2048) throw AuthFailure(AuthCode.INVALID_REQUEST)
            selection=NativeExportPolicy.selection(NativeVaultJson.decode(input))
        } catch(_:Exception) { close(AuthCode.INVALID_REQUEST); return }
        sessionGeneration=auth.vaultGeneration; gate=ForegroundRequest(); buildUi()
        appLock.addListener(lockChanged)
        ContextCompat.registerReceiver(this,screenReceiver,IntentFilter(Intent.ACTION_SCREEN_OFF),ContextCompat.RECEIVER_NOT_EXPORTED); receiverRegistered=true
        onBackPressedDispatcher.addCallback(this,object:OnBackPressedCallback(true) { override fun handleOnBackPressed()=close() })
    }
    private fun buildUi() {
        val column=LinearLayout(this).apply {
            orientation=LinearLayout.VERTICAL; isSaveEnabled=false; filterTouchesWhenObscured=true
            importantForAutofill=View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
            importantForContentCapture=View.IMPORTANT_FOR_CONTENT_CAPTURE_NO_EXCLUDE_DESCENDANTS
        }
        fun label(text:String)=TextView(this).apply {
            this.text=text; textSize=17f; isSaveEnabled=false; freezesText=false; setTextIsSelectable(false); isLongClickable=false
            setPadding(0,12.dp(),0,12.dp()); column.addView(this)
        }
        label("SallimBook · 가계 자료 내보내기").textSize=24f
        label("${selection!!.formats.joinToString(" + ") { it.uppercase() }} · 선택한 문서 ${selection!!.documents.size}개 · ZIP 최대 64MiB")
        label("일반 가계 기록과 선택한 문서 원본을 암호화하지 않은 ZIP 사본으로 저장합니다. 진료 기록과 메모의 민감한 내용은 그대로 포함될 수 있어요. 카드 보관함·보안코드·인증 자료·전체 계좌/증권번호 전용 필드는 제외하지만, 메모나 문서 안의 번호를 자동으로 지우지는 않습니다.")
        label("사본은 앱 밖에 남으며 원격으로 회수하거나 만료시킬 수 없어요. 저장 위치와 공유 대상을 확인하세요. 중단되면 빈 파일이나 일부 내용이 남을 수 있습니다.")
        label("로그인 재인증 후 1분 안에 저장 위치를 선택하세요. 파일 처리 중 화면을 벗어나거나 잠그면 취소합니다.")
        status=label("현재 계정의 로그인 암호로 재인증해 주세요.")
        password=object:EditText(this) { override fun onTextContextMenuItem(id:Int)=false }.apply {
            hint="현재 계정 로그인 암호"; inputType=InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
            imeOptions=EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING; isSaveEnabled=false; isSaveFromParentEnabled=false; freezesText=false
            importantForAutofill=View.IMPORTANT_FOR_AUTOFILL_NO; importantForContentCapture=View.IMPORTANT_FOR_CONTENT_CAPTURE_NO
            isLongClickable=false; filterTouchesWhenObscured=true; filters=arrayOf(InputFilter.LengthFilter(1024)); setSingleLine(true)
            minimumHeight=48.dp(); column.addView(this)
        }
        confirmation=CheckBox(this).apply {
            text="선택한 자료와 앱 밖에 평문 사본이 남는 점을 확인했고 저장할게요"
            isSaveEnabled=false; filterTouchesWhenObscured=true; column.addView(this)
        }
        fun button(text:String,action:()->Unit)=Button(this).apply {
            this.text=text; minimumHeight=48.dp(); isSaveEnabled=false; filterTouchesWhenObscured=true; setOnClickListener { action() }; column.addView(this)
        }
        submit=button("재인증 후 저장 위치 선택",::authenticate)
        button("취소하고 닫기") { close() }
        val scroll=ScrollView(this).apply { isSaveEnabled=false; addView(column) }
        ViewCompat.setOnApplyWindowInsetsListener(scroll) { view,insets ->
            val bars=insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            view.setPadding(bars.left+20.dp(),bars.top+12.dp(),bars.right+20.dp(),bars.bottom+12.dp()); insets
        }
        setContentView(scroll)
    }
    private fun current():Boolean {
        val request=gate ?: return false; val ticket=request.appLockTicket() ?: return false
        return request.isActive() && appLock.isCurrent(ticket) && !appLock.locked && !keyguard.isDeviceLocked &&
            auth.vaultGeneration==sessionGeneration && !closing && !isFinishing && !isDestroyed
    }
    private fun ready()=current() && resumed && hasWindowFocus()
    private fun keepPicker():Boolean=try { flow.check(NativeExportFlow.Phase.PICKER); current() && pickerFlow.keepPicker() } catch(_:Exception) { false }
    private fun deadline(phase:NativeExportFlow.Phase) { main.removeCallbacks(expired); main.postDelayed(expired,phase.millis) }
    private fun authenticate() {
        if(!ready() || busy) return
        if(!confirmation.isChecked || password.length()==0) { status.text="로그인 암호와 사본 보관 확인이 필요합니다."; return }
        val secret=CharArray(password.length()).also { password.text.getChars(0,password.length(),it,0); password.text.clear() }
        try { flow.beginAuthentication() } catch(_:Exception) { secret.fill('\u0000'); close(); return }
        busy=true; submit.isEnabled=false; password.isEnabled=false; confirmation.isEnabled=false
        status.text="현재 계정을 재인증하고 있어요."; deadline(NativeExportFlow.Phase.AUTH)
        val request=ForegroundRequest().also { authGate=it }
        auth.reauthenticate(secret,request) { result ->
            secret.fill('\u0000')
            main.post {
                if(authGate!==request || !request.isActive() || !ready()) { request.cancel(); close(); return@post }
                authGate=null; request.cancel()
                try { flow.check(NativeExportFlow.Phase.AUTH) } catch(_:Exception) { close(AuthCode.AUTH_CANCELLED); return@post }
                if(result.code!=null || result.value?.get("status")!="authenticated") { failure(result.code?.name ?: "AUTH_FAILED"); return@post }
                launchPicker()
            }
        }
    }
    private fun launchPicker() {
        if(!ready()) { close(); return }
        try {
            flow.beginPicker(); if(!pickerFlow.beginPicker()) throw AuthFailure(AuthCode.AUTH_CANCELLED)
            main.removeCallbacks(expired); main.postDelayed(pickerExpired,60_000)
            status.text="저장 위치를 선택해 주세요. 선택한 뒤 새 파일을 요청합니다."
            picker.launch(Intent(Intent.ACTION_CREATE_DOCUMENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE); type="application/zip"; putExtra(Intent.EXTRA_TITLE,"sallimbook-export.zip")
            })
        } catch(_:Exception) { failure("ACCESS_DENIED") }
    }
    private fun finishPicker() {
        val uri=pendingUri ?: return
        if(!ready()) return
        try {
            if(!pickerFlow.resumePicker()) throw AuthFailure(AuthCode.AUTH_CANCELLED)
            flow.beginTransfer(); pendingUri=null; destination=uri; main.removeCallbacks(pickerExpired)
            deadline(NativeExportFlow.Phase.TRANSFER); status.text="새 가계 자료를 준비하고 무결성을 확인하고 있어요."
            val request=gate ?: throw AuthFailure(AuthCode.AUTH_CANCELLED)
            auth.exportArchive(selection ?: throw AuthFailure(AuthCode.INVALID_REQUEST),request) { response ->
                if(!request.isActive()) { response.archive?.close(); return@exportArchive }
                main.post {
                val archive=response.archive
                if(!ready()) { archive?.close(); close(); return@post }
                if(response.code!=null || archive==null) { archive?.close(); failure(response.code ?: "ACCESS_DENIED"); return@post }
                try {
                    flow.beginWrite(); deadline(NativeExportFlow.Phase.WRITE)
                    status.text="검증한 ZIP 사본을 선택한 위치에 저장하고 있어요."
                    pendingArchive=archive
                    io.execute { writeDestination(archive,request) }
                } catch(_:Exception) { archive.close(); failure("AUTH_CANCELLED") }
            } }
        } catch(_:Exception) { failure("AUTH_CANCELLED") }
    }
    private fun cancelAsync(action:()->Unit) {
        Thread({ try { action() } catch(_:Exception) { } },"sallimbook-export-cancel").apply { isDaemon=true; start() }
    }
    private fun writeDestination(archive:NativeExportArchive,request:ForegroundRequest) {
        val signal=CancellationSignal(); val signalOwner=Any()
        request.bindCancellation(signalOwner) { cancelAsync(signal::cancel) }
        fun check() { request.check(); flow.check(NativeExportFlow.Phase.WRITE) }
        try {
            check(); val uri=destination ?: throw AuthFailure(AuthCode.AUTH_CANCELLED)
            val descriptor=contentResolver.openFileDescriptor(uri,"wt",signal) ?: throw AuthFailure(AuthCode.ACCESS_DENIED)
            val owner=Any(); request.bindCancellation(owner) { cancelAsync { descriptor.closeWithError("Export cancelled") } }
            try {
                ParcelFileDescriptor.AutoCloseOutputStream(descriptor).use { stream -> archive.content.writeTo(stream,::check); stream.flush(); check() }
            } finally { request.releaseCancellation(owner); try { descriptor.close() } catch(_:Exception) { } }
            main.post {
                if(!ready()) { close(); return@post }
                try {
                    flow.finish(); completed=true; setResult(Activity.RESULT_OK,Intent().putExtra(NativeAuthActivity.EXTRA_STATUS,"exported")); close()
                } catch(_:Exception) { failure("AUTH_CANCELLED") }
            }
        } catch(failure:AuthFailure) { main.post { failure(failure.code.name) } }
        catch(_:Exception) { main.post { failure("NETWORK_UNAVAILABLE") } }
        finally { request.releaseCancellation(signalOwner); archive.close(); if(pendingArchive===archive) pendingArchive=null }
    }
    private fun cleanupDestination() {
        val uri=destination ?: return; destination=null
        if(!completed) cancelAsync { DocumentsContract.deleteDocument(contentResolver,uri) }
    }
    private fun failure(code:String) {
        if(closing) return
        flow.close(); pickerFlow.cancel(); gate?.cancel(); authGate?.cancel(); authGate=null; pendingUri=null; selection=null
        pendingArchive?.close(); pendingArchive=null
        main.removeCallbacks(expired); main.removeCallbacks(pickerExpired); cleanupDestination()
        val safe=AuthCode.entries.firstOrNull { it.name==code } ?: AuthCode.ACCESS_DENIED
        setResult(Activity.RESULT_CANCELED,Intent().putExtra(NativeAuthActivity.EXTRA_ERROR,safe.name))
        if(!::status.isInitialized) { close(safe); return }
        password.text.clear(); password.isEnabled=false; confirmation.isEnabled=false; submit.isEnabled=false
        status.text=NativeExportPolicy.message(code)
    }
    private fun close(code:AuthCode?=null) {
        if(closing) return
        closing=true; flow.close(); pickerFlow.cancel(); gate?.cancel(); authGate?.cancel(); authGate=null; pendingUri=null; selection=null
        pendingArchive?.close(); pendingArchive=null
        main.removeCallbacks(expired); main.removeCallbacks(pickerExpired); cleanupDestination()
        if(::password.isInitialized) password.text.clear()
        if(code!=null && !completed) setResult(Activity.RESULT_CANCELED,Intent().putExtra(NativeAuthActivity.EXTRA_ERROR,code.name))
        if(!isFinishing) finish()
    }
    override fun onResume() { super.onResume(); resumed=true; if(keyguard.isDeviceLocked) close(AuthCode.APP_LOCKED) else main.post { finishPicker() } }
    override fun onWindowFocusChanged(hasFocus:Boolean) {
        super.onWindowFocusChanged(hasFocus)
        if(hasFocus) { hadFocus=true; main.post { finishPicker() } } else if(hadFocus && !keepPicker()) close()
    }
    override fun onPause() { resumed=false; if(!keepPicker()) close(); super.onPause() }
    override fun onStop() { if(!keepPicker()) close(); super.onStop() }
    override fun onSaveInstanceState(outState:Bundle) { if(!keepPicker()) close(); super.onSaveInstanceState(outState); outState.clear() }
    override fun onDestroy() {
        close(); appLock.removeListener(lockChanged); io.shutdownNow()
        if(receiverRegistered) unregisterReceiver(screenReceiver); receiverRegistered=false; super.onDestroy()
    }
    private fun Int.dp()=(this*resources.displayMetrics.density).toInt()
}
