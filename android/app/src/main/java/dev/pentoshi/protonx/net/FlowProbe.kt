package dev.pentoshi.protonx.net

import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.security.SecureRandom

/**
 * Proves the tunnel actually forwards packets. Proton's in-tunnel resolver only
 * answers when traffic crosses the WireGuard link, so a reply is real evidence
 * rather than "the interface exists".
 */
object FlowProbe {
    const val RESOLVER = "10.2.0.1"
    const val PROBE_NAME = "proton.me"
    const val HTTPS_PROBE = "https://proton.me/favicon.ico"
    const val TIMEOUT_MS = 3000

    fun reachesInternet(name: String = PROBE_NAME, resolver: String = RESOLVER, timeoutMs: Int = TIMEOUT_MS): Boolean =
        runCatching { dnsQuery(name, resolver, timeoutMs) }.getOrDefault(false)

    /**
     * Proton's in-tunnel resolver answers at connect time but can go quiet for a
     * healthy tunnel, so a live HTTPS fetch is the second, independent signal.
     */
    fun httpsReachable(timeoutMs: Int = 5000): Boolean = runCatching {
        val connection = (java.net.URL(HTTPS_PROBE).openConnection() as java.net.HttpURLConnection).apply {
            requestMethod = "GET"
            connectTimeout = timeoutMs
            readTimeout = timeoutMs
            instanceFollowRedirects = false
            useCaches = false
            setRequestProperty("User-Agent", "ProtonX")
        }
        try {
            connection.responseCode in 200..399
        } finally {
            connection.disconnect()
        }
    }.getOrDefault(false)

    /** Either channel proves the tunnel forwards packets. */
    fun healthy(): Boolean = reachesInternet() || httpsReachable()

    fun dnsQuery(name: String, resolver: String, timeoutMs: Int): Boolean {
        val identifier = SecureRandom().nextInt(0xFFFF)
        val query = query(name, identifier)
        DatagramSocket().use { socket ->
            socket.soTimeout = timeoutMs
            socket.connect(InetAddress.getByName(resolver), 53)
            socket.send(DatagramPacket(query, query.size))
            val buffer = ByteArray(512)
            val answer = DatagramPacket(buffer, buffer.size)
            socket.receive(answer)
            return answer.length >= 12 && ((buffer[0].toInt() and 0xFF) shl 8 or (buffer[1].toInt() and 0xFF)) == identifier
        }
    }

    fun query(name: String, identifier: Int): ByteArray {
        val out = ArrayList<Byte>(64)
        out.add((identifier shr 8 and 0xFF).toByte())
        out.add((identifier and 0xFF).toByte())
        listOf(0x01, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00).forEach { out.add(it.toByte()) }
        name.trim('.').split('.').forEach { label ->
            val bytes = label.toByteArray(Charsets.US_ASCII)
            out.add(bytes.size.toByte())
            bytes.forEach { out.add(it) }
        }
        out.add(0)
        listOf(0x00, 0x01, 0x00, 0x01).forEach { out.add(it.toByte()) }
        return out.toByteArray()
    }
}
