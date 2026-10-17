package io.github.jihoon22lee.sallimbook.auth

internal class NativeExportSelection(val formats: List<String>, val documents: List<String>) {
    fun body(): Map<String,Any?> = mapOf("formats" to formats.toList(),"document_ids" to documents.toList())
    override fun toString() = "NativeExportSelection(redacted)"
}

internal object NativeExportPolicy {
    const val PATH="/api/v1/exports"
    fun arguments(value:Any?):NativeExportSelection {
        val outer=value as? Map<*,*> ?: throw AuthFailure(AuthCode.INVALID_REQUEST)
        if(outer.keys!=setOf("input")) throw AuthFailure(AuthCode.INVALID_REQUEST)
        return selection(outer["input"])
    }
    fun selection(value:Any?):NativeExportSelection {
        val input=value as? Map<*,*> ?: throw AuthFailure(AuthCode.INVALID_REQUEST)
        if(input.keys.any { it !in setOf("formats","document_ids") }) throw AuthFailure(AuthCode.INVALID_REQUEST)
        val formats=(if(input.containsKey("formats")) input["formats"] else listOf("json","csv")) as? List<*>
            ?: throw AuthFailure(AuthCode.INVALID_REQUEST)
        val documents=(if(input.containsKey("document_ids")) input["document_ids"] else emptyList<String>()) as? List<*>
            ?: throw AuthFailure(AuthCode.INVALID_REQUEST)
        if(formats.size !in 1..2 || formats.any { it !in setOf("json","csv") } || formats.toSet().size!=formats.size ||
            documents.size>10 || documents.any { it !is String || !PasskeyPolicy.uuid.matches(it) } || documents.toSet().size!=documents.size)
            throw AuthFailure(AuthCode.INVALID_REQUEST)
        return NativeExportSelection(formats.map { it as String },documents.map { it as String })
    }
    val errors=mapOf(
        "REAUTHENTICATION_REQUIRED" to 403,"STEP_UP_REQUIRED" to 403,"NOT_FOUND" to 404,
        "EXPORT_TIMEOUT" to 408,"EXPORT_DOCUMENT_CHANGED" to 409,"EXPORT_CONFLICT" to 409,
        "EXPORT_TOO_LARGE" to 413,"VALIDATION_ERROR" to 422,"EXPORT_BUSY" to 503,
        "DOCUMENT_STORAGE_UNAVAILABLE" to 503,
    )
    fun error(status:Int,body:Any?):String {
        if(status==401) return "SESSION_EXPIRED"
        val code=((body as? Map<*,*>)?.get("error") as? Map<*,*>)?.get("code") as? String
        return code?.takeIf { errors[it]==status } ?: if(status==429) "RATE_LIMITED" else "ACCESS_DENIED"
    }
    fun message(code:String):String = when(code) {
        "EXPORT_TOO_LARGE" -> "내보내기 용량 한도를 넘었어요. 선택한 문서 수를 줄이거나 자료 범위를 확인해 주세요."
        "EXPORT_BUSY" -> "다른 내보내기를 처리하고 있어요. 잠시 뒤 새 요청으로 다시 진행해 주세요."
        "EXPORT_TIMEOUT", "NETWORK_UNAVAILABLE" -> "내보내기를 완료하지 못했어요. 자동으로 다시 요청하지 않았습니다. 선택한 위치에 불완전한 파일이 남았는지 확인해 주세요."
        "EXPORT_DOCUMENT_CHANGED", "EXPORT_CONFLICT", "NOT_FOUND" -> "선택한 문서나 자료 상태가 바뀌었어요. 목록을 다시 확인한 뒤 새로 내보내 주세요."
        "SESSION_EXPIRED", "APP_LOCKED", "REAUTHENTICATION_REQUIRED", "STEP_UP_REQUIRED" -> "로그인 또는 잠금 상태를 다시 확인한 뒤 내보내 주세요."
        "AUTH_FAILED" -> "현재 계정의 로그인 암호를 확인한 뒤 다시 진행해 주세요."
        "RATE_LIMITED" -> "요청이 많아 잠시 기다려야 해요. 나중에 다시 진행해 주세요."
        else -> "내보내기 파일을 확인하거나 저장하지 못했어요. 자동 재전송하지 않았습니다. 선택한 위치의 불완전한 파일을 확인해 주세요."
    }
}

/** Native monotonic bounds; server authentication and provider grants remain separate authorities. */
internal class NativeExportFlow(private val clock:()->Long) {
    enum class Phase(val millis:Long) { IDLE(0), AUTH(60_000), PICKER(60_000), TRANSFER(180_000), WRITE(180_000), COMPLETE(0), CLOSED(0) }
    private var phase=Phase.IDLE
    private var began=0L
    @Synchronized fun beginAuthentication()=advance(Phase.IDLE,Phase.AUTH)
    @Synchronized fun beginPicker()=advance(Phase.AUTH,Phase.PICKER)
    @Synchronized fun beginTransfer()=advance(Phase.PICKER,Phase.TRANSFER)
    @Synchronized fun beginWrite()=advance(Phase.TRANSFER,Phase.WRITE)
    @Synchronized fun finish()=advance(Phase.WRITE,Phase.COMPLETE)
    private fun advance(expected:Phase,next:Phase) {
        if(phase!=expected) throw AuthFailure(AuthCode.AUTH_CANCELLED)
        if(expected!=Phase.IDLE) check(expected)
        phase=next; began=clock()
    }
    @Synchronized fun check(expected:Phase) {
        val elapsed=clock()-began
        if(phase!=expected || expected.millis==0L || elapsed !in 0 until expected.millis) throw AuthFailure(AuthCode.AUTH_CANCELLED)
    }
    @Synchronized fun close() { phase=Phase.CLOSED }
}
