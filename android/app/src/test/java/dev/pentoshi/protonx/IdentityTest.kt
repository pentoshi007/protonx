package dev.pentoshi.protonx

import dev.pentoshi.protonx.core.Identity
import org.junit.Assert.assertEquals
import org.junit.Test
import java.util.Base64

class IdentityTest {
    private val seed = ByteArray(32) { it.toByte() }

    @Test
    fun derivationMatchesTheDesktopEngine() {
        val identity = Identity.derive(seed)
        assertEquals("AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8=", Base64.getEncoder().encodeToString(identity.seed))
        assertEquals("A6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg=", identity.ed25519PublicKey)
        assertEquals("OJTupJxYCu+BaTV2K+BJVZ1tFEDe3hLmoSXxhB//jm8=", identity.x25519PrivateKey)
        assertEquals("RwHQhIhFH1RaQJ+1iuPlhYHKQKw/fxFGmM1x3qxzygE=", identity.x25519PublicKey)
    }

    @Test
    fun aStoredSeedRoundTrips() {
        val restored = Identity.fromSeed(Base64.getEncoder().encodeToString(seed))
        assertEquals(Identity.derive(seed).ed25519PublicKey, restored?.ed25519PublicKey)
    }

    @Test
    fun badSeedsAreRejected() {
        assertEquals(null, Identity.fromSeed("not-base64"))
        assertEquals(null, Identity.fromSeed(Base64.getEncoder().encodeToString(ByteArray(31))))
    }
}
