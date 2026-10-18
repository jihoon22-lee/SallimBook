package io.github.jihoon22lee.sallimbook.auth

internal object NativeVaultUiPolicy {
    val cardActions = setOf("view", "edit", "purge", "cvc-view", "cvc-edit", "cvc-delete")
    val memberActions = setOf("share", "revoke-member")
    val offerActions = setOf("accept-share", "cancel-share")
    val rotationActions = setOf("resume-rotation", "abort-rotation")
    val plainActions = setOf("manage", "setup", "register-device", "change-password", "recover", "rotate")
    val actions = cardActions + memberActions + offerActions + rotationActions + plainActions
    fun idField(action: String): String? = when(action) {
        in cardActions -> "cardId"; in memberActions -> "memberId"; in offerActions -> "offerId"; in rotationActions -> "rotationId"
        in plainActions -> null; else -> throw NativeVaultFailure("INVALID_REQUEST")
    }
    fun arguments(value: Any?): Pair<String,String?> {
        val raw=value as? Map<*,*> ?: throw NativeVaultFailure("INVALID_REQUEST")
        val action=raw["action"] as? String ?: throw NativeVaultFailure("INVALID_REQUEST")
        val field=idField(action)
        if(raw.keys != setOf("action")+(field?.let { setOf(it) } ?: emptySet())) throw NativeVaultFailure("INVALID_REQUEST")
        return action to field?.let { NativeVaultWire.id(raw[it]) }
    }
    fun native(action: String, id: String?) { val field=idField(action); if((field!=null)!=(id!=null)) throw NativeVaultFailure("INVALID_REQUEST"); id?.let(NativeVaultWire::id) }
    fun metadata(operation: VaultOperation, value: Any?): NativeVaultCommand {
        val raw=value as? Map<*,*> ?: throw NativeVaultFailure("INVALID_REQUEST")
        val command=when(operation) {
            VaultOperation.STATUS -> { if(raw.isNotEmpty()) throw NativeVaultFailure("INVALID_REQUEST"); NativeVaultCommand(operation) }
            VaultOperation.ROTATION_GET -> { if(raw.keys!=setOf("rotationId")) throw NativeVaultFailure("INVALID_REQUEST"); NativeVaultCommand(operation,id=NativeVaultWire.id(raw["rotationId"])) }
            VaultOperation.SHARES -> {
                if(raw.keys.any { it!="query" }) throw NativeVaultFailure("INVALID_REQUEST")
                val query=if(raw.containsKey("query")) raw["query"] as? Map<*,*> ?: throw NativeVaultFailure("INVALID_REQUEST") else emptyMap<Any,Any>()
                if(query.keys.any { it !in setOf("cursor","limit") }) throw NativeVaultFailure("INVALID_REQUEST")
                val limit=if(query.containsKey("limit")) NativeVaultWire.version(query["limit"]).also { n -> if(n>200) throw NativeVaultFailure("INVALID_REQUEST") }.toInt() else 50
                NativeVaultCommand(operation,cursor=query["cursor"]?.let(NativeVaultWire::id),limit=limit)
            }
            else -> throw NativeVaultFailure("INVALID_REQUEST")
        }
        NativeVaultWire.route(command); return command
    }
}
