package io.github.jihoon22lee.sallimbook

import android.app.Activity
import android.app.KeyguardManager
import android.content.Intent
import android.graphics.Rect
import android.os.SystemClock
import android.text.Editable
import android.text.TextWatcher
import android.view.Choreographer
import android.view.View
import android.view.ViewGroup
import android.view.ViewTreeObserver
import android.view.WindowInsets
import android.webkit.WebView
import android.widget.TextView
import android.widget.EditText
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
import io.github.jihoon22lee.sallimbook.auth.NativeOnboardingPolicy
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
        INVALID_SESSION_EMPTY, FILL_NAME, NAME_PRESERVED, FILL_PASSWORD, PASSWORD_PRESERVED,
        FILL_CONFIRMATION, CONFIRMATION_PRESERVED, PREPARE_VALID_SUBMIT,
        PRESUBMIT_FIELDS, PRESUBMIT_POLICY, PRESUBMIT_READY, SUBMIT_VALID,
        SESSION_CREATED, APP_UNLOCKED, MAIN_RESUMED, BRIDGE_READY, AUTHENTICATED_HOME, FINISH_MAIN
    }
    private enum class CloudReason {
        ASSERTION, NO_MATCHING_VIEW, AMBIGUOUS_VIEW, NO_MATCHING_ROOT, ROOT_NOT_FOCUSED,
        DETACHED_VIEW, SCROLL_CONSTRAINT, ACTION_FAILED, UI_NOT_IDLE, INJECTION_REJECTED,
        INTERRUPTED, SCROLL_LIMIT, SCROLL_NOT_SETTLED, UNKNOWN
    }
    private enum class CloudStatus {
        NOT_CHECKED, NOT_RECOGNIZED, INPUT_INVALID, REQUEST_PENDING, RESULT_DISCARDED,
        FOCUS_INTERRUPTED, SETUP_UNAVAILABLE, SETUP_COMPLETE, INVALID_CONNECTION_CODE,
        HOUSEHOLD_FULL, REGISTRATION_OR_LOGIN_CONFLICT, RATE_LIMITED, REAUTHENTICATION_REQUIRED,
        AUTH_FAILED, REQUEST_INVALID, NETWORK_UNAVAILABLE, SESSION_EXPIRED, KEY_INVALIDATED,
        CANCELLED_OR_LOCKED, AUTH_UNAVAILABLE
    }
    private val publicStatuses = mapOf(
        "이름, 비밀번호 길이와 확인, 연결 코드를 확인해 주세요." to CloudStatus.INPUT_INVALID,
        "확인하고 있어요." to CloudStatus.REQUEST_PENDING,
        "요청 상태가 바뀌어 완료 결과를 사용하지 않았어요. 이미 가입했다면 로그인해 주세요." to CloudStatus.RESULT_DISCARDED,
        "요청을 중단했어요. 이미 가입됐다면 로그인 화면에서 다시 확인해 주세요." to CloudStatus.FOCUS_INTERRUPTED,
        "이 연결에서는 처음 시작할 수 없어요. 허용된 사설 연결을 확인해 주세요." to CloudStatus.SETUP_UNAVAILABLE,
        "이미 시작한 가계가 있어요. 로그인하거나 배우자 연결을 이용해 주세요." to CloudStatus.SETUP_COMPLETE,
        "연결 코드가 올바르지 않거나 만료됐어요. 새 코드를 확인해 주세요." to CloudStatus.INVALID_CONNECTION_CODE,
        "이미 두 사람이 연결되어 있어요. 기존 계정으로 로그인해 주세요." to CloudStatus.HOUSEHOLD_FULL,
        "가입 상태가 변경됐어요. 이미 가입했다면 로그인해 주세요." to CloudStatus.REGISTRATION_OR_LOGIN_CONFLICT,
        "요청이 많아요. 잠시 후 다시 시도해 주세요." to CloudStatus.RATE_LIMITED,
        "연결 코드를 만들려면 현재 계정 비밀번호를 다시 확인해 주세요." to CloudStatus.REAUTHENTICATION_REQUIRED,
        "현재 비밀번호를 확인해 주세요." to CloudStatus.AUTH_FAILED,
        "입력 항목을 확인해 주세요." to CloudStatus.REQUEST_INVALID,
        "연결을 확인하지 못했어요. 이미 가입됐다면 로그인해 주세요. 자동 재전송은 하지 않았어요." to CloudStatus.NETWORK_UNAVAILABLE,
        "로그인이 만료됐어요. 화면을 닫고 다시 로그인해 주세요." to CloudStatus.SESSION_EXPIRED,
        "기기에 로그인을 안전하게 저장하지 못했어요. 로그인 화면에서 다시 확인해 주세요." to CloudStatus.KEY_INVALIDATED,
        "요청이 취소됐어요. 결과를 확인한 후 다시 진행해 주세요." to CloudStatus.CANCELLED_OR_LOCKED,
        "요청을 완료하지 못했어요. 연결과 현재 가계 상태를 확인해 주세요." to CloudStatus.AUTH_UNAVAILABLE
    )
    // Flow bits: native session exists, app unlocked, original MainActivity resumed.
    private class FlowFailure(val flow: String, val status: CloudStatus) : RuntimeException()
    // Last tap only: name preserved, password empty, confirmation empty, status updated,
    // window focus lost. A normal successful departure can also lose window focus.
    private data class TapState(val bits: String, val status: CloudStatus)
    private var tapState = TapState("-----", CloudStatus.NOT_CHECKED)
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
            val outcome = error as? FlowFailure
            val code = detail?.reason ?: if (outcome != null) CloudReason.ASSERTION else reason(error)
            val before = detail?.before?.bits() ?: "----"
            val after = detail?.after?.bits() ?: "----"
            val flow = outcome?.flow ?: "---"
            val status = outcome?.status ?: CloudStatus.NOT_CHECKED
            throw AssertionError("SALLIMBOOK_CLOUD_STAGE: ${stage.name}; REASON: ${code.name}; PRE: $before; POST: $after; FLOW: $flow; STATUS: ${status.name}; TAP: ${tapState.bits}; TAP_STATUS: ${tapState.status.name}")
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
    // Geometry remains only in native test memory; never format it in diagnostics.
    private data class ScrollGeometry(
        val scrollX: Int, val scrollY: Int, val target: Rect, val viewport: Rect,
        val window: Rect, val focused: Boolean, val attached: Boolean,
        val laidOut: Boolean, val displayed: Boolean, val inputFocused: Boolean, val ime: Boolean
    )
    private fun awaitScrollSettled(owner: Activity, view: View, container: ScrollView?) {
        val before = controlState(owner, view)
        val completed = CountDownLatch(1)
        var settled = false
        var previous: ScrollGeometry? = null
        var stableSince = 0L
        var quietFrames = 0
        lateinit var callback: Choreographer.FrameCallback
        instrumentation.runOnMainSync {
            val choreographer = Choreographer.getInstance()
            callback = Choreographer.FrameCallback {
                val now = SystemClock.elapsedRealtime()
                val position = IntArray(2)
                view.getLocationOnScreen(position)
                val viewport = Rect().also { (container ?: owner.window.decorView).getGlobalVisibleRect(it) }
                val window = Rect().also { owner.window.decorView.getWindowVisibleDisplayFrame(it) }
                val state = ScrollGeometry(container?.scrollX ?: 0, container?.scrollY ?: 0,
                    Rect(position[0], position[1], position[0] + view.width, position[1] + view.height),
                    viewport, window, resumed() === owner && owner.hasWindowFocus(),
                    view.isAttachedToWindow && view.rootView === owner.window.decorView,
                    view.isLaidOut && !view.isLayoutRequested && container?.isLayoutRequested != true &&
                        !owner.window.decorView.isLayoutRequested,
                    isDisplayingAtLeast(90).matches(view), view.hasFocus(),
                    view.rootWindowInsets?.isVisible(WindowInsets.Type.ime()) == true)
                if (state != previous || !state.focused || !state.attached || !state.laidOut || state.ime) {
                    previous = state
                    stableSince = now
                    quietFrames = 0
                }
                // Android 16 ScrollView intercepts DOWN during fling/edge effects. Glow
                // absorb+recede can take ~800ms; stretch uses a damped spring, not that timer.
                // Require 1s unchanged geometry and two subsequent animation frames; this
                // is conservative test synchronization, not a claimed universal effect bound.
                // AOSP android-16.0.0_r1: ScrollView.onInterceptTouchEvent, EdgeEffect.draw.
                if (now - stableSince >= 1_000) quietFrames++
                if (quietFrames >= 2) {
                    settled = true
                    completed.countDown()
                } else choreographer.postFrameCallback(callback)
            }
            choreographer.postFrameCallback(callback)
        }
        try {
            if (!completed.await(10, TimeUnit.SECONDS))
                throw InteractionFailure(CloudReason.SCROLL_NOT_SETTLED, before, controlState(owner, view))
        } finally {
            instrumentation.runOnMainSync { Choreographer.getInstance().removeFrameCallback(callback) }
        }
        if (!settled) throw InteractionFailure(CloudReason.SCROLL_NOT_SETTLED, before, controlState(owner, view))
        checkControl(before, controlState(owner, view))
    }
    private fun scrollIntoView(owner: Activity, view: View) {
        // A user can dismiss the IME before scrolling. Do not call listeners directly,
        // lower Espresso's visibility threshold, or assume requestRectangleOnScreen worked.
        interaction(owner, view) { Espresso.closeSoftKeyboard() }
        val before = controlState(owner, view)
        checkControl(before, before)
        var scroll: ScrollView? = null
        instrumentation.runOnMainSync {
            var ancestor = view.parent
            while (ancestor is View) {
                if (ancestor is ScrollView) { scroll = ancestor; break }
                ancestor = ancestor.parent
            }
        }
        awaitScrollSettled(owner, view, scroll)
        if (controlState(owner, view)?.displayed == true) return
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
            awaitScrollSettled(owner, view, container)
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

    private fun field(owner: Activity, caption: String): EditText {
        val captionView = label(owner.window.decorView, caption) ?: throw AssertionError()
        return owner.findViewById<EditText>(captionView.labelFor) ?: throw AssertionError()
    }
    private fun assertFields(owner: Activity, expectedPassword: String, includePassword: Boolean, includeConfirmation: Boolean) {
        var preserved = false
        instrumentation.runOnMainSync {
            preserved = field(owner, "표시 이름").text.toString() == "Synthetic Android Owner" &&
                (!includePassword || field(owner, "새 비밀번호 · 15~128자").text.contentEquals(expectedPassword)) &&
                (!includeConfirmation || field(owner, "새 비밀번호 확인").text.contentEquals(expectedPassword))
        }
        // Only the boolean escapes the UI callback. Never print actual text or lengths.
        assertTrue(preserved)
    }
    private fun assertInputPolicy(owner: Activity) {
        var valid = false
        instrumentation.runOnMainSync {
            val source = field(owner, "새 비밀번호 · 15~128자").text
            val secret = CharArray(source.length).also { source.getChars(0, source.length, it, 0) }
            try {
                valid = NativeOnboardingPolicy.name(field(owner, "표시 이름").text.toString()) &&
                    NativeOnboardingPolicy.password(secret) && field(owner, "새 비밀번호 확인").text.contentEquals(source)
            } finally { secret.fill('\u0000') }
        }
        assertTrue(valid)
    }
    private fun publicStatus(view: View): CloudStatus? {
        // Inputs are never inspected for status classification, even if their value resembles a message.
        if (view is EditText) return null
        if (view is TextView) publicStatuses[view.text.toString()]?.let { return it }
        if (view is ViewGroup) for (index in 0 until view.childCount) {
            publicStatus(view.getChildAt(index))?.let { return it }
        }
        return null
    }
    private fun publicStatusView(view: View): TextView? {
        if (view is EditText) return null
        if (view is TextView && publicStatuses.containsKey(view.text.toString())) return view
        if (view is ViewGroup) for (index in 0 until view.childCount) {
            publicStatusView(view.getChildAt(index))?.let { return it }
        }
        return null
    }
    private fun observeSubmit(owner: Activity, action: () -> Unit) {
        var updated = false
        var focusLost = false
        lateinit var name: EditText
        lateinit var password: EditText
        lateinit var confirmation: EditText
        lateinit var status: TextView
        lateinit var observer: ViewTreeObserver
        val watcher = object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) {}
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) {}
            override fun afterTextChanged(s: Editable?) { updated = true }
        }
        val focus = ViewTreeObserver.OnWindowFocusChangeListener { hasFocus -> if (!hasFocus) focusLost = true }
        instrumentation.runOnMainSync {
            name = field(owner, "표시 이름")
            password = field(owner, "새 비밀번호 · 15~128자")
            confirmation = field(owner, "새 비밀번호 확인")
            status = publicStatusView(owner.window.decorView) ?: throw AssertionError()
            observer = owner.window.decorView.viewTreeObserver
            status.addTextChangedListener(watcher)
            observer.addOnWindowFocusChangeListener(focus)
        }
        try { action() }
        finally {
            instrumentation.runOnMainSync {
                try {
                    tapState = TapState(listOf(name.text.toString() == "Synthetic Android Owner",
                        password.text.isEmpty(), confirmation.text.isEmpty(), updated, focusLost)
                        .joinToString("") { if (it) "1" else "0" },
                        publicStatuses[status.text.toString()] ?: CloudStatus.NOT_RECOGNIZED)
                } finally {
                    status.removeTextChangedListener(watcher)
                    if (observer.isAlive) observer.removeOnWindowFocusChangeListener(focus)
                }
            }
        }
    }
    private fun flowState(main: MainActivity, form: Activity): FlowFailure {
        var result: FlowFailure? = null
        instrumentation.runOnMainSync {
            val bits = listOf(NativeAuthSession.get(context).hasLocalSession(),
                !AppLockController.get(context).locked, resumed() === main)
                .joinToString("") { if (it) "1" else "0" }
            result = FlowFailure(bits, publicStatus(form.window.decorView) ?: CloudStatus.NOT_RECOGNIZED)
        }
        return result!!
    }
    private fun awaitFlow(main: MainActivity, form: Activity, bit: Int, deadline: Long) {
        while (SystemClock.elapsedRealtime() < deadline) {
            if (flowState(main, form).flow[bit] == '1') return
            SystemClock.sleep(100)
        }
        throw flowState(main, form)
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
            at(CloudStage.NAME_PRESERVED) { assertFields(form, password, false, false) }
            at(CloudStage.FILL_PASSWORD) { fill(form, "새 비밀번호 · 15~128자", password) }
            at(CloudStage.PASSWORD_PRESERVED) { assertFields(form, password, true, false) }
            at(CloudStage.FILL_CONFIRMATION) { fill(form, "새 비밀번호 확인", password) }
            at(CloudStage.CONFIRMATION_PRESERVED) { assertFields(form, password, true, true) }
            val submit = at(CloudStage.PREPARE_VALID_SUBMIT) {
                readyControl(form, "가계 만들고 시작").also { scrollIntoView(form, it) }
            }
            // Check AFTER the final IME/scroll interaction, immediately before the real click.
            at(CloudStage.PRESUBMIT_FIELDS) { assertFields(form, password, true, true) }
            at(CloudStage.PRESUBMIT_POLICY) { assertInputPolicy(form) }
            at(CloudStage.PRESUBMIT_READY) {
                var ready = false
                instrumentation.runOnMainSync {
                    ready = resumed() === form && form.hasWindowFocus() && !form.isFinishing && !form.isDestroyed &&
                        !form.getSystemService(KeyguardManager::class.java).isDeviceLocked &&
                        !NativeAuthSession.get(context).hasLocalSession()
                }
                assertTrue(ready)
            }
            at(CloudStage.SUBMIT_VALID) {
                observeSubmit(form) { interaction(form, submit) { target(form, submit).perform(click()) } }
            }
            val deadline = SystemClock.elapsedRealtime() + 30_000
            at(CloudStage.SESSION_CREATED) { awaitFlow(main, form, 0, deadline) }
            at(CloudStage.APP_UNLOCKED) { awaitFlow(main, form, 1, deadline) }
            at(CloudStage.MAIN_RESUMED) {
                awaitFlow(main, form, 2, deadline)
                val state = flowState(main, form)
                if (state.flow != "111") throw state
            }
            at(CloudStage.BRIDGE_READY) { assertTrue(main.secureBridgeReady) }
            at(CloudStage.AUTHENTICATED_HOME) { awaitWebState("authenticated home API data", main, authenticatedHome) }
        } finally {
            at(CloudStage.FINISH_MAIN) { instrumentation.runOnMainSync { main.finish() } }
        }
    }
}
