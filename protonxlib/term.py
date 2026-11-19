import contextlib
import getpass
import os
import shutil
import sys
import threading
import time
from dataclasses import dataclass, field

WINDOWS = os.name == "nt"

if WINDOWS:
    import msvcrt
else:
    import select as _select
    import termios


class Back(Exception):
    pass


@dataclass
class Choice:
    label: str
    value: object
    detail: str = ""
    badge: str = ""
    badge_tone: str = ""
    keywords: str = ""
    tone: str = ""
    search: str = field(init=False)

    def __post_init__(self):
        self.search = " ".join((self.label, self.detail, self.keywords)).lower()


def _enable_windows_vt():
    if not WINDOWS:
        return True
    try:
        import ctypes

        kernel = ctypes.windll.kernel32
        handle = kernel.GetStdHandle(-11)
        mode = ctypes.c_uint32()
        if not kernel.GetConsoleMode(handle, ctypes.byref(mode)):
            return False
        return bool(kernel.SetConsoleMode(handle, mode.value | 0x0004))
    except (AttributeError, OSError):
        return False


def _supports_unicode():
    encoding = (getattr(sys.stdout, "encoding", "") or "").lower()
    return "utf" in encoding


PLAIN = os.environ.get("TERM") == "dumb" or os.environ.get("PROTONX_PLAIN") == "1" or not _enable_windows_vt()
COLOR = not PLAIN and "NO_COLOR" not in os.environ and sys.stdout.isatty()
UNICODE = _supports_unicode()

SYMBOLS = {
    "pointer": "❯" if UNICODE else ">",
    "ok": "✔" if UNICODE else "+",
    "fail": "✖" if UNICODE else "x",
    "dot": "●" if UNICODE else "*",
    "ring": "○" if UNICODE else "o",
    "sep": "·" if UNICODE else "-",
    "up": "↑" if UNICODE else "^",
    "down": "↓" if UNICODE else "v",
}
SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏" if UNICODE else "|/-\\"

CODES = {
    "bold": "1",
    "dim": "2",
    "red": "31",
    "green": "32",
    "yellow": "33",
    "blue": "34",
    "magenta": "35",
    "cyan": "36",
}


def paint(text, *styles):
    if not COLOR or not styles:
        return text
    return "\x1b[%sm%s\x1b[0m" % (";".join(CODES[style] for style in styles if style), text)


def symbol(name):
    return SYMBOLS[name]


def width():
    return max(20, shutil.get_terminal_size((80, 24)).columns)


def height():
    return max(10, shutil.get_terminal_size((80, 24)).lines)


def fit(parts, limit=None):
    limit = (limit or width()) - 1
    pieces = []
    used = 0
    for text, styles in parts:
        if used >= limit:
            break
        chunk = text[: limit - used]
        used += len(chunk)
        pieces.append(paint(chunk, *styles))
    return "".join(pieces)


def write(text):
    sys.stdout.write(text)
    sys.stdout.flush()


def say(text=""):
    write(text + "\n")


def success(text):
    say("%s %s" % (paint(symbol("ok"), "green"), text))


def failure(text):
    say("%s %s" % (paint(symbol("fail"), "red"), text))


def note(text):
    say(paint(text, "dim"))


def load_tone(percent):
    return "green" if percent < 50 else "yellow" if percent < 80 else "red"


@contextlib.contextmanager
def _keyboard():
    if WINDOWS:
        yield
        return
    descriptor = sys.stdin.fileno()
    saved = termios.tcgetattr(descriptor)
    changed = termios.tcgetattr(descriptor)
    changed[3] &= ~(termios.ICANON | termios.ECHO)
    changed[6][termios.VMIN] = 1
    changed[6][termios.VTIME] = 0
    termios.tcsetattr(descriptor, termios.TCSADRAIN, changed)
    try:
        yield
    finally:
        termios.tcsetattr(descriptor, termios.TCSADRAIN, saved)


@contextlib.contextmanager
def _hidden_cursor():
    if not PLAIN:
        write("\x1b[?25l")
    try:
        yield
    finally:
        if not PLAIN:
            write("\x1b[?25h")


POSIX_SEQUENCES = {
    "[A": "up",
    "[B": "down",
    "[C": "right",
    "[D": "left",
    "OA": "up",
    "OB": "down",
    "OC": "right",
    "OD": "left",
    "[5~": "pageup",
    "[6~": "pagedown",
    "[H": "home",
    "[F": "end",
    "OH": "home",
    "OF": "end",
    "[1~": "home",
    "[4~": "end",
    "[3~": "delete",
}
WINDOWS_SCANCODES = {
    "H": "up",
    "P": "down",
    "K": "left",
    "M": "right",
    "I": "pageup",
    "Q": "pagedown",
    "G": "home",
    "O": "end",
    "S": "delete",
}
CONTROL_KEYS = {
    "\r": "enter",
    "\n": "enter",
    "\x7f": "backspace",
    "\x08": "backspace",
    "\t": "tab",
    "\x03": "ctrl-c",
    "\x04": "ctrl-d",
    "\x15": "ctrl-u",
}


def _pending(timeout):
    if WINDOWS:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if msvcrt.kbhit():
                return True
            time.sleep(0.02)
        return msvcrt.kbhit()
    return bool(_select.select([sys.stdin.fileno()], [], [], timeout)[0])


def _read_char():
    if WINDOWS:
        return msvcrt.getwch()
    descriptor = sys.stdin.fileno()
    first = os.read(descriptor, 1)
    if not first:
        return "\x04"
    expected = 1
    if first[0] >= 0xF0:
        expected = 4
    elif first[0] >= 0xE0:
        expected = 3
    elif first[0] >= 0xC0:
        expected = 2
    data = first
    while len(data) < expected:
        data += os.read(descriptor, expected - len(data))
    return data.decode("utf-8", errors="replace")


def _read_escape():
    sequence = ""
    while _pending(0.05):
        sequence += _read_char()
        if sequence[-1].isalpha() or sequence[-1] == "~":
            break
    return POSIX_SEQUENCES.get(sequence, "escape" if not sequence else None)


def read_key():
    char = _read_char()
    if WINDOWS and char in ("\x00", "\xe0"):
        return WINDOWS_SCANCODES.get(msvcrt.getwch())
    if char == "\x1b":
        return _read_escape()
    if char in CONTROL_KEYS:
        return CONTROL_KEYS[char]
    return char if char.isprintable() else None


class _Canvas:
    def __init__(self):
        self.lines = 0

    def draw(self, lines):
        self.clear()
        write("".join("\x1b[2K%s\n" % line for line in lines))
        self.lines = len(lines)

    def clear(self):
        if self.lines:
            write("\x1b[%dA\r\x1b[J" % self.lines)
        self.lines = 0


def _matches(choices, query):
    needle = query.lower().strip()
    if not needle:
        return list(choices)
    return [choice for choice in choices if all(word in choice.search for word in needle.split())]


def _row(choice, active, label_width):
    pointer = (symbol("pointer"), ("cyan",)) if active else (" ", ())
    label_style = ("cyan", "bold") if active else ((choice.tone,) if choice.tone else ())
    parts = [("  ", ()), pointer, (" ", ()), (choice.label.ljust(label_width), label_style)]
    if choice.badge:
        parts.append(("  " + choice.badge, (choice.badge_tone,) if choice.badge_tone else ()))
    if choice.detail:
        parts.append(("  " + choice.detail, ("dim",)))
    return fit(parts)


def _window(total, cursor, rows):
    if total <= rows:
        return 0, total
    start = min(max(0, cursor - rows // 2), total - rows)
    return start, start + rows


def _select_plain(title, choices, allow_back):
    say(paint("? ", "cyan") + paint(title, "bold"))
    for index, choice in enumerate(choices, 1):
        extra = "  ".join(part for part in (choice.badge.strip(), choice.detail) if part)
        say("  %2d) %s%s" % (index, choice.label, "  " + extra if extra else ""))
    hint = "number" + (", or Enter to go back" if allow_back else "")
    while True:
        try:
            answer = input("  %s: " % hint).strip()
        except EOFError:
            raise Back()
        if not answer and allow_back:
            raise Back()
        if answer.isdigit() and 1 <= int(answer) <= len(choices):
            return choices[int(answer) - 1].value


def select(title, choices, allow_back=True, searchable=None):
    choices = list(choices)
    if not choices:
        raise Back()
    if PLAIN:
        return _select_plain(title, choices, allow_back)
    searchable = len(choices) > 8 if searchable is None else searchable
    query = ""
    cursor = 0
    canvas = _Canvas()
    label_width = min(max(len(choice.label) for choice in choices), max(12, width() // 2))
    keys = "%s%s move %s Enter select" % (symbol("up"), symbol("down"), symbol("sep"))
    if searchable:
        keys = "type to filter %s %s" % (symbol("sep"), keys)
    if allow_back:
        keys += " %s Esc back" % symbol("sep")
    rows = max(3, min(14, height() - 6))
    steps = {"up": -1, "down": 1, "tab": 1}
    if not searchable:
        steps.update({"k": -1, "j": 1})
    with _keyboard(), _hidden_cursor():
        try:
            while True:
                visible = _matches(choices, query)
                cursor = min(cursor, max(0, len(visible) - 1))
                start, end = _window(len(visible), cursor, rows)
                lines = [fit([("? ", ("cyan",)), (title, ("bold",)), ("  " + keys, ("dim",))])]
                if searchable:
                    lines.append(fit([("  filter: ", ("dim",)), (query or "", ("yellow",)), ("_", ("dim",))]))
                if not visible:
                    lines.append(paint("    no matches", "dim"))
                if start > 0:
                    lines.append(paint("    %s %d more" % (symbol("up"), start), "dim"))
                lines.extend(_row(choice, index == cursor, label_width) for index, choice in enumerate(visible[start:end], start))
                if end < len(visible):
                    lines.append(paint("    %s %d more" % (symbol("down"), len(visible) - end), "dim"))
                canvas.draw(lines)
                key = read_key()
                step = steps.get(key)
                if step and visible:
                    cursor = (cursor + step) % len(visible)
                elif key == "pageup":
                    cursor = max(0, cursor - rows)
                elif key == "pagedown":
                    cursor = min(len(visible) - 1, cursor + rows) if visible else 0
                elif key == "home":
                    cursor = 0
                elif key == "end":
                    cursor = max(0, len(visible) - 1)
                elif key == "enter" and visible:
                    chosen = visible[cursor]
                    canvas.clear()
                    say(fit([(symbol("ok") + " ", ("green",)), (title, ()), ("  " + chosen.label, ("cyan",))]))
                    return chosen.value
                elif key == "escape" and searchable and query:
                    query = ""
                elif key in ("escape", "left", "ctrl-d") and allow_back:
                    canvas.clear()
                    raise Back()
                elif key == "ctrl-c":
                    canvas.clear()
                    raise KeyboardInterrupt()
                elif key == "backspace" and searchable:
                    query = query[:-1]
                elif key == "ctrl-u" and searchable:
                    query = ""
                elif searchable and key and len(key) == 1:
                    query += key
                    cursor = 0
        except KeyboardInterrupt:
            canvas.clear()
            raise


def ask(prompt, default=None, secret=False, required=True):
    suffix = paint(" (%s)" % default, "dim") if default else ""
    label = "%s %s%s: " % (paint("?", "cyan"), paint(prompt, "bold"), suffix)
    while True:
        try:
            answer = getpass.getpass(label) if secret else input(label)
        except EOFError:
            say()
            raise Back()
        except KeyboardInterrupt:
            say()
            raise Back()
        answer = answer.strip() if not secret else answer
        if not answer and default:
            return default
        if answer or not required:
            return answer
        note("  Leave it empty and press Ctrl+C to go back.")


def confirm(question, default=True):
    options = [Choice("Yes", True), Choice("No", False)]
    if not default:
        options.reverse()
    try:
        return select(question, options, allow_back=True, searchable=False)
    except Back:
        return False


def pause(message="Press any key to continue"):
    if PLAIN:
        try:
            input(paint("  %s (Enter) " % message, "dim"))
        except EOFError:
            pass
        return
    write(paint("  %s " % message, "dim"))
    with _keyboard(), _hidden_cursor():
        read_key()
    write("\r\x1b[2K")


def live(render, interval=1.0):
    if PLAIN:
        for line in render():
            say(line)
        pause()
        return
    canvas = _Canvas()
    with _keyboard(), _hidden_cursor():
        try:
            while True:
                canvas.draw(render() + ["", paint("  Press any key to go back", "dim")])
                if _pending(interval):
                    read_key()
                    break
        finally:
            canvas.clear()


@contextlib.contextmanager
def spinner(message):
    if PLAIN or not sys.stdout.isatty():
        say(paint("%s..." % message, "dim"))
        yield
        return
    stop = threading.Event()

    def spin():
        frame = 0
        while not stop.wait(0.08):
            write("\r\x1b[2K%s %s" % (paint(SPINNER[frame % len(SPINNER)], "cyan"), message))
            frame += 1

    write("%s %s" % (paint(SPINNER[0], "cyan"), message))
    worker = threading.Thread(target=spin, daemon=True)
    with _hidden_cursor():
        worker.start()
        try:
            yield
        finally:
            stop.set()
            worker.join()
            write("\r\x1b[2K")
