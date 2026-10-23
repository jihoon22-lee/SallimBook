package io.github.jihoon22lee.sallimbook.auth

import android.app.Activity
import android.widget.Toast

/**
 * A session end cancels every open request, so a signed-in native screen would otherwise keep
 * showing its progress text. Such a screen says the sign-in ended and closes instead.
 */
internal object NativeSessionEnd {
    const val MESSAGE = "로그인이 끝나 화면을 닫았어요. 다시 로그인해 주세요."

    /** Only the screen's own current request, on a screen still in front, that began signed in. */
    fun ended(current: Boolean, ready: Boolean, startedSignedIn: Boolean, signedIn: Boolean): Boolean =
        current && ready && startedSignedIn && !signedIn

    fun close(activity: Activity) {
        Toast.makeText(activity.applicationContext, MESSAGE, Toast.LENGTH_LONG).show()
        activity.setResult(Activity.RESULT_CANCELED)
        activity.finish()
    }
}
