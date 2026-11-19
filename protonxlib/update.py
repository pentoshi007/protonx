import hashlib
import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import urllib.request

from . import __version__
from .errors import ProtonxError

try:
    import certifi

    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    SSL_CONTEXT = ssl.create_default_context()

REPO = "pentoshi007/protonx"
API = "https://api.github.com/repos/%s/releases/latest" % REPO
TIMEOUT = 20


class UpdateError(ProtonxError):
    pass


def _version_tuple(value):
    parts = [int(part) for part in re.findall(r"\d+", value)[:3]]
    return tuple(parts + [0] * (3 - len(parts)))


def latest_release():
    request = urllib.request.Request(API, headers={"User-Agent": "protonx/%s" % __version__})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT, context=SSL_CONTEXT) as response:
            payload = json.load(response)
    except (OSError, ValueError) as error:
        raise UpdateError("could not check for updates: %s" % error) from error
    tag = str(payload.get("tag_name") or "").lstrip("v")
    if not tag:
        raise UpdateError("the latest release has no version tag")
    return tag


def check():
    latest = latest_release()
    return {
        "current": __version__,
        "latest": latest,
        "update": _version_tuple(latest) > _version_tuple(__version__),
    }


def _download(url, path):
    request = urllib.request.Request(url, headers={"User-Agent": "protonx/%s" % __version__})
    try:
        with urllib.request.urlopen(request, timeout=180, context=SSL_CONTEXT) as response, open(path, "wb") as handle:
            shutil.copyfileobj(response, handle)
    except OSError as error:
        raise UpdateError("download failed: %s" % error) from error


def _verify(archive):
    try:
        with open(archive + ".sha256") as handle:
            expected = handle.read().split()[0]
        with open(archive, "rb") as handle:
            actual = hashlib.sha256(handle.read()).hexdigest()
    except (OSError, IndexError) as error:
        raise UpdateError("could not verify the download: %s" % error) from error
    if actual != expected:
        raise UpdateError("the downloaded archive failed its checksum")


def _extract(archive, directory):
    try:
        with tarfile.open(archive) as bundle:
            try:
                bundle.extractall(directory, filter="data")
            except TypeError:
                bundle.extractall(directory)
    except (OSError, tarfile.TarError) as error:
        raise UpdateError("could not unpack the release: %s" % error) from error


def _privileged(args):
    return args if os.geteuid() == 0 else ["sudo"] + args


def _run(args):
    try:
        result = subprocess.run(args)
    except OSError as error:
        raise UpdateError("could not start the installer: %s" % error) from error
    if result.returncode != 0:
        raise UpdateError("the installer exited with status %d" % result.returncode)


def _install_macos(version):
    with tempfile.TemporaryDirectory() as directory:
        archive = os.path.join(directory, "protonx.tar.gz")
        _download("https://codeload.github.com/%s/tar.gz/v%s" % (REPO, version), archive)
        _extract(archive, directory)
        installer = os.path.join(directory, "protonx-%s" % version, "cli", "install-macos.sh")
        if not os.path.exists(installer):
            raise UpdateError("the release has no macOS installer")
        _run(_privileged(["bash", installer]))


def _install_app(version):
    archive = "protonx-%s-macos-universal.tar.gz" % version
    base = "https://github.com/%s/releases/download/v%s" % (REPO, version)
    with tempfile.TemporaryDirectory() as directory:
        path = os.path.join(directory, archive)
        _download(base + "/" + archive, path)
        _download(base + "/" + archive + ".sha256", path + ".sha256")
        _verify(path)
        _extract(path, directory)
        installer = os.path.join(directory, "protonx-%s" % version, "install.sh")
        if not os.path.exists(installer):
            raise UpdateError("the release archive has no app installer")
        _run(_privileged([installer]))


def _install_unix(version):
    with tempfile.TemporaryDirectory() as directory:
        archive = os.path.join(directory, "protonx.tar.gz")
        _download("https://codeload.github.com/%s/tar.gz/v%s" % (REPO, version), archive)
        _extract(archive, directory)
        installer = os.path.join(directory, "protonx-%s" % version, "cli", "install-linux.sh")
        if not os.path.exists(installer):
            raise UpdateError("the release has no Linux installer")
        _run(_privileged(["bash", installer]))


def _install_windows(version):
    with tempfile.TemporaryDirectory() as directory:
        archive = os.path.join(directory, "protonx.tar.gz")
        _download("https://codeload.github.com/%s/tar.gz/v%s" % (REPO, version), archive)
        _extract(archive, directory)
        installer = os.path.join(directory, "protonx-%s" % version, "cli", "install-windows.ps1")
        if not os.path.exists(installer):
            raise UpdateError("the release has no Windows installer")
        _run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", installer])


def install(version, target="cli"):
    if target == "app" and sys.platform != "darwin":
        raise UpdateError("the ProtonX app is only available on macOS")
    if sys.platform == "darwin":
        _install_app(version) if target == "app" else _install_macos(version)
    elif sys.platform.startswith("linux"):
        _install_unix(version)
    elif sys.platform == "win32":
        _install_windows(version)
    else:
        raise UpdateError("updates are not supported on %s" % sys.platform)


def _confirm(status):
    if not sys.stdin.isatty():
        raise UpdateError("run protonx update in a terminal to install the update")
    answer = input("Update protonx %s to %s? [Y/n] " % (status["current"], status["latest"]))
    return not answer.strip().lower().startswith("n")


def update(check_only=False, assume_yes=False, target="cli"):
    status = check()
    if check_only or not status["update"]:
        return status
    if not assume_yes and not _confirm(status):
        return dict(status, cancelled=True)
    install(status["latest"], target)
    return dict(status, installed=True)
