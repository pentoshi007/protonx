import json
import os

from .cache import CONFIG_DIR
from .service import ConnectOptions

PATH = os.path.join(CONFIG_DIR, "preferences.json")
STORED = ("paid", "p2p", "dns", "ssh_guard")


def load():
    try:
        with open(PATH) as handle:
            saved = json.load(handle)
    except (OSError, ValueError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    return ConnectOptions(**{key: bool(saved[key]) for key in STORED if key in saved})


def save(options):
    os.makedirs(os.path.dirname(PATH), mode=0o700, exist_ok=True)
    with open(PATH, "w") as handle:
        json.dump({key: getattr(options, key) for key in STORED}, handle, indent=2)
