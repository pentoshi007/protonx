package dev.pentoshi.protonx.data

import android.content.Context
import dev.pentoshi.protonx.core.Logical
import dev.pentoshi.protonx.core.Logicals
import org.json.JSONObject
import java.io.File

class Catalog(val servers: List<Logical>, val fetchedAt: Long)

/** The last server list Proton returned, so the app opens instantly and works offline. */
class CatalogStore(context: Context) {
    private val file = File(context.applicationContext.filesDir, "catalog.json")

    fun load(): Catalog? = runCatching {
        if (!file.exists()) return null
        val payload = JSONObject(file.readText())
        val servers = Logicals.parse(payload.optJSONObject("payload") ?: JSONObject())
        if (servers.isEmpty()) return null
        Catalog(servers, payload.optLong("fetchedAt", 0L))
    }.getOrNull()

    fun save(payload: JSONObject, fetchedAt: Long) {
        val body = JSONObject().put("fetchedAt", fetchedAt).put("payload", payload)
        val temporary = File(file.parentFile, "${file.name}.tmp")
        temporary.writeText(body.toString())
        if (!temporary.renameTo(file)) {
            temporary.delete()
            throw IllegalStateException("could not store the server list")
        }
    }
}
