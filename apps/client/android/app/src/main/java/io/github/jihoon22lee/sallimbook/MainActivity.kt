package io.github.jihoon22lee.sallimbook

import android.os.Bundle
import android.view.ViewGroup
import android.view.View
import android.view.WindowManager
import android.webkit.WebView
import android.widget.TextView
import androidx.webkit.WebViewFeature
import com.getcapacitor.BridgeActivity
import com.getcapacitor.CapConfig
import io.github.jihoon22lee.sallimbook.auth.SallimBookAuthPlugin
import io.github.jihoon22lee.sallimbook.auth.AppLockController
import io.github.jihoon22lee.sallimbook.auth.AppLockScreen

class MainActivity : BridgeActivity() {
    private var secureWebView: SecureBridgeWebView? = null
    private var appLockScreen: AppLockScreen? = null
    val secureBridgeReady: Boolean get() = secureWebView?.isBoundaryReady == true

    override fun onCreate(savedInstanceState: Bundle?) {
        AppLockController.get(this)
        window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
        registerPlugin(SallimBookAuthPlugin::class.java)
        super.onCreate(savedInstanceState)
    }

    override fun load() {
        // BridgeActivity has inflated its WebView, but has not created MessageHandler or
        // navigated yet. Replacing it here preserves Capacitor's normal builder/lifecycle.
        val original = findViewById<WebView>(com.getcapacitor.android.R.id.webview)
        val parent = original.parent as ViewGroup
        val position = parent.indexOfChild(original)
        val parameters = original.layoutParams
        parent.removeView(original)
        original.destroy()
        val secured = SecureBridgeWebView(this).also { it.id = com.getcapacitor.android.R.id.webview }
        secured.visibility = View.INVISIBLE
        secureWebView = secured
        parent.addView(secured, position, parameters)
        try {
            val bundled = CapConfig.loadDefault(this)
            config = bundled
            if (!WebViewFeature.isFeatureSupported(WebViewFeature.WEB_MESSAGE_LISTENER) ||
                bundled.isUsingLegacyBridge || bundled.serverUrl != null ||
                bundled.hostname != "localhost" || bundled.androidScheme != "https" ||
                !bundled.allowNavigation.isNullOrEmpty() || bundled.isMixedContentAllowed) {
                showUnsupportedWebView()
                return
            }
            super.load()
            if (!secured.activate()) showUnsupportedWebView()
            else appLockScreen = AppLockScreen(this)
        } catch (_: Exception) {
            showUnsupportedWebView()
        }
    }

    internal fun setAppContentVisible(visible: Boolean) {
        secureWebView?.visibility = if (visible) View.VISIBLE else View.INVISIBLE
        secureWebView?.importantForAccessibility = if (visible) View.IMPORTANT_FOR_ACCESSIBILITY_AUTO else View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS
    }
    override fun onResume() {
        super.onResume()
        // Evaluate elapsed background time before a cached WebView can become visible.
        AppLockController.get(this).onActivityResumed(this)
        appLockScreen?.onResume()
    }
    override fun onPause() { appLockScreen?.onPause(); super.onPause() }
    override fun onStop() { appLockScreen?.onStop(); super.onStop() }
    override fun onWindowFocusChanged(hasFocus: Boolean) { super.onWindowFocusChanged(hasFocus); appLockScreen?.onFocusChanged(hasFocus) }
    override fun onDestroy() { appLockScreen?.onDestroy(); appLockScreen = null; super.onDestroy() }

    private fun showUnsupportedWebView() {
        bridge?.onDestroy()
        bridge = null
        secureWebView?.let { view ->
            (view.parent as? ViewGroup)?.removeView(view)
            view.stopLoading()
            view.destroy()
        }
        secureWebView = null
        setContentView(TextView(this).apply {
            text = "안전한 앱 연결을 시작할 수 없어요. Android System WebView를 업데이트한 후 앱을 다시 열어 주세요."
            setPadding(32, 48, 32, 32)
            textSize = 18f
        })
    }
}
