"""wiki-factory plugin — profile-scoped BibTeX watcher lifecycle.

Starts one ``bibwatch.py --watch`` process per topic configured in
~/Prog/research-wiki-factory/wiki-factory.yaml when the FIRST researcher-profile session
starts, and stops them when the LAST session ends.

Design:
- The plugin itself only runs inside the researcher profile because it
  lives in ~/.hermes/profiles/researcher/plugins/.
- Watcher processes are detached (start_new_session=True) so they
  survive the session; a refcounted lockfile
  (~/Prog/research-wiki-factory/state/bibwatch.json) tracks how many live sessions rely on
  them. Last session out kills the watchers.
- Crash-safe: on start, stale lockfile entries (dead PIDs) are pruned;
  if watchers are already running and healthy, they are NOT restarted.
- Idempotent within a process: on_session_start may fire for concurrent
  sessions; a lockfile + flock serializes refcount updates.
"""

from __future__ import annotations

import fcntl
import json
import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

RESEARCH_ROOT = Path.home() / "Prog" / "research-wiki-factory"
SCRIPTS_DIR = RESEARCH_ROOT / "scripts"
STATE_DIR = RESEARCH_ROOT / "state"
LOCKFILE = STATE_DIR / "bibwatch.json"
CONFIG_PATH = RESEARCH_ROOT / "wiki-factory.yaml"
BIBWATCH = SCRIPTS_DIR / "bibwatch.py"


# ---------------------------------------------------------------------------
# Lockfile helpers (atomic under flock)
# ---------------------------------------------------------------------------

def _with_lock(fn):
    """Run fn(state_dict) under an exclusive flock on the lockfile."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOCKFILE, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        fh.seek(0)
        try:
            state = json.load(fh)
        except Exception:
            state = {}
        state.setdefault("watchers", {})   # topic -> pid
        state.setdefault("sessions", {})   # session_id -> started_ts
        new_state = fn(state)
        fh.seek(0)
        fh.truncate()
        json.dump(new_state, fh, indent=2)
        fh.flush()
        os.fsync(fh.fileno())
        return new_state


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _load_topics() -> List[str]:
    """Read topic names from wiki-factory.yaml (list or mapping form)."""
    if not CONFIG_PATH.exists():
        return []
    try:
        import yaml
        with open(CONFIG_PATH) as fh:
            cfg = yaml.safe_load(fh) or {}
    except Exception as exc:
        logger.warning("wiki-factory: failed to parse %s: %s", CONFIG_PATH, exc)
        return []
    topics = cfg.get("topics", [])
    if isinstance(topics, dict):
        return list(topics.keys())
    names = []
    for item in topics:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict) and "name" in item:
            names.append(item["name"])
    return names


# ---------------------------------------------------------------------------
# Watcher process management
# ---------------------------------------------------------------------------

def _start_watcher(topic: str) -> Optional[int]:
    """Spawn bibwatch.py --watch for a topic, detached. Returns PID."""
    if not BIBWATCH.exists():
        logger.warning("wiki-factory: %s not found", BIBWATCH)
        return None
    log_path = STATE_DIR / f"bibwatch-{topic}.log"
    try:
        proc = subprocess.Popen(
            [sys.executable, str(BIBWATCH), topic, "--watch"],
            stdout=open(log_path, "ab"),
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,   # detach from our process group
        )
        logger.info("wiki-factory: started bibwatch for %s (pid %d)", topic, proc.pid)
        return proc.pid
    except Exception as exc:
        logger.warning("wiki-factory: failed to start watcher for %s: %s", topic, exc)
        return None


def _stop_watcher(pid: int, topic: str) -> None:
    """Terminate a watcher process (SIGTERM, then SIGKILL after grace)."""
    try:
        os.kill(pid, signal.SIGTERM)
        for _ in range(20):  # up to 2s grace
            if not _pid_alive(pid):
                break
            time.sleep(0.1)
        if _pid_alive(pid):
            os.kill(pid, signal.SIGKILL)
        logger.info("wiki-factory: stopped bibwatch for %s (pid %d)", topic, pid)
    except ProcessLookupError:
        pass
    except Exception as exc:
        logger.warning("wiki-factory: error stopping watcher %s (pid %d): %s", topic, pid, exc)


# ---------------------------------------------------------------------------
# Hook callbacks
# ---------------------------------------------------------------------------

def _on_session_start(session_id: str = "", **kwargs: Any) -> None:
    topics = _load_topics()
    if not topics:
        return

    def _update(state: Dict[str, Any]) -> Dict[str, Any]:
        # Prune dead watchers and stale sessions first
        state["watchers"] = {t: p for t, p in state["watchers"].items() if _pid_alive(p)}
        state["sessions"][session_id or f"unknown-{time.time()}"] = time.time()

        for topic in topics:
            if topic not in state["watchers"]:
                pid = _start_watcher(topic)
                if pid:
                    state["watchers"][topic] = pid
        return state

    try:
        _with_lock(_update)
    except Exception as exc:
        logger.warning("wiki-factory: on_session_start failed: %s", exc)


def _on_session_end(session_id: str = "", **kwargs: Any) -> None:
    def _update(state: Dict[str, Any]) -> Dict[str, Any]:
        state["sessions"].pop(session_id, None)
        # Prune sessions we never saw end but whose process is gone is not
        # possible here (session ids are not PIDs) — rely on the refcount:
        # if no sessions remain, stop all watchers.
        if not state["sessions"]:
            for topic, pid in list(state["watchers"].items()):
                _stop_watcher(pid, topic)
            state["watchers"] = {}
        return state

    try:
        _with_lock(_update)
    except Exception as exc:
        logger.warning("wiki-factory: on_session_end failed: %s", exc)


# ---------------------------------------------------------------------------
# Plugin entry point
# ---------------------------------------------------------------------------

def register(ctx) -> None:
    ctx.register_hook("on_session_start", _on_session_start)
    ctx.register_hook("on_session_end", _on_session_end)
