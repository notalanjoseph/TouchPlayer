# This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public License,
# as published by the Free Software Foundation, either version 2 of the License, or (at your option) any
# later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the  GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, see <https://www.gnu.org/licenses/>.

'''
Crash dialog for native crashes, in the spirit of Ubuntu's Apport.

A segfault in libmpv or the GPU driver kills the process outright, so it cannot report itself.
TouchPlayer therefore runs as a child of a small supervisor. When the child dies from a crash
signal, the supervisor shows a dialog that can open a pre-filled GitHub issue.

Only the standard library is imported here at module level, to keep the waiting parent light.
'''

import faulthandler
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import urllib.parse

ISSUES_URL = "https://github.com/notalanjoseph/TouchPlayer/issues/new"
MAX_URL_LENGTH = 7500  # GitHub rejects much longer new-issue URLs
CRASH_SIGNALS = {signal.SIGSEGV, signal.SIGABRT, signal.SIGBUS, signal.SIGFPE, signal.SIGILL}

ENV_SUPERVISED = "TOUCHPLAYER_SUPERVISED"
ENV_CRASH_FILE = "TOUCHPLAYER_CRASH_FILE"
ENV_STATE_FILE = "TOUCHPLAYER_STATE_FILE"
ENV_DISABLE = "TOUCHPLAYER_NO_SUPERVISOR"  # run unsupervised, e.g. under gdb

_traceFile = None  # kept open for faulthandler for the whole run
_stateFile = None
_state = {}
_stateLock = threading.Lock()  # media is noted from the playlist worker thread too


# --- Child side ---------------------------------------------------------------

def enableInChild():
    """Write the native crash trace where the supervisor will look for it"""
    global _traceFile, _stateFile
    crashFile = os.environ.pop(ENV_CRASH_FILE, None)
    _stateFile = os.environ.pop(ENV_STATE_FILE, None)
    os.environ.pop(ENV_SUPERVISED, None)  # anything we launch is not part of this supervision
    if crashFile and _traceFile is None:
        _traceFile = open(crashFile, "w")
        faulthandler.enable(file=_traceFile, all_threads=True)


def noteState(**values):
    """Record facts the report needs (versions, current media); a no-op when unsupervised"""
    if not _stateFile:
        return
    with _stateLock:
        _state.update(values)
        try:
            tmp = _stateFile + ".tmp"
            with open(tmp, "w") as f:
                json.dump(_state, f)
            os.replace(tmp, _stateFile)
        except OSError:
            pass


def noteMedia(path):
    noteState(media=path)


# --- Supervisor side --------------------------------------------------------

def isCrash(returncode):
    """Killed by a crash signal. SIGTERM, SIGKILL and SIGINT are someone stopping us, not a crash."""
    return returncode is not None and returncode < 0 and -returncode in CRASH_SIGNALS


def superviseOrContinue():
    """In the parent: run TouchPlayer as a child, report a crash, and exit with its status.
    In the child, or when disabled: return so the caller starts the app normally."""
    if os.environ.get(ENV_SUPERVISED) or os.environ.get(ENV_DISABLE):
        enableInChild()
        return
    # orig_argv keeps interpreter flags such as -X dev; Python 3.9 lacks it
    args = getattr(sys, "orig_argv", None)
    cmd = [sys.executable] + args[1:] if args else [sys.executable, os.path.abspath(sys.argv[0])] + sys.argv[1:]
    sys.exit(supervise(cmd))


def supervise(cmd, showDialog=None):
    """Run cmd as a supervised child; returns the exit status to pass on"""
    work = tempfile.mkdtemp(prefix="touchplayer-")
    crashFile = os.path.join(work, "crash.txt")
    stateFile = os.path.join(work, "state.json")
    env = dict(os.environ, **{ENV_SUPERVISED: "1", ENV_CRASH_FILE: crashFile, ENV_STATE_FILE: stateFile})
    saved = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    try:
        child = subprocess.Popen(cmd, env=env)
        _forwardSignals(child)
        returncode = child.wait()
        trace, state = _read(crashFile), _readState(stateFile)
    finally:
        # The child is gone: from here a logout must stop us, not be forwarded to nobody
        for sig, handler in saved.items():
            signal.signal(sig, handler)
        shutil.rmtree(work, ignore_errors=True)  # before the dialog, which may be killed at logout
    if isCrash(returncode):
        report = buildReport(returncode, trace, state)  # may run ffprobe, so only after the handlers are back
        (showDialog or showCrashDialog)(report, signalName(returncode))
    # Killed by signal N: exit 128+N, the shell convention. sys.exit() of a negative number is meaningless.
    return 128 - returncode if returncode < 0 else returncode


def _forwardSignals(child):
    # Ctrl+C reaches the whole process group; the child quits by itself, so the parent waits.
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    for sig in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, lambda signum, _frame: child.send_signal(signum))


def _read(path):
    try:
        with open(path, errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def _readState(path):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


# --- Report -------------------------------------------------------------------

def signalName(returncode):
    try:
        return signal.Signals(-returncode).name
    except ValueError:
        return "signal %d" % -returncode


def buildReport(returncode, trace, state):
    """Markdown for the issue. Holds the media's format but never its name or path."""
    lines = [
        "**TouchPlayer stopped unexpectedly** (%s)" % signalName(returncode),
        "",
        "- TouchPlayer: %s" % state.get("version", "unknown"),
        "- OS: %s" % _osName(),
        "- Session: %s, %s" % (os.environ.get("XDG_SESSION_TYPE", "?"), os.environ.get("XDG_CURRENT_DESKTOP", "?")),
        "- Python %s, Qt %s, PyQt %s, mpv %s" % (
            platform.python_version(), state.get("qt", "?"), state.get("pyqt", "?"), state.get("mpv", "?")),
        "",
        "### Media format",
        "```",
        mediaFormat(state.get("media")),
        "```",
        "",
        "### Crash trace",
        "```",
        _scrub(crashingThreadFirst(trace.strip()), state.get("media")) or "(no trace was written)",
        "```",
    ]
    return "\n".join(lines)


def _osName():
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return platform.platform()


def _scrub(text, media):
    """Keep the media's name and the home folder out of text that goes into a public issue"""
    if media:
        text = text.replace(media, "<media>")
        name = os.path.basename(media.rstrip("/"))
        if name:  # replacing "" would put <media> between every character
            text = text.replace(name, "<media>")
    # Inside a snap, HOME is a private ~/snap/... folder; SNAP_REAL_HOME is the one with the user's name in it
    for home in (os.environ.get("SNAP_REAL_HOME"), os.path.expanduser("~")):
        if home and home != "/":
            text = text.replace(home, "~")
    return text


def crashingThreadFirst(trace):
    """faulthandler lists every thread; move the one that crashed to the top, so shortening keeps it"""
    blocks = trace.split("\n\n")
    isThread = [b.lstrip().startswith(("Thread ", "Current thread")) for b in blocks]
    if True not in isThread:
        return trace
    first = isThread.index(True)  # the "Fatal Python error" header stays on top
    threads = [b for b, t in zip(blocks, isThread) if t]
    threads.sort(key=lambda b: not b.lstrip().startswith("Current thread"))
    rest = [b for b, t in zip(blocks[first:], isThread[first:]) if not t]
    return "\n\n".join(blocks[:first] + threads + rest)


def mediaFormat(path):
    if not path:
        return "no media loaded"
    if path.startswith("file://"):
        path = urllib.parse.unquote(urllib.parse.urlparse(path).path)
    elif "://" in path:
        return "network stream"
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-of", "json", "-show_entries",
             "format=format_name:stream=codec_type,codec_name,profile,width,height,pix_fmt,sample_rate,channels",
             path], capture_output=True, text=True, timeout=5).stdout
        return describeProbe(json.loads(out))
    except (OSError, ValueError, subprocess.SubprocessError):
        return "unavailable (ffprobe failed)"


def describeProbe(probe):
    """ffprobe's JSON as short lines: container, then one line per stream"""
    lines = ["container: %s" % probe.get("format", {}).get("format_name", "?")]
    for s in probe.get("streams", []):
        kind = s.get("codec_type", "?")
        parts = [s.get("codec_name", "?")]
        if s.get("profile"):
            parts[0] += " (%s)" % s["profile"]
        if kind == "video":
            parts.append("%sx%s" % (s.get("width", "?"), s.get("height", "?")))
            if s.get("pix_fmt"):
                parts.append(s["pix_fmt"])
        elif kind == "audio":
            parts.append("%s Hz, %s ch" % (s.get("sample_rate", "?"), s.get("channels", "?")))
        lines.append("%s: %s" % (kind, ", ".join(parts)))
    return "\n".join(lines)


def issueUrl(report, signame="crash"):
    """A new-issue link with the report as body, shortened to fit GitHub's URL limit"""
    title = "Crash: TouchPlayer stopped unexpectedly (%s)" % signame
    body = report
    marker = "\n...\n(trace shortened; full details in the crash dialog)\n```"
    while True:
        url = ISSUES_URL + "?" + urllib.parse.urlencode({"title": title, "body": body})
        if len(url) <= MAX_URL_LENGTH or len(body) < 200:
            return url
        body = report[:int(len(body) * 0.8)] + marker


# --- Dialog -------------------------------------------------------------------

def showCrashDialog(report, signame):
    from PyQt6 import QtCore, QtGui, QtWidgets
    signal.signal(signal.SIGINT, signal.SIG_DFL)  # Python's Ctrl+C handler cannot run inside Qt's loop
    _app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv[:1])  # noqa: F841 (must outlive exec)
    box = buildCrashDialog(report)
    box.exec()
    if box.clickedButton() is box.reportButton:
        QtGui.QDesktopServices.openUrl(QtCore.QUrl(issueUrl(report, signame)))


def buildCrashDialog(report):
    from PyQt6 import QtWidgets
    box = QtWidgets.QMessageBox()
    box.setIcon(QtWidgets.QMessageBox.Icon.Critical)
    box.setWindowTitle("TouchPlayer")
    box.setText("Sorry, TouchPlayer has stopped unexpectedly.")
    box.setInformativeText(
        "Send a problem report to the developers?\n\n"
        "The report opens on GitHub so you can check it before sending. "
        "It includes the video's format, not its name.")
    box.setDetailedText(report)  # adds Qt's own "Show Details..." button
    box.addButton("Don't Send", QtWidgets.QMessageBox.ButtonRole.RejectRole)
    box.reportButton = box.addButton("Report on GitHub", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
    box.setDefaultButton(box.reportButton)
    return box
