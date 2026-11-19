import time

from . import cache, logicals, selection
from .countries import NAMES
from .errors import CatalogUnavailable


def _parse(payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("LogicalServers"), list):
        raise CatalogUnavailable("Proton did not return a valid server list.")
    try:
        return logicals.parse(payload)
    except (AttributeError, TypeError, ValueError) as error:
        raise CatalogUnavailable("The server list could not be read.") from error


def cached():
    try:
        saved = cache.load()
        return _parse(saved["payload"]), int(saved.get("fetchedAt", 0))
    except (KeyError, TypeError, OSError, ValueError, CatalogUnavailable) as error:
        raise CatalogUnavailable("No usable server list is stored on this machine. Refresh to download it.") from error


def live(client):
    payload = client.logicals()
    pool = _parse(payload)
    fetched_at = int(time.time())
    cache.save(payload, fetched_at)
    return pool, fetched_at


def free_snapshot(pool, fetched_at):
    grouped = {}
    for server in sorted(selection.eligible(pool), key=lambda item: (item.load, item.display_name())):
        grouped.setdefault(server.exit_country, []).append({
            "name": server.display_name(),
            "city": server.city,
            "load": max(0, min(100, server.load)),
        })
    countries = [
        {"code": code, "name": NAMES.get(code, code), "servers": rows}
        for code, rows in grouped.items()
    ]
    return {"fetchedAt": fetched_at, "countries": sorted(countries, key=lambda row: row["name"])}
