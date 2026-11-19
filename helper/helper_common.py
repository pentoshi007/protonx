import os
import shutil
import subprocess

TOOL_PATH = "/opt/homebrew/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
COMMAND_TIMEOUT = 12


class HelperError(Exception):
    pass


def tool(name):
    found = shutil.which(name, path=TOOL_PATH)
    if not found:
        raise HelperError("%s is not installed" % name)
    return found


def run(args, check=True):
    try:
        result = subprocess.run(
            args, capture_output=True, text=True, env={"PATH": TOOL_PATH}, timeout=COMMAND_TIMEOUT
        )
    except subprocess.TimeoutExpired as error:
        raise HelperError("%s timed out" % os.path.basename(args[0])) from error
    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise HelperError("%s failed: %s" % (args[0], detail))
    return result


def write_private(path, text):
    temporary = path + ".new"
    with open(temporary, "w") as handle:
        handle.write(text)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
