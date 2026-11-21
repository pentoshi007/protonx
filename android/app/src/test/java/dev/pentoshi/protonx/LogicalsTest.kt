package dev.pentoshi.protonx

import dev.pentoshi.protonx.core.Logicals
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class LogicalsTest {
    private fun fixture(): JSONObject = javaClass.getResourceAsStream("/catalog.json")!!
        .bufferedReader().use { JSONObject(it.readText()) }

    @Test
    fun parsesARealProtonResponse() {
        val servers = Logicals.parse(fixture())
        assertEquals(3, servers.size)
        servers.forEach { logical ->
            assertTrue(logical.exitCountry.isNotBlank())
            assertTrue(logical.displayName().isNotBlank())
            assertTrue(logical.wireguardEntries.isNotEmpty())
        }
        val first = servers.first().wireguardEntries.first()
        assertEquals(51820, first.port)
        assertTrue(first.endpointHost.isNotBlank())
    }

    @Test
    fun readsProtocolEntriesWhenProtonSendsThem() {
        val protocol = JSONObject()
            .put("Ipv4", "5.6.7.8")
            .put("Ports", JSONArray(listOf(443, 51820)))
            .put("X25519PublicKey", KEY)
        val server = JSONObject()
            .put("ID", "s1")
            .put("Name", "NL-FREE#9")
            .put("Domain", "nl.example")
            .put("EntryIP", "9.9.9.9")
            .put("ProtocolEntries", JSONObject().put("WireGuardUDP", protocol))
        val logical = JSONObject()
            .put("ID", "id")
            .put("Name", "NL-FREE#9")
            .put("ExitCountry", "nl")
            .put("City", "Amsterdam")
            .put("Tier", 0)
            .put("Load", 12)
            .put("Status", 1)
            .put("Servers", JSONArray().put(server))
        val payload = JSONObject().put("LogicalServers", JSONArray().put(logical))

        val entry = Logicals.parse(payload).single().wireguardEntries.single()
        assertEquals("5.6.7.8", entry.endpointHost)
        assertEquals(listOf(443, 51820), entry.ports)
        assertEquals(443, entry.port)
        assertEquals(KEY, entry.x25519)
        assertEquals("NL", Logicals.parse(payload).single().exitCountry)
    }

    private companion object {
        const val KEY = "aGVsbG8gd29ybGQgdGhpcyBpcyBhIHRlc3Qga2V5ISE="
    }
}
