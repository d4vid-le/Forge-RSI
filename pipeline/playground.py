"""
SkillForge — Playground stage (eval / chat tester).

Real inference only. Nothing here fabricates a token or a score:

  * endpoints are discovered by probing (Ollama on 11434, mlx_lm.server on 8080)
  * timings are measured from the server's own reported durations
  * the robustness probe runs one greedy sample plus N at temperature 0.3 and
    reports the observed agreement with a Wilson confidence interval
  * if no server answers, the stage says so and shows how to start one — it
    never invents a reply

`mlx_lm.server` can be started from here with an adapter attached, which is how
a trained adapter gets exercised end to end.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOGS_DIR = REPO_ROOT / "runs"

OLLAMA_URL = "http://127.0.0.1:11434"
MLX_PORTS = [8080, 8081]

_SERVERS: dict[int, subprocess.Popen] = {}


# ── http helpers ────────────────────────────────────────────────────────────

def _post(url: str, payload: dict, timeout: float = 300.0) -> dict:
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _get(url: str, timeout: float = 5.0):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


# ── discovery ───────────────────────────────────────────────────────────────

def discover() -> list[dict]:
    """Probe for local inference servers. Only reachable ones are returned."""
    found = []
    try:
        tags = _get(f"{OLLAMA_URL}/api/tags", timeout=2.0)
        models = [m["name"] for m in tags.get("models", [])]
        found.append(dict(kind="ollama", url=OLLAMA_URL, label="Ollama",
                          models=models, adapter_support=False))
    except Exception:
        pass
    for port in MLX_PORTS:
        base = f"http://127.0.0.1:{port}"
        try:
            info = _get(f"{base}/v1/models", timeout=1.5)
            models = [m.get("id") for m in info.get("data", [])]
            found.append(dict(kind="openai", url=base, label=f"mlx_lm.server:{port}",
                              models=models, adapter_support=True))
        except Exception:
            pass
    return found


def _pick(endpoint: str, kind: str | None) -> tuple[str, str]:
    """Resolve a requested endpoint; auto-select if not given."""
    if endpoint:
        for e in discover():
            if e["url"] == endpoint:
                return e["url"], e["kind"]
        return endpoint, kind or ("ollama" if "11434" in endpoint else "openai")
    found = discover()
    if not found:
        raise RuntimeError("no local inference server found — start Ollama or "
                           "mlx_lm.server, or launch one from this page")
    return found[0]["url"], found[0]["kind"]


# ── chat ────────────────────────────────────────────────────────────────────

def chat(messages: list[dict], model: str | None = None, endpoint: str | None = None,
         kind: str | None = None, temperature: float = 0.3, max_tokens: int = 512,
         timeout: float = 300.0) -> dict:
    """One real completion. Timings come from the server, not from guesses."""
    url, kind = _pick(endpoint or "", kind)
    t0 = time.time()

    if kind == "ollama":
        model = model or (discover()[0]["models"] or [None])[0]
        if not model:
            raise RuntimeError("no model available on the Ollama endpoint")
        resp = _post(f"{url}/api/chat", dict(
            model=model, messages=messages, stream=False,
            options=dict(temperature=temperature, num_predict=max_tokens)),
            timeout=timeout)
        text = (resp.get("message") or {}).get("content", "")
        load_ns = resp.get("load_duration") or 0
        prompt_ns = resp.get("prompt_eval_duration") or 0
        eval_ns = resp.get("eval_duration") or 0
        n_out = resp.get("eval_count") or 0
        ttft_ms = (load_ns + prompt_ns) / 1e6 if (load_ns or prompt_ns) else None
        tok_s = (n_out / (eval_ns / 1e9)) if eval_ns else None
        usage = dict(prompt_tokens=resp.get("prompt_eval_count"), completion_tokens=n_out)
        raw = {k: v for k, v in resp.items() if k != "message"}
    else:
        model = model or "default"
        resp = _post(f"{url}/v1/chat/completions", dict(
            model=model, messages=messages, temperature=temperature,
            max_tokens=max_tokens, stream=False), timeout=timeout)
        text = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content", "")
        usage = resp.get("usage") or {}
        wall = time.time() - t0
        n_out = usage.get("completion_tokens") or 0
        ttft_ms = None                       # not observable without streaming
        tok_s = (n_out / wall) if (wall > 0 and n_out) else None
        raw = {k: v for k, v in resp.items() if k != "choices"}

    return dict(text=text, model=model, endpoint=url, kind=kind,
                wall_ms=round((time.time() - t0) * 1000, 1),
                ttft_ms=round(ttft_ms, 1) if ttft_ms else None,
                tok_s=round(tok_s, 1) if tok_s else None,
                usage=usage, raw=raw,
                at=datetime.now().isoformat(timespec="seconds"))


# ── robustness probe (R3) ───────────────────────────────────────────────────

def normalize_answer(s: str) -> str:
    """Comparison form for agreement — the observed string, not a model score."""
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def wilson_ci(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / d
    return (max(0.0, centre - half), min(1.0, centre + half))


def probe(messages: list[dict], n_samples: int = 6, temperature: float = 0.3,
          model: str | None = None, endpoint: str | None = None, kind: str | None = None,
          max_tokens: int = 512) -> dict:
    """R3: greedy baseline + N samples at temperature; report real agreement."""
    greedy = chat(messages, model, endpoint, kind, temperature=0.0, max_tokens=max_tokens)
    target = normalize_answer(greedy["text"])
    samples = []
    for i in range(n_samples):
        try:
            r = chat(messages, greedy["model"], endpoint, kind, temperature=temperature,
                     max_tokens=max_tokens)
            samples.append(dict(ok=True, text=r["text"], tok_s=r["tok_s"],
                                matches=normalize_answer(r["text"]) == target))
        except Exception as e:
            samples.append(dict(ok=False, error=str(e), matches=False))
    good = [s for s in samples if s["ok"]]
    matches = sum(1 for s in good if s["matches"])
    lo, hi = wilson_ci(matches, len(good)) if good else (0.0, 0.0)
    return dict(greedy=greedy, target=target, samples=samples,
                n=len(good), matches=matches, temperature=temperature,
                agreement=(matches / len(good)) if good else None,
                wilson=(lo, hi), at=datetime.now().isoformat(timespec="seconds"))


# ── mlx server control (adapter testing) ────────────────────────────────────

def start_mlx_server(model: str, adapter_path: str | None = None,
                     port: int = 8080) -> dict:
    import shutil
    cli = shutil.which("mlx_lm.server")
    if not cli:
        return dict(ok=False, reason="mlx_lm.server not found on PATH")
    if server_status(port).get("running"):
        return dict(ok=False, reason=f"a server is already listening on {port}")
    if adapter_path and not Path(adapter_path).expanduser().exists():
        return dict(ok=False, reason=f"adapter path not found: {adapter_path}")
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"mlx_server_{port}.log"
    cmd = [cli, "--model", model, "--host", "127.0.0.1", "--port", str(port)]
    if adapter_path:
        cmd += ["--adapter-path", str(Path(adapter_path).expanduser())]
    log = open(log_path, "w", encoding="utf-8")
    log.write(f"$ {' '.join(cmd)}\n\n")
    log.flush()
    proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                            start_new_session=True)
    _SERVERS[port] = proc
    return dict(ok=True, pid=proc.pid, port=port, cmd=cmd, log=str(log_path),
                note="loading the model can take a minute on 14B — poll status")


def server_status(port: int = 8080) -> dict:
    try:
        info = _get(f"http://127.0.0.1:{port}/v1/models", timeout=1.5)
        return dict(running=True, port=port, models=[m.get("id") for m in info.get("data", [])])
    except Exception:
        proc = _SERVERS.get(port)
        log = LOGS_DIR / f"mlx_server_{port}.log"
        tail = log.read_text(errors="replace").strip().splitlines()[-8:] if log.exists() else []
        return dict(running=False, port=port,
                    starting=bool(proc and proc.poll() is None),
                    pid=proc.pid if proc else None, tail=tail)


def stop_mlx_server(port: int = 8080) -> dict:
    import os, signal
    proc = _SERVERS.get(port)
    if proc and proc.poll() is None:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        return dict(ok=True, stopped=port)
    return dict(ok=False, reason="no server started by SkillForge on that port")


def status_overview() -> dict:
    return dict(endpoints=discover(), servers={p: server_status(p) for p in MLX_PORTS})
