"""SkillForge Ops — a read-only local dashboard.

Run:
    uvicorn dashboard.app:app --host 127.0.0.1 --port 8765
or:
    python -m forge_rsi dashboard
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse

from forge_rsi import config as cfgmod

from .status import collect

app = FastAPI(title="SkillForge Ops", version="0.1.0")

try:
    CFG = cfgmod.load()
except Exception as exc:  # config.toml missing or unreadable
    CFG = None
    CFG_ERROR = str(exc)
else:
    CFG_ERROR = None

STATIC = Path(__file__).resolve().parent / "static"


@app.get("/api/health")
def health():
    return {"ok": True, "configured": CFG is not None}


@app.get("/api/status")
def status():
    if CFG is None:
        return {"error": f"config not loaded: {CFG_ERROR}",
                "hint": "cp config.example.toml config.toml and edit the model paths"}
    return collect(CFG)


@app.get("/api/report/{name}", response_class=PlainTextResponse)
def report(name: str):
    if CFG is None:
        raise HTTPException(status_code=503, detail="config not loaded")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+\.md", name):
        raise HTTPException(status_code=400, detail="invalid report name")
    root = Path(CFG["paths"]["reports"]).resolve()
    path = (root / name).resolve()
    if root not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="report not found")
    return path.read_text()


@app.get("/", response_class=HTMLResponse)
def index():
    return (STATIC / "index.html").read_text()
