package dev.pentoshi.protonx.core

import org.json.JSONArray
import org.json.JSONObject

data class Session(
    val userId: String = "",
    val accessToken: String = "",
    val refreshToken: String = "",
    val username: String = "",
    val scopes: List<String> = emptyList(),
) {
    fun toJson(): JSONObject = JSONObject()
        .put("userId", userId)
        .put("accessToken", accessToken)
        .put("refreshToken", refreshToken)
        .put("username", username)
        .put("scopes", JSONArray(scopes))

    companion object {
        fun from(json: JSONObject): Session = Session(
            userId = json.optString("userId"),
            accessToken = json.optString("accessToken"),
            refreshToken = json.optString("refreshToken"),
            username = json.optString("username"),
            scopes = json.optJSONArray("scopes")?.let { array ->
                (0 until array.length()).map { array.optString(it) }
            } ?: emptyList(),
        )

        fun fromAuth(result: JSONObject, username: String): Session = Session(
            userId = Json.text(result, "UID"),
            accessToken = Json.text(result, "AccessToken"),
            refreshToken = Json.text(result, "RefreshToken"),
            username = username,
            scopes = Json.text(result, "Scope").split(" ").filter { it.isNotBlank() },
        )
    }
}

object Json {
    fun text(json: JSONObject, key: String): String = if (json.isNull(key)) "" else json.optString(key, "")
    fun number(json: JSONObject, key: String): Int = if (json.isNull(key)) 0 else json.optInt(key, 0)
    fun flag(json: JSONObject, key: String): Boolean {
        if (json.isNull(key)) return false
        return when (val value = json.opt(key)) {
            is Boolean -> value
            is Number -> value.toInt() != 0
            is String -> value.equals("true", ignoreCase = true) || value == "1"
            else -> false
        }
    }
}

data class SavedServer(
    val country: String,
    val server: String,
    val label: String,
    val city: String,
    val load: Int,
    val tier: String,
) {
    fun toJson(): JSONObject = JSONObject()
        .put("country", country)
        .put("server", server)
        .put("label", label)
        .put("city", city)
        .put("load", load)
        .put("tier", tier)

    companion object {
        fun from(json: JSONObject?): SavedServer? {
            if (json == null) return null
            val server = json.optString("server")
            if (server.isBlank()) return null
            return SavedServer(
                country = json.optString("country"),
                server = server,
                label = json.optString("label").ifBlank { server },
                city = json.optString("city"),
                load = json.optInt("load"),
                tier = json.optString("tier", "free"),
            )
        }

        fun of(logical: Logical): SavedServer = SavedServer(
            country = logical.exitCountry,
            server = logical.displayName(),
            label = logical.displayName(),
            city = logical.city.ifBlank { CountryNames.of(logical.exitCountry) },
            load = logical.load,
            tier = if (logical.free) "free" else "plus",
        )
    }
}

enum class Phase { IDLE, CONNECTING, CONNECTED, DISCONNECTING, ERROR }

data class Traffic(val received: Long, val sent: Long)

data class Snapshot(
    val phase: Phase,
    val server: SavedServer?,
    val error: String?,
    val since: Long,
)

sealed interface Target {
    data object Fastest : Target
    data object Last : Target
    data class Server(val country: String, val name: String) : Target
}
