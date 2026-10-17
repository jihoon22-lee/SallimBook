package io.github.jihoon22lee.sallimbook

import android.webkit.JavascriptInterface
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.*
import org.junit.Test
import org.junit.runner.RunWith

/** Real WebView checks; JVM policy tests cannot validate JavaScript-interface exposure. */
@RunWith(AndroidJUnit4::class)
class SecureBridgeWebViewTest {
    private class LegacyInterface {
        @JavascriptInterface fun postMessage(message: String) = Unit
    }

    private fun onWebView(action: (SecureBridgeWebView) -> Unit) {
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.runOnMainSync {
            val view = SecureBridgeWebView(instrumentation.targetContext)
            try { action(view) } finally { view.destroy() }
        }
    }

    @Test fun initialNavigationWaitsForBridgeConstruction() = onWebView { view ->
        view.loadUrl("https://localhost/")
        assertNull(view.url)
        assertFalse(view.isBoundaryReady)
    }

    @Test fun listenerFailureFallbackCannotLoadAPageOrEnableAuth() = onWebView { view ->
        // This is the exact fallback API that Capacitor calls if listener registration throws.
        view.addJavascriptInterface(LegacyInterface(), "androidBridge")
        view.loadUrl("https://localhost/")
        assertFalse(view.activate())
        assertFalse(view.isBoundaryReady)
        assertNull(view.url)
        // A second navigation must not erase the remembered failure.
        view.loadUrl("https://localhost/settings")
        assertFalse(view.activate())
        assertNull(view.url)
    }

    @Test fun fallbackAfterQueuedNavigationStillFailsClosed() = onWebView { view ->
        view.loadUrl("https://localhost/", mutableMapOf("Accept" to "text/html"))
        view.addJavascriptInterface(LegacyInterface(), "androidBridge")
        assertFalse(view.activate())
        assertNull(view.url)
    }

    @Test fun initialNavigationCannotEscapeTheBundledOrigin() = onWebView { view ->
        for (url in listOf("https://synthetic.invalid/", "http://localhost/", "file:///test",
            "https://localhost:443/", "https://user@localhost/")) {
            view.loadUrl(url)
            assertFalse(view.activate())
            assertNull(view.url)
        }
    }
}
