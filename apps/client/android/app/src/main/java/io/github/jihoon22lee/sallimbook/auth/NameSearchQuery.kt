package io.github.jihoon22lee.sallimbook.auth

import java.net.URLDecoder
import java.net.URLEncoder
import java.nio.charset.StandardCharsets

/** Only a bounded metadata search value may contain encoded query text. Paths stay fixed. */
internal object NameSearchQuery {
    fun validate(value: Any?) {
        if (value !is String || value.codePointCount(0, value.length) > 120 ||
            value.any { it.code < 32 || it.code == 127 }) throw AuthFailure(AuthCode.INVALID_REQUEST)
    }
    fun encode(value: Any?): String {
        validate(value)
        return URLEncoder.encode(value as String, StandardCharsets.UTF_8.name())
    }
    fun decode(value: String): String = URLDecoder.decode(value, StandardCharsets.UTF_8.name()).also(::validate)
    fun value(key: String, value: Any?): String = if (key == "q") encode(value) else value.toString()
}
