package dev.pentoshi.protonx.core

import org.json.JSONObject

internal fun JSONObject.text(key: String): String = if (isNull(key)) "" else optString(key, "")

internal fun JSONObject.number(key: String): Int = if (isNull(key)) 0 else optInt(key, 0)

data class Entry(
    val serverId: String,
    val name: String,
    val domain: String,
    val entryIp: String,
    val x25519: String,
    val ports: List<Int>,
) {
    val endpointHost: String get() = entryIp.ifBlank { domain }
    val port: Int get() = ports.firstOrNull() ?: WIREGUARD_PORT

    companion object {
        const val WIREGUARD_PORT = 51820
    }
}

data class Logical(
    val id: String,
    val name: String,
    val exitCountry: String,
    val entryCountry: String,
    val city: String,
    val tier: Int,
    val load: Int,
    val status: Int,
    val features: Int,
    val entries: List<Entry>,
) {
    val free: Boolean get() = tier == 0
    val online: Boolean get() = status == 1

    // Proton marks Secure Core on the logical, or by entry/exit country mismatch.
    val secureCore: Boolean get() = features and SECURE_CORE_FEATURE != 0 || entryCountry != exitCountry
    val wireguardEntries: List<Entry> get() = entries.filter { it.x25519.isNotEmpty() }

    fun displayName(): String = name.ifBlank { id }

    companion object {
        const val SECURE_CORE_FEATURE = 4
    }
}

object Logicals {
    const val PROTOCOL = "WireGuardUDP"

    fun parse(payload: JSONObject): List<Logical> {
        val raw = payload.optJSONArray("LogicalServers") ?: return emptyList()
        return (0 until raw.length()).mapNotNull { index ->
            raw.optJSONObject(index)?.let(::parseLogical)
        }
    }

    private fun parseLogical(raw: JSONObject): Logical {
        val exit = raw.text("ExitCountry").uppercase()
        val servers = raw.optJSONArray("Servers")
        val entries = if (servers == null) emptyList() else
            (0 until servers.length()).mapNotNull { servers.optJSONObject(it)?.let(::parseEntry) }
        return Logical(
            id = raw.text("ID"),
            name = raw.text("Name"),
            exitCountry = exit,
            entryCountry = raw.text("EntryCountry").ifBlank { exit }.uppercase(),
            city = raw.text("City"),
            tier = raw.number("Tier"),
            load = raw.number("Load"),
            status = raw.number("Status"),
            features = raw.number("Features"),
            entries = entries,
        )
    }

    private fun parseEntry(server: JSONObject): Entry {
        val protocol = protocolEntry(server)
        val x25519 = server.text("X25519PublicKey").ifBlank { protocol?.text("X25519PublicKey") ?: "" }
        val ipv4 = listOf(protocol?.text("Ipv4"), protocol?.text("IPv4"), server.text("EntryIP"))
            .firstOrNull { !it.isNullOrBlank() } ?: ""
        return Entry(
            serverId = server.text("ID"),
            name = server.text("Name").ifBlank { server.text("Domain").ifBlank { server.text("EntryIP") } },
            domain = server.text("Domain"),
            entryIp = ipv4,
            x25519 = x25519,
            ports = ports(protocol),
        )
    }

    private fun protocolEntry(server: JSONObject): JSONObject? =
        server.optJSONObject("ProtocolEntries")?.optJSONObject(PROTOCOL)
            ?: server.optJSONObject("EntryPerProtocol")?.optJSONObject(PROTOCOL)

    private fun ports(protocol: JSONObject?): List<Int> {
        val raw = protocol?.optJSONArray("Ports") ?: return emptyList()
        return (0 until raw.length()).mapNotNull { index ->
            raw.optString(index).toIntOrNull()
        }
    }
}
