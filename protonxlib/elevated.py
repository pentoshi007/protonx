"""Elevated half of a Windows tunnel operation, started by elevate.run.

Reads the request the unprivileged CLI wrote, performs the privileged work and
writes the reply back. Nothing is read from stdin and nothing is printed: the
process runs behind the UAC prompt with its console hidden.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.realpath(__file__))))

from protonxlib import tunnel_windows


def _reply(path, payload):
    with open(path, "w") as handle:
        json.dump(payload, handle)


def main(argv):
    if len(argv) != 3:
        return 2
    request_path, reply_path = argv[1], argv[2]
    try:
        with open(request_path) as handle:
            request = json.load(handle)
        result = tunnel_windows.run_local(request.get("operation"), request.get("payload"))
        answer = {"ok": True, "result": result}
    except Exception as error:  # every failure has to reach the waiting parent
        answer = {"ok": False, "error": str(error) or error.__class__.__name__}
    try:
        _reply(reply_path, answer)
    except OSError:
        return 1
    return 0 if answer["ok"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
