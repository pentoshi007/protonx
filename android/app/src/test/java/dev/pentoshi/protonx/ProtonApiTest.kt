package dev.pentoshi.protonx

import dev.pentoshi.protonx.core.HttpRequest
import dev.pentoshi.protonx.core.HttpResponse
import dev.pentoshi.protonx.core.KeyConflict
import dev.pentoshi.protonx.core.ProtonApi
import dev.pentoshi.protonx.core.Session
import dev.pentoshi.protonx.core.SignInOutcome
import dev.pentoshi.protonx.core.Transport
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.Base64

class ProtonApiTest {
    private val vectors: JSONObject = javaClass.getResourceAsStream("/srp-vectors.json")!!
        .bufferedReader().use { JSONObject(it.readText()) }

    private var session = Session(userId = "uid", accessToken = "old", refreshToken = "refresh", username = "user")
    private val requests = mutableListOf<HttpRequest>()

    private fun api(responses: (HttpRequest) -> HttpResponse): ProtonApi =
        ProtonApi(
            transport = Transport { request ->
                requests += request
                responses(request)
            },
            sessionProvider = { session },
            sessionSaver = { session = it },
        )

    @Test
    fun anExpiredTokenIsRefreshedOnceAndTheRequestIsRetried() {
        var logicalCalls = 0
        val api = api { request ->
            when {
                request.url.contains("/auth/v4/refresh") ->
                    HttpResponse(200, """{"Code":1000,"AccessToken":"new","RefreshToken":"newr"}""")
                request.url.contains("/vpn/v1/logicals") && logicalCalls++ == 0 ->
                    HttpResponse(401, """{"Code":401,"Error":"Unauthorized"}""")
                request.url.contains("/vpn/v1/logicals") ->
                    HttpResponse(200, """{"Code":1000,"LogicalServers":[]}""")
                else -> HttpResponse(500, "{}")
            }
        }
        api.logicals()
        assertEquals("new", session.accessToken)
        assertEquals("newr", session.refreshToken)
        assertEquals(3, requests.size)
        assertEquals("Bearer new", requests.last().headers["Authorization"])
    }

    @Test
    fun theLogicalsRequestAsksForWireGuardEntries() {
        val api = api { HttpResponse(200, """{"Code":1000,"LogicalServers":[]}""") }
        api.logicals()
        assertTrue(requests.single().url.contains("WithEntriesForProtocols=WireGuardUDP"))
        assertEquals("macos-vpn@4.5.0", requests.single().headers["x-pm-appversion"])
    }

    @Test
    fun aFingerprintConflictIsReportedSoTheKeyCanRotate() {
        val api = api { HttpResponse(409, """{"Code":2500,"Error":"ClientPublicKey fingerprint conflict"}""") }
        val failure = runCatching { api.registerKey(KEY) }.exceptionOrNull()
        assertTrue(failure is KeyConflict)
    }

    @Test
    fun theCertificateRequestCarriesTheDeviceKey() {
        val api = api { HttpResponse(200, """{"Code":1000,"ExpirationTime":1}""") }
        api.registerKey(KEY)
        val body = JSONObject(requests.single().body!!.toString(Charsets.UTF_8))
        assertEquals(KEY, body.getString("ClientPublicKey"))
        assertEquals("session", body.getString("Mode"))
        assertEquals("1 day", body.getString("Duration"))
        assertEquals("POST", requests.single().method)
    }

    @Test
    fun signInCompletesTheSrpExchange() {
        val api = api { request ->
            when {
                request.url.endsWith("/auth/v4/sessions") ->
                    HttpResponse(200, """{"Code":1000,"UID":"uid","AccessToken":"carrier"}""")
                request.url.endsWith("/auth/v4/info") -> HttpResponse(200, infoBody)
                request.url.endsWith("/auth/v4") ->
                    HttpResponse(200, """{"Code":1000,"UID":"uid","AccessToken":"at","RefreshToken":"rt","Scope":"vpn"}""")
                else -> HttpResponse(500, "{}")
            }
        }
        val outcome = api.signIn("user", "password")
        assertTrue(outcome is SignInOutcome.SignedIn)
        assertEquals("at", session.accessToken)

        val srpBody = JSONObject(requests.first { it.url.endsWith("/auth/v4") }.body!!.toString(Charsets.UTF_8))
        assertEquals("s", srpBody.getString("SRPSession"))
        assertEquals(256, Base64.getDecoder().decode(srpBody.getString("ClientEphemeral")).size)
        assertEquals(256, Base64.getDecoder().decode(srpBody.getString("ClientProof")).size)
    }

    @Test
    fun twoFactorEnabledIsReportedInsteadOfSilentlySigningIn() {
        val api = api { request ->
            when {
                request.url.endsWith("/auth/v4/sessions") ->
                    HttpResponse(200, """{"Code":1000,"UID":"uid","AccessToken":"carrier"}""")
                request.url.endsWith("/auth/v4/info") -> HttpResponse(200, infoBody)
                else -> HttpResponse(200, """{"Code":1000,"UID":"uid","AccessToken":"at","TwoFactor":{"Enabled":1}}""")
            }
        }
        assertTrue(api.signIn("user", "password") is SignInOutcome.NeedsCode)
    }

    private val infoBody: String
        get() = """
            {"Code":1000,"SRPSession":"s","Salt":"${vectors.getString("salt")}",
             "Modulus":"-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\n${vectors.getString("modulus")}\n-----BEGIN PGP SIGNATURE-----\nabc\n-----END PGP SIGNATURE-----",
             "ServerEphemeral":"${vectors.getString("serverEphemeral")}"}
        """.trimIndent()

    private companion object {
        const val KEY = "A6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg="
    }
}
