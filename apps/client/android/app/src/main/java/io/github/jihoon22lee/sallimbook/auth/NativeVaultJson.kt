package io.github.jihoon22lee.sallimbook.auth

import com.google.gson.GsonBuilder
import com.google.gson.Strictness
import com.google.gson.stream.JsonReader
import com.google.gson.stream.JsonToken
import java.io.StringReader

/** Gson's strict parser with bounded containers, duplicate-name rejection and integer-only values. */
internal object NativeVaultJson {
    private val gson=GsonBuilder().setStrictness(Strictness.STRICT).serializeNulls().create()
    fun encode(command:NativeVaultCommand):ByteArray? {
        NativeVaultWire.route(command)
        return command.body?.let { gson.toJson(it).toByteArray(Charsets.UTF_8) }
    }
    fun decode(text:String):Any? {
        if(text.length>1_048_576) throw NativeVaultFailure("ACCESS_DENIED")
        return JsonReader(StringReader(text)).use { reader ->
            reader.strictness=Strictness.STRICT
            val value=read(reader,0)
            if(reader.peek()!=JsonToken.END_DOCUMENT) throw NativeVaultFailure("ACCESS_DENIED")
            value
        }
    }
    private fun read(reader:JsonReader,depth:Int):Any? {
        if(depth>12) throw NativeVaultFailure("ACCESS_DENIED")
        return when(reader.peek()) {
            JsonToken.NULL -> { reader.nextNull(); null }
            JsonToken.BOOLEAN -> reader.nextBoolean()
            JsonToken.STRING -> reader.nextString()
            JsonToken.NUMBER -> {
                val text=reader.nextString()
                if(!Regex("-?(0|[1-9][0-9]*)").matches(text)) throw NativeVaultFailure("ACCESS_DENIED")
                val number=text.toLongOrNull() ?: throw NativeVaultFailure("ACCESS_DENIED")
                if(number in Int.MIN_VALUE..Int.MAX_VALUE) number.toInt() else number
            }
            JsonToken.BEGIN_OBJECT -> {
                val result=linkedMapOf<String,Any?>(); reader.beginObject()
                while(reader.hasNext()) {
                    val name=reader.nextName()
                    if(name.length>128 || result.size>=64 || result.containsKey(name)) throw NativeVaultFailure("ACCESS_DENIED")
                    result[name]=read(reader,depth+1)
                }
                reader.endObject(); result
            }
            JsonToken.BEGIN_ARRAY -> {
                val result=mutableListOf<Any?>(); reader.beginArray()
                while(reader.hasNext()) { if(result.size>=2000) throw NativeVaultFailure("ACCESS_DENIED"); result.add(read(reader,depth+1)) }
                reader.endArray(); result
            }
            else -> throw NativeVaultFailure("ACCESS_DENIED")
        }
    }
}
