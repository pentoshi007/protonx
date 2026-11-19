import json
import os
import tempfile
import time

CONFIG_DIR = os.path.expanduser("~/.config/protonx")
CACHE_PATH = os.path.join(CONFIG_DIR, "logicals.json")
DEFAULT_TTL = 600


def save(payload, fetched_at=None):
    if fetched_at is None:
        fetched_at = int(time.time())
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=CONFIG_DIR, delete=False) as handle:
        temporary = handle.name
        try:
            json.dump({"fetchedAt": fetched_at, "payload": payload}, handle, separators=(",", ":"))
            handle.close()
            os.replace(temporary, CACHE_PATH)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return CACHE_PATH


def load():
    with open(CACHE_PATH) as handle:
        return json.load(handle)


def fresh(ttl=DEFAULT_TTL):
    try:
        cached = load()
    except (OSError, json.JSONDecodeError):
        return None
    if int(time.time()) - int(cached.get("fetchedAt", 0)) > ttl:
        return None
    return cached.get("payload")


def cached_at():
    try:
        return int(load().get("fetchedAt", 0))
    except (OSError, json.JSONDecodeError):
        return 0
