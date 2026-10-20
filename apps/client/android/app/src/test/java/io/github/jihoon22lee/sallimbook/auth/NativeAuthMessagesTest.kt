package io.github.jihoon22lee.sallimbook.auth

import org.junit.Assert.*
import org.junit.Test

class NativeAuthMessagesTest {
    @Test fun rateLimitIsNotPresentedAsWrongCredentials() {
        assertEquals("잠시 후 다시 시도해 주세요.", NativeAuthMessages.message(AuthCode.RATE_LIMITED))
        assertEquals("로그인 정보를 확인해 주세요.", NativeAuthMessages.message(AuthCode.AUTH_FAILED))
        assertEquals("연결을 확인할 수 없어요. 자동으로 다시 전송하지 않았어요.", NativeAuthMessages.message(AuthCode.NETWORK_UNAVAILABLE))
    }
    @Test fun movedMessagesKeepTheirWording() {
        assertEquals("이 화면을 닫고 다시 로그인한 후 진행해 주세요.", NativeAuthMessages.message(AuthCode.SESSION_EXPIRED))
        assertEquals("인증을 취소했어요.", NativeAuthMessages.message(AuthCode.AUTH_CANCELLED))
        assertEquals("인증을 완료할 수 없어요. 앱 설정을 확인해 주세요.", NativeAuthMessages.message(AuthCode.AUTH_UNAVAILABLE))
    }
}
