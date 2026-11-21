package dev.pentoshi.protonx.data

import android.content.Context
import dev.pentoshi.protonx.core.Identity
import dev.pentoshi.protonx.core.Phase
import dev.pentoshi.protonx.core.SavedServer
import dev.pentoshi.protonx.core.Session
import dev.pentoshi.protonx.core.Snapshot
import org.json.JSONObject

class StateStore(context: Context) {
    private val prefs = context.applicationContext.getSharedPreferences(FILE, Context.MODE_PRIVATE)
    private val secrets = SecretBox(prefs)

    fun session(): Session? = secrets.get(KEY_SESSION)?.let { raw ->
        runCatching { Session.from(JSONObject(raw)) }.getOrNull()
    }

    fun saveSession(session: Session) {
        secrets.put(KEY_SESSION, session.toJson().toString())
    }

    fun clearSession() {
        secrets.remove(KEY_SESSION)
    }

    fun signedIn(): Boolean = session() != null

    fun identity(): Identity {
        val saved = secrets.get(KEY_IDENTITY)?.let(Identity::fromSeed)
        if (saved != null) return saved
        val created = Identity.create()
        saveIdentity(created)
        return created
    }

    fun saveIdentity(identity: Identity) {
        secrets.put(KEY_IDENTITY, identity.seedBase64)
    }

    fun lastServer(): SavedServer? = readServer(KEY_LAST)
    fun currentServer(): SavedServer? = readServer(KEY_CURRENT)

    fun rememberServer(server: SavedServer) {
        writeServer(KEY_LAST, server)
    }

    fun setCurrentServer(server: SavedServer?) {
        writeServer(KEY_CURRENT, server)
    }

    var phase: Phase
        get() = runCatching { Phase.valueOf(prefs.getString(KEY_PHASE, null) ?: Phase.IDLE.name) }
            .getOrDefault(Phase.IDLE)
        set(value) = prefs.edit().putString(KEY_PHASE, value.name).apply()

    var lastError: String?
        get() = prefs.getString(KEY_ERROR, null)
        set(value) = prefs.edit().putString(KEY_ERROR, value).apply()

    var connectedAt: Long
        get() = prefs.getLong(KEY_CONNECTED_AT, 0L)
        set(value) = prefs.edit().putLong(KEY_CONNECTED_AT, value).apply()

    var catalogFetchedAt: Long
        get() = prefs.getLong(KEY_CATALOG_AT, 0L)
        set(value) = prefs.edit().putLong(KEY_CATALOG_AT, value).apply()

    var showPaid: Boolean
        get() = prefs.getBoolean(KEY_SHOW_PAID, false)
        set(value) = prefs.edit().putBoolean(KEY_SHOW_PAID, value).apply()

    fun snapshot(): Snapshot = Snapshot(
        phase = phase,
        server = currentServer(),
        error = lastError,
        since = connectedAt,
    )

    private fun readServer(key: String): SavedServer? = prefs.getString(key, null)?.let { raw ->
        runCatching { SavedServer.from(JSONObject(raw)) }.getOrNull()
    }

    private fun writeServer(key: String, server: SavedServer?) {
        val editor = prefs.edit()
        if (server == null) editor.remove(key).apply() else editor.putString(key, server.toJson().toString()).apply()
    }

    private companion object {
        const val FILE = "protonx"
        const val KEY_SESSION = "session"
        const val KEY_IDENTITY = "identity_seed"
        const val KEY_LAST = "last_server"
        const val KEY_CURRENT = "current_server"
        const val KEY_PHASE = "phase"
        const val KEY_ERROR = "last_error"
        const val KEY_CONNECTED_AT = "connected_at"
        const val KEY_CATALOG_AT = "catalog_at"
        const val KEY_SHOW_PAID = "show_paid"
    }
}
