package dev.pentoshi.protonx.core

import org.json.JSONObject
import java.util.Base64

class ApiException(val status: Int, val code: Int?, message: String) : Exception(message)
class SessionExpired(message: String = "Sign in to Proton again.") : Exception(message)
class KeyConflict(message: String) : Exception(message)
class HumanVerification(message: String) : Exception(message)
class ClientVersionRefused(message: String) : Exception(message)

sealed interface SignInOutcome {
    data class SignedIn(val session: Session) : SignInOutcome
    data class NeedsCode(val session: Session) : SignInOutcome
}

/**
 * The VPN API and the account API live on different hosts, but Proton gates the
 * auth routes on the client version, so both send the single version the desktop
 * engine is proven to be accepted with.
 */
class ProtonApi(
    private val transport: Transport = UrlConnectionTransport(),
    private val sessionProvider: () -> Session?,
    private val sessionSaver: (Session) -> Unit,
) {
    fun logicals(): JSONObject = authenticated(VPN_BASE, "/vpn/v1/logicals", LOGICAL_PARAMS, null, "GET")

    fun clientConfig(): JSONObject = authenticated(VPN_BASE, "/vpn/v2/clientconfig", emptyMap(), null, "GET")

    fun registerKey(publicKeyBase64: String): JSONObject = authenticated(
        VPN_BASE,
        "/vpn/v1/certificate",
        emptyMap(),
        JSONObject()
            .put("ClientPublicKey", publicKeyBase64)
            .put("Mode", "session")
            .put("Duration", "1 day"),
        "POST",
    )

    fun refreshSession(): Session {
        val current = sessionProvider() ?: throw SessionExpired()
        val response = transport.execute(
            authRequest(
                "/auth/v4/refresh",
                JSONObject()
                    .put("GrantType", "refresh_token")
                    .put("ResponseType", "token")
                    .put("RefreshToken", current.refreshToken)
                    .put("RedirectURI", "https://protonvpn.com"),
                null,
                "POST",
            ),
        )
        val payload = decode(response)
        if (response.status !in 200..299) {
            throw SessionExpired("Proton rejected the stored session (HTTP ${response.status}). Sign in again.")
        }
        val updated = current.copy(
            accessToken = Json.text(payload, "AccessToken").ifBlank { current.accessToken },
            refreshToken = Json.text(payload, "RefreshToken").ifBlank { current.refreshToken },
        )
        sessionSaver(updated)
        return updated
    }

    fun createSession(): Session {
        val payload = authPost("/auth/v4/sessions", JSONObject(), null)
        return Session(userId = Json.text(payload, "UID"), accessToken = Json.text(payload, "AccessToken"))
    }

    fun signIn(username: String, password: String): SignInOutcome {
        val carrier = createSession()
        val info = authPost(
            "/auth/v4/info",
            JSONObject().put("Username", username).put("Intent", "Proton"),
            carrier,
        )
        val salt = Base64.getDecoder().decode(Json.text(info, "Salt"))
        val modulus = Srp.cleartextModulus(Json.text(info, "Modulus"))
        val serverEphemeral = Base64.getDecoder().decode(Json.text(info, "ServerEphemeral"))
        val proofs = Srp.generateProofs(password, salt, modulus, serverEphemeral)
        val encoder = Base64.getEncoder()

        val result = authPost(
            "/auth/v4",
            JSONObject()
                .put("Username", username)
                .put("ClientEphemeral", encoder.encodeToString(proofs.clientEphemeral))
                .put("ClientProof", encoder.encodeToString(proofs.clientProof))
                .put("SRPSession", Json.text(info, "SRPSession"))
                .put("Payload", JSONObject()),
            carrier,
        )
        val expected = encoder.encodeToString(proofs.serverProof)
        val actual = Json.text(result, "ServerProof")
        if (actual.isNotEmpty() && actual != expected) {
            throw SrpException("server could not prove it knows the password hash; login aborted")
        }

        val session = Session.fromAuth(result, username)
        val twoFactor = result.optJSONObject("TwoFactor")
        if (twoFactor != null && Json.flag(twoFactor, "Enabled")) {
            return SignInOutcome.NeedsCode(session)
        }
        sessionSaver(session)
        return SignInOutcome.SignedIn(session)
    }

    fun finishTwoFactor(session: Session, code: String): Session {
        val payload = authPost("/auth/v4/2fa", JSONObject().put("TwoFactorCode", code), session)
        val scopes = Json.text(payload, "Scope").ifBlank { session.scopes.joinToString(" ") }
        val updated = session.copy(scopes = scopes.split(" ").filter { it.isNotBlank() })
        sessionSaver(updated)
        return updated
    }

    fun authPost(path: String, body: JSONObject, session: Session?): JSONObject {
        val response = transport.execute(authRequest(path, body, session, "POST"))
        val payload = decode(response)
        if (response.status == 401) throw SessionExpired()
        if (response.status !in 200..299) {
            val code = if (payload.has("Code")) payload.optInt("Code") else null
            if (code == HUMAN_VERIFICATION) {
                throw HumanVerification(
                    "Proton asked for a human-verification check. Open account.proton.me in a browser, " +
                        "sign in there once, then try again here.",
                )
            }
            if (code == REFUSED_CLIENT_VERSION || code == RETIRED_CLIENT_VERSION) {
                throw ClientVersionRefused(versionRefusedMessage(code))
            }
            throw ApiException(response.status, code, Json.text(payload, "Error").ifBlank { "request failed" })
        }
        return payload
    }

    private fun authenticated(
        base: String,
        path: String,
        params: Map<String, String>,
        body: JSONObject?,
        method: String,
    ): JSONObject {
        val current = sessionProvider() ?: throw SessionExpired()
        var response = transport.execute(vpnRequest(base, path, params, body, method, current))
        if (response.status == 401) {
            val fresh = refreshSession()
            response = transport.execute(vpnRequest(base, path, params, body, method, fresh))
        }
        val payload = decode(response)
        val code = if (payload.has("Code")) payload.optInt("Code") else null
        val ok = response.status == 200 && (code == null || code == 1000 || code == 1001)
        if (ok) return payload
        if (response.status == 409 && code == KEY_FINGERPRINT_CONFLICT) {
            throw KeyConflict(Json.text(payload, "Error"))
        }
        if (response.status == 401) throw SessionExpired()
        if (code == REFUSED_CLIENT_VERSION || code == RETIRED_CLIENT_VERSION) {
            throw ClientVersionRefused(versionRefusedMessage(code))
        }
        throw ApiException(
            response.status,
            code,
            Json.text(payload, "Error").ifBlank { Json.text(payload, "Details").ifBlank { "request failed" } },
        )
    }

    private fun vpnRequest(
        base: String,
        path: String,
        params: Map<String, String>,
        body: JSONObject?,
        method: String,
        session: Session,
    ): HttpRequest = HttpRequest(
        method = method,
        url = buildUrl(base, path, params),
        headers = mapOf(
            "x-pm-appversion" to VPN_APP_VERSION,
            "x-pm-uid" to session.userId,
            "Authorization" to "Bearer ${session.accessToken}",
            "Accept" to ACCEPT,
            "User-Agent" to USER_AGENT,
        ) + if (body != null) mapOf("Content-Type" to "application/json") else emptyMap(),
        body = body?.toString()?.toByteArray(Charsets.UTF_8),
    )

    private fun authRequest(path: String, body: JSONObject, session: Session?, method: String): HttpRequest {
        val headers = mutableMapOf(
            "x-pm-appversion" to AUTH_APP_VERSION,
            "Accept" to ACCEPT,
            "User-Agent" to USER_AGENT,
        )
        if (session != null) {
            headers["x-pm-uid"] = session.userId
            headers["Authorization"] = "Bearer ${session.accessToken}"
        }
        if (body.length() > 0) headers["Content-Type"] = "application/json"
        return HttpRequest(
            method = method,
            url = AUTH_BASE + path,
            headers = headers,
            body = if (body.length() > 0) body.toString().toByteArray(Charsets.UTF_8) else null,
        )
    }

    private fun decode(response: HttpResponse): JSONObject =
        runCatching { JSONObject(response.body) }.getOrElse { JSONObject().put("Error", response.body) }

    companion object {
        const val VPN_BASE = "https://vpn-api.proton.me"
        const val AUTH_BASE = "https://mail-api.proton.me"
        const val VPN_APP_VERSION = "macos-vpn@4.5.0"

        /**
         * Proton retires client versions on the auth routes; the retired android-mail@3.0.12
         * made every sign-in fail with 8004 "Operation not allowed". Derived from the engine
         * version so the two cannot drift, and re-checked with:
         *   curl -s -X POST https://mail-api.proton.me/auth/v4/sessions \
         *     -H 'content-type: application/json' -H 'x-pm-appversion: <version>' -d '{}'
         */
        const val AUTH_APP_VERSION = VPN_APP_VERSION
        const val USER_AGENT = "ProtonVPN/4.5.0 (macOS)"
        const val ACCEPT = "application/vnd.protonmail.v1+json"
        const val KEY_FINGERPRINT_CONFLICT = 2500
        const val HUMAN_VERIFICATION = 9001
        const val REFUSED_CLIENT_VERSION = 8004
        const val RETIRED_CLIENT_VERSION = 5003
        val LOGICAL_PARAMS = mapOf("WithEntriesForProtocols" to "WireGuardUDP", "WithState" to "true")

        private fun versionRefusedMessage(code: Int): String =
            "Proton no longer accepts this app's client version (code $code). " +
                "Install the latest ProtonX release from github.com/pentoshi007/protonx/releases."
    }
}
