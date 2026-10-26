"""Guarded, sequential job queue for the SkillForge loop.

Every job is an explicit, allowlisted chain of CLI steps. There is no shell and
no free-form command: the API validates parameters, records the exact argv, and
streams the child's own output to a log. A human gate sits between measurement
and promotion.

State lives in ``data/jobs.json`` and logs in ``runs/jobs/`` — both local-only.
"""
from __future__ import annotations

import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
JOBS_FILE = Path(os.environ.get("SKILLFORGE_JOBS", str(REPO_ROOT / "data" / "jobs.json")))
LOG_DIR = Path(os.environ.get("SKILLFORGE_JOB_LOGS", str(REPO_ROOT / "runs" / "jobs")))

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{1,63}$")
ROUND_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,31}$")

KINDS = ("skills_round", "rsi_round", "reports")


class JobError(ValueError):
    """Invalid job request."""


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _new_id() -> str:
    return f"job_{time.strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(2)}"


def _skills(value) -> str:
    if isinstance(value, str):
        items = [x.strip() for x in value.split(",") if x.strip()]
    elif isinstance(value, list):
        items = [str(x).strip() for x in value if str(x).strip()]
    else:
        raise JobError("skills must be a comma-separated string or a list")
    if not items:
        raise JobError("choose at least one skill")
    if len(items) > 8:
        raise JobError("at most 8 skills per round")
    for item in items:
        if not NAME_RE.match(item):
            raise JobError(f"invalid skill name: {item!r}")
    return ",".join(dict.fromkeys(items))


def _int(params: dict, key: str, lo: int, hi: int, default: int) -> int:
    try:
        n = int(params.get(key, default))
    except (TypeError, ValueError):
        raise JobError(f"{key} must be an integer")
    if not lo <= n <= hi:
        raise JobError(f"{key} must be between {lo} and {hi}")
    return n


def _run_id(params: dict) -> str:
    value = str(params.get("run_id") or "").strip()
    if not RUN_ID_RE.match(value):
        raise JobError("run_id must be 2-64 chars: letters, digits, dot, dash, underscore")
    return value


def _round(params: dict) -> str:
    value = str(params.get("round") or "").strip()
    if not ROUND_RE.match(value):
        raise JobError("round must be 1-32 chars: letters, digits, dot, dash, underscore")
    return value


def build_steps(kind: str, params: dict, python: str | None = None) -> tuple[list[dict], dict]:
    """Return (steps, normalised params). Commands are argv lists, never a shell."""
    py = python or sys.executable
    base = [py, "-m", "forge_rsi"]
    if kind == "skills_round":
        skills = _skills(params.get("skills"))
        rows = _int(params, "rows", 10, 400, 40)
        iters = _int(params, "iters", 10, 1000, 120)
        run_id = _run_id(params)
        normalised = dict(skills=skills, rows=rows, iters=iters, run_id=run_id)
        steps = [
            dict(name="build corpora", cmd=base + ["skills-build", "--skills", skills,
                                                   "--rows", str(rows)]),
            dict(name="train adapters", cmd=base + ["skills-train", "--skills", skills,
                                                    "--iters", str(iters)],
                 guard="base"),
            dict(name="gated evaluation", cmd=base + ["skills-eval", "--splits",
                                                      "dev,holdout,skills",
                                                      "--run-id", run_id],
                 gate=True),
            dict(name="promotion decision", cmd=base + ["skills-decide",
                                                        "--run-prefix", run_id]),
            dict(name="skill report", cmd=base + ["skills-report"]),
            dict(name="final report", cmd=base + ["final-report"]),
        ]
    elif kind == "rsi_round":
        rnd = _round(params)
        iterations = _int(params, "iterations", 1, 20, 3)
        normalised = dict(round=rnd, iterations=iterations)
        steps = [
            dict(name="harness loop", cmd=base + ["loop", "--round", rnd,
                                                  "--iterations", str(iterations)],
                 guard="base", gate=True),
            dict(name="round report", cmd=base + ["report", "--round", rnd]),
            dict(name="final report", cmd=base + ["final-report"]),
        ]
    elif kind == "reports":
        normalised = {}
        steps = [dict(name="skill report", cmd=base + ["skills-report"]),
                 dict(name="final report", cmd=base + ["final-report"])]
    else:
        raise JobError(f"unknown job kind: {kind!r}")

    for i, step in enumerate(steps):
        step.update(index=i, status="pending", exit_code=None,
                    started=None, finished=None)
    return steps, normalised


def _read(path: Path) -> dict:
    if not path.exists():
        return {"jobs": []}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {"jobs": []}
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        return {"jobs": []}
    return data


def _write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    tmp.replace(path)


def base_guard() -> tuple[bool, str]:
    """Refuse to train when the configured base is missing or has drifted."""
    try:
        from forge_rsi import config as forge_cfg
        from pipeline import forge as forge_mod
        cfg = forge_cfg.load()
    except Exception as e:  # config is required for engine jobs
        return False, f"config not loaded: {e}"
    agent = Path(cfg["paths"]["agent"])
    if not agent.exists():
        return False, f"base model not found: {agent}"
    lock = forge_mod.base_lock(str(agent), verify=False)
    if lock.get("verified") is False:
        return False, "base lock mismatch — refusing to train"
    missing = [f["file"] for f in lock.get("files", []) if f.get("status") == "missing"]
    if missing:
        return False, f"base files missing: {', '.join(missing[:3])}"
    return True, "base present"


class JobQueue:
    """One background worker; jobs run one at a time, in submission order."""

    def __init__(self, path: Path | None = None, log_dir: Path | None = None,
                 autostart: bool = True):
        self.path = Path(path or JOBS_FILE)
        self.log_dir = Path(log_dir or LOG_DIR)
        self._lock = threading.RLock()
        self._wake = threading.Condition(self._lock)
        self._proc: subprocess.Popen | None = None
        self._cancel: set[str] = set()
        data = _read(self.path)
        self._jobs: list[dict] = data["jobs"]
        for job in self._jobs:
            if job.get("status") == "running":
                pid = job.get("pid")
                if isinstance(pid, int):
                    try:
                        os.killpg(os.getpgid(pid), signal.SIGTERM)
                    except OSError:
                        pass
                job["status"] = "failed"
                job["note"] = "interrupted by a server restart"
                job["finished"] = _now()
        self._persist()
        self._thread: threading.Thread | None = None
        if autostart:
            self._thread = threading.Thread(target=self._loop, name="skillforge-jobs",
                                            daemon=True)
            self._thread.start()

    # ── public API ────────────────────────────────────────────────────────
    def list(self) -> list[dict]:
        with self._lock:
            return [json.loads(json.dumps(j)) for j in sorted(
                self._jobs, key=lambda j: j.get("created", ""), reverse=True)]

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = next((j for j in self._jobs if j["id"] == job_id), None)
            return json.loads(json.dumps(job)) if job else None

    def submit(self, kind: str, params: dict | None) -> dict:
        if kind not in KINDS:
            raise JobError(f"unknown job kind: {kind!r}")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise JobError("params must be an object")
        steps, normalised = build_steps(kind, params)
        job = dict(id=_new_id(), kind=kind, params=normalised, steps=steps,
                   status="queued", created=_now(), started=None, finished=None,
                   approved=None, note="", current=0, pid=None, log="")
        # one log file per job, named after the job id
        job["log"] = str(self.log_dir / f"{job['id']}.log")
        with self._wake:
            self._jobs.append(job)
            self._persist()
            self._wake.notify_all()
        return self.get(job["id"])  # type: ignore[return-value]

    def approve(self, job_id: str, approve: bool, note: str = "") -> dict:
        with self._wake:
            job = self._find(job_id)
            if job["status"] != "awaiting_approval":
                raise JobError("job is not awaiting approval")
            job["approved"] = bool(approve)
            job["note"] = note or ("approved by operator" if approve else "rejected by operator")
            if approve:
                for step in job["steps"]:
                    if step.get("gate") and step["status"] != "done":
                        step["status"] = "done"
                        step["finished"] = _now()
                        step["exit_code"] = 0
                job["status"] = "queued"
            else:
                job["status"] = "rejected"
                job["finished"] = _now()
            self._persist()
            self._wake.notify_all()
            return self.get(job_id)  # type: ignore[return-value]

    def cancel(self, job_id: str) -> dict:
        with self._wake:
            job = self._find(job_id)
            if job["status"] in ("completed", "failed", "rejected", "cancelled"):
                return self.get(job_id)  # type: ignore[return-value]
            self._cancel.add(job_id)
            proc = self._proc
            if proc is not None and job["status"] == "running":
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except OSError:
                    pass
            job["status"] = "cancelled"
            job["finished"] = _now()
            job["note"] = job.get("note") or "cancelled by operator"
            self._persist()
            self._wake.notify_all()
            return self.get(job_id)  # type: ignore[return-value]

    def log_tail(self, job_id: str, lines: int = 80) -> str:
        job = self.get(job_id)
        if not job:
            raise JobError("unknown job")
        p = Path(job["log"])
        if not p.exists():
            return ""
        text = p.read_text(errors="replace")
        return "\n".join(text.splitlines()[-max(1, min(lines, 400)):])

    # ── worker ────────────────────────────────────────────────────────────
    def _find(self, job_id: str) -> dict:
        job = next((j for j in self._jobs if j["id"] == job_id), None)
        if not job:
            raise JobError("unknown job")
        return job

    def _persist(self) -> None:
        _write(self.path, {"jobs": self._jobs})

    def _next_queued(self) -> dict | None:
        return next((j for j in self._jobs if j["status"] == "queued"), None)

    def _loop(self) -> None:
        while True:
            with self._wake:
                job = self._next_queued()
                while job is None:
                    self._wake.wait(timeout=30)
                    job = self._next_queued()
                job["status"] = "running"
                job["started"] = job.get("started") or _now()
                self._persist()
            try:
                self._run(job["id"])
            except Exception as e:  # never kill the worker thread
                with self._lock:
                    j = self._find(job["id"])
                    j["status"] = "failed"
                    j["note"] = f"runner error: {e}"
                    j["finished"] = _now()
                    self._persist()

    def _run(self, job_id: str) -> None:
        with self._lock:
            job = self._find(job_id)
            steps = job["steps"]
            self.log_dir.mkdir(parents=True, exist_ok=True)
        for i, step in enumerate(steps):
            if step["status"] == "done":
                continue
            with self._lock:
                job = self._find(job_id)
                if job["status"] == "cancelled":
                    return
                job["current"] = i
                self._persist()

            if step.get("guard") == "base":
                ok, why = base_guard()
                if not ok:
                    with self._lock:
                        j = self._find(job_id)
                        step["status"] = "failed"
                        step["finished"] = _now()
                        j["status"] = "failed"
                        j["note"] = why
                        j["finished"] = _now()
                        self._persist()
                    return

            with self._lock:
                step["status"] = "running"
                step["started"] = _now()
                self._persist()

            code = self._spawn(job_id, step)

            with self._lock:
                job = self._find(job_id)
                step["finished"] = _now()
                step["exit_code"] = code
                if job["status"] == "cancelled" or job_id in self._cancel:
                    step["status"] = "cancelled"
                    self._persist()
                    return
                if code != 0:
                    step["status"] = "failed"
                    job["status"] = "failed"
                    job["note"] = f"{step['name']} exited {code}"
                    job["finished"] = _now()
                    self._persist()
                    return
                step["status"] = "done"
                if step.get("gate"):
                    job["status"] = "awaiting_approval"
                    self._persist()
                    return
                self._persist()

        with self._lock:
            job = self._find(job_id)
            job["status"] = "completed"
            job["finished"] = _now()
            job["note"] = job.get("note") or "all steps completed"
            self._persist()

    def _spawn(self, job_id: str, step: dict) -> int:
        log = Path(self.get(job_id)["log"])
        env = os.environ.copy()
        env["PYTHONPATH"] = str(REPO_ROOT) + (
            os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
        with open(log, "a") as f:
            f.write(f"\n===== {_now()} · {step['name']} =====\n")
            f.write("$ " + " ".join(step["cmd"]) + "\n")
            f.flush()
            proc = subprocess.Popen(step["cmd"], cwd=str(REPO_ROOT), env=env,
                                    stdout=f, stderr=subprocess.STDOUT,
                                    start_new_session=True)
            with self._lock:
                self._proc = proc
                self._find(job_id)["pid"] = proc.pid
                self._persist()
            code = proc.wait()
            with self._lock:
                self._proc = None
                self._find(job_id)["pid"] = None
                self._persist()
        return code


_QUEUE: JobQueue | None = None
_QUEUE_LOCK = threading.Lock()


def queue() -> JobQueue:
    global _QUEUE
    with _QUEUE_LOCK:
        if _QUEUE is None:
            _QUEUE = JobQueue()
        return _QUEUE
