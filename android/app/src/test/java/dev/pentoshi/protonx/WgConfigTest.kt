package dev.pentoshi.protonx

import dev.pentoshi.protonx.core.WgConfig
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class WgConfigTest {
    private val privateKey = "OJTupJxYCu+BaTV2K+BJVZ1tFEDe3hLmoSXxhB//jm8="
    private val publicKey = "RwHQhIhFH1RaQJ+1iuPlhYHKQKw/fxFGmM1x3qxzygE="

    @Test
    fun rendersTheSameProfileTheDesktopEngineUses() {
        val config = WgConfig.render(privateKey, publicKey, "89.39.107.113", 51820)
        assertEquals(
            """
            [Interface]
            PrivateKey = $privateKey
            Address = 10.2.0.2/32
            DNS = 10.2.0.1
            MTU = 1420

            [Peer]
            PublicKey = $publicKey
            AllowedIPs = 0.0.0.0/0
            Endpoint = 89.39.107.113:51820
            PersistentKeepalive = 25
            """.trimIndent() + "\n",
            config,
        )
    }

    @Test
    fun omitsDnsWhenDisabled() {
        val config = WgConfig.render(privateKey, publicKey, "1.2.3.4", 51820, dns = null)
        assertTrue(!config.contains("DNS"))
    }

    @Test
    fun rejectsKeysThatAreNot32Bytes() {
        val failure = runCatching { WgConfig.render("short", publicKey, "1.2.3.4", 51820) }.exceptionOrNull()
        assertTrue(failure?.message.orEmpty().contains("private key"))
    }
}
