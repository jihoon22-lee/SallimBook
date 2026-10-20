package io.github.jihoon22lee.sallimbook.auth

import android.os.Build
import android.view.View

internal object NativeSecretViews {
    /** Hides revealed secrets from non-accessibility-tool services on API 34+; accessibility tools such as TalkBack still read them. */
    fun <T : View> sensitive(view: T): T {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            view.setAccessibilityDataSensitive(View.ACCESSIBILITY_DATA_SENSITIVE_YES)
        }
        return view
    }
}
