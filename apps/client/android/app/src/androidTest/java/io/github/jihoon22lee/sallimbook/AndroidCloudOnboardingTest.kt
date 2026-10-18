package io.github.jihoon22lee.sallimbook

import android.app.Activity
import android.content.Intent
import android.os.SystemClock
import android.view.View
import android.view.ViewGroup
import android.webkit.WebView
import android.widget.TextView
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.action.ViewActions.*
import androidx.test.espresso.matcher.ViewMatchers.*
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import io.github.jihoon22lee.sallimbook.auth.AppLockController
import io.github.jihoon22lee.sallimbook.auth.NativeAuthSession
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeTrue
import org.junit.Test
import org.junit.runner.RunWith
import java.util.UUID
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/** Partial A01: a fresh schema per invocation, actual native UI/HTTP and bundled WebView.
 * No screenshots/hierarchy dumps; failures deliberately discard Espresso's view/argument
 * diagnostics because they can contain native password fields. Never run on personal data.
 */
@RunWith(AndroidJUnit4::class)
class AndroidCloudOnboardingTest {
    private val instrumentation get() = InstrumentationRegistry.getInstrumentation()
    private val context get() = instrumentation.targetContext

    private fun safeStep(label: String, action: () -> Unit) {
        try { action() } catch (_: Throwable) { throw AssertionError("Cloud onboarding step failed: $label") }
    }

    private fun awaitState(label: String, condition: () -> Boolean) {
        val deadline = SystemClock.elapsedRealtime() + 30_000
        while (SystemClock.elapsedRealtime() < deadline) {
            var ready = false
            instrumentation.runOnMainSync { ready = condition() }
            if (ready) return
            SystemClock.sleep(100)
        }
        throw AssertionError("Cloud onboarding timed out: $label")
    }

    private fun resumed(): Activity? = ActivityLifecycleMonitorRegistry.getInstance()
        .getActivitiesInStage(Stage.RESUMED).singleOrNull()

    private fun label(view: View, text: String): TextView? {
        if (view is TextView && view.text.toString() == text) return view
        if (view is ViewGroup) for (index in 0 until view.childCount) {
            label(view.getChildAt(index), text)?.let { return it }
        }
        return null
    }

    private fun click(text: String) = safeStep("click $text") {
        onView(withText(text)).perform(scrollTo(), click())
    }

    private fun fill(caption: String, value: String) = safeStep("fill $caption") {
        var id = View.NO_ID
        instrumentation.runOnMainSync {
            id = resumed()?.window?.decorView?.let { label(it, caption)?.labelFor } ?: View.NO_ID
        }
        assertTrue(id != View.NO_ID)
        onView(withId(id)).perform(scrollTo(), replaceText(value), closeSoftKeyboard())
    }

    @Test fun firstStartCancelInvalidInputThenRealSessionAndHome() {
        assumeTrue("Requires the disposable cloud HTTPS fixture",
            InstrumentationRegistry.getArguments().getString("sallimbookCloudFixture") == "true")
        assertTrue(BuildConfig.SALLIMBOOK_API_ORIGIN.startsWith("https://127.0.0.1:"))
        assertFalse(NativeAuthSession.get(context).hasLocalSession())
        val main = instrumentation.startActivitySync(
            Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        ) as MainActivity
        try {
            awaitState("setup available") {
                label(main.window.decorView, "처음 시작하기")?.let { it.isShown && it.isEnabled } == true
            }
            click("처음 시작하기")
            click("닫기")
            assertFalse(NativeAuthSession.get(context).hasLocalSession())
            click("처음 시작하기")
            click("가계 만들고 시작")
            awaitState("invalid input rejected") {
                resumed()?.window?.decorView?.let {
                    label(it, "이름, 비밀번호 길이와 확인, 연결 코드를 확인해 주세요.") != null
                } == true
            }
            assertFalse(NativeAuthSession.get(context).hasLocalSession())
            // Generated solely in native test memory; never an argument, log or fixture file.
            val password = UUID.randomUUID().toString() + UUID.randomUUID().toString()
            fill("표시 이름", "Synthetic Android Owner")
            fill("새 비밀번호 · 15~128자", password)
            fill("새 비밀번호 확인", password)
            click("가계 만들고 시작")
            awaitState("real session and unlocked main") {
                NativeAuthSession.get(context).hasLocalSession() &&
                    !AppLockController.get(context).locked && resumed() === main
            }
            assertTrue(main.secureBridgeReady)
            val deadline = SystemClock.elapsedRealtime() + 30_000
            var home = false
            while (!home && SystemClock.elapsedRealtime() < deadline) {
                val latch = CountDownLatch(1)
                instrumentation.runOnMainSync {
                    main.findViewById<WebView>(com.getcapacitor.android.R.id.webview).evaluateJavascript(
                        "location.pathname === '/' && document.body.innerText.includes('소모품') && " +
                            "document.body.innerText.includes('자산')"
                    ) { home = it == "true"; latch.countDown() }
                }
                assertTrue("WebView callback deadline", latch.await(5, TimeUnit.SECONDS))
                if (!home) SystemClock.sleep(200)
            }
            assertTrue("Authenticated bundled home must render", home)
        } finally {
            instrumentation.runOnMainSync { main.finish() }
        }
    }
}
