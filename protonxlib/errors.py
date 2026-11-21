class ProtonxError(RuntimeError):
    pass


# A tunnel can finish its handshake and still carry nothing when the server
# will not accept the client key. Connect uses this marker to rotate the key
# instead of reporting a dead tunnel as connected.
NO_TRAFFIC = "the tunnel is not carrying traffic"


class SessionMissing(ProtonxError):
    pass


class SessionExpired(ProtonxError):
    pass


class ApiError(ProtonxError):
    def __init__(self, status, code, message):
        self.status = status
        self.code = code
        self.message = message
        super().__init__(f"HTTP {status} code {code}: {message}")


class CatalogUnavailable(ProtonxError):
    pass


class SelectionError(ProtonxError):
    pass


class TunnelError(ProtonxError):
    pass
