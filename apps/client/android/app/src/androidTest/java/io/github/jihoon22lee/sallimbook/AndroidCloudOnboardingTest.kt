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

    // Public fixed labels only. Never attach Throwable, view hierarchy, ID or input to failure.
    private enum class CloudStage {
        FIXTURE_ORIGIN, EMPTY_SESSION, MAIN_LAUNCH, PREDICATE_ASSET, SIGNED_OUT_HOME,
        ANONYMOUS_REJECTED, SETUP_AVAILABLE, OPEN_CANCEL_FORM, CANCEL_FORM,
        CANCELLED_SESSION_EMPTY, OPEN_SETUP_FORM, SUBMIT_EMPTY, INVALID_INPUT,
        INVALID_SESSION_EMPTY, FILL_NAME, FILL_PASSWORD, FILL_CONFIRMATION,
        SUBMIT_VALID, SESSION_AND_MAIN, BRIDGE_READY, AUTHENTICATED_HOME, FINISH_MAIN
    }
    private fun <T> at(stage: CloudStage, action: () -> T): T {
        try { return action() }
        catch (_: Throwable) { throw AssertionError("SALLIMBOOK_CLOUD_STAGE: ${stage.name}").apply { stackTrace = emptyArray() } }
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

    private fun click(text: String) {
        onView(withText(text)).perform(scrollTo(), click())
    }

    private fun fill(caption: String, value: String) {
        var id = View.NO_ID
        instrumentation.runOnMainSync {
            id = resumed()?.window?.decorView?.let { label(it, caption)?.labelFor } ?: View.NO_ID
        }
        assertTrue(id != View.NO_ID)
        onView(withId(id)).perform(scrollTo(), replaceText(value), closeSoftKeyboard())
    }

    private fun evaluateBoolean(main: MainActivity, script: String): Boolean {
        val latch = CountDownLatch(1)
        var value = false
        instrumentation.runOnMainSync {
            main.findViewById<WebView>(com.getcapacitor.android.R.id.webview).evaluateJavascript(script) {
                value = it == "true"
                latch.countDown()
            }
        }
        assertTrue("WebView callback deadline", latch.await(5, TimeUnit.SECONDS))
        return value
    }

    private fun awaitWebState(label: String, main: MainActivity, script: String) {
        val deadline = SystemClock.elapsedRealtime() + 30_000
        while (SystemClock.elapsedRealtime() < deadline) {
            if (evaluateBoolean(main, script)) return
            SystemClock.sleep(200)
        }
        throw AssertionError("Cloud onboarding timed out: $label")
    }

    @Test fun firstStartCancelInvalidInputThenRealSessionAndHome() {
        assumeTrue("Requires the disposable cloud HTTPS fixture",
            InstrumentationRegistry.getArguments().getString("sallimbookCloudFixture") == "true")
        at(CloudStage.FIXTURE_ORIGIN) { assertTrue(BuildConfig.SALLIMBOOK_API_ORIGIN.startsWith("https://127.0.0.1:")) }
        at(CloudStage.EMPTY_SESSION) { assertFalse(NativeAuthSession.get(context).hasLocalSession()) }
        val main = at(CloudStage.MAIN_LAUNCH) {
            instrumentation.startActivitySync(
                Intent(context, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            ) as MainActivity
        }
        try {
            val authenticatedHome = at(CloudStage.PREDICATE_ASSET) {
                instrumentation.context.assets.open("sallimbook_cloud_authenticated_home.js").bufferedReader().use { it.readText() }
            }
            at(CloudStage.SIGNED_OUT_HOME) {
                awaitWebState("signed-out home shell", main,
                    "Boolean(location.pathname === '/' && document.querySelector('#assets-title') && " +
                        "document.querySelector('#consumables-title'))")
            }
            at(CloudStage.ANONYMOUS_REJECTED) { assertFalse(evaluateBoolean(main, authenticatedHome)) }
            at(CloudStage.SETUP_AVAILABLE) {
                awaitState("setup available") {
                    label(main.window.decorView, "처음 시작하기")?.let { it.isShown && it.isEnabled } == true
                }
            }
            at(CloudStage.OPEN_CANCEL_FORM) { click("처음 시작하기") }
            at(CloudStage.CANCEL_FORM) { click("닫기") }
            at(CloudStage.CANCELLED_SESSION_EMPTY) { assertFalse(NativeAuthSession.get(context).hasLocalSession()) }
            at(CloudStage.OPEN_SETUP_FORM) { click("처음 시작하기") }
            at(CloudStage.SUBMIT_EMPTY) { click("가계 만들고 시작") }
            at(CloudStage.INVALID_INPUT) {
                awaitState("invalid input rejected") {
                    resumed()?.window?.decorView?.let {
                        label(it, "이름, 비밀번호 길이와 확인, 연결 코드를 확인해 주세요.") != null
                    } == true
                }
            }
            at(CloudStage.INVALID_SESSION_EMPTY) { assertFalse(NativeAuthSession.get(context).hasLocalSession()) }
            // Generated solely in native test memory; never an argument, log or fixture file.
            val password = UUID.randomUUID().toString() + UUID.randomUUID().toString()
            at(CloudStage.FILL_NAME) { fill("표시 이름", "Synthetic Android Owner") }
            at(CloudStage.FILL_PASSWORD) { fill("새 비밀번호 · 15~128자", password) }
            at(CloudStage.FILL_CONFIRMATION) { fill("새 비밀번호 확인", password) }
            at(CloudStage.SUBMIT_VALID) { click("가계 만들고 시작") }
            at(CloudStage.SESSION_AND_MAIN) {
                awaitState("real session and unlocked main") {
                    NativeAuthSession.get(context).hasLocalSession() &&
                        !AppLockController.get(context).locked && resumed() === main
                }
            }
            at(CloudStage.BRIDGE_READY) { assertTrue(main.secureBridgeReady) }
            at(CloudStage.AUTHENTICATED_HOME) { awaitWebState("authenticated home API data", main, authenticatedHome) }
        } finally {
            at(CloudStage.FINISH_MAIN) { instrumentation.runOnMainSync { main.finish() } }
        }
    }
}
