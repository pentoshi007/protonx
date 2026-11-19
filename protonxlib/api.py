import json
import ssl
import urllib.error
import urllib.parse
import urllib.request

from .errors import ApiError, ProtonxError, SessionExpired

BASE_URL = "https://vpn-api.proton.me"
AUTH_BASE = "https://mail-api.proton.me"
APP_VERSION = "macos-vpn@4.5.0"
AUTH_APP_VERSION = "android-mail@3.0.12"
USER_AGENT = "ProtonVPN/4.5.0 (macOS)"
ACCEPT = "application/vnd.protonmail.v1+json"


def _ca_file():
    try:
        import certifi

        return certifi.where()
    except ImportError:
        return "/etc/ssl/cert.pem"


SSL_CONTEXT = ssl.create_default_context(cafile=_ca_file())


def _decode(payload):
    if not payload:
        return {}
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return {"Error": payload.decode(errors="replace")}


def _raise_for_code(status, data):
    code = data.get("Code")
    if status == 200 and code in (None, 1000, 1001):
        return
    message = data.get("Error") or data.get("Details") or "request failed"
    if status == 401:
        raise SessionExpired(f"{message} (code {code})")
    raise ApiError(status, code, message)


class Client:
    def __init__(self, session, refresh=None):
        self.session = session
        self._refresh = refresh

    def _headers(self, authenticated):
        headers = {
            "x-pm-appversion": APP_VERSION,
            "x-pm-uid": self.session.get("userId", ""),
            "Accept": ACCEPT,
            "User-Agent": USER_AGENT,
        }
        if authenticated:
            headers["Authorization"] = f"Bearer {self.session.get('accessToken', '')}"
        return headers

    def request(self, method, path, params=None, body=None, authenticated=True, retry=True):
        url = BASE_URL + path
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        data = json.dumps(body).encode() if body is not None else None
        headers = self._headers(authenticated)
        if data:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30, context=SSL_CONTEXT) as response:
                payload = _decode(response.read())
                _raise_for_code(response.status, payload)
                return payload
        except urllib.error.HTTPError as error:
            payload = _decode(error.read())
            if error.code == 401 and retry and authenticated and self._refresh:
                self.session = self._refresh()
                return self.request(method, path, params, body, authenticated, retry=False)
            _raise_for_code(error.code, payload)
            raise ApiError(error.code, payload.get("Code"), "request failed")

    def get(self, path, params=None):
        return self.request("GET", path, params=params)

    def post(self, path, body, authenticated=True):
        return self.request("POST", path, body=body, authenticated=authenticated)

    def logicals(self, protocols=("WireGuardUDP",)):
        return self.get(
            "/vpn/v1/logicals",
            {"WithEntriesForProtocols": ",".join(protocols), "WithState": "true"},
        )

    def client_config(self):
        return self.get("/vpn/v2/clientconfig")

    def register_key(self, public_key_b64, mode="session"):
        return self.post(
            "/vpn/v1/certificate",
            {"ClientPublicKey": public_key_b64, "Mode": mode, "Duration": "1 day"},
        )


def _raise_auth_error(status, payload):
    code = payload.get("Code")
    if code == 9001:
        raise ProtonxError(
            "Proton asked for a human-verification check for this sign-in. Open "
            "account.proton.me in a browser, sign in there once, then try again here."
        )
    raise ApiError(status, code, payload.get("Error") or "request failed")


def auth_post(path, body, session=None, method="POST", app_version=APP_VERSION, timeout=30):
    headers = {
        "x-pm-appversion": app_version,
        "Accept": ACCEPT,
        "User-Agent": USER_AGENT,
        "Content-Type": "application/json",
    }
    if session:
        headers["x-pm-uid"] = session.get("userId", "")
        headers["Authorization"] = "Bearer " + session.get("accessToken", "")
    payload_data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(AUTH_BASE + path, data=payload_data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=SSL_CONTEXT) as response:
            payload = _decode(response.read())
    except urllib.error.HTTPError as error:
        _raise_auth_error(error.code, _decode(error.read()))
        raise
    if payload.get("Code") not in (None, 1000, 1001):
        _raise_auth_error(200, payload)
    return payload


def create_session():
    created = auth_post("/auth/v4/sessions", {})
    return {"userId": created.get("UID"), "accessToken": created.get("AccessToken")}
