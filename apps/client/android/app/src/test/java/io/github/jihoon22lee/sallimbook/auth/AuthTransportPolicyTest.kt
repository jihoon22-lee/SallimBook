package io.github.jihoon22lee.sallimbook.auth

import okhttp3.Authenticator
import okhttp3.CookieJar
import okhttp3.HttpUrl.Companion.toHttpUrl
import okio.Buffer
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException
import java.net.CookieHandler
import java.net.URI

class AuthTransportPolicyTest {
    @Test fun accountClientDoesNotShareCookiesRetryRedirectAuthenticateOrCache() {
        val client = accountHttpClient()
        assertSame(CookieJar.NO_COOKIES, client.cookieJar)
        assertSame(Authenticator.NONE, client.authenticator)
        assertSame(Authenticator.NONE, client.proxyAuthenticator)
        assertFalse(client.followRedirects)
        assertFalse(client.followSslRedirects)
        assertFalse(client.retryOnConnectionFailure)
        assertNull(client.cache)
        assertTrue(client.interceptors.isEmpty())
        assertTrue(client.networkInterceptors.isEmpty())
        assertEquals(15_000, client.callTimeoutMillis)
        assertEquals(10_000, client.connectTimeoutMillis)
        assertEquals(10_000, client.readTimeoutMillis)
        assertEquals(10_000, client.writeTimeoutMillis)
    }

    @Test fun authBodyCannotBeWrittenASecondTimeEvenIfACallerAttemptsAFollowUp() {
        val body = OneShotAuthBody("{}".toByteArray())
        assertTrue(body.isOneShot())
        val first = Buffer()
        body.writeTo(first)
        assertEquals("{}", first.readUtf8())
        val second = Buffer()
        try {
            body.writeTo(second)
            fail("An authentication body was replayed")
        } catch (_: IOException) {
            assertEquals(0L, second.size)
        }
    }

    @Test fun javaNetCookieHandlerCannotSupplyOrReceiveAccountClientCookies() {
        val original = CookieHandler.getDefault()
        var handlerCalls = 0
        val synthetic = object : CookieHandler() {
            override fun get(uri: URI, requestHeaders: Map<String, List<String>>): Map<String, List<String>> {
                handlerCalls++
                return mapOf("Cookie" to listOf("synthetic=not-a-session"))
            }
            override fun put(uri: URI, responseHeaders: Map<String, List<String>>) { handlerCalls++ }
        }
        try {
            // Models Capacitor's global handler. The production factory must neither use nor replace it.
            CookieHandler.setDefault(synthetic)
            val client = accountHttpClient()
            val url = "https://synthetic.invalid".toHttpUrl()
            assertTrue(client.cookieJar.loadForRequest(url).isEmpty())
            client.cookieJar.saveFromResponse(url, emptyList())
            assertSame(synthetic, CookieHandler.getDefault())
            assertEquals(0, handlerCalls)
        } finally { CookieHandler.setDefault(original) }
    }
}
