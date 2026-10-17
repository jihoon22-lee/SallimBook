package io.github.jihoon22lee.sallimbook.auth

import android.content.Context
import android.content.pm.PackageManager
import io.github.jihoon22lee.sallimbook.BuildConfig
import java.security.MessageDigest
import java.util.Base64

internal class PasskeyConfiguration private constructor(val rpId: String, val androidOrigin: String) {
    companion object {
        fun read(context: Context): PasskeyConfiguration? = try {
            val info = context.packageManager.getPackageInfo(context.packageName, PackageManager.GET_SIGNING_CERTIFICATES)
            val signers = info.signingInfo?.apkContentsSigners
            if (signers == null || signers.size != 1) null
            else {
                val digest = MessageDigest.getInstance("SHA-256").digest(signers.single().toByteArray())
                val hex = digest.joinToString("") { "%02x".format(it.toInt() and 0xff) }
                if (!PasskeyPolicy.configuration(BuildConfig.SALLIMBOOK_API_ORIGIN,
                        BuildConfig.SALLIMBOOK_PASSKEY_RP_ID, BuildConfig.SALLIMBOOK_PASSKEY_CERT_SHA256, hex)) null
                else PasskeyConfiguration(BuildConfig.SALLIMBOOK_PASSKEY_RP_ID,
                    "android:apk-key-hash:" + Base64.getUrlEncoder().withoutPadding().encodeToString(digest))
            }
        } catch (_: Exception) { null }
    }
}
