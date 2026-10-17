package io.github.jihoon22lee.sallimbook

import android.content.Context
import com.getcapacitor.CapacitorWebView
import java.net.URI

/** Keeps Capacitor's source-aware message listener, but never installs its legacy fallback.
 * Bridge construction requests the first navigation synchronously. Defer it until the
 * Activity has verified that construction completed without attempting that fallback.
 */
internal class SecureBridgeWebView(context: Context) : CapacitorWebView(context, null) {
    private var legacyAttempted = false
    private var pendingUrl: String? = null
    private var pendingHeaders: Map<String, String>? = null
    var isBoundaryReady = false
        private set

    override fun addJavascriptInterface(instance: Any, name: String) {
        if (name == "androidBridge") {
            // MessageHandler calls this after a listener registration exception as well as
            // on unsupported WebViews. Never call super: even a temporary exposure is unsafe.
            legacyAttempted = true
            isBoundaryReady = false
            stopLoading()
            return
        }
        super.addJavascriptInterface(instance, name)
    }

    override fun loadUrl(url: String) {
        if (!isBoundaryReady) {
            pendingUrl = url
            pendingHeaders = null
        } else super.loadUrl(url)
    }

    override fun loadUrl(url: String, additionalHttpHeaders: MutableMap<String, String>) {
        if (!isBoundaryReady) {
            pendingUrl = url
            pendingHeaders = additionalHttpHeaders.toMap()
        } else super.loadUrl(url, additionalHttpHeaders)
    }

    fun activate(): Boolean {
        val url = pendingUrl ?: return false
        val local = try {
            val uri = URI(url)
            uri.scheme == "https" && uri.host == "localhost" && uri.port == -1 &&
                uri.rawUserInfo == null && '\\' !in url
        } catch (_: Exception) { false }
        if (legacyAttempted || !local || isBoundaryReady) return false
        pendingUrl = null
        isBoundaryReady = true
        val headers = pendingHeaders
        pendingHeaders = null
        if (headers == null) super.loadUrl(url) else super.loadUrl(url, headers)
        return true
    }
}
