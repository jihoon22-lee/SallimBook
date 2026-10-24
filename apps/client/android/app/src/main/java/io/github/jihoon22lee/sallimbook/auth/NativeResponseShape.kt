package io.github.jihoon22lee.sallimbook.auth

import java.util.IdentityHashMap

/**
 * Forward-compatible metadata responses. A later API version may add response fields; an installed
 * APK must keep working without passing those unknown fields to the WebView.
 *
 * Inside [project] (the finance metadata entry point), validators accept a server object whose
 * keys include every required field, validate the fields they know and register that object here.
 * [project] then rebuilds the result: every registered object keeps only its known keys. Outside
 * [project] (request bodies, queries, reveal routes and the vault, audit, onboarding and export
 * wires) the same call is the exact key check. Required fields stay required in both modes.
 *
 * Validators run synchronously on the account executor, so the mode is a thread-local.
 */
internal object NativeResponseShape {
    private val registry = ThreadLocal<IdentityHashMap<Any, MutableSet<String>>?>()

    /** True only while a metadata response is being validated. */
    val tolerant: Boolean get() = registry.get() != null

    /**
     * [raw] is the parsed server object itself (not a copy), so the projection can find it.
     * Strict mode: keys must equal [known] apart from optional fields. Response mode: unknown keys are
     * allowed and later dropped.
     */
    fun accept(raw: Any, keys: Set<String>, known: Set<String>, required: Set<String>, invalid: () -> Nothing) {
        if (!keys.containsAll(required)) invalid()
        val current = registry.get()
        if (current == null) {
            if (!known.containsAll(keys)) invalid()
            return
        }
        // An added field named like a credential, key or card/account/policy number is a server bug,
        // not a compatible addition: refuse the response instead of silently dropping it.
        if (keys.any { it !in known && !AuthPolicy.safeField(it) }) invalid()
        current.getOrPut(raw) { mutableSetOf() }.addAll(known)
    }

    /** The parsed object itself in response mode, where identity matters to [project]; keys are already strings. */
    @Suppress("UNCHECKED_CAST")
    fun identity(row: Map<*, *>): Map<String, Any?> = row as Map<String, Any?>

    /** The known part of a registered server object, for comparisons that must ignore added fields. */
    fun known(row: Map<String, Any?>): Map<String, Any?> {
        val keys = registry.get()?.get(row) ?: return row
        return row.filterKeys { it in keys }
    }

    /**
     * A flat reply outside the metadata wires (invitations, passkey options): its [known] fields,
     * also when a later API adds safe ones. Every known field is required; [invalid] also covers a
     * non-string key, more than 24 keys and an added name that looks like a credential. Nested
     * values stay as sent.
     */
    fun fields(value: Any?, known: Set<String>, invalid: () -> Nothing): Map<String, Any?> {
        val row = value as? Map<*, *> ?: invalid()
        if (row.size > 24 || row.keys.any { it !is String }) invalid()
        @Suppress("UNCHECKED_CAST")
        return project { accept(row, row.keys as Set<String>, known, known, invalid); row } as Map<String, Any?>
    }

    /** Validates a metadata response and returns it without fields this APK does not know. */
    fun project(validate: () -> Any?): Any? {
        if (registry.get() != null) return validate()
        val current = IdentityHashMap<Any, MutableSet<String>>()
        registry.set(current)
        try {
            return strip(validate(), current)
        } finally {
            registry.remove()
        }
    }

    private fun strip(value: Any?, allowed: IdentityHashMap<Any, MutableSet<String>>): Any? = when (value) {
        is Map<*, *> -> {
            val keys = allowed[value]
            val result = LinkedHashMap<String, Any?>()
            for ((key, item) in value) if (keys == null || key in keys) result[key as String] = strip(item, allowed)
            result
        }
        is List<*> -> value.map { strip(it, allowed) }
        else -> value
    }
}
