package io.github.jihoon22lee.sallimbook.auth

import java.util.Collections

/** Account step-up retains only identity and a validated, immutable opaque request. No raw vault key. */
internal class NativeVaultReauthentication private constructor(
    before: NativeVaultSnapshot, command: NativeVaultCommand?,
) {
    private val identity=listOf(before.householdId,before.memberId,before.me["user_id"],before.deviceId)
    private var retained=command
    private var active=true
    private var authenticated=false
    val hasCommand get()=retained!=null
    fun challenge() { checkActive(); authenticated=false }
    fun authenticated(current:NativeVaultSnapshot) { checkIdentity(current); authenticated=true }
    fun retry(current:NativeVaultSnapshot):NativeVaultCommand {
        checkIdentity(current)
        if(!authenticated) throw NativeVaultFailure("REAUTHENTICATION_REQUIRED")
        return retained ?: throw NativeVaultFailure("INVALID_REQUEST")
    }
    private fun checkActive() { if(!active) throw NativeVaultFailure("AUTH_CANCELLED") }
    private fun checkIdentity(current:NativeVaultSnapshot) {
        checkActive()
        if(identity!=listOf(current.householdId,current.memberId,current.me["user_id"],current.deviceId)) {
            discard(); throw NativeVaultFailure("ACCESS_DENIED")
        }
    }
    fun discard() { active=false; authenticated=false; retained=null }
    override fun toString()="NativeVaultReauthentication(redacted)"
    companion object {
        fun required(code:String?)=code in setOf("REAUTHENTICATION_REQUIRED","STEP_UP_REQUIRED")
        fun form(before:NativeVaultSnapshot)=NativeVaultReauthentication(before,null)
        fun command(before:NativeVaultSnapshot,command:NativeVaultCommand):NativeVaultReauthentication {
            if(NativeVaultWire.route(command).method=="GET") throw NativeVaultFailure("INVALID_REQUEST")
            @Suppress("UNCHECKED_CAST")
            val body=immutable(command.body) as VaultRecord?
            val owned=NativeVaultCommand(command.operation,command.id,command.childId,body,command.version,command.idempotencyKey,command.cursor,command.limit)
            NativeVaultWire.route(owned)
            return NativeVaultReauthentication(before,owned)
        }
        fun prepared(value:NativeVaultPrepared):NativeVaultReauthentication {
            try {
                // Nonzero code means the user has not acknowledged its offline storage yet.
                if(value.recoveryCode?.any { it!='\u0000' }==true) throw NativeVaultFailure("ACCESS_DENIED")
                return command(value.material.snapshot,value.command)
            } finally { value.discard() }
        }
        private fun immutable(value:Any?):Any?=when(value) {
            null,is String,is Boolean,is Int,is Long -> value
            is Map<*,*> -> Collections.unmodifiableMap(value.entries.associate { (key,item) ->
                (key as? String ?: throw NativeVaultFailure("INVALID_REQUEST")) to immutable(item) })
            is List<*> -> Collections.unmodifiableList(value.map(::immutable))
            else -> throw NativeVaultFailure("INVALID_REQUEST")
        }
    }
}
