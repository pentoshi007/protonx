package dev.pentoshi.protonx.core

import org.bouncycastle.crypto.params.Ed25519PrivateKeyParameters
import org.bouncycastle.crypto.params.X25519PrivateKeyParameters
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64

/**
 * Proton binds a device key to the account certificate. The Ed25519 key is the
 * identity Proton knows; the X25519 key is the WireGuard private key derived
 * from the same seed the way the desktop engine derives it.
 */
data class Identity(
    val seed: ByteArray,
    val ed25519PublicKey: String,
    val x25519PrivateKey: String,
    val x25519PublicKey: String,
) {
    val seedBase64: String get() = Base64.getEncoder().encodeToString(seed)

    companion object {
        fun create(random: SecureRandom = SecureRandom()): Identity {
            val seed = ByteArray(32)
            random.nextBytes(seed)
            return derive(seed)
        }

        fun derive(seed: ByteArray): Identity {
            require(seed.size == 32) { "seed must be 32 bytes" }
            val edPublic = Ed25519PrivateKeyParameters(seed, 0).generatePublicKey().encoded

            val digest = MessageDigest.getInstance("SHA-512").digest(seed).copyOf(32)
            digest[0] = (digest[0].toInt() and 248).toByte()
            digest[31] = (digest[31].toInt() and 127).toByte()
            digest[31] = (digest[31].toInt() or 64).toByte()
            val xPublic = X25519PrivateKeyParameters(digest, 0).generatePublicKey().encoded

            val encoder = Base64.getEncoder()
            return Identity(
                seed = seed,
                ed25519PublicKey = encoder.encodeToString(edPublic),
                x25519PrivateKey = encoder.encodeToString(digest),
                x25519PublicKey = encoder.encodeToString(xPublic),
            )
        }

        fun fromSeed(seedBase64: String): Identity? = runCatching {
            val seed = Base64.getDecoder().decode(seedBase64)
            if (seed.size != 32) null else derive(seed)
        }.getOrNull()
    }
}
