package dev.pentoshi.protonx.core

import java.util.Base64

object WgConfig {
    const val DEFAULT_DNS = "10.2.0.1"
    const val DEFAULT_MTU = 1420
    const val ADDRESS = "10.2.0.2/32"
    const val ALLOWED_IPS = "0.0.0.0/0"
    const val KEEPALIVE = 25

    fun render(
        privateKey: String,
        peerPublicKey: String,
        endpointHost: String,
        endpointPort: Int,
        dns: String? = DEFAULT_DNS,
        mtu: Int = DEFAULT_MTU,
        keepalive: Int = KEEPALIVE,
    ): String {
        requireKey(privateKey, "private key")
        requireKey(peerPublicKey, "peer public key")
        require(endpointHost.isNotBlank()) { "endpoint host is empty" }
        require(endpointPort in 1..65535) { "endpoint port is out of range" }

        val lines = mutableListOf("[Interface]", "PrivateKey = $privateKey", "Address = $ADDRESS")
        if (!dns.isNullOrBlank()) lines += "DNS = $dns"
        lines += "MTU = $mtu"
        lines += ""
        lines += "[Peer]"
        lines += "PublicKey = $peerPublicKey"
        lines += "AllowedIPs = $ALLOWED_IPS"
        lines += "Endpoint = $endpointHost:$endpointPort"
        if (keepalive > 0) lines += "PersistentKeepalive = $keepalive"
        return lines.joinToString("\n", postfix = "\n")
    }

    fun requireKey(value: String, field: String) {
        val raw = runCatching { Base64.getDecoder().decode(value) }.getOrNull()
        require(value.length == 44 && raw != null && raw.size == 32) { "$field is not a 32-byte base64 key" }
    }
}
