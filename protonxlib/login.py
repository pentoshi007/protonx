import base64
from urllib.error import URLError

from . import api, credentials, srp
from .errors import ProtonxError, SessionMissing

SERVICE = "protonx"
SESSION_ACCOUNT = "session"
PENDING_ACCOUNT = "pending"
VPN_SCOPE = "vpn"


def store(session):
    credentials.write_json(SERVICE, SESSION_ACCOUNT, session)
    credentials.delete(SERVICE, PENDING_ACCOUNT)


def _session_from(result, username):
    return {
        "userId": result.get("UID"),
        "accessToken": result.get("AccessToken"),
        "refreshToken": result.get("RefreshToken"),
        "scopes": (result.get("Scope") or "").split(),
        "username": username,
    }


def _needs_two_factor(result):
    return bool((result.get("TwoFactor") or {}).get("Enabled"))


def challenge(username, password):
    carrier = api.create_session()
    info = api.auth_post("/auth/v4/info", {"Username": username, "Intent": "Proton"}, session=carrier)
    salt = base64.b64decode(info["Salt"])
    modulus = srp.cleartext_modulus(info["Modulus"])
    server_ephemeral = base64.b64decode(info["ServerEphemeral"])
    proofs = srp.generate_proofs(password, salt, modulus, server_ephemeral)
    body = {
        "Username": username,
        "ClientEphemeral": base64.b64encode(proofs.client_ephemeral).decode(),
        "ClientProof": base64.b64encode(proofs.client_proof).decode(),
        "SRPSession": info["SRPSession"],
        "Payload": {},
    }
    result = api.auth_post("/auth/v4", body, session=carrier)
    expected = base64.b64encode(proofs.expected_server_proof).decode()
    if result.get("ServerProof") and result["ServerProof"] != expected:
        raise ProtonxError("server could not prove it knows the password hash; login aborted")
    return result


def _submit_two_factor(session, code):
    result = api.auth_post("/auth/v4/2fa", {"TwoFactorCode": code}, session=session)
    session["scopes"] = (result.get("Scope") or " ".join(session.get("scopes", []))).split()
    return session


def sign_in(username, password, code=None):
    result = challenge(username, password)
    session = _session_from(result, username)
    if _needs_two_factor(result) and not code:
        credentials.write_json(SERVICE, PENDING_ACCOUNT, session)
        return {"status": "two-factor", "username": username}
    if code:
        session = _submit_two_factor(session, code)
    store(session)
    return {"status": "signed-in", "username": username, "scopes": session["scopes"]}


def finish_two_factor(code):
    try:
        session = credentials.read_json(SERVICE, PENDING_ACCOUNT)
    except SessionMissing as error:
        raise SessionMissing("no sign-in waiting for a two-factor code; start over") from error
    session = _submit_two_factor(session, code)
    store(session)
    return {"status": "signed-in", "username": session.get("username"), "scopes": session["scopes"]}


def current():
    try:
        session = credentials.read_json(SERVICE, SESSION_ACCOUNT)
    except SessionMissing:
        return None
    return session if session.get("accessToken") else None


def pending():
    try:
        return credentials.read_json(SERVICE, PENDING_ACCOUNT)
    except SessionMissing:
        return None


def sign_out():
    session = current()
    credentials.delete(SERVICE, SESSION_ACCOUNT)
    credentials.delete(SERVICE, PENDING_ACCOUNT)
    if current() or pending():
        raise ProtonxError("Could not remove the local ProtonX session.")
    if not session:
        return
    try:
        api.auth_post("/core/v4/auth", None, session=session, method="DELETE", timeout=4)
    except (ProtonxError, URLError, TimeoutError):
        pass
