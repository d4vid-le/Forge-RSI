"""Deterministic verifier: run a candidate solution against hidden unittest tests.

The candidate only ever writes `solution.py` inside a throwaway temp dir. The
test module lives beside it for the duration of the subprocess and is never
returned to the model — only a short failure line is.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import time
from pathlib import Path


def _classify(output: str) -> str:
    if "SyntaxError" in output or "IndentationError" in output:
        return "syntax"
    if "ModuleNotFoundError" in output or "ImportError" in output:
        return "import"
    if "AssertionError" in output:
        return "assertion"
    if "FAILED" in output or "Error" in output:
        return "runtime"
    return "unknown"


def verify(code: str, task: dict, python_exe: str | None = None,
           timeout_s: int | None = None) -> dict:
    """Return {passed, output, error_class, seconds}."""
    t0 = time.time()
    if not code or not code.strip():
        return {"passed": False, "output": "empty solution", "error_class": "empty",
                "seconds": 0.0}

    timeout_s = timeout_s or int(task.get("timeout_s", 20))
    exe = python_exe or sys.executable
    with tempfile.TemporaryDirectory(prefix="forge_rsi_") as td:
        td = Path(td)
        (td / "solution.py").write_text(code.rstrip() + "\n")
        (td / "test_solution.py").write_text(task["tests"].rstrip() + "\n")
        try:
            p = subprocess.run(
                [exe, "-m", "unittest", "-q", "test_solution"],
                cwd=td, capture_output=True, text=True, timeout=timeout_s,
            )
            output = (p.stderr or "") + (p.stdout or "")
            passed = p.returncode == 0
            error_class = "none" if passed else _classify(output)
        except subprocess.TimeoutExpired:
            output = f"timeout after {timeout_s}s"
            passed = False
            error_class = "timeout"
        except Exception as e:  # pragma: no cover - defensive
            output = f"verifier error: {e!r}"
            passed = False
            error_class = "verifier"
    return {
        "passed": passed,
        "output": output[-3000:],
        "error_class": error_class,
        "seconds": round(time.time() - t0, 3),
    }


def short_feedback(output: str, limit: int = 400) -> str:
    """Keep the useful tail of a unittest failure, nothing else."""
    lines = [ln.strip() for ln in output.splitlines() if ln.strip()]
    if not lines:
        return "no output"
    # Prefer the final assertion/error block.
    tail = "\n".join(lines[-4:])
    return tail[-limit:]
