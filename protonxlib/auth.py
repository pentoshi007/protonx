import os

from . import keychain, login
from .api import Client
from .errors import ApiError, SessionExpired, SessionMissing

LEGACY_SERVICE = "ProtonVPN"
LEGACY_ACCOUNT = "authCredentials"


def _from_env():
    raw = os.environ.get("PROTONX_SESSION")
    if not raw:
        return None
    import json

    return json.loads(raw)


def load_session():
    from_env = _from_env()
    if from_env:
        return from_env
    session = login.current()
    if session:
        return session
    if keychain.exists(LEGACY_SERVICE, LEGACY_ACCOUNT):
        raise SessionMissing(
            "the Proton VPN app's keychain copy of the session is already stale, because the app "
            "keeps refreshed tokens in memory only. Sign in to ProtonX once instead."
        )
    raise SessionMissing("not signed in yet. Sign in once in ProtonX, then this works without asking again.")


def store(session):
    if os.environ.get("PROTONX_SESSION") is None:
        login.store(session)


def refresh_session(session):
    body = {
        "GrantType": "refresh_token",
        "ResponseType": "token",
        "RefreshToken": session.get("refreshToken", ""),
        "RedirectURI": "https://protonvpn.com",
    }
    try:
        data = Client(session).post("/auth/v4/refresh", body, authenticated=False)
    except ApiError as error:
        if error.status not in (400, 401, 403, 422):
            raise
        raise SessionExpired(
            f"the server rejected the stored session (HTTP {error.status}, code {error.code}: "
            f"{error.message}). Sign in again."
        ) from error
    updated = dict(session)
    updated["accessToken"] = data.get("AccessToken", session.get("accessToken"))
    if data.get("RefreshToken"):
        updated["refreshToken"] = data["RefreshToken"]
    store(updated)
    return updated


def make_client(session, persist=True):
    if not persist:
        return Client(session)
    return Client(session, refresh=lambda: refresh_session(session))


def verify(client):
    return client.client_config()


def logout(session=None):
    login.sign_out()
