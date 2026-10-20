package io.github.jihoon22lee.sallimbook.auth

/** Native login, invitation and reauthentication screen wording for each failure code. */
internal object NativeAuthMessages {
    fun message(code: AuthCode): String = when (code) {
        AuthCode.AUTH_FAILED -> "로그인 정보를 확인해 주세요."
        AuthCode.RATE_LIMITED -> "잠시 후 다시 시도해 주세요."
        AuthCode.REGISTRATION_FAILED -> "초대 코드와 입력 정보를 확인해 주세요. 이미 수락했다면 로그인해 주세요."
        AuthCode.NETWORK_UNAVAILABLE -> "연결을 확인할 수 없어요. 자동으로 다시 전송하지 않았어요."
        AuthCode.KEY_INVALIDATED -> "기기 인증 저장소를 사용할 수 없어요. 다시 로그인해 주세요."
        AuthCode.SESSION_EXPIRED -> "이 화면을 닫고 다시 로그인한 후 진행해 주세요."
        AuthCode.ACCESS_DENIED -> "권한과 현재 가계 상태를 확인해 주세요."
        AuthCode.AUTH_CANCELLED -> "인증을 취소했어요."
        else -> "인증을 완료할 수 없어요. 앱 설정을 확인해 주세요."
    }

    /** Password change and sign-out-others screens. Everything else keeps [message]. */
    fun accountMessage(code: AuthCode, changingPassword: Boolean): String = when {
        code == AuthCode.AUTH_FAILED -> "현재 비밀번호를 확인해 주세요."
        code == AuthCode.VALIDATION_ERROR -> "새 비밀번호는 15자 이상이고 현재 비밀번호와 달라야 해요."
        code == AuthCode.NETWORK_UNAVAILABLE && changingPassword ->
            "응답을 받지 못했어요. 비밀번호가 이미 바뀌었을 수 있으니, 다시 시도할 때는 현재 비밀번호 칸에 새 비밀번호를 넣어 보세요."
        else -> message(code)
    }
}
