package io.github.jihoon22lee.sallimbook.auth

import java.io.ByteArrayOutputStream
import java.io.IOException
import java.nio.ByteBuffer
import java.nio.charset.CodingErrorAction
import okhttp3.Call
import okhttp3.EventListener
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response

internal fun vaultHttpClient(): OkHttpClient = accountHttpClient().newBuilder()
    .eventListener(object : EventListener() {
        override fun followUpDecision(call: Call, networkResponse: Response, nextRequest: Request?) {
            if (nextRequest != null) call.cancel()
        }
    }).build()

/** Only validated opaque vault wire data. No secret plaintext or CVC serializer exists here. */
internal class NativeVaultHttp(private val origin: String, private val client: OkHttpClient = vaultHttpClient()) {
    fun send(command: NativeVaultCommand, accessToken: String, gate: ForegroundRequest): NativeHttpResponse {
        val route = NativeVaultWire.route(command)
        if (AuthPolicy.apiOrigin(origin) == null) throw AuthFailure(AuthCode.AUTH_UNAVAILABLE)
        gate.checkHttp(route.method, route.path)
        val bytes = NativeVaultJson.encode(command)
        try {
            val request = Request.Builder().url(origin + route.path)
                .method(route.method, bytes?.let { OneShotAuthBody(it) { gate.checkHttp(route.method, route.path) } })
                .header("Accept", "application/json").header("X-SallimBook-Native", "1")
                .header("Authorization", "Bearer $accessToken")
                .apply { command.version?.let { header("If-Match", "\"$it\"") }; command.idempotencyKey?.let { header("Idempotency-Key", it) } }
                .build()
            val call = client.newCall(request)
            gate.bindNetworkCancellation { call.cancel() }
            gate.checkHttp(route.method, route.path)
            return call.execute().use { response ->
                if (response.code in 300..399) throw AuthFailure(AuthCode.ACCESS_DENIED)
                val type = response.body.contentType()
                if (type?.type != "application" || type.subtype != "json") throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
                val buffer = ByteArray(4096)
                val output = object : ByteArrayOutputStream() { fun wipe() { buf.fill(0); reset() } }
                var parsedBytes: ByteArray? = null
                try {
                    response.body.byteStream().use { stream ->
                        while (true) {
                            gate.checkHttp(route.method, route.path)
                            val count = stream.read(buffer); if (count < 0) break
                            if (output.size() + count > 1_048_576) throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE)
                            output.write(buffer, 0, count)
                        }
                    }
                    parsedBytes = output.toByteArray()
                    val text = Charsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT).onUnmappableCharacter(CodingErrorAction.REPORT)
                        .decode(ByteBuffer.wrap(parsedBytes)).toString()
                    val value = NativeVaultJson.decode(text)
                    gate.checkHttp(route.method, route.path)
                    NativeHttpResponse(response.code, value, null)
                } finally { buffer.fill(0); parsedBytes?.fill(0); output.wipe() }
            }
        } catch (failure: AuthFailure) { throw failure }
        catch (_: IOException) { throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE) }
        catch (_: Exception) { throw AuthFailure(AuthCode.NETWORK_UNAVAILABLE) }
        finally { gate.releaseNetworkCancellation(); bytes?.fill(0) }
    }

}

internal object NativeVaultErrors {
    private val conflicts = setOf("VAULT_NOT_INITIALIZED", "VAULT_ALREADY_INITIALIZED", "VAULT_ROTATION_IN_PROGRESS", "VAULT_ROTATION_REQUIRED",
        "VAULT_KEY_VERSION_CONFLICT", "VAULT_NOT_PREPARED", "VAULT_NONCE_REUSED", "VAULT_SALT_REUSED", "VAULT_STATE_CONFLICT",
        "VAULT_MEMBER_UNAVAILABLE", "VAULT_SHARE_UNAVAILABLE", "VAULT_ALREADY_ENROLLED", "VAULT_SHARE_PENDING", "VAULT_LAST_MEMBER",
        "VAULT_ROTATION_UNAVAILABLE", "VAULT_VERSION_EXHAUSTED", "VAULT_ROTATION_INCOMPLETE", "VAULT_ALREADY_PREPARED",
        "VAULT_ROTATION_SNAPSHOT_CONFLICT", "VAULT_GENERATION_CONFLICT", "VERSION_CONFLICT", "IDEMPOTENCY_CONFLICT")
    fun code(status: Int, body: Any?): String {
        val code = ((body as? Map<*, *>)?.get("error") as? Map<*, *>)?.get("code") as? String
        if (status == 401) return "SESSION_EXPIRED"
        if (status == 409 && code in conflicts || status == 403 && code in setOf("VAULT_ACCESS_DENIED", "REAUTHENTICATION_REQUIRED", "STEP_UP_REQUIRED") ||
            status == 404 && code in setOf("NOT_FOUND", "VAULT_SECRET_NOT_SET") || status == 422 && code == "VAULT_SHARE_TARGET") return code!!
        return if (status == 429) "RATE_LIMITED" else "ACCESS_DENIED"
    }
    fun message(code: String): String = when(code) {
        "SESSION_EXPIRED", "REAUTHENTICATION_REQUIRED", "STEP_UP_REQUIRED" -> "현재 계정을 다시 인증한 뒤 보관함을 열어 주세요. 보관함 암호와 로그인 암호는 별개입니다."
        "KEY_INVALIDATED" -> "기기 키를 사용할 수 없습니다. 보관함 암호로 확인한 뒤 이 기기를 명시적으로 다시 등록해 주세요."
        "VAULT_ACCESS_DENIED" -> "보관함 공유 권한이 없습니다. 기존 구성원의 공유와 본인 수락이 필요합니다."
        "VAULT_ROTATION_REQUIRED" -> "공유 권한이 변경되어 새 보관함 키로 회전해야 합니다."
        "VAULT_ROTATION_IN_PROGRESS", "VAULT_ALREADY_PREPARED" -> "진행 중인 키 회전을 새로 확인한 뒤 이어서 처리해 주세요."
        "VAULT_ROTATION_INCOMPLETE", "VAULT_NOT_PREPARED" -> "회전할 카드와 구성원 준비가 아직 끝나지 않았습니다. 상태를 다시 확인해 주세요."
        "VAULT_SECRET_NOT_SET" -> "이 카드에 저장된 보호 정보가 없습니다."
        "VAULT_SHARE_UNAVAILABLE" -> "공유 요청이 만료되거나 종료됐습니다. 최신 요청을 확인해 주세요."
        "VAULT_LAST_MEMBER" -> "마지막 보관함 구성원의 접근 권한은 철회할 수 없습니다."
        "VAULT_SHARE_PENDING" -> "이미 진행 중인 공유 요청이 있습니다. 기존 요청을 확인해 주세요."
        "VAULT_NONCE_REUSED", "VAULT_SALT_REUSED" -> "암호화 값을 새로 준비해야 합니다. 이 화면을 닫고 최신 상태에서 다시 시작해 주세요."
        "DECRYPTION_FAILED", "INVALID_FORMAT" -> "보관함 암호 또는 복구코드와 암호문을 확인해 주세요. 복호화한 정보는 표시하지 않았습니다."
        "PASSWORD_POLICY" -> "새 보관함 암호는 12자 이상, UTF-8 1,024바이트 이내여야 합니다. 로그인 암호나 짧은 PIN을 재사용하지 마세요."
        "CVC_GATE_CLOSED" -> "로컬 보안코드는 보안 검토와 실제 기기 검증이 끝난 뒤 활성화할 수 있습니다."
        "NETWORK_UNAVAILABLE" -> "서버 처리 결과를 확인하지 못했습니다. 재시도할 경우 같은 요청을 사용하며 화면을 닫은 뒤에는 서버 상태부터 다시 확인합니다."
        "APP_LOCKED", "AUTH_CANCELLED" -> "화면이 잠기거나 요청이 취소되어 보호 정보를 지웠습니다."
        "RATE_LIMITED" -> "잠시 후 다시 시도해 주세요."
        else -> "보관함 상태가 바뀌었거나 요청을 처리할 수 없습니다. 최신 상태를 다시 확인해 주세요."
    }
}
