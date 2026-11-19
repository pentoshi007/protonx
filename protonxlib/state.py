import json
import os

from .cache import CONFIG_DIR

STATE_PATH = os.path.join(CONFIG_DIR, "last.json")


def save(record):
    os.makedirs(CONFIG_DIR, mode=0o700, exist_ok=True)
    with open(STATE_PATH, "w") as handle:
        json.dump(record, handle, indent=2)
    os.chmod(STATE_PATH, 0o600)
    return STATE_PATH


def load():
    try:
        with open(STATE_PATH) as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return None


def clear():
    if os.path.exists(STATE_PATH):
        os.unlink(STATE_PATH)
