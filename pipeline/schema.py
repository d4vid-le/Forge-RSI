"""
SkillForge pipeline — internal record model and ChatML rendering.

One internal shape for everything: a record is a list of {role, content}
messages plus provenance. Every loader converts into it, every cleaner flags it,
and every exporter renders from it. Nothing downstream needs to know which
original schema a row came from.

Target format is Qwen2.5-Coder ChatML:

    <|im_start|>system
    ...<|im_end|>
    <|im_start|>user
    ...<|im_end|>
    <|im_start|>assistant
    ...<|im_end|>
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, asdict

# ── Qwen / ChatML tokens ────────────────────────────────────────────────────
_L, _R = "<|", "|>"
IM_START = _L + "im_start" + _R
IM_END = _L + "im_end" + _R
TOOL_CALL_OPEN = "<tool_call>"
TOOL_CALL_CLOSE = "</tool_call>"


def _verify_tokens():
    """Fail loudly if the ChatML tokens are missing or malformed.

    A silent empty token here produces plausible-looking but untrainable text,
    so this is checked at import time rather than trusted.
    """
    for name, val, expect in (("IM_START", IM_START, "im_start"),
                              ("IM_END", IM_END, "im_end")):
        if not val or expect not in val:
            raise RuntimeError(
                f"[FORMAT] {name} is {val!r} - the ChatML token is missing. "
                f"Rendering would emit text the tokenizer cannot train on.")


_verify_tokens()

VALID_ROLES = ("system", "user", "assistant", "tool")

# role aliases seen across downloaded datasets
ROLE_ALIASES = {
    "human": "user", "user": "user", "prompt": "user", "instruction": "user",
    "gpt": "assistant", "assistant": "assistant", "bot": "assistant",
    "ai": "assistant", "model": "assistant", "response": "assistant",
    "system": "system", "sys": "system",
    "tool": "tool", "function": "tool", "observation": "tool",
    "tool_response": "tool", "toolresult": "tool",
}


@dataclass
class Record:
    """One training row, internal shape."""

    messages: list[dict]
    source_file: str = ""
    source_line: int = 0
    schema: str = "unknown"
    domain: str = "unknown"
    flags: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    row_id: int | None = None          # assigned by the store
    decision: str = "pending"          # pending | accepted | rejected | edited

    # ── derived ─────────────────────────────────────────────────────────────
    @property
    def raw_text(self) -> str:
        return "\n".join(m.get("content") or "" for m in self.messages)

    @property
    def char_len(self) -> int:
        return len(render_chatml(self.messages))

    @property
    def est_tokens(self) -> int:
        """Cheap token estimate (chars/4). Use tokenizer for exact counts."""
        return max(1, self.char_len // 4)

    @property
    def dedupe_hash(self) -> str:
        """Key for duplicate detection: normalised message text."""
        blob = "\n".join(
            f"{m.get('role')}:{norm_ws(m.get('content') or '')}" for m in self.messages
        )
        return hashlib.md5(blob.encode("utf-8", "replace")).hexdigest()

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Record":
        return Record(**d)


def norm_ws(s: str) -> str:
    """Collapse whitespace and lowercase — duplicate detection only."""
    return re.sub(r"\s+", " ", s or "").strip().lower()


def canonical_role(role: str) -> str | None:
    return ROLE_ALIASES.get((role or "").strip().lower())


def content_to_text(content) -> str:
    """Normalise OpenAI-style content (str | list of parts | None) to text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict):
                # {"type":"text","text":...} | {"type":"input_text",...}
                parts.append(p.get("text") or p.get("content") or "")
        return "\n".join(x for x in parts if x)
    return str(content)


def tool_calls_to_text(tool_calls) -> str:
    """Render OpenAI tool_calls into the <tool_call> block the trainer expects."""
    if not tool_calls:
        return ""
    if isinstance(tool_calls, dict):          # single function_call
        tool_calls = [tool_calls]
    out = []
    for call in tool_calls:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") if isinstance(call.get("function"), dict) else None
        name = (fn or {}).get("name") or call.get("name") or ""
        args = (fn or {}).get("arguments", call.get("arguments", {}))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except Exception:
                args = {"raw": args}
        out.append(
            TOOL_CALL_OPEN
            + json.dumps({"name": name, "arguments": args}, ensure_ascii=False)
            + TOOL_CALL_CLOSE
        )
    return "\n".join(out)


def normalize_messages(msgs: list) -> list[dict]:
    """Convert any message list into canonical {role, content} form.

    Handles OpenAI tool_calls / function_call and content-as-parts; skips
    roleless entries rather than inventing a role.
    """
    out: list[dict] = []
    for m in msgs or []:
        if not isinstance(m, dict):
            continue
        role = canonical_role(m.get("role") or m.get("from") or m.get("speaker") or "")
        if role is None:
            continue
        content = content_to_text(m.get("content", m.get("value", m.get("text"))))
        extra = tool_calls_to_text(m.get("tool_calls") or m.get("function_call"))
        if extra:
            content = (content + "\n" + extra).strip() if content else extra
        if not content.strip():
            continue                      # empty turns carry no signal
        out.append({"role": role, "content": content})
    return out


def render_chatml(messages: list[dict], add_generation_prompt: bool = False) -> str:
    """Render messages into ChatML text (the onepath / completion format)."""
    parts = []
    for m in messages:
        parts.append(f"{IM_START}{m['role']}\n{m['content']}{IM_END}\n")
    if add_generation_prompt:
        parts.append(f"{IM_START}assistant\n")
    return "".join(parts)


CHATML_TURN = re.compile(
    r"<\|im_start\|>(?P<role>[a-zA-Z_]+)\n(?P<content>.*?)(?:<\|im_end\|>|$)", re.DOTALL
)

# Lenient fallback: known roles only, newline after the role optional. Used
# exclusively by parse_chatml's second pass (see its docstring).
CHATML_TURN_LENIENT = re.compile(
    r"<\|im_start\|>(?P<role>system|user|assistant|tool)\n?(?P<content>.*?)(?:<\|im_end\|>|$)",
    re.DOTALL
)


def parse_chatml(text: str) -> list[dict]:
    """Parse ChatML-rendered text back into messages.

    Much of the existing corpora stores a whole conversation in one `text`
    field with full ChatML markup — that must be re-normalised into turns, not
    kept as raw prose.

    Two passes. Pass 1 is the strict historical form (role line terminated by
    newline) and is byte-for-byte the old behaviour. Pass 2 runs ONLY when pass
    1 finds no user turn: some frozen corpora (e.g. hermes-family frames) abut
    content directly against the role marker with no newline, and strict parsing
    then silently merges the user turn into system. Pass 2 accepts only known
    role names so prose can never invent a role.
    """
    msgs = []
    for m in CHATML_TURN.finditer(text or ""):
        role = canonical_role(m.group("role"))
        if role is None:
            continue
        content = m.group("content").replace(IM_END, "").strip()
        if content:
            msgs.append({"role": role, "content": content})
    if not any(m["role"] == "user" for m in msgs) and (text or "").count(IM_START) >= 2:
        retry = []
        for m in CHATML_TURN_LENIENT.finditer(text):
            role = canonical_role(m.group("role"))
            if role is None:
                continue
            content = m.group("content").replace(IM_END, "").strip()
            if content:
                retry.append({"role": role, "content": content})
        if any(m["role"] == "user" for m in retry):
            return retry
    return msgs


def looks_like_chatml(text: str) -> bool:
    return bool(text) and text.count(IM_START) >= 2


LONE_SURROGATE = re.compile(r"[\ud800-\udfff]")


def strip_surrogates(text: str) -> str:
    """Remove lone surrogates — they are unrenderable and break UTF-8 writes."""
    return LONE_SURROGATE.sub("", text or "")


def json_safe(obj) -> str:
    """json.dumps that can never raise on unpaired surrogates.

    Lone surrogates arrive from real downloads (split emoji) and would otherwise
    crash SQLite/file writes far from the defect. We strip them at the boundary
    and let the cleaner report them as a defect.
    """
    return LONE_SURROGATE.sub("", json.dumps(obj, ensure_ascii=False))


def validate_messages(msgs: list[dict]) -> list[str]:
    """Structural problems worth flagging for human review."""
    problems = []
    if not msgs:
        return ["empty_record"]
    roles = [m["role"] for m in msgs]
    if "assistant" not in roles:
        problems.append("no_assistant_turn")
    if "user" not in roles:
        problems.append("no_user_turn")
    if roles[0] == "assistant":
        problems.append("starts_with_assistant")
    for m in msgs:
        if m["role"] not in VALID_ROLES:
            problems.append("bad_role")
            break
    return problems
