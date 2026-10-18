package io.github.jihoon22lee.sallimbook

import android.app.Activity
import android.content.Intent
import android.os.SystemClock
import android.view.View
import android.view.ViewGroup
import android.webkit.WebView
import android.widget.TextView
import android.widget.ScrollView
import androidx.test.espresso.Espresso
import androidx.test.espresso.Espresso.onView
import androidx.test.espresso.action.ScrollToAction
import androidx.test.espresso.action.ViewActions.*
import androidx.test.espresso.matcher.ViewMatchers.*
import androidx.test.espresso.matcher.RootMatchers.withDecorView
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.runner.lifecycle.ActivityLifecycleMonitorRegistry
import androidx.test.runner.lifecycle.Stage
import io.github.jihoon22lee.sallimbook.auth.AppLockController
import io.github.jihoon22lee.sallimbook.auth.NativeAuthSession
import io.github.jihoon22lee.sallimbook.auth.NativeOnboardingActivity
import org.hamcrest.Matchers.sameInstance
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
        FIXTURE_ORIGIN, EMPTY_SESSION, MAIN_LAUNCH, PREDICATE_ASSET, INITIAL_CURTAIN, INITIAL_DOCUMENT,
        ANONYMOUS_REJECTED, SETUP_AVAILABLE, OPEN_CANCEL_FORM, CANCEL_FORM, CANCEL_SCROLL, CANCEL_CLICK,
        CANCEL_RETURN, SECOND_SETUP_AVAILABLE,
        CANCELLED_SESSION_EMPTY, OPEN_SETUP_FORM, SUBMIT_EMPTY, INVALID_INPUT,
        INVALID_SESSION_EMPTY, FILL_NAME, FILL_PASSWORD, FILL_CONFIRMATION,
        SUBMIT_VALID, SESSION_AND_MAIN, BRIDGE_READY, AUTHENTICATED_HOME, FINISH_MAIN
    }
    private enum class CloudReason {
        ASSERTION, NO_MATCHING_VIEW, AMBIGUOUS_VIEW, NO_MATCHING_ROOT, ROOT_NOT_FOCUSED,
        DETACHED_VIEW, SCROLL_CONSTRAINT, ACTION_FAILED, UI_NOT_IDLE, INJECTION_REJECTED,
        INTERRUPTED, SCROLL_LIMIT, UNKNOWN
    }
    // The order is public and fixed: focused owner, attached to that root, scroll constraint, >=90% visible.
    private data class ControlState(val focused: Boolean, val attached: Boolean, val constraint: Boolean, val displayed: Boolean) {
        fun bits() = listOf(focused, attached, constraint, displayed).joinToString("") { if (it) "1" else "0" }
    }
    private class InteractionFailure(val reason: CloudReason, val before: ControlState?, val after: ControlState?) : RuntimeException()
    private fun reason(error: Throwable): CloudReason {
        // Only exact public exception class names; never read message, stack or view descriptions.
        val names = listOfNotNull(error.cause?.javaClass?.name, error.javaClass.name)
        for (name in names) when (name) {
            "androidx.test.espresso.NoMatchingViewException" -> return CloudReason.NO_MATCHING_VIEW
            "androidx.test.espresso.AmbiguousViewMatcherException" -> return CloudReason.AMBIGUOUS_VIEW
            "androidx.test.espresso.NoMatchingRootException" -> return CloudReason.NO_MATCHING_ROOT
            "androidx.test.espresso.base.RootViewPicker\$RootViewWithoutFocusException" -> return CloudReason.ROOT_NOT_FOCUSED
            "androidx.test.espresso.AppNotIdleException", "androidx.test.espresso.IdlingResourceTimeoutException" -> return CloudReason.UI_NOT_IDLE
            "androidx.test.espresso.InjectEventSecurityException", "java.lang.SecurityException" -> return CloudReason.INJECTION_REJECTED
            "java.lang.InterruptedException" -> return CloudReason.INTERRUPTED
            "androidx.test.espresso.PerformException" -> return CloudReason.ACTION_FAILED
            "java.lang.AssertionError" -> return CloudReason.ASSERTION
        }
        return CloudReason.UNKNOWN
    }
    private fun <T> at(stage: CloudStage, action: () -> T): T {
        try { return action() }
        catch (error: Throwable) {
            val detail = error as? InteractionFailure
            val code = detail?.reason ?: reason(error)
            val before = detail?.before?.bits() ?: "----"
            val after = detail?.after?.bits() ?: "----"
            throw AssertionError("SALLIMBOOK_CLOUD_STAGE: ${stage.name}; REASON: ${code.name}; PRE: $before; POST: $after")
                .apply { stackTrace = emptyArray() }
        }
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

    private fun awaitActivity(type: Class<out Activity>): Activity {
        var found: Activity? = null
        awaitState("focused native activity") {
            found = resumed()?.takeIf { type.isInstance(it) && it.hasWindowFocus() && !it.isFinishing }
            found != null
        }
        return found!!
    }

    private fun readyControl(owner: Activity, text: String): View {
        var found: View? = null
        awaitState("native control ready") {
            found = if (resumed() === owner && owner.hasWindowFocus())
                label(owner.window.decorView, text)?.takeIf { it.isShown && it.isEnabled } else null
            found != null
        }
        return found!!
    }

    private fun target(owner: Activity, view: View) = onView(sameInstance(view))
        .inRoot(withDecorView(sameInstance(owner.window.decorView)))

    private fun controlState(owner: Activity, view: View): ControlState? {
        var state: ControlState? = null
        try {
            instrumentation.runOnMainSync {
                state = ControlState(resumed() === owner && owner.hasWindowFocus(),
                    view.isAttachedToWindow && view.rootView === owner.window.decorView,
                    ScrollToAction().constraints.matches(view), isDisplayingAtLeast(90).matches(view))
            }
        } catch (_: Throwable) { /* Diagnostics cannot replace the interaction's failure. */ }
        return state
    }
    private fun <T> interaction(owner: Activity, view: View, action: () -> T): T {
        val before = controlState(owner, view)
        try { return action() }
        catch (error: Throwable) { throw InteractionFailure(reason(error), before, controlState(owner, view)) }
    }
    private fun checkControl(before: ControlState?, state: ControlState?) {
        val code = when {
            state == null -> CloudReason.UNKNOWN
            !state.focused -> CloudReason.ROOT_NOT_FOCUSED
            !state.attached -> CloudReason.DETACHED_VIEW
            !state.constraint -> CloudReason.SCROLL_CONSTRAINT
            else -> return
        }
        throw InteractionFailure(code, before, state)
    }
    private fun scrollIntoView(owner: Activity, view: View) {
        // A user can dismiss the IME before scrolling. Do not call listeners directly,
        // lower Espresso's visibility threshold, or assume requestRectangleOnScreen worked.
        interaction(owner, view) { Espresso.closeSoftKeyboard() }
        val before = controlState(owner, view)
        checkControl(before, before)
        if (before!!.displayed) return
        var scroll: ScrollView? = null
        instrumentation.runOnMainSync {
            var ancestor = view.parent
            while (ancestor is View) {
                if (ancestor is ScrollView) { scroll = ancestor; break }
                ancestor = ancestor.parent
            }
        }
        val container = scroll ?: throw InteractionFailure(CloudReason.SCROLL_CONSTRAINT, before, controlState(owner, view))
        repeat(6) {
            val state = controlState(owner, view)
            checkControl(before, state)
            if (state!!.displayed) return
            var above = false
            instrumentation.runOnMainSync {
                val control = IntArray(2); val viewport = IntArray(2)
                view.getLocationOnScreen(control); container.getLocationOnScreen(viewport)
                above = control[1] < viewport[1] + container.paddingTop
            }
            interaction(owner, view) { target(owner, container).perform(if (above) swipeDown() else swipeUp()) }
        }
        val after = controlState(owner, view)
        checkControl(before, after)
        if (after!!.displayed) return
        throw InteractionFailure(CloudReason.SCROLL_LIMIT, before, after)
    }
    private fun click(owner: Activity, text: String) {
        val view = readyControl(owner, text)
        scrollIntoView(owner, view)
        interaction(owner, view) { target(owner, view).perform(click()) }
    }

    private fun fill(owner: Activity, caption: String, value: String) {
        val captionView = readyControl(owner, caption)
        var field: View? = null
        instrumentation.runOnMainSync { field = owner.findViewById(captionView.labelFor) }
        assertTrue(field != null)
        scrollIntoView(owner, field!!)
        interaction(owner, field!!) { target(owner, field!!).perform(replaceText(value), closeSoftKeyboard()) }
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
            at(CloudStage.INITIAL_CURTAIN) {
                awaitState("locked native initial curtain") {
                    resumed() === main && main.hasWindowFocus() && main.secureBridgeReady &&
                        AppLockController.get(context).locked && !NativeAuthSession.get(context).hasLocalSession() &&
                        label(main.window.decorView, "SallimBook · 시작")?.isShown == true
                }
            }
            at(CloudStage.INITIAL_DOCUMENT) {
                awaitWebState("bundled initial document", main,
                    "Boolean(document.readyState === 'complete' && location.pathname === '/')")
            }
            at(CloudStage.ANONYMOUS_REJECTED) { assertFalse(evaluateBoolean(main, authenticatedHome)) }
            at(CloudStage.SETUP_AVAILABLE) { readyControl(main, "처음 시작하기") }
            val firstForm = at(CloudStage.OPEN_CANCEL_FORM) {
                click(main, "처음 시작하기"); awaitActivity(NativeOnboardingActivity::class.java)
            }
            val close = at(CloudStage.CANCEL_FORM) { readyControl(firstForm, "닫기") }
            at(CloudStage.CANCEL_SCROLL) { scrollIntoView(firstForm, close) }
            at(CloudStage.CANCEL_CLICK) { interaction(firstForm, close) { target(firstForm, close).perform(click()) } }
            at(CloudStage.CANCEL_RETURN) { assertTrue(awaitActivity(MainActivity::class.java) === main) }
            at(CloudStage.CANCELLED_SESSION_EMPTY) { assertFalse(NativeAuthSession.get(context).hasLocalSession()) }
            // Returning to MainActivity refreshes setup status asynchronously.
            at(CloudStage.SECOND_SETUP_AVAILABLE) { readyControl(main, "처음 시작하기") }
            val form = at(CloudStage.OPEN_SETUP_FORM) {
                click(main, "처음 시작하기"); awaitActivity(NativeOnboardingActivity::class.java)
            }
            at(CloudStage.SUBMIT_EMPTY) { click(form, "가계 만들고 시작") }
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
            at(CloudStage.FILL_NAME) { fill(form, "표시 이름", "Synthetic Android Owner") }
            at(CloudStage.FILL_PASSWORD) { fill(form, "새 비밀번호 · 15~128자", password) }
            at(CloudStage.FILL_CONFIRMATION) { fill(form, "새 비밀번호 확인", password) }
            at(CloudStage.SUBMIT_VALID) { click(form, "가계 만들고 시작") }
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
