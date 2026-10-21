package io.github.jihoon22lee.sallimbook.auth

/** A synthetic response as a later API version might send it: every object gains one new field. */
internal fun withAddedFields(value: Any?): Any? = when (value) {
    is Map<*, *> -> value.entries.associate { it.key as String to withAddedFields(it.value) } + ("added_note" to "synthetic later field")
    is List<*> -> value.map(::withAddedFields)
    else -> value
}
