package dev.pentoshi.protonx.core

import at.favre.lib.crypto.bcrypt.BCrypt
import java.math.BigInteger
import java.security.MessageDigest
import java.security.SecureRandom
import java.util.Base64

class SrpException(message: String) : Exception(message)

data class Proofs(
    val clientEphemeral: ByteArray,
    val clientProof: ByteArray,
    val serverProof: ByteArray,
    val sharedSecret: ByteArray,
)

/**
 * Proton's SRP-6a variant: 2048-bit modulus, little-endian arithmetic, and a
 * bcrypt password hash whose salt is the account salt with "proton" appended
 * (Proton's salt is 10 bytes, which makes exactly a 16-byte bcrypt salt).
 */
object Srp {
    const val BYTE_LENGTH = 256
    private const val GENERATOR = 2
    private val MIN_SECRET = BigInteger.ONE.shiftLeft(512)
    private const val SALT_SUFFIX = "proton"
    private const val SIGNATURE = "-----BEGIN PGP SIGNATURE-----"
    private const val HASH_HEADER = "Hash: SHA256"

    fun expandHash(data: ByteArray): ByteArray {
        val digest = MessageDigest.getInstance("SHA-512")
        val out = ByteArray(BYTE_LENGTH)
        for (index in 0 until 4) {
            digest.reset()
            digest.update(data)
            digest.update(index.toByte())
            System.arraycopy(digest.digest(), 0, out, index * 64, 64)
        }
        return out
    }

    fun bcryptDigest(password: String, salt: ByteArray): ByteArray {
        val bcryptSalt = salt + SALT_SUFFIX.toByteArray(Charsets.US_ASCII)
        return BCrypt.with(BCrypt.Version.VERSION_2Y).hash(10, bcryptSalt, password.toByteArray(Charsets.UTF_8))
    }

    fun hashPassword(password: String, salt: ByteArray, modulus: ByteArray): ByteArray {
        return expandHash(bcryptDigest(password, salt) + modulus)
    }

    fun cleartextModulus(signedMessage: String): ByteArray {
        val lines = signedMessage.trim().lines()
        val start = lines.indexOf(HASH_HEADER)
        val end = lines.indexOf(SIGNATURE)
        if (start < 0 || end < 0 || end <= start + 2) {
            throw SrpException("server modulus is not a clear-signed OpenPGP message")
        }
        val body = lines.subList(start + 2, end).joinToString("").trim()
        if (body.isEmpty()) throw SrpException("server modulus is empty")
        return Base64.getDecoder().decode(body)
    }

    fun generateProofs(
        password: String,
        salt: ByteArray,
        modulus: ByteArray,
        serverEphemeral: ByteArray,
        secret: BigInteger? = null,
    ): Proofs {
        val modulusInt = leInt(modulus)
        val serverInt = leInt(serverEphemeral)
        validate(modulusInt, serverInt)

        val hashed = leInt(hashPassword(password, salt, modulus))
        val secretInt = secret ?: randomSecret(modulusInt)
        val generator = BigInteger.valueOf(GENERATOR.toLong())
        val ephemeral = leBytes(generator.modPow(secretInt, modulusInt))

        val scramble = leInt(expandHash(ephemeral + serverEphemeral))
        val multiplier = leInt(expandHash(leBytes(generator) + leBytes(modulusInt))).mod(modulusInt)
        val base = (serverInt - multiplier.multiply(generator.modPow(hashed, modulusInt))).mod(modulusInt)
        val exponent = scramble.multiply(hashed).add(secretInt).mod(modulusInt.subtract(BigInteger.ONE))
        val shared = leBytes(base.modPow(exponent, modulusInt))

        val proof = expandHash(ephemeral + serverEphemeral + shared)
        return Proofs(
            clientEphemeral = ephemeral,
            clientProof = proof,
            serverProof = expandHash(ephemeral + proof + shared),
            sharedSecret = shared,
        )
    }

    private fun validate(modulus: BigInteger, serverEphemeral: BigInteger) {
        if (modulus.bitLength() != BYTE_LENGTH * 8) {
            throw SrpException("server modulus is ${modulus.bitLength()} bits, expected ${BYTE_LENGTH * 8}")
        }
        if (serverEphemeral <= BigInteger.ONE || serverEphemeral >= modulus.subtract(BigInteger.ONE)) {
            throw SrpException("server ephemeral is out of range")
        }
    }

    private fun randomSecret(modulus: BigInteger): BigInteger {
        val random = SecureRandom()
        while (true) {
            val candidate = BigInteger(BYTE_LENGTH * 8, random)
            if (candidate > MIN_SECRET && candidate < modulus.subtract(BigInteger.ONE)) return candidate
        }
    }

    fun leInt(data: ByteArray): BigInteger {
        val reversed = data.reversedArray()
        return BigInteger(1, reversed)
    }

    fun leBytes(value: BigInteger): ByteArray {
        val raw = value.toByteArray()
        val magnitude = if (raw.size > 1 && raw[0] == 0.toByte()) raw.copyOfRange(1, raw.size) else raw
        if (magnitude.size > BYTE_LENGTH) throw SrpException("value does not fit in $BYTE_LENGTH bytes")
        val out = ByteArray(BYTE_LENGTH)
        for (index in magnitude.indices) {
            out[index] = magnitude[magnitude.size - 1 - index]
        }
        return out
    }
}
