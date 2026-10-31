"""Windowless entry point for a Windows scheduled task (pythonw.exe).

pythonw.exe gives the process no console, so sys.stderr is None and
serve_node.py's log() would crash. Point both streams at a log file first,
then hand off to serve_node.py unmodified.

USERPROFILE is pinned explicitly from this file's own location: under a Task
Scheduler S4U logon ("run whether the user is logged on or not", no stored
password) the environment is sparse, and if expanduser("~") drifted -- e.g. to
C:\\Users -- the node would not find its secret.key, would mint a fresh one,
and the endpoint id would silently change.

Deploy next to serve_node.py in the node directory, e.g.
C:\\Users\\me\\iroh7\\serve_launcher.py -- for that layout the profile root is
BASE.parents[0]; adjust the index if you deploy deeper.
"""
import os, pathlib, runpy, sys

BASE = pathlib.Path(__file__).resolve().parent          # ...\iroh7
os.environ["USERPROFILE"] = str(BASE.parents[0])        # C:\Users\me

LOG = BASE / "serve.log"
if LOG.exists() and LOG.stat().st_size > 1_000_000:
    LOG.replace(BASE / "serve.log.1")                   # rotate at ~1 MB

sys.stdout = sys.stderr = open(LOG, "a", buffering=1, encoding="utf-8", errors="replace")

sys.argv = ["serve_node.py", "serve", "22"]
runpy.run_path(str(BASE / "serve_node.py"), run_name="__main__")
