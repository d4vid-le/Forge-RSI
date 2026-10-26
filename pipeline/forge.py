"""
SkillForge — Forge stage (training).

Real MLX LoRA training over mlx_lm, wrapped so the UI can drive it honestly:

  * R1 base lock   : per-file sha256 verification against the recorded
                     checksums/base_before.txt (their lab format), cached by
                     (size, mtime) so re-verifying unchanged 30 GB is cheap.
  * R7 data gate   : the exported rows are run through the protocol gates
                     before anything is written; a failing dataset refuses to
                     become a training run unless explicitly allowed.
  * R6 scale math  : rank and alpha are inputs, scale = alpha/rank is derived
                     and written into the mlx_lm YAML config.
  * no simulations : if mlx_lm, the model, or the data is missing, the run is
                     refused with the reason. Nothing fabricates a loss curve.

Runs live in runs/<name>/: train.jsonl, valid.jsonl, lora_config.yaml,
command.txt, train.log, run.json.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNS_DIR = REPO_ROOT / "runs"
ADAPTERS_DIR = REPO_ROOT / "adapters"
DATA_DIR = REPO_ROOT / "data"
CACHE_FILE = DATA_DIR / "base_lock_cache.json"

# Optional extra lab roots, supplied by the operator (never hardcoded):
#   SKILLFORGE_LABS=/path/one:/path/two
KNOWN_LABS = [
    Path(p).expanduser()
    for p in os.environ.get("SKILLFORGE_LABS", "").split(os.pathsep)
    if p.strip()
]
HF_HUB = Path.home() / ".cache" / "huggingface" / "hub"

# live subprocesses, keyed by run name (in-memory; pid is also persisted)
_PROCS: dict[str, subprocess.Popen] = {}

TRAIN_RE = re.compile(
    r"Iter\s+(?P<iter>\d+):\s+Train loss\s+(?P<loss>[0-9.]+)"
    r"(?:,\s+Learning Rate\s+(?P<lr>[0-9.eE\-+]+))?"
    r"(?:,\s+It/sec\s+(?P<itsec>[0-9.]+))?"
    r"(?:,\s+Tokens/sec\s+(?P<toksec>[0-9.]+))?"
    r"(?:,\s+Trained Tokens\s+(?P<tokens>\d+))?"
    r"(?:,\s+Peak mem\s+(?P<mem>[0-9.]+)\s*GB)?")
VAL_RE = re.compile(r"Iter\s+(?P<iter>\d+):\s+Val loss\s+(?P<loss>[0-9.]+)"
                    r"(?:,\s+Val took\s+(?P<secs>[0-9.]+)s)?")


# ── environment ─────────────────────────────────────────────────────────────

def mlx_info() -> dict:
    info = {"mlx": None, "mlx_lm": None, "lora_cli": None, "python": sys.version.split()[0]}
    try:
        import mlx.core as mx
        info["mlx"] = getattr(mx, "__version__", "unknown")
    except Exception as e:
        info["mlx_error"] = str(e)
    try:
        import mlx_lm
        info["mlx_lm"] = getattr(mlx_lm, "__version__", "unknown")
    except Exception as e:
        info["mlx_lm_error"] = str(e)
    import shutil
    info["lora_cli"] = shutil.which("mlx_lm.lora")
    info["server_cli"] = shutil.which("mlx_lm.server")
    return info


def discover_models() -> list[dict]:
    """Every model this machine can actually train on, found by inspection."""
    out = []
    for lab in KNOWN_LABS:
        if (lab / "config.json").exists():
            out.append(dict(id=str(lab), label=f"{lab.name} (local HF dir)",
                            kind="hf_dir", path=str(lab),
                            size_gb=_dir_size_gb(lab), lock=_lock_path_for(lab)))
    if HF_HUB.exists():
        for d in sorted(HF_HUB.glob("models--*")):
            snaps = sorted((d / "snapshots").glob("*")) if (d / "snapshots").exists() else []
            if not snaps:
                continue
            snap = snaps[-1]
            if not (snap / "config.json").exists():
                continue
            repo = d.name.replace("models--", "").replace("--", "/", 1)
            out.append(dict(id=repo, label=f"{repo} (HF cache)",
                            kind="hf_cache", path=str(snap),
                            size_gb=_dir_size_gb(snap), lock=None))
    return out


def _dir_size_gb(p: Path) -> float:
    total = 0
    for root, _dirs, files in os.walk(p):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return round(total / 1e9, 2)


def _lock_path_for(model_dir: Path) -> str | None:
    """Their lab records checksums/base_before.txt next to the model."""
    for cand in (model_dir / "checksums" / "base_before.txt",
                 model_dir.parent / "checksums" / "base_before.txt"):
        if cand.exists():
            return str(cand)
    return None


def _sha256_file(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def base_lock(model_dir: str, verify: bool = False) -> dict:
    """R1: report (and optionally verify) the base model's file digests.

    Verification is cached on (path, size, mtime) so an unchanged 30 GB base is
    not re-hashed on every page load.
    """
    d = Path(model_dir).expanduser()
    lock_file = _lock_path_for(d)
    res = dict(model=str(d), lock_file=lock_file, recorded={}, files=[],
               verified=None, checked_at=None, note="")
    if not d.exists():
        res["note"] = "model directory does not exist"
        return res
    if not lock_file:
        res["note"] = ("no recorded checksum for this model — HF cache blobs are "
                       "content-addressed, so there is nothing to drift")
        return res

    try:
        recorded = json.loads(Path(lock_file).read_text())
        res["recorded"] = recorded.get("files", {})
    except Exception as e:
        res["note"] = f"unreadable checksum file: {e}"
        return res

    cache = {}
    if CACHE_FILE.exists():
        try:
            cache = json.loads(CACHE_FILE.read_text())
        except Exception:
            cache = {}

    rows, all_ok = [], True
    for name, expect in res["recorded"].items():
        p = d / name
        if not p.exists():
            rows.append(dict(file=name, status="missing", expected=expect[:12]))
            all_ok = False
            continue
        st = p.stat()
        if not verify:
            # inventory only — never hash 30 GB just to draw a page
            rows.append(dict(file=name, status="unverified", expected=expect[:12],
                             size_mb=round(st.st_size / 1e6, 1),
                             modified=datetime.fromtimestamp(int(st.st_mtime)).isoformat(timespec="seconds")))
            continue
        key = f"{p}:{st.st_size}:{int(st.st_mtime)}"
        got = cache.get(key)
        if got is None:
            got = _sha256_file(p)
            cache[key] = got
        ok = (got == expect)
        all_ok &= ok
        rows.append(dict(file=name, status="match" if ok else "MISMATCH",
                         expected=expect[:12], actual=got[:12],
                         size_mb=round(st.st_size / 1e6, 1)))
    if verify:
        try:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            CACHE_FILE.write_text(json.dumps(cache))
        except Exception:
            pass
        res["files"] = rows
        res["verified"] = all_ok
        res["note"] = ("all files match the recorded base" if all_ok
                       else "MISMATCH — the base has been modified since it was recorded")
    else:
        res["files"] = rows
        res["verified"] = None
        res["note"] = (f"{len(rows)} files recorded · click Verify to hash them "
                       "against the lock")
    res["checked_at"] = datetime.now().isoformat(timespec="seconds")
    return res


# ── adapters ────────────────────────────────────────────────────────────────

def adapter_roots() -> list[Path]:
    roots = [ADAPTERS_DIR]
    for lab in KNOWN_LABS:
        if (lab / "adapters").is_dir():
            roots.append(lab / "adapters")
    return roots


def adapters_registry() -> list[dict]:
    out = []
    for root in adapter_roots():
        if not root.is_dir():
            continue
        for d in sorted(root.iterdir()):
            if not d.is_dir() or d.name.startswith("."):
                continue
            files = [f.name for f in d.rglob("*.safetensors")] + \
                    [f.name for f in d.iterdir() if f.is_file()]
            cfg = {}
            cfgf = d / "adapter_config.json"
            if cfgf.exists():
                try:
                    cfg = json.loads(cfgf.read_text())
                except Exception:
                    cfg = {}
            if (d / "adapters.safetensors").exists():
                fmt = "mlx_lm"                       # loadable by mlx_lm.server
            elif (d / "onepath.safetensors").exists():
                fmt = "skillforge-onepath"           # custom gated trainer output
            else:
                fmt = "unknown"
            newest = max((f.stat().st_mtime for f in d.rglob("*") if f.is_file()),
                         default=0)
            out.append(dict(
                name=d.name, path=str(d), root=str(root), format=fmt,
                size_mb=round(_dir_size_gb(d) * 1000, 1),
                modified=datetime.fromtimestamp(newest).isoformat(timespec="seconds") if newest else None,
                rank=(cfg.get("lora_parameters") or {}).get("rank") or cfg.get("r"),
                scale=(cfg.get("lora_parameters") or {}).get("scale") or cfg.get("lora_alpha"),
                num_layers=cfg.get("num_layers"),
                files=sorted(set(files))[:8],
            ))
    return out


# ── runs ────────────────────────────────────────────────────────────────────

def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._\-]+", "-", name).strip("-") or "run"


def _run_dir(name: str) -> Path:
    return RUNS_DIR / _slug(name)


def prepare_dataset(run_name: str, records, valid_ratio: float = 0.05,
                    seed: int = 0, max_tokens: int = 2048,
                    allow_flagged: bool = False) -> dict:
    """Write train/valid/test jsonl for a run from reviewed records.

    Uses the export gates: a dataset containing secrets, host paths, invalid
    tool JSON or oversize rows is refused unless allow_flagged is set.
    """
    from .export import validate_export

    rd = _run_dir(run_name)
    rd.mkdir(parents=True, exist_ok=True)

    v = validate_export(records, max_tokens=max_tokens)
    if not v["passed"] and not allow_flagged:
        return dict(ok=False, reason="dataset failed the training gates", validation=v,
                    run_dir=str(rd))

    import random
    rng = random.Random(seed)
    rows = list(records)
    rng.shuffle(rows)
    n_valid = max(1, int(len(rows) * valid_ratio)) if len(rows) > 1 else 0
    valid, train = rows[:n_valid], rows[n_valid:]

    def write(path: Path, rs):
        with open(path, "w", encoding="utf-8") as f:
            for r in rs:
                f.write(json.dumps({"messages": r.messages}, ensure_ascii=False) + "\n")

    write(rd / "train.jsonl", train)
    write(rd / "valid.jsonl", valid or train[:1])
    write(rd / "test.jsonl", valid or train[:1])
    return dict(ok=True, run_dir=str(rd), train=len(train), valid=len(valid),
                est_tokens=sum(r.est_tokens for r in rows), validation=v)


def build_command(model: str, run_dir: Path, adapter_path: Path, cfg: dict) -> list[str]:
    """Exact argv for mlx_lm.lora (flags verified against the installed CLI)."""
    cmd = [
        "mlx_lm.lora",
        "--model", model,
        "--train",
        "--data", str(run_dir),
        "--adapter-path", str(adapter_path),
        "--config", str(run_dir / "lora_config.yaml"),
        "--batch-size", str(cfg["batch_size"]),
        "--iters", str(cfg["iters"]),
        "--learning-rate", f"{cfg['learning_rate']:g}",
        "--num-layers", str(cfg["num_layers"]),
        "--max-seq-length", str(cfg["max_seq_length"]),
        "--grad-accumulation-steps", str(cfg["grad_accum"]),
        "--steps-per-report", str(cfg["steps_per_report"]),
        "--steps-per-eval", str(cfg["steps_per_eval"]),
        "--save-every", str(cfg["save_every"]),
        "--val-batches", str(cfg["val_batches"]),
        "--seed", str(cfg["seed"]),
    ]
    if cfg.get("mask_prompt", True):
        cmd.append("--mask-prompt")
    if cfg.get("grad_checkpoint"):
        cmd.append("--grad-checkpoint")
    return cmd


def lora_config_text(rank: int, alpha: int, dropout: float) -> str:
    """R6: scale is derived, never hand-set - scale = alpha / rank."""
    return ("# generated by SkillForge - R6: scale is derived from alpha/rank\n"
            "lora_parameters:\n"
            f"  rank: {rank}\n"
            f"  scale: {alpha / rank:g}\n"
            f"  dropout: {dropout:g}\n")


def write_lora_config(run_dir: Path, rank: int, alpha: int, dropout: float) -> dict:
    (run_dir / "lora_config.yaml").write_text(lora_config_text(rank, alpha, dropout))
    return dict(rank=rank, alpha=alpha, scale=alpha / rank, dropout=dropout)


def preview_command(run_name: str, model: str, cfg: dict) -> dict:
    """Exactly what would run - nothing started, nothing written.

    Pre-registration: read the command, the derived scale and the data checks
    before committing hours of GPU to it.
    """
    rd = _run_dir(run_name)
    adapter = ADAPTERS_DIR / _slug(run_name)
    cmd = build_command(model, rd, adapter, cfg)
    return dict(
        run_name=run_name, cmd=cmd, cmdline=shlex.join(cmd),
        lora_config=lora_config_text(cfg["rank"], cfg["alpha"], cfg.get("dropout", 0.0)),
        lora=dict(rank=cfg["rank"], alpha=cfg["alpha"],
                  scale=cfg["alpha"] / cfg["rank"], dropout=cfg.get("dropout", 0.0)),
        run_dir=str(rd), adapter_path=str(adapter),
        checks=dict(
            mlx_ok=bool(mlx_info().get("lora_cli")),
            model=model, model_ok=(Path(model).expanduser().exists() or "/" in model),
            train_rows=_count_lines(rd / "train.jsonl"),
            valid_rows=_count_lines(rd / "valid.jsonl"),
            running=is_running(run_name),
        ))


def start_run(run_name: str, model: str, cfg: dict) -> dict:
    """Launch a real mlx_lm training run. Fails closed, never fakes."""
    info = mlx_info()
    if not info.get("lora_cli"):
        return dict(ok=False, reason="mlx_lm.lora not found on PATH — install mlx-lm")
    rd = _run_dir(run_name)
    if not (rd / "train.jsonl").exists():
        return dict(ok=False, reason=f"no dataset prepared for run '{run_name}'"
                                     " — prepare a dataset first")
    if not (rd / "valid.jsonl").exists():
        return dict(ok=False, reason="valid.jsonl missing — cannot train without a holdout")
    if not (Path(model).expanduser().exists() or "/" in model):
        return dict(ok=False, reason=f"model not found: {model}")
    if is_running(run_name):
        return dict(ok=False, reason=f"run '{run_name}' is already training")

    ADAPTERS_DIR.mkdir(parents=True, exist_ok=True)
    adapter_path = ADAPTERS_DIR / re.sub(r"[^A-Za-z0-9._\-]+", "-", run_name)
    adapter_path.mkdir(parents=True, exist_ok=True)

    lora = write_lora_config(rd, cfg["rank"], cfg["alpha"], cfg.get("dropout", 0.0))
    cmd = build_command(model, rd, adapter_path, cfg)
    (rd / "command.txt").write_text(" ".join(shlex.quote(c) for c in cmd) + "\n")

    log = open(rd / "train.log", "w", encoding="utf-8")
    log.write(f"$ {shlex.join(cmd)}\n\n")
    log.flush()
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                            cwd=str(REPO_ROOT), start_new_session=True)
    _PROCS[run_name] = proc
    meta = dict(name=run_name, model=model, adapter_path=str(adapter_path), pid=proc.pid,
                started=datetime.now().isoformat(timespec="seconds"), cmd=cmd,
                cfg=cfg, lora=lora, status="running", run_dir=str(rd))
    (rd / "run.json").write_text(json.dumps(meta, indent=2))
    return dict(ok=True, run=meta)


def is_running(run_name: str) -> bool:
    proc = _PROCS.get(run_name)
    if proc is not None and proc.poll() is None:
        return True
    meta = _read_meta(run_name)
    pid = (meta or {}).get("pid")
    if pid:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    return False


def _read_meta(run_name: str) -> dict | None:
    f = _run_dir(run_name) / "run.json"
    if f.exists():
        try:
            return json.loads(f.read_text())
        except Exception:
            return None
    return None


def stop_run(run_name: str) -> dict:
    proc = _PROCS.get(run_name)
    if proc and proc.poll() is None:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        return dict(ok=True, stopped="process group")
    meta = _read_meta(run_name)
    if meta and meta.get("pid"):
        try:
            os.killpg(os.getpgid(meta["pid"]), signal.SIGTERM)
            return dict(ok=True, stopped=f"pid {meta['pid']}")
        except OSError as e:
            return dict(ok=False, reason=str(e))
    return dict(ok=False, reason="not running")


def run_status(run_name: str) -> dict:
    rd = _run_dir(run_name)
    meta = _read_meta(run_name) or dict(name=run_name, run_dir=str(rd))
    logf = rd / "train.log"
    train_pts, val_pts, tail, err = [], [], [], None
    if logf.exists():
        text = logf.read_text(errors="replace")
        for m in TRAIN_RE.finditer(text):
            train_pts.append(dict(iter=int(m.group("iter")), loss=float(m.group("loss")),
                                  lr=float(m.group("lr")) if m.group("lr") else None,
                                  it_sec=float(m.group("itsec")) if m.group("itsec") else None,
                                  tok_sec=float(m.group("toksec")) if m.group("toksec") else None,
                                  mem=float(m.group("mem")) if m.group("mem") else None))
        for m in VAL_RE.finditer(text):
            val_pts.append(dict(iter=int(m.group("iter")), loss=float(m.group("loss")),
                                secs=float(m.group("secs")) if m.group("secs") else None))
        tail = text.strip().splitlines()[-25:]
        if "Traceback" in text:
            err = "traceback in log"
        else:
            for ln in reversed(text.strip().splitlines()[-5:] or []):
                if re.match(r"^(Error|error|Exception|[A-Za-z_.]+Error):", ln.strip()):
                    err = ln.strip()[:200]
                    break
    proc = _PROCS.get(run_name)
    if proc is not None:
        code = proc.poll()
        status = "running" if code is None else ("finished" if code == 0 else "failed")
    else:
        code = None
        status = meta.get("status", "unknown")
        if is_running(run_name):
            status = "running"
        elif train_pts:
            status = "finished" if meta.get("status") != "failed" else "failed"
    if status == "running" and proc is None and not is_running(run_name):
        status = "stopped"
    return dict(**meta, status=status, exit_code=code, train=train_pts, val=val_pts,
                last_train=train_pts[-1] if train_pts else None,
                last_val=val_pts[-1] if val_pts else None,
                tail=tail, error=err,
                elapsed_s=_elapsed(meta.get("started"), status))


def _elapsed(started: str | None, status: str) -> float | None:
    if not started:
        return None
    try:
        t0 = datetime.fromisoformat(started)
    except Exception:
        return None
    if status == "running":
        return round((datetime.now() - t0).total_seconds(), 1)
    meta_end = None
    return None


def list_runs() -> list[dict]:
    if not RUNS_DIR.exists():
        return []
    out = []
    for d in sorted(RUNS_DIR.iterdir(), reverse=True):
        if not d.is_dir():
            continue
        st = run_status(d.name)
        out.append(dict(name=d.name, status=st.get("status"), model=st.get("model"),
                        adapter_path=st.get("adapter_path"),
                        last_train=st.get("last_train"), last_val=st.get("last_val"),
                        started=st.get("started"), run_dir=str(d),
                        data=dict(
                            train=_count_lines(d / "train.jsonl"),
                            valid=_count_lines(d / "valid.jsonl"))))
    return out


def _count_lines(p: Path) -> int:
    if not p.exists():
        return 0
    with open(p, "rb") as f:
        return sum(1 for _ in f)


def status_overview() -> dict:
    return dict(
        machine=dict(platform=sys.platform, python=sys.version.split()[0]),
        mlx=mlx_info(),
        models=discover_models(),
        adapters=adapters_registry(),
        runs=list_runs(),
        runs_dir=str(RUNS_DIR),
        adapters_dir=str(ADAPTERS_DIR),
    )
