package io.github.jihoon22lee.sallimbook

import android.os.Bundle
import android.view.ViewGroup
import android.webkit.WebView
import android.widget.TextView
import androidx.webkit.WebViewFeature
import com.getcapacitor.BridgeActivity
import com.getcapacitor.CapConfig
import io.github.jihoon22lee.sallimbook.auth.SallimBookAuthPlugin

class MainActivity : BridgeActivity() {
    private var secureWebView: SecureBridgeWebView? = null
    val secureBridgeReady: Boolean get() = secureWebView?.isBoundaryReady == true

    override fun onCreate(savedInstanceState: Bundle?) {
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
        } catch (_: Exception) {
            showUnsupportedWebView()
        }
    }

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
