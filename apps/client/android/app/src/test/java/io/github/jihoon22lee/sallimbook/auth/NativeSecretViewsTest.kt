package io.github.jihoon22lee.sallimbook.auth

import java.io.File
import org.junit.Assert.*
import org.junit.Test

class NativeSecretViewsTest {
    private val root = File("src/main/java/io/github/jihoon22lee/sallimbook/auth")
    @Test fun everySecretDisplayIsMarkedAccessibilityDataSensitive() {
        val displays = mapOf("NativeVaultActivity.kt" to "secretOutput", "NativeAccountNumberActivity.kt" to "output",
            "NativeInsurancePolicyNumberActivity.kt" to "output", "NativePasskeyActivity.kt" to "code",
            "NativeAuthActivity.kt" to "invitationText", "NativeOnboardingActivity.kt" to "codeText")
        for ((file, view) in displays) {
            val source = File(root, file).readText()
            assertTrue("$file $view", Regex("""\b$view\s*=\s*NativeSecretViews\.sensitive\(label\(""").containsMatchIn(source))
            assertFalse("$file $view", Regex("""\b$view\s*=\s*label\(""").containsMatchIn(source))
        }
    }
    @Test fun helperGuardsTheApi34Call() {
        val helper = File(root, "NativeSecretViews.kt").readText()
        assertTrue(helper.contains("Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE"))
        assertTrue(helper.contains("setAccessibilityDataSensitive(View.ACCESSIBILITY_DATA_SENSITIVE_YES)"))
    }
}
