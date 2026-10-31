package io.github.jihoon22lee.sallimbook.auth

import android.app.Activity
import android.app.KeyguardManager
import android.content.BroadcastReceiver
import android.content.ComponentName
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
import android.text.InputFilter
import android.text.InputType
import android.view.View
import android.view.WindowManager
import android.view.inputmethod.EditorInfo
import android.widget.Button
import android.widget.CheckBox
import android.widget.RadioButton
import android.widget.RadioGroup
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import androidx.activity.OnBackPressedCallback
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import javax.crypto.Cipher

/** All vault plaintext, passwords, recovery codes and local security codes stay on this native screen. */
class NativeVaultActivity : AppCompatActivity() {
    companion object { internal const val MODE="vault"; internal const val EXTRA_ACTION="vaultAction" }
    private val auth by lazy { NativeAuthSession.get(applicationContext) }
    private val local by lazy { NativeVaultStore.get(applicationContext) }
    private val appLock by lazy { AppLockController.get(applicationContext) }
    private val keyguard by lazy { getSystemService(KeyguardManager::class.java) }
    private val life=NativeVaultLifetime(SystemClock::elapsedRealtime)
    private val handler=Handler(Looper.getMainLooper())
    private var entry:ForegroundRequest?=null
    private var sessionGeneration=0L
    private var resumed=false; private var hadFocus=false; private var loaded=false; private var receiverRegistered=false
    private var action="manage"; private var target:String?=null; private var completed=false
    private var work:ForegroundRequest?=null
    private var activeWorkId:Long?=null
    private var snapshot:NativeVaultSnapshot?=null
    private var rotation:VaultRecord?=null
    private var pending:NativeVaultPrepared?=null
    private var retryCommand:NativeVaultCommand?=null
    private var managementReauthentication:NativeVaultReauthentication?=null
    private var showing=false; private var recoveryShowing=false
    private lateinit var column:LinearLayout
    private lateinit var status:TextView
    private lateinit var secretOutput:TextView
    private val inputs=mutableListOf<EditText>()
    private val controls=mutableListOf<Button>()
    private class Prompt(val id:Long,val operation:NativeVaultKeyOperation,val plaintext:ByteArray?,val gate:ForegroundRequest,
        val signal:CancellationSignal,val next:(ByteArray?)->Unit) {
        var returned:Cipher?=null
        fun discard() { returned=null; plaintext?.fill(0); operation.discard(); gate.cancel() }
    }
    private var prompt:Prompt?=null
    private val screenReceiver=object:BroadcastReceiver() { override fun onReceive(context:Context?,intent:Intent?) { if(intent?.action==Intent.ACTION_SCREEN_OFF) close() } }
    private val lockListener:()->Unit={ if(appLock.locked) close() }
    private val timer=object:Runnable { override fun run() {
        if(isFinishing || isDestroyed) return
        if(auth.vaultGeneration!=sessionGeneration || appLock.locked || keyguard.isDeviceLocked) { close(); return }
        life.expire()?.let { if(prompt?.id==it) { prompt?.discard(); prompt?.signal?.cancel() } }
        if(work!=null && activeWorkId?.let { !life.workActive(it) } != false) { close(); return }
        if(prompt?.returned!=null) finishPrompt()
        if(showing && life.displayRemaining()==0L) {
            secretOutput.text=""; showing=false
            if(recoveryShowing) { recoveryShowing=false; pending?.discard(); pending=null; retryCommand=null; controls.forEach { it.isEnabled=false } }
            status.text="표시 시간이 끝났어요. 새로 열어 다시 확인해 주세요."
        }
        handler.postDelayed(this,100)
    } }
    override fun onCreate(state:Bundle?) {
        super.onCreate(null); window.addFlags(WindowManager.LayoutParams.FLAG_SECURE); setResult(Activity.RESULT_CANCELED)
        sessionGeneration=auth.vaultGeneration; entry=ForegroundRequest()
        action=intent.getStringExtra(EXTRA_ACTION) ?: ""; target=intent.getStringExtra(NativePasskeyActivity.EXTRA_ID)
        val internal=try { !packageManager.getActivityInfo(ComponentName(this,NativeVaultActivity::class.java),0).exported } catch(_:Exception) { false }
        val fields=setOf(NativeAuthActivity.EXTRA_MODE,EXTRA_ACTION)+(if(target!=null) setOf(NativePasskeyActivity.EXTRA_ID) else emptySet())
        try {
            if(!internal || state!=null || !auth.available || intent.getStringExtra(NativeAuthActivity.EXTRA_MODE)!=MODE || intent.extras?.keySet()!=fields) throw NativeVaultFailure("ACCESS_DENIED")
            NativeVaultUiPolicy.native(action,target)
        } catch(_:Exception) { finish(); return }
        column=LinearLayout(this).apply {
            orientation=LinearLayout.VERTICAL; isSaveEnabled=false; filterTouchesWhenObscured=true
            importantForAutofill=View.IMPORTANT_FOR_AUTOFILL_NO_EXCLUDE_DESCENDANTS
            importantForContentCapture=View.IMPORTANT_FOR_CONTENT_CAPTURE_NO_EXCLUDE_DESCENDANTS
        }
        val scroll=ScrollView(this).apply { isSaveEnabled=false; addView(column) }
        ViewCompat.setOnApplyWindowInsetsListener(scroll) { view,insets ->
            val bars=insets.getInsets(WindowInsetsCompat.Type.systemBars() or WindowInsetsCompat.Type.ime())
            view.setPadding(bars.left+20.dp(),bars.top+12.dp(),bars.right+20.dp(),bars.bottom+12.dp()); insets
        }
        setContentView(scroll); heading()
        ContextCompat.registerReceiver(this,screenReceiver,IntentFilter(Intent.ACTION_SCREEN_OFF),ContextCompat.RECEIVER_NOT_EXPORTED); receiverRegistered=true
        appLock.addListener(lockListener)
        onBackPressedDispatcher.addCallback(this,object:OnBackPressedCallback(true) { override fun handleOnBackPressed()=close() })
        handler.post(timer)
    }
    private fun ready():Boolean = resumed && hasWindowFocus() && !keyguard.isDeviceLocked && !appLock.locked &&
        auth.vaultGeneration==sessionGeneration && !isFinishing && !isDestroyed && try { entry?.check(); entry!=null } catch(_:Exception) { false }
    private fun label(text:String,size:Float=17f)=TextView(this).apply {
        this.text=text; textSize=size; isSaveEnabled=false; freezesText=false; setTextIsSelectable(false); isLongClickable=false
        setPadding(0,10.dp(),0,10.dp()); column.addView(this)
    }
    private fun button(text:String,cancellable:Boolean=false,click:()->Unit)=Button(this).apply {
        this.text=text; minimumHeight=48.dp(); filterTouchesWhenObscured=true; isSaveEnabled=false
        setOnClickListener { if(ready() && (cancellable || work==null && prompt==null)) try { click() }
            catch(failure:NativeVaultFailure) { failure(failure.code) } catch(_:Exception) { failure("ACCESS_DENIED") } }; column.addView(this); if(!cancellable) controls.add(this)
    }
    private fun checkbox(text:String)=CheckBox(this).apply { this.text=text; isSaveEnabled=false; filterTouchesWhenObscured=true; column.addView(this) }
    private fun input(hint:String,numeric:Boolean=false,maximum:Int=1024)=object:EditText(this) { override fun onTextContextMenuItem(id:Int)=false }.apply {
        this.hint=hint; inputType=if(numeric) InputType.TYPE_CLASS_NUMBER or InputType.TYPE_NUMBER_VARIATION_PASSWORD else
            InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD or InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
        imeOptions=EditorInfo.IME_FLAG_NO_PERSONALIZED_LEARNING; isSaveEnabled=false; isSaveFromParentEnabled=false; freezesText=false
        importantForAutofill=View.IMPORTANT_FOR_AUTOFILL_NO; importantForContentCapture=View.IMPORTANT_FOR_CONTENT_CAPTURE_NO
        isLongClickable=false; filterTouchesWhenObscured=true; filters=arrayOf(InputFilter.LengthFilter(maximum)); setSingleLine(true); minimumHeight=48.dp()
        column.addView(this); inputs.add(this)
    }
    private fun take(field:EditText)=CharArray(field.length()).also { field.text.getChars(0,field.length(),it,0); field.text.clear() }
    private fun heading() {
        inputs.forEach { it.text.clear() }; inputs.clear(); controls.clear(); column.removeAllViews(); showing=false; recoveryShowing=false
        label("SallimBook · 카드 보관함",24f)
        label("보호 정보는 이 네이티브 화면에서만 처리합니다. 화면을 벗어나면 입력과 표시를 지웁니다.",14f)
        status=label("현재 계정과 보관함을 확인하고 있어요."); secretOutput=NativeSecretViews.sensitive(label("",22f))
    }
    private fun failure(code:String) { if(::status.isInitialized) status.text=NativeVaultErrors.message(code); if(code in setOf("APP_LOCKED","SESSION_EXPIRED")) close() }
    private fun busy(value:Boolean) { controls.forEach { it.isEnabled=!value }; if(value) status.text="보관함을 처리하고 있어요." }
    private fun <T> runNative(discard:(T)->Unit={}, supplied:List<CharArray> = emptyList(), display:Boolean=false,
        abandoned:()->Unit={}, reauthentication:(()->Unit)?=null, task:(NativeVaultConnection)->T, done:(T)->Unit) {
        if(!ready() || work!=null || prompt!=null) { supplied.forEach { it.fill('\u0000') }; abandoned(); return }
        val id=life.beginWork() ?: run { supplied.forEach { it.fill('\u0000') }; abandoned(); return }
        val gate=ForegroundRequest().also { work=it; activeWorkId=id }; busy(true)
        var entered=false
        auth.vault(gate,discard,{ connection -> entered=true; try { task(connection) } finally { supplied.forEach { it.fill('\u0000') } } }) { result ->
            supplied.forEach { it.fill('\u0000') }
            if(!entered) abandoned()
            runOnUiThread {
                val value=result.value
                if(work!==gate || !gate.isActive() || !ready() || !life.workActive(id)) { value?.let(discard); gate.cancel(); if(work===gate) { work=null; activeWorkId=null }; return@runOnUiThread }
                work=null; activeWorkId=null; gate.cancel(); busy(false)
                if(!life.consumeWork(id,display && result.code==null,::ready) {
                    if(result.code!=null || value==null) {
                        value?.let(discard)
                        if(NativeVaultReauthentication.required(result.code)) {
                            try { if(reauthentication!=null) reauthentication() else reauthenticateForm() }
                            catch(_:Exception) { close() }
                        } else failure(result.code ?: "ACCESS_DENIED")
                    }
                    else try { done(value) } catch(_:Exception) { discard(value); failure("ACCESS_DENIED") }
                }) { value?.let(discard); close() }
            }
        }
    }
    private class Loaded(val snapshot:NativeVaultSnapshot,val cards:List<VaultRecord>,val shares:List<VaultRecord>,val rotation:VaultRecord?)
    @Suppress("UNCHECKED_CAST")
    private fun load() {
        if(loaded || !ready() || work!=null) return
        runNative(task={ c ->
            val s=c.snapshot(if(action in NativeVaultUiPolicy.cardActions) target else null)
            val r=if(action in NativeVaultUiPolicy.rotationActions) c.rotation(s,target!!) else s.status["pending_rotation_id"]?.let { if(s.scope!=null) c.rotation(s,it as String) else null }
            val cards=if(action=="manage" && s.scope!=null) c.cardList(s) else emptyList()
            val shares=if(action=="manage" && s.status["initialized"]==true) {
                val page=c.call(NativeVaultCommand(VaultOperation.SHARES)); val rows=page["items"] as List<VaultRecord>
                if(rows.any { it["household_id"]!=s.householdId }) throw NativeVaultFailure("ACCESS_DENIED"); rows
            } else emptyList()
            Loaded(s,cards,shares,r)
        },done={ data -> loaded=true; snapshot=data.snapshot; rotation=data.rotation; render(data) })
    }
    private fun navigate(next:String,id:String?=null) {
        NativeVaultUiPolicy.native(next,id); pending?.discard(); pending=null; retryCommand=null
        managementReauthentication?.discard(); managementReauthentication=null
        action=next; target=id; snapshot=null; rotation=null; loaded=false; heading(); load()
    }
    private fun title(card:VaultRecord)=listOfNotNull(card["alias"] as? String ?: card["product_name"] as? String,card["masked_number"] as? String).joinToString(" · ")
    private fun render(data:Loaded) {
        heading(); val s=data.snapshot
        status.text="${s.me["display_name"]} · "+(if(s.status["initialized"]==true) "키 버전 ${s.status["current_key_version"]}" else "보관함 미설정")
        if(s.card!=null) label(title(s.card),20f)
        when(action) {
            "manage" -> manage(data)
            "setup" -> setupForm()
            "view" -> viewForm()
            "edit" -> editForm()
            "register-device" -> registerForm()
            "change-password" -> changeForm()
            "recover" -> recoverForm()
            "share" -> shareForm()
            "accept-share" -> acceptForm()
            "purge", "cancel-share", "revoke-member", "abort-rotation" -> confirmationForm()
            "rotate", "resume-rotation" -> rotationForm()
            "cvc-edit", "cvc-view", "cvc-delete" -> cvcForm()
        }
        button("닫기",true,::close)
    }
    private fun manage(data:Loaded) {
        val s=data.snapshot
        if(s.status["initialized"]!=true) { button("보관함 처음 설정") { navigate("setup") }; return }
        if(s.scope!=null) {
            button("이 기기에 보관함 등록") { navigate("register-device") }
            button("보관함 암호 변경") { navigate("change-password") }; button("복구코드로 암호 복구") { navigate("recover") }
            if(data.rotation!=null) {
                button("진행 중인 키 회전 이어가기") { navigate("resume-rotation",data.rotation["id"] as String) }
                button("진행 중인 키 회전 중단") { navigate("abort-rotation",data.rotation["id"] as String) }
            } else button(if(s.status["rotation_required"]==true) "접근 철회 후 키 회전" else "보관함 키 회전") { navigate("rotate") }
            @Suppress("UNCHECKED_CAST") val members=s.status["members"] as List<VaultRecord>
            for(member in members) {
                val id=member["member_id"] as String
                if(id==s.memberId) continue
                val name=s.members.single { it["member_id"]==id }["display_name"]
                if(member["status"]=="active") button("$name 님 보관함 접근 철회") { navigate("revoke-member",id) }
                else button("$name 님에게 보관함 공유") { navigate("share",id) }
            }
            for(card in data.cards) {
                label(title(card),18f); val id=card["id"] as String
                if(card["has_secret"]==true) {
                    button("보호 정보 보기") { navigate("view",id) }; button("카드 비밀 삭제") { navigate("purge",id) }
                    button("이 기기 보안코드 관리") { navigate("cvc-edit",id) }
                }
                button("번호·유효기간 입력/수정") { navigate("edit",id) }
            }
        } else label("기존 구성원의 공유 요청을 수락해야 보관함을 열 수 있습니다.")
        for(offer in data.shares.filter { it["state"]=="pending" }) {
            val id=offer["id"] as String
            if(offer["target_member_id"]==s.memberId) button("받은 보관함 공유 확인·수락") { navigate("accept-share",id) }
            button("보관함 공유 요청 취소") { navigate("cancel-share",id) }
        }
    }
    private fun passwordHint()=label("보관함 전용 암호를 입력하세요. 새 암호는 12자 이상이며 로그인 암호나 짧은 PIN을 재사용하지 마세요.",14f)
    private fun setupForm() {
        if(snapshot?.status?.get("initialized")!=false) { failure("VAULT_ALREADY_INITIALIZED"); return }
        passwordHint(); val first=input("새 보관함 암호"); val second=input("새 보관함 암호 확인")
        button("복구코드 준비") {
            val a=take(first); val b=take(second)
            if(!a.contentEquals(b)) { a.fill('\u0000'); b.fill('\u0000'); failure("PASSWORD_POLICY"); return@button }; b.fill('\u0000')
            runNative(discard=NativeVaultPrepared::discard,supplied=listOf(a),display=true,task={ c -> NativeVaultActions.initialize(c.snapshot(),a) },done=::prepared)
        }
    }
    private fun unlock(c:NativeVaultConnection,password:CharArray,cardId:String?=null):Pair<NativeVaultMaterial,VaultRecord> {
        val s=c.snapshot(cardId); s.requireEnrolled(); val wrap=c.ownWrapping(s)
        val key=NativeVaultActions.unlock(password,wrap,s.householdId,s.memberId,s.keyVersion)
        try { c.check(); return NativeVaultMaterial(s,key) to wrap } catch(failure:Exception) { key.fill(0); throw failure }
    }
    private fun prepared(value:NativeVaultPrepared) {
        pending?.discard(); pending=value; retryCommand=value.command
        if(value.recoveryCode==null) { commitPrepared(); return }
        heading(); status.text="복구코드를 오프라인의 안전한 곳에 보관하세요. 이 화면은 한 번만, 최대 30초 표시합니다."
        label("복구코드나 보관함 암호·신뢰 기기가 모두 없으면 기존 카드 비밀을 복원할 수 없습니다. 자동 복사·백업은 제공하지 않습니다.",14f)
        secretOutput.text=String(value.recoveryCode); showing=true; recoveryShowing=true
        val saved=checkbox("복구코드를 오프라인에 안전하게 보관했어요")
        button("보관 확인 후 저장") {
            if(!saved.isChecked || life.displayRemaining()==0L || pending!==value) { status.text="복구코드 보관 확인이 필요합니다."; return@button }
            secretOutput.text=""; showing=false; recoveryShowing=false; value.recoveryCode.fill('\u0000'); life.lock(); commitPrepared()
        }
        button("취소",true,::close)
    }
    private fun sameIdentity(a:NativeVaultSnapshot,b:NativeVaultSnapshot) {
        if(a.householdId!=b.householdId || a.memberId!=b.memberId || a.me["user_id"]!=b.me["user_id"] || a.deviceId!=b.deviceId) throw NativeVaultFailure("ACCESS_DENIED")
    }
    private fun commitPrepared() {
        val value=pending ?: return
        var continuation:NativeVaultReauthentication?=null
        runNative(reauthentication={
            pending=null; retryCommand=null
            managementReauthenticate(continuation ?: NativeVaultReauthentication.prepared(value))
        },task={ c ->
            try { sameIdentity(value.material.snapshot,c.snapshot()); c.call(value.command) }
            catch(failure:NativeVaultFailure) {
                if(NativeVaultReauthentication.required(failure.code)) continuation=NativeVaultReauthentication.prepared(value)
                throw failure
            }
        },done={
            completed=true; pending=null; retryCommand=null
            if(value.command.operation==VaultOperation.ROTATION_PREPARE) {
                val material=value.material; value.recoveryCode?.fill('\u0000'); continueRotation(material,value.command.id!!)
            } else {
                if(value.command.operation==VaultOperation.CARD_WRITE) value.material.snapshot.scope?.let { local.clearCard(it,value.command.id!!) }
                value.discard(); success()
            }
        })
        if(controls.none { it.text=="동일 요청 다시 확인" }) button("동일 요청 다시 확인") { if(pending===value) commitPrepared() }
    }
    private fun commitSimple(command:NativeVaultCommand) {
        retryCommand=command; val before=snapshot ?: return
        runNative(reauthentication={ managementReauthenticate(NativeVaultReauthentication.command(before,command)) },task={ c -> sameIdentity(before,c.snapshot()); c.call(command) },done={
            completed=true; retryCommand=null
            if(command.operation==VaultOperation.CARD_DELETE) before.scope?.let { local.clearCard(it,command.id!!) }
            success()
        })
        if(controls.none { it.text=="동일 요청 다시 확인" }) button("동일 요청 다시 확인") { if(retryCommand===command) commitSimple(command) }
    }
    private fun success(message:String="보관함 변경을 완료했어요.") {
        heading(); status.text=message; button("보관함 상태 다시 확인") { navigate("manage") }; button("닫기",true,::close)
    }
    private fun viewForm() {
        val s=snapshot ?: return; val card=s.card ?: return
        if(card["has_secret"]!=true || s.scope==null) { failure("VAULT_SECRET_NOT_SET"); return }
        if(local.exists(NativeVaultBinding(s.scope))) button("지문으로 최대 30초 보기") { biometricView(false) }
        passwordHint(); val password=input("보관함 암호")
        button("암호로 최대 30초 보기") {
            val chars=take(password)
            runNative(discard=VaultCardSecret::discard,supplied=listOf(chars),display=true,task={ c ->
                val (material,_)=unlock(c,chars,target)
                try { val envelope=c.cardEnvelope(material.snapshot,target!!); c.check(); NativeVaultActions.openCard(material.key,envelope,material.snapshot.householdId,material.snapshot.keyVersion) }
                finally { material.discard() }
            },done=::showCard)
        }
        button("기기 등록 또는 재등록") { navigate("register-device") }
    }
    private fun showCard(secret:VaultCardSecret) {
        try { secretOutput.text=String(secret.pan)+"\n%02d/%04d".format(secret.expiryMonth,secret.expiryYear)+(if(secret.schemaVersion==2) "\n공유 CVC: "+(if(secret.cvc.isEmpty()) "미입력" else String(secret.cvc)) else ""); showing=true; completed=true
            status.text="최대 30초 표시합니다. 화면 이탈·잠금 시 즉시 가립니다." }
        finally { secret.discard() }
    }
    private fun editForm() {
        passwordHint(); val password=input("보관함 암호"); val pan=input("전체 카드번호 · 숫자만",true,19)
        val year=input("유효기간 연도 · 네 자리",true,4); val month=input("유효기간 월",true,2)
        label("공유 CVC는 보관함 공유 구성원과 복구 수단 소유자가 볼 수 있고 암호문이 서버·백업에 포함됩니다. 삭제해도 이전 백업에 남을 수 있습니다. 기기 로컬 CVC는 별개이며 카드 비밀 변경 시 무효화될 수 있습니다.",14f)
        val modes=RadioGroup(this).apply { isSaveEnabled=false; column.addView(this) }
        val choices=listOf("기존 공유 CVC 유지","공유 CVC 입력·교체","공유 CVC 삭제").map { text ->
            RadioButton(this).apply { id=View.generateViewId(); this.text=text; isSaveEnabled=false; filterTouchesWhenObscured=true; modes.addView(this) }
        }
        modes.check(choices[0].id)
        val code=input("공유 CVC · 3~4자리",true,4).apply { isEnabled=false }
        val consent=checkbox("공유 CVC의 접근·백업·삭제 범위를 확인했어요")
        modes.setOnCheckedChangeListener { _, id -> code.text?.clear(); code.isEnabled=id==choices[1].id; consent.isChecked=false }
        button("카드번호·유효기간·공유 CVC 저장") {
            val mode=choices.indexOfFirst { it.id==modes.checkedRadioButtonId }
            if(mode !in 0..2 || mode!=0 && !consent.isChecked) { status.text="공유 CVC 변경 범위를 확인해 주세요."; return@button }
            val pw=take(password); val p=take(pan); val y=take(year); val m=take(month); val cv=take(code)
            val yearValue=String(y).toIntOrNull(); val monthValue=String(m).toIntOrNull(); y.fill('\u0000'); m.fill('\u0000')
            if(yearValue==null || monthValue==null || mode==1 && (cv.size !in 3..4 || cv.any { it !in '0'..'9' })) {
                listOf(pw,p,cv).forEach { it.fill('\u0000') }; failure("INVALID_FORMAT"); return@button
            }
            runNative(discard=NativeVaultPrepared::discard,supplied=listOf(pw,p,cv),task={ c ->
                val (material,_)=unlock(c,pw,target)
                var old:VaultCardSecret?=null; var secret:VaultCardSecret?=null
                try {
                    val savedCard=material.snapshot.card ?: throw NativeVaultFailure("INVALID_REQUEST")
                    if(mode==0 && savedCard["has_secret"]==true) {
                        val envelope=c.cardEnvelope(material.snapshot,target!!)
                        if(NativeVaultWire.version(envelope["card_version"])!=NativeVaultWire.version(savedCard["version"])) throw NativeVaultFailure("VERSION_CONFLICT")
                        old=NativeVaultActions.openCard(material.key,envelope,material.snapshot.householdId,material.snapshot.keyVersion)
                    }
                    secret=VaultCardSecret(p,yearValue,monthValue,if(mode==0) old?.cvc?.copyOf() ?: charArrayOf() else if(mode==1) cv.copyOf() else charArrayOf(),2)
                    NativeVaultActions.writeCard(material,secret)
                } catch(failure:Exception) { material.discard(); throw failure }
                finally { old?.discard(); secret?.discard() }
            },done=::prepared)
        }
    }
    private fun changeForm() {
        passwordHint(); val old=input("현재 보관함 암호"); val fresh=input("새 보관함 암호"); val confirm=input("새 암호 확인")
        button("보관함 암호 변경") {
            val a=take(old); val b=take(fresh); val d=take(confirm)
            if(!b.contentEquals(d)) { listOf(a,b,d).forEach { it.fill('\u0000') }; failure("PASSWORD_POLICY"); return@button }; d.fill('\u0000')
            runNative(discard=NativeVaultPrepared::discard,supplied=listOf(a,b),task={ c ->
                val (material,wrap)=unlock(c,a)
                try { NativeVaultActions.changePassword(material,b,wrap) } catch(failure:Exception) { material.discard(); throw failure }
            },done=::prepared)
        }
    }
    private fun recoverForm() {
        label("계정 로그인 복구와 보관함 복구는 다릅니다. 복구코드로 현재 키를 확인한 뒤 새 보관함 암호와 새 복구코드를 설정합니다.")
        label("코드 유출에 대응하려면 복구 후 새 보관함 키 회전도 수행해야 합니다. 예전 코드와 wrapping의 오프라인 사본을 회수할 수는 없습니다.",14f)
        passwordHint(); val code=input("보관함 복구코드",maximum=43); val fresh=input("새 보관함 암호"); val confirm=input("새 암호 확인")
        button("복구 확인과 새 코드 준비") {
            val a=take(code); val b=take(fresh); val d=take(confirm)
            if(!b.contentEquals(d)) { listOf(a,b,d).forEach { it.fill('\u0000') }; failure("PASSWORD_POLICY"); return@button }; d.fill('\u0000')
            runNative(discard=NativeVaultPrepared::discard,supplied=listOf(a,b),display=true,task={ c ->
                val s=c.snapshot(); s.requireEnrolled(); val wrap=c.call(NativeVaultCommand(VaultOperation.RECOVERY_WRAP))
                val key=NativeVaultActions.unlockRecovery(a,wrap,s.householdId,s.keyVersion); val material=NativeVaultMaterial(s,key)
                try { NativeVaultActions.recover(material,b,wrap) } catch(failure:Exception) { material.discard(); throw failure }
            },done=::prepared)
        }
    }
    private fun shareForm() {
        val s=snapshot ?: return; val member=s.members.singleOrNull { it["member_id"]==target } ?: run { failure("VAULT_MEMBER_UNAVAILABLE"); return }
        label("${member["display_name"]} 님과 공유합니다. 상대가 이 신뢰 기기에서 본인의 보관함 암호를 직접 입력하고, 본인 계정에서 15분 안에 확인·수락해야 합니다.")
        passwordHint(); val mine=input("현재 내 보관함 암호"); val theirs=input("상대가 사용할 보관함 암호"); val confirm=input("상대 암호 확인")
        button("공유 요청 만들기") {
            val a=take(mine); val b=take(theirs); val d=take(confirm)
            if(!b.contentEquals(d)) { listOf(a,b,d).forEach { it.fill('\u0000') }; failure("PASSWORD_POLICY"); return@button }; d.fill('\u0000')
            runNative(discard=NativeVaultPrepared::discard,supplied=listOf(a,b),task={ c ->
                val (material,_)=unlock(c,a)
                try { NativeVaultActions.share(material,target!!,b) } catch(failure:Exception) { material.discard(); throw failure }
            },done=::prepared)
        }
    }
    @Suppress("UNCHECKED_CAST")
    private fun acceptForm() {
        label("신뢰 기기에서 공유를 준비할 때 입력한 본인 보관함 암호로 키를 확인하고 수락합니다.")
        val password=input("공유받은 보관함 암호"); val confirm=checkbox("이 가계의 보관함 공유를 수락할게요")
        button("키 확인 후 공유 수락") {
            if(!confirm.isChecked) { status.text="공유 수락 확인이 필요합니다."; return@button }
            val pw=take(password)
            runNative(discard=NativeVaultPrepared::discard,supplied=listOf(pw),task={ c ->
                val s=c.snapshot(); val wrap=c.call(NativeVaultCommand(VaultOperation.SHARE_WRAP,id=target!!))
                val offer=wrap["offer"] as VaultRecord
                if(offer["household_id"]!=s.householdId || offer["target_member_id"]!=s.memberId) throw NativeVaultFailure("ACCESS_DENIED")
                val key=NativeVaultActions.unlock(pw,wrap,s.householdId,s.memberId,s.keyVersion)
                try { val command=NativeVaultActions.simple(VaultOperation.SHARE_ACCEPT,s,target,NativeVaultWire.version(offer["version"]),mapOf("key_version" to s.keyVersion,"key_check_confirmed" to true))
                    NativeVaultPrepared(command,NativeVaultMaterial(s,key)) }
                catch(failure:Exception) { key.fill(0); throw failure }
            },done=::prepared)
        }
    }
    @Suppress("UNCHECKED_CAST")
    private fun confirmationForm() {
        val description=when(action) {
            "purge" -> "이 카드의 서버에 남은 모든 버전 암호문을 삭제합니다. 일반 카드와 감사 이력은 남습니다. 기존 백업·다른 기기의 사본을 즉시 회수할 수는 없습니다."
            "revoke-member" -> "상대의 보관함 접근 권한을 철회합니다. 이미 본 정보는 회수할 수 없고 이어서 새 키 회전이 필요합니다."
            "abort-rotation" -> "준비 중인 키 회전을 중단합니다. 기존 현재 키는 유지되고 중단한 키 버전을 재사용하지 않습니다."
            else -> "진행 중인 보관함 공유 요청을 취소합니다."
        }
        label(description); val confirm=checkbox("대상과 결과를 확인했고 진행할게요")
        button("확인 후 진행") {
            if(!confirm.isChecked) { status.text="진행 확인이 필요합니다."; return@button }
            runNative(task={ c ->
                val s=c.snapshot(if(action=="purge") target else null)
                when(action) {
                    "purge" -> { s.requireEnrolled(); NativeVaultActions.simple(VaultOperation.CARD_DELETE,s,target,NativeVaultWire.version(s.card!!["version"]),null) }
                    "revoke-member" -> {
                        s.requireEnrolled(); val member=(s.status["members"] as List<VaultRecord>).singleOrNull { it["member_id"]==target } ?: throw NativeVaultFailure("VAULT_MEMBER_UNAVAILABLE")
                        NativeVaultActions.simple(VaultOperation.REVOKE,s,target,NativeVaultWire.version(member["version"]))
                    }
                    "abort-rotation" -> { val r=c.rotation(s,target!!); NativeVaultActions.simple(VaultOperation.ROTATION_ABORT,s,target,NativeVaultWire.version(r["version"])) }
                    else -> {
                        var cursor:String?=null; var found:VaultRecord?=null; var count=0
                        do { val page=c.call(NativeVaultCommand(VaultOperation.SHARES,cursor=cursor)); val offers=page["items"] as List<VaultRecord>
                            found=offers.singleOrNull { it["id"]==target }; count+=offers.size; if(count>2000) throw NativeVaultFailure("ACCESS_DENIED"); cursor=page["next_cursor"] as String?
                        } while(found==null && cursor!=null)
                        val offer=found ?: throw NativeVaultFailure("VAULT_SHARE_UNAVAILABLE")
                        if(offer["household_id"]!=s.householdId || s.memberId !in setOf(offer["source_member_id"],offer["target_member_id"])) throw NativeVaultFailure("ACCESS_DENIED")
                        NativeVaultActions.simple(VaultOperation.SHARE_CANCEL,s,target,NativeVaultWire.version(offer["version"]))
                    }
                }
            },done=::commitSimple)
        }
    }
    private fun strongReady():Boolean = keyguard.isDeviceSecure && getSystemService(BiometricManager::class.java)
        .canAuthenticate(BiometricManager.Authenticators.BIOMETRIC_STRONG)==BiometricManager.BIOMETRIC_SUCCESS
    private fun registerForm() {
        label("이 기기에 강력한 생체인증이 필요합니다. 기기 키는 추출·복사하지 않으며, 지문 등록 변경 뒤에는 보관함 암호로 명시적으로 다시 등록해야 합니다.")
        if(!strongReady()) { label("강력한 생체인증을 사용할 수 없습니다. 카드 보기에서 보관함 암호를 직접 입력할 수 있습니다."); return }
        passwordHint(); val password=input("보관함 암호"); val confirm=checkbox("인증과 저장이 완료되면 이 기기의 등록 정보를 갱신할게요")
        button("암호 확인 후 기기 등록") {
            if(!confirm.isChecked) { status.text="기기 등록 확인이 필요합니다."; return@button }
            val pw=take(password)
            runNative(discard=NativeVaultMaterial::discard,supplied=listOf(pw),task={ c -> unlock(c,pw).first },done={ material ->
                try {
                    val op=local.prepareEncryption(NativeVaultBinding(material.snapshot.requireEnrolled()))
                    beginPrompt(op,material.key) { _ ->
                        runNative(task={ c -> val current=c.snapshot(); sameIdentity(material.snapshot,current)
                            if(current.keyVersion!=material.snapshot.keyVersion) throw NativeVaultFailure("KEY_INVALIDATED"); Unit
                        },done={ completed=true; success("이 기기 보관함 등록을 완료했어요. 이후 보기에는 매번 별도 생체인증이 필요합니다.") })
                    }
                } catch(_:Exception) { material.discard(); failure("KEY_INVALIDATED") }
            })
        }
        label("지문 등록 변경 등으로 기기 키가 영구 무효화된 경우에만 이전 기기 등록을 별도로 지울 수 있습니다. 삭제 뒤 보관함 암호로 다시 등록하세요.",14f)
        val reset=checkbox("영구 무효화가 확인된 이 기기의 등록을 삭제할게요")
        button("무효화 확인 후 기기 등록 삭제") {
            if(!reset.isChecked) { status.text="무효화된 기기 등록 삭제 확인이 필요합니다."; return@button }
            runNative(task={ c -> c.snapshot().also { it.requireEnrolled() } },done={ current ->
                local.clearInvalidatedRegistration(NativeVaultBinding(current.requireEnrolled()),true)
                status.text="무효화된 기기 등록을 삭제했어요. 보관함 암호를 입력해 다시 등록하세요."
            })
        }
    }
    private class BiometricLoad(val snapshot:NativeVaultSnapshot,val envelope:VaultRecord)
    private fun biometricView(localCode:Boolean) {
        if(!strongReady()) { failure("KEY_INVALIDATED"); return }
        runNative(task={ c -> val s=c.snapshot(target); val e=c.cardEnvelope(s,target!!); BiometricLoad(s,e) },done={ data ->
            val binding=if(localCode) NativeVaultBinding(data.snapshot.requireEnrolled(),target!!,NativeVaultWire.id(data.envelope["id"]),NativeVaultWire.version(data.envelope["revision"]))
                else NativeVaultBinding(data.snapshot.requireEnrolled())
            if(localCode && !local.exists(binding)) {
                status.text="이 기기에 저장된 보안코드가 없어요. 직접 입력해 주세요."; return@runNative
            }
            try {
                beginPrompt(local.prepareDecryption(binding),null) { raw ->
                    val bytes=raw ?: throw NativeVaultFailure("KEY_INVALIDATED")
                    if(localCode) {
                        runNative(discard={ value:ByteArray -> value.fill(0) },display=true,abandoned={ bytes.fill(0) },task={ c ->
                            try {
                                val s=c.snapshot(target); sameIdentity(data.snapshot,s); val e=c.cardEnvelope(s,target!!)
                                if(s.keyVersion!=data.snapshot.keyVersion || e["id"]!=data.envelope["id"] || e["revision"]!=data.envelope["revision"]) throw NativeVaultFailure("KEY_INVALIDATED")
                                bytes.copyOf()
                            } finally { bytes.fill(0) }
                        },done={ value -> try { secretOutput.text=value.toString(Charsets.US_ASCII); showing=true; completed=true; status.text="이 기기에 직접 입력한 보안코드 · 최대 30초" } finally { value.fill(0) } })
                    } else {
                        runNative(discard=VaultCardSecret::discard,display=true,abandoned={ bytes.fill(0) },task={ c ->
                            try {
                                val s=c.snapshot(target); sameIdentity(data.snapshot,s)
                                if(s.keyVersion!=data.snapshot.keyVersion) throw NativeVaultFailure("KEY_INVALIDATED")
                                val wrap=c.ownWrapping(s); NativeVaultActions.verify(bytes,wrap,s.householdId,s.keyVersion)
                                val e=c.cardEnvelope(s,target!!); c.check(); NativeVaultActions.openCard(bytes,e,s.householdId,s.keyVersion)
                            } finally { bytes.fill(0) }
                        },done=::showCard)
                    }
                }
            } catch(failure:NativeVaultFailure) { failure(failure.code) }
            catch(_:Exception) { failure("KEY_INVALIDATED") }
        })
    }
    private fun beginPrompt(operation:NativeVaultKeyOperation,plaintext:ByteArray?,next:(ByteArray?)->Unit) {
        val id=if(ready() && strongReady()) life.beginPrompt() else null
        if(id==null) { plaintext?.fill(0); operation.discard(); failure("KEY_INVALIDATED"); return }
        val current=Prompt(id,operation,plaintext,ForegroundRequest(),CancellationSignal(),next); prompt=current; busy(true)
        try {
            val system=BiometricPrompt.Builder(this).setTitle("SallimBook 카드 보관함")
                .setSubtitle(if(operation.encrypt) "기기 키로 보호하기" else "등록된 기기 키 사용 · 최대 30초 표시")
                .setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_STRONG)
                .setNegativeButton("취소",mainExecutor) { _,_ -> endPrompt(current,"AUTH_CANCELLED") }.build()
            system.authenticate(BiometricPrompt.CryptoObject(operation.cipher),current.signal,mainExecutor,object:BiometricPrompt.AuthenticationCallback() {
                override fun onAuthenticationSucceeded(result:BiometricPrompt.AuthenticationResult) {
                    if(prompt!==current) return
                    val returned=result.cryptoObject?.cipher
                    val valid=try { current.gate.check(); auth.vaultGeneration==sessionGeneration && resumed && !appLock.locked && !keyguard.isDeviceLocked } catch(_:Exception) { false }
                    if(!valid || returned!==operation.cipher || !life.promptSucceeded(id)) { endPrompt(current,"AUTH_CANCELLED"); return }
                    current.returned=returned; finishPrompt()
                }
                override fun onAuthenticationError(errorCode:Int,errString:CharSequence) { endPrompt(current,"AUTH_CANCELLED") }
                override fun onAuthenticationFailed() { if(prompt===current) status.text="인증을 확인하지 못했어요. 다시 시도하거나 취소해 주세요." }
            })
        } catch(_:Exception) { life.lock(); current.signal.cancel(); close() }
    }
    private fun endPrompt(current:Prompt,code:String) {
        if(prompt!==current) return
        life.promptEnded(current.id); life.lock(); prompt=null; current.discard(); busy(false); failure(code)
    }
    private fun finishPrompt() {
        val current=prompt ?: return; val returned=current.returned ?: return
        if(life.focusRemaining(current.id)==0L) { endPrompt(current,"AUTH_CANCELLED"); return }
        if(!ready() || !life.claimCipher(current.id)) return
        var value:ByteArray?=null
        try {
            current.gate.whileActive { value=local.finish(current.operation,returned,current.plaintext) }
            if(!ready() || !life.finishCipher(current.id,false)) throw NativeVaultFailure("AUTH_CANCELLED")
            prompt=null; current.discard(); busy(false)
            current.next(value); value=null
        } catch(failure:NativeVaultFailure) { value?.fill(0); endPrompt(current,failure.code); failure(failure.code) }
        catch(_:Exception) { value?.fill(0); endPrompt(current,"KEY_INVALIDATED"); failure("KEY_INVALIDATED") }
    }
    private class CodeLoad(val data:BiometricLoad,val bytes:ByteArray) { fun discard()=bytes.fill(0) }
    private fun cvcForm() {
        label("보안코드는 이 Android 기기에 직접 입력하고 별도 기기 키로 보호합니다. 서버·웹·백업·기기 이전으로 복구할 수 없습니다. 기기마다 다시 입력해야 합니다.")
        if(action=="cvc-delete") {
            val confirm=checkbox("이 기기의 보안코드를 삭제할게요")
            button("로컬 보안코드 삭제") {
                if(!confirm.isChecked) return@button
                runNative(task={ c -> c.snapshot(target).also { it.requireEnrolled() } },done={ s -> local.clearCard(s.requireEnrolled(),target!!); completed=true; success("이 기기의 보안코드를 삭제했어요.") })
            }; return
        }
        if(!strongReady()) { failure("KEY_INVALIDATED"); return }
        if(action=="cvc-view") {
            button("기기 인증 후 보안코드 보기") { biometricView(true) }
            button("보안코드 직접 입력·수정") { navigate("cvc-edit",target) }
            button("이 기기 보안코드 삭제") { navigate("cvc-delete",target) }; return
        }
        label("저장은 선택 사항입니다. 이 기기를 사용하는 사람이 등록된 생체인증으로 볼 수 있어요. 지문 등록 변경·재설치·기기 교체 후에는 삭제하고 다시 입력해야 합니다.")
        val code=input("이 기기에 직접 입력할 3~4자리 보안코드",true,4)
        val confirm=checkbox("이 기기에 보관할 위험과 재입력 필요성을 확인했고 직접 입력했어요")
        button("기기 인증 후 로컬 저장") {
            if(!confirm.isChecked) { status.text="보관 확인이 필요합니다."; return@button }
            val value=try { NativeVaultCvcPolicy.input(confirm.isChecked,take(code)) }
                catch(problem:NativeVaultFailure) { failure(problem.code); return@button }
            runNative(discard=CodeLoad::discard,abandoned={ value.fill(0) },task={ c ->
                try { val s=c.snapshot(target); val e=c.cardEnvelope(s,target!!); CodeLoad(BiometricLoad(s,e),value) } catch(failure:Exception) { value.fill(0); throw failure }
            },done={ owned ->
                val data=owned.data
                try {
                    val binding=NativeVaultBinding(data.snapshot.requireEnrolled(),target!!,NativeVaultWire.id(data.envelope["id"]),NativeVaultWire.version(data.envelope["revision"]))
                    beginPrompt(local.prepareEncryption(binding),owned.bytes) { _ ->
                        runNative(task={ c -> val current=c.snapshot(target); sameIdentity(data.snapshot,current); val envelope=c.cardEnvelope(current,target!!)
                            if(current.keyVersion!=data.snapshot.keyVersion || envelope["id"]!=data.envelope["id"] || envelope["revision"]!=data.envelope["revision"]) throw NativeVaultFailure("KEY_INVALIDATED"); Unit
                        },done={ completed=true; success("이 기기에만 보안코드를 저장했어요.") })
                    }
                } catch(_:Exception) { value.fill(0); failure("KEY_INVALIDATED") }
            })
        }
        button("저장된 보안코드 보기") { navigate("cvc-view",target) }; button("이 기기 보안코드 삭제") { navigate("cvc-delete",target) }
    }
    @Suppress("UNCHECKED_CAST")
    private fun rotationForm() {
        if(action=="rotate") {
            label("새 키로 모든 카드와 유지할 구성원의 wrapping을 준비한 뒤 함께 전환합니다. 준비 중에도 기존 키로 볼 수 있으며 변경은 잠시 동결됩니다.")
            val compromised=checkbox("키 또는 복구코드 유출에 대응하는 회전이에요")
            val confirm=checkbox("키 회전을 시작하고 유지할 구성원의 새 암호를 이 신뢰 기기에서 준비할게요")
            button("키 회전 시작") {
                if(!confirm.isChecked) { status.text="키 회전 시작 확인이 필요합니다."; return@button }
                val reason=if(compromised.isChecked) "key_compromised" else if(snapshot?.status?.get("rotation_required")==true) "member_access_removed" else "routine"
                runNative(task={ c -> val s=c.snapshot(); s.requireEnrolled(); NativeVaultActions.simple(VaultOperation.ROTATION_START,s,body=mapOf("reason" to reason)) },done=::commitStart)
            }; return
        }
        val r=rotation ?: run { failure("VAULT_ROTATION_UNAVAILABLE"); return }
        if(r["state"]!="staging") { status.text="이 회전은 ${r["state"]} 상태입니다. 현재 보관함을 다시 확인해 주세요."; button("현재 상태 보기") { navigate("manage") }; return }
        label("회전 대상 카드 ${(r["cards"] as List<*>).size}개 · 구성원 ${(r["members"] as List<*>).size}명")
        val old=input("현재 키의 내 보관함 암호")
        if(r["key_check_prepared"]==true && r["recovery_prepared"]==true) {
            label("서버에 준비된 본인 wrapping으로 새 키를 복원해 이어갑니다. 새 키를 다시 생성하지 않습니다.")
            val fresh=input("이 회전에 준비한 새 보관함 암호")
            button("준비된 키 확인 후 이어가기") {
                val a=take(old); val b=take(fresh)
                runNative(discard=NativeVaultMaterial::discard,supplied=listOf(a,b),task={ c ->
                    val (material,_)=unlock(c,a); var next:ByteArray?=null
                    try {
                        val current=c.rotation(material.snapshot,target!!)
                        val wrap=c.ownWrapping(material.snapshot,current)
                        next=NativeVaultActions.unlock(b,wrap,material.snapshot.householdId,material.snapshot.memberId,NativeVaultWire.version(current["key_version"]))
                        NativeVaultMaterial(material.snapshot,material.key,next)
                    } catch(failure:Exception) { material.discard(); next?.fill(0); throw failure }
                },done={ material -> continueRotation(material,target!!) })
            }
        } else {
            passwordHint(); val passwords=linkedMapOf<String,Pair<EditText,EditText>>()
            for(member in r["members"] as List<VaultRecord>) {
                val id=member["member_id"] as String; val name=snapshot!!.members.single { it["member_id"]==id }["display_name"]
                label("$name 님이 이 신뢰 기기에서 회전 후 사용할 암호를 직접 입력하세요.")
                passwords[id]=input("$name 님의 새 보관함 암호") to input("암호 확인")
            }
            button("새 키와 복구코드 준비") {
                val oldChars=take(old); val values=linkedMapOf<String,CharArray>(); var matches=true
                for((id,fields) in passwords) { val a=take(fields.first); val b=take(fields.second); if(!a.contentEquals(b)) matches=false; b.fill('\u0000'); values[id]=a }
                if(!matches) { oldChars.fill('\u0000'); values.values.forEach { it.fill('\u0000') }; failure("PASSWORD_POLICY"); return@button }
                runNative(discard=NativeVaultPrepared::discard,supplied=listOf(oldChars)+values.values,display=true,task={ c ->
                    val (material,_)=unlock(c,oldChars)
                    try { val current=c.rotation(material.snapshot,target!!)
                        if(current["key_check_prepared"]!=false) throw NativeVaultFailure("VAULT_ALREADY_PREPARED")
                        NativeVaultActions.prepareRotation(material,current,values)
                    } catch(failure:Exception) { material.discard(); throw failure }
                },done=::prepared)
            }
        }
    }
    private fun commitStart(command:NativeVaultCommand) {
        retryCommand=command; val before=snapshot ?: return
        runNative(reauthentication={ managementReauthenticate(NativeVaultReauthentication.command(before,command)) },task={ c -> sameIdentity(before,c.snapshot()); c.call(command) },done={ ref ->
            completed=true; retryCommand=null; navigate("resume-rotation",NativeVaultWire.id(ref["id"]))
        })
        if(controls.none { it.text=="동일 시작 요청 다시 확인" }) button("동일 시작 요청 다시 확인") { if(retryCommand===command) commitStart(command) }
    }
    private class RotationProgress(val material:NativeVaultMaterial?,val rotationId:String,val retry:NativeVaultCommand?,val code:String?,
        val cursor:NativeVaultRotationCursor?=null,val advance:Boolean=false,val resumeSnapshot:NativeVaultSnapshot?=null) {
        fun discard() { material?.discard(); cursor?.discard() }
    }
    private var rotationProgress:RotationProgress?=null
    @Suppress("UNCHECKED_CAST")
    private fun continueRotation(material:NativeVaultMaterial,rotationId:String,retry:NativeVaultCommand?=null,previous:NativeVaultRotationCursor?=null) {
        rotationProgress=null
        runNative(discard=RotationProgress::discard,abandoned={ material.discard(); previous?.discard() },task={ c ->
            var failedCommand:NativeVaultCommand?=retry; var retained=false; var cursor=previous
            try {
                val fresh=c.snapshot(); sameIdentity(material.snapshot,fresh)
                if(fresh.keyVersion!=material.snapshot.keyVersion) {
                    val finished=c.rotation(fresh,rotationId)
                    if(finished["state"]=="current" && NativeVaultWire.version(finished["key_version"])==fresh.keyVersion) {
                        NativeVaultActions.verify(material.nextKey ?: throw NativeVaultFailure("VAULT_NOT_PREPARED"),c.ownWrapping(fresh),fresh.householdId,fresh.keyVersion)
                        return@runNative RotationProgress(null,rotationId,null,null)
                    }
                    throw NativeVaultFailure("VAULT_KEY_VERSION_CONFLICT")
                }
                NativeVaultActions.verify(material.key,c.ownWrapping(fresh),fresh.householdId,fresh.keyVersion)
                if(retry!=null) {
                    c.call(retry); failedCommand=null
                    if(retry.operation==VaultOperation.ROTATION_FINALIZE) {
                        confirmRotation(c,material,rotationId)
                        return@runNative RotationProgress(null,rotationId,null,null)
                    }
                }
                val manifest=c.rotation(fresh,rotationId)
                if(manifest["state"]!="staging") throw NativeVaultFailure("VAULT_ROTATION_UNAVAILABLE")
                val newKey=material.nextKey ?: throw NativeVaultFailure("VAULT_NOT_PREPARED")
                NativeVaultActions.verify(newKey,c.ownWrapping(fresh,manifest),fresh.householdId,NativeVaultWire.version(manifest["key_version"]))
                val progress=cursor ?: NativeVaultRotationCursor(manifest,material.key,newKey).also { cursor=it }
                progress.checkKeys(material.key,newKey)
                val card=progress.next(manifest)
                // Exactly one card per foreground work lease; the next card receives its own 60s gate.
                if(card!=null) {
                    c.check(); val cardId=card.id; val source=c.cardEnvelope(fresh,cardId)
                    if(source["id"]!=card.source || NativeVaultWire.version(source["revision"])!=card.revision || source["last_four"]!=card.lastFour) throw NativeVaultFailure("VAULT_ROTATION_SNAPSHOT_CONFLICT")
                    val row=(manifest["cards"] as List<VaultRecord>).single { it["card_id"]==cardId }
                    if(row["prepared"]==true) {
                        val staged=c.cardEnvelope(fresh,cardId,manifest)
                        val oldSecret=NativeVaultActions.openCard(material.key,source,fresh.householdId,fresh.keyVersion)
                        var newSecret:VaultCardSecret?=null
                        try {
                            newSecret=NativeVaultActions.openCard(newKey,staged,fresh.householdId,NativeVaultWire.version(manifest["key_version"]))
                            if(!oldSecret.pan.contentEquals(newSecret.pan) || oldSecret.expiryMonth!=newSecret.expiryMonth || oldSecret.expiryYear!=newSecret.expiryYear || oldSecret.schemaVersion!=newSecret.schemaVersion || !oldSecret.cvc.contentEquals(newSecret.cvc)) throw NativeVaultFailure("VAULT_ROTATION_SNAPSHOT_CONFLICT")
                        } finally { oldSecret.discard(); newSecret?.discard() }
                    } else {
                        failedCommand=NativeVaultActions.stageCard(material,manifest,source)
                        c.call(failedCommand); failedCommand=null
                    }
                    c.check(); progress.verified(card); retained=true
                    return@runNative RotationProgress(material,rotationId,null,null,progress,true)
                }
                progress.requireComplete(manifest)
                failedCommand=NativeVaultActions.simple(VaultOperation.ROTATION_FINALIZE,fresh,rotationId,NativeVaultWire.version(manifest["version"]),
                    mapOf("key_version" to manifest["key_version"],"key_check_confirmed" to true))
                c.call(failedCommand); failedCommand=null; confirmRotation(c,material,rotationId)
                RotationProgress(null,rotationId,null,null)
            } catch(failure:Exception) {
                val code=when(failure) { is NativeVaultFailure -> failure.code; is AuthFailure -> failure.code.name; is VaultCryptoFailure -> failure.code.name; else -> "ACCESS_DENIED" }
                if(code=="NETWORK_UNAVAILABLE" && failedCommand!=null) {
                    retained=true; RotationProgress(material,rotationId,failedCommand,code,cursor)
                } else if(code in setOf("REAUTHENTICATION_REQUIRED","STEP_UP_REQUIRED")) {
                    // Only continuity metadata survives account reauth; both raw keys are discarded now.
                    material.discard(); retained=true
                    RotationProgress(null,rotationId,failedCommand,code,cursor,resumeSnapshot=material.snapshot)
                } else throw failure
            } finally { if(!retained) { material.discard(); cursor?.discard() } }
        },done={ progress ->
            if(progress.advance) {
                status.text="카드 ${progress.cursor!!.verifiedCount}/${progress.cursor.total}개 확인·준비 완료"
                continueRotation(progress.material!!,progress.rotationId,previous=progress.cursor)
            } else if(progress.resumeSnapshot!=null) rotationReauthentication(progress)
            else if(progress.code==null) { completed=true; progress.discard(); success("새 키로 전환했어요. 이 기기의 보관함을 다시 등록하고 보안코드는 기기에서 다시 입력해 주세요.") }
            else {
                rotationProgress=progress; heading(); failure(progress.code)
                button("같은 회전 요청 확인 후 계속") { val retained=rotationProgress ?: return@button; rotationProgress=null; continueRotation(retained.material!!,retained.rotationId,retained.retry,retained.cursor) }
                button("닫고 나중에 이어가기",true,::close)
            }
        })
    }
    private fun confirmRotation(c:NativeVaultConnection,material:NativeVaultMaterial,rotationId:String) {
        val current=c.snapshot(); sameIdentity(material.snapshot,current); val finished=c.rotation(current,rotationId)
        if(finished["state"]!="current" || current.keyVersion==material.snapshot.keyVersion ||
            NativeVaultWire.version(finished["key_version"])!=current.keyVersion) throw NativeVaultFailure("VAULT_KEY_VERSION_CONFLICT")
        NativeVaultActions.verify(material.nextKey ?: throw NativeVaultFailure("VAULT_NOT_PREPARED"),c.ownWrapping(current),current.householdId,current.keyVersion)
    }
    private fun reauthenticateForm() {
        val before=snapshot ?: run { failure("REAUTHENTICATION_REQUIRED"); return }
        pending?.discard(); pending=null; retryCommand=null
        rotationProgress?.discard(); rotationProgress=null
        managementReauthenticate(NativeVaultReauthentication.form(before))
    }
    private fun managementReauthenticate(continuation:NativeVaultReauthentication) {
        if(managementReauthentication!==continuation) managementReauthentication?.discard()
        managementReauthentication=continuation; continuation.challenge()
        pending?.discard(); pending=null; retryCommand=null; life.lock(); heading()
        status.text="이 작업을 계속하려면 계정 재인증이 필요합니다. 원문 보관함 키와 입력은 지웠어요."
        label("현재 계정의 로그인 암호를 입력하세요. 준비된 암호화 요청은 같은 내용으로 다시 확인하며, 보관함 키가 필요한 다음 단계에서는 암호를 다시 입력합니다.")
        val password=input("현재 계정 로그인 암호")
        button("로그인 암호로 재인증") {
            reauthenticateAccount(take(password)) {
                if(managementReauthentication!==continuation) { close(); return@reauthenticateAccount }
                runNative(reauthentication={ managementReauthenticate(continuation) },task={ c ->
                    c.snapshot().also { continuation.authenticated(it) }
                },done={ fresh ->
                    if(managementReauthentication!==continuation) { close() }
                    else if(!continuation.hasCommand) {
                        val next=action; val id=target; navigate(next,id)
                        status.text="계정 재인증을 완료했어요. 지워진 보관함 입력을 다시 입력해 계속하세요."
                    } else {
                        snapshot=fresh; heading(); status.text="계정 재인증을 완료했어요. 준비한 동일 요청을 확인해 계속하세요."
                        button("동일 요청 확인 후 계속") { replayManagement(continuation) }
                        button("취소",true,::close)
                    }
                })
            }
        }
        button("취소",true,::close)
    }
    private fun replayManagement(continuation:NativeVaultReauthentication) {
        if(managementReauthentication!==continuation) return
        var sent:NativeVaultCommand?=null
        runNative(reauthentication={ managementReauthenticate(continuation) },task={ c ->
            val current=c.snapshot(); val command=continuation.retry(current); sent=command
            c.call(command)
        },done={ ref ->
            if(managementReauthentication!==continuation) { close(); return@runNative }
            val command=sent ?: throw NativeVaultFailure("ACCESS_DENIED")
            continuation.discard(); managementReauthentication=null; completed=true
            when(command.operation) {
                VaultOperation.ROTATION_START -> navigate("resume-rotation",NativeVaultWire.id(ref["id"]))
                // Raw old/new keys were wiped before reauth. Reopen staged wraps with explicit input.
                VaultOperation.ROTATION_PREPARE -> navigate("resume-rotation",command.id!!)
                else -> {
                    if(command.operation in setOf(VaultOperation.CARD_WRITE,VaultOperation.CARD_DELETE)) snapshot?.scope?.let { local.clearCard(it,command.id!!) }
                    success()
                }
            }
        })
    }
    private fun rotationReauthentication(progress:RotationProgress) {
        rotationProgress=progress; heading()
        status.text="계정 재인증이 필요해 보관함 키를 지웠어요. 확인한 카드 진행 정보는 이 화면에서만 유지합니다."
        label("현재 계정의 로그인 암호로 재인증한 뒤, 기존·새 보관함 암호로 같은 키를 다시 확인합니다. 화면을 닫거나 벗어나면 진행 정보도 지워집니다.")
        val password=input("현재 계정 로그인 암호")
        button("로그인 암호로 재인증") {
            val secret=take(password)
            reauthenticateAccount(secret) {
                if(rotationProgress!==progress) { close(); return@reauthenticateAccount }
                rotationUnlockAfterReauthentication(progress)
            }
        }
        button("닫고 나중에 이어가기",true,::close)
    }
    private fun reauthenticateAccount(password:CharArray,done:()->Unit) {
        val id=if(ready() && work==null && prompt==null) life.beginWork() else null
        if(id==null) { password.fill('\u0000'); return }
        val gate=ForegroundRequest().also { work=it; activeWorkId=id }; busy(true)
        auth.reauthenticate(password,gate) { result ->
            password.fill('\u0000')
            runOnUiThread {
                if(work!==gate || !gate.isActive() || !ready()) { gate.cancel(); if(work===gate) { work=null; activeWorkId=null }; return@runOnUiThread }
                work=null; activeWorkId=null; gate.cancel(); busy(false)
                if(!life.consumeWork(id,false,::ready) {
                    if(result.code==null && result.value?.get("status")=="authenticated") done()
                    else failure(result.code?.name ?: "AUTH_FAILED")
                }) close()
            }
        }
    }
    private fun rotationUnlockAfterReauthentication(progress:RotationProgress) {
        heading(); status.text="계정 재인증을 완료했어요. 같은 보관함 키를 확인한 뒤 다음 카드부터 계속합니다."
        val old=input("현재 키의 내 보관함 암호"); val fresh=input("이 회전에 준비한 새 보관함 암호")
        button("보관함 키 재확인 후 계속") {
            val a=take(old); val b=take(fresh)
            runNative(discard=NativeVaultMaterial::discard,supplied=listOf(a,b),task={ c ->
                val (material,_)=unlock(c,a); var next:ByteArray?=null
                try {
                    val expected=progress.resumeSnapshot ?: throw NativeVaultFailure("ACCESS_DENIED")
                    sameIdentity(expected,material.snapshot)
                    if(expected.keyVersion!=material.snapshot.keyVersion) throw NativeVaultFailure("VAULT_KEY_VERSION_CONFLICT")
                    val manifest=c.rotation(material.snapshot,progress.rotationId)
                    progress.cursor?.check(manifest)
                    next=NativeVaultActions.unlock(b,c.ownWrapping(material.snapshot,manifest),material.snapshot.householdId,
                        material.snapshot.memberId,NativeVaultWire.version(manifest["key_version"]))
                    progress.cursor?.checkKeys(material.key,next)
                    NativeVaultMaterial(material.snapshot,material.key,next)
                } catch(failure:Exception) { material.discard(); next?.fill(0); throw failure }
            },done={ material ->
                if(rotationProgress!==progress) { material.discard(); close() }
                else { rotationProgress=null; continueRotation(material,progress.rotationId,progress.retry,progress.cursor) }
            })
        }
        button("닫고 나중에 이어가기",true,::close)
    }
    private fun close() {
        entry?.cancel(); work?.cancel(); work=null; activeWorkId=null; life.lock(); prompt?.signal?.cancel(); prompt?.discard(); prompt=null
        pending?.discard(); pending=null; rotationProgress?.discard(); rotationProgress=null; retryCommand=null
        managementReauthentication?.discard(); managementReauthentication=null
        inputs.forEach { it.text.clear() }; if(::secretOutput.isInitialized) secretOutput.text=""
        showing=false; recoveryShowing=false; snapshot=null; rotation=null
        if(completed) setResult(Activity.RESULT_OK,Intent().putExtra(NativeAuthActivity.EXTRA_STATUS,"completed"))
        if(!isFinishing) finish()
    }
    override fun onResume() { super.onResume(); resumed=true; life.presentation(true,hasWindowFocus(),!keyguard.isDeviceLocked,!appLock.locked); if(keyguard.isDeviceLocked) close() else if(hasWindowFocus()) load() }
    override fun onWindowFocusChanged(hasFocus:Boolean) {
        super.onWindowFocusChanged(hasFocus)
        life.presentation(resumed,hasFocus,!keyguard.isDeviceLocked,!appLock.locked)?.let { if(prompt?.id==it) prompt?.signal?.cancel() }
        if(hasFocus) { hadFocus=true; if(prompt!=null) finishPrompt() else load() }
        else { inputs.forEach { it.text.clear() }; if(::secretOutput.isInitialized) secretOutput.text=""; showing=false
            if(hadFocus && prompt==null) close() }
    }
    override fun onPause() { resumed=false; close(); super.onPause() }
    override fun onSaveInstanceState(outState:Bundle) { close(); super.onSaveInstanceState(outState); outState.clear() }
    override fun onDestroy() { close(); handler.removeCallbacksAndMessages(null); if(receiverRegistered) unregisterReceiver(screenReceiver); appLock.removeListener(lockListener); super.onDestroy() }
    private fun Int.dp()=(this*resources.displayMetrics.density).toInt()
}
