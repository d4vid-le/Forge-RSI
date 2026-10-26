"""
SkillForge pipeline — cleaning and defect flagging.

This is the curation protocol expressed as code. Every defect the MiMo audit
found in real downloaded data is detected here and surfaced as a named flag, so
the human review pass is driven by evidence instead of by vibes.

Policy (matching the protocol):
  * SYNTAX-ONLY tool-call damage (trailing comma, unescaped backslash, stray
    control char) is REPAIRED — the content is intact.
  * TRUNCATION damage (mid-string cut, missing delimiter) is REMOVED together
    with its observation — the content is gone and "repairing" it would teach
    the model to emit cut-off commands.
  * Secrets are MASKED and logged for rotation. Host paths are neutralised.
  * Nothing is dropped here. Everything gets flagged; the human decides.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass

from .schema import Record, validate_messages, norm_ws

# ── tool schema (Qwen harness executor) ─────────────────────────────────────

DEFAULT_SCHEMA_TOOLS = {
    "ls", "read", "write", "edit", "glob", "grep", "bash", "multiedit",
    "notebookread", "notebookedit", "todowrite", "todoread", "webfetch",
    "websearch", "question", "task",
}

# tools that only exist inside someone else's harness — never executable here
INTERNAL_TOOLS = {
    "askuserquestion", "enterplanmode", "exitplanmode", "taskoutput",
    "taskstop", "writepythonscript", "senduserfile",
}

TOOL_CALL_RE = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
PLACEHOLDER_JSON = re.compile(
    r"\{json\}|\{name\}|\{arguments\}|<function-name>|<args-json-object>|"
    r"<tool_name>|<parameters>", re.I)

SECRETS = re.compile(
    r"(?:sk-ant-[A-Za-z0-9\-_]{20,}|sk-unsloth-[A-Za-z0-9\-_]{12,}|"
    r"sk-[A-Za-z0-9]{20,}|hf_[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|"
    r"gho_[A-Za-z0-9]{20,}|xox[baprs]-[A-Za-z0-9\-]{10,}|"
    r"AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z\-_]{30,}|"
    r"Bearer\s+[A-Za-z0-9\-._~+/]{20,}=*|"
    r"-----BEGIN[A-Z ]*PRIVATE KEY-----)"
)

# real host paths (placeholders like /home/user/app are legitimate and skipped)
HOSTPATH = re.compile(
    r"(?:/Users/(?!(?:user|username|yourname|you|me|someone|example|agent)\b)[A-Za-z0-9._\-]+|"
    r"/home/(?!(?:user|username|yourname|you|me|someone|example|agent|ubuntu|runner)\b)[A-Za-z0-9._\-]+|"
    r"/private/var/folders/[A-Za-z0-9_/\-]+|"
    r"/data/agent/[A-Za-z0-9._\-]+|"
    r"[A-Z]:\\\\Users\\\\[A-Za-z0-9._\-]+)"
)

MOJIBAKE = re.compile(r"[ÃÂ][\x80-\xbf]|â€[™œ\x9d\x9c]|\ufffd")
LONE_SURROGATE = re.compile(r"[\ud800-\udfff]")

VALID_ESC = set('"\\/bfnrtu')
SYNTAX_ONLY = {"unescaped_backslash", "trailing_comma", "raw_control_char"}

REDACTED = "<REDACTED>"


def iter_call_bodies(content: str):
    """Yield NON-EMPTY tool-call JSON bodies from a message.

    Empty pairs (`<tool_call></tool_call>`) are how a system prompt documents the
    format - they are not malformed calls and must never be reported as defects.
    The cleaner and the export validator both use this helper so they cannot
    disagree about what counts as a defect.
    """
    for m in TOOL_CALL_RE.finditer(content or ""):
        body = m.group(1).strip()
        if body:
            yield body


@dataclass
class CleanOptions:
    fix_tool_calls: bool = True        # syntax-only repairs
    remove_truncated: bool = True      # remove truncated call + its observation
    mask_secrets: bool = True
    flag_hostpaths: bool = True
    strict_tools: bool = False         # flag any non-schema tool name
    max_tokens: int = 4096
    min_chars: int = 20
    dedupe: str = "both"               # both | exact | normalized | none


# ── tool-call JSON diagnosis ────────────────────────────────────────────────

def classify_json_failure(body: str) -> str | None:
    """Name the defect of an unparseable tool-call body."""
    try:
        json.loads(body)
        return None
    except Exception as e:
        msg = str(e)
    if "Unterminated string" in msg:
        return "truncated_mid_string"
    if "Invalid \\escape" in msg:
        return "unescaped_backslash"
    if "trailing comma" in msg:
        return "trailing_comma"
    if "control character" in msg:
        return "raw_control_char"
    if "Expecting" in msg and "delimiter" in msg:
        return "truncated_or_missing_delimiter"
    if "Extra data" in msg:
        return "trailing_data"
    if "Expecting value" in msg:
        return "malformed_json"
    return "other_invalid_json"


def repair_tool_json(body: str, allow_truncated: bool = False):
    """Repair syntax-only damage. Returns (obj, reason) — obj None if unsafe."""
    s = body.strip()
    mode = classify_json_failure(s)
    if mode is None:
        try:
            return json.loads(s), None
        except Exception:
            return None, "malformed_json"
    if mode not in SYNTAX_ONLY and not allow_truncated:
        return None, mode                       # content is gone — do not invent

    s2 = re.sub(r",\s*([}\]])", r"\1", s)       # trailing commas
    out, i, in_str = [], 0, False               # escape stray backslashes
    while i < len(s2):
        ch = s2[i]
        if ch == '"':
            in_str = not in_str
            out.append(ch); i += 1; continue
        if ch == "\\" and in_str:
            nxt = s2[i + 1] if i + 1 < len(s2) else ""
            if nxt in VALID_ESC:
                out.append(ch); out.append(nxt); i += 2; continue
            out.append("\\\\"); i += 1; continue
        out.append(ch); i += 1
    s2 = "".join(out)
    for cand in (s2, s2 + '"', s2 + "}", s2 + '"}', s2 + '"}}'):
        try:
            obj = json.loads(cand)
        except Exception:
            continue
        if isinstance(obj, dict) and (obj.get("name") or obj.get("tool")):
            return obj, None
    return None, mode


def tool_name(body: str) -> str:
    try:
        obj = json.loads(body)
    except Exception:
        return ""
    name = obj.get("name") or obj.get("tool") or ""
    return str(name)


# ── per-record cleaning ─────────────────────────────────────────────────────

def _clean_assistant_tools(content: str, opts: CleanOptions, stats: Counter):
    """Repair or strip tool calls inside one assistant turn."""
    def sub(m):
        body = m.group(1).strip()
        if not body.startswith("{"):
            return m.group(0)
        mode = classify_json_failure(body)
        if mode is None:
            return m.group(0)                    # already valid
        obj, reason = repair_tool_json(body, allow_truncated=False)
        if obj is not None and opts.fix_tool_calls:
            stats["tool_calls_repaired"] += 1
            stats[f"repaired:{reason}"] += 1
            return "<tool_call>" + json.dumps(obj, ensure_ascii=False) + "</tool_call>"
        if opts.remove_truncated:
            stats["tool_calls_removed"] += 1
            stats[f"removed:{reason}"] += 1
            return ""
        return m.group(0)

    return TOOL_CALL_RE.sub(sub, content)


def clean_record(rec: Record, opts: CleanOptions, stats: Counter,
                 seen_exact: dict, seen_norm: dict) -> Record:
    """Clean one record in place; return it with flags populated."""
    flags = set(rec.flags)

    # ── text hygiene on every turn ──────────────────────────────────────────
    for m in rec.messages:
        c = m.get("content") or ""

        if LONE_SURROGATE.search(c):
            c = LONE_SURROGATE.sub("", c)
            flags.add("lone_surrogate")
            stats["lone_surrogate"] += 1

        if MOJIBAKE.search(c):
            flags.add("mojibake")
            stats["mojibake"] += 1

        if SECRETS.search(c):
            flags.add("secret")
            stats["secret"] += 1
            if opts.mask_secrets:
                for hit in SECRETS.finditer(c):
                    stats[f"secret_kind:{hit.group(0)[:10]}"] += 1
                c = SECRETS.sub(REDACTED, c)
                flags.add("secret_masked")

        if opts.flag_hostpaths and HOSTPATH.search(c):
            flags.add("hostpath")
            stats["hostpath"] += 1

        # Placeholders are only dangerous in turns the model reads as data or
        # learns to generate (user/assistant). Frozen system prompts legitimately
        # carry schema templates (e.g. the hermes frame's `<function-name>`), which
        # must stay byte-exact — flagging them would punish the training format.
        if m["role"] != "system" and PLACEHOLDER_JSON.search(c):
            flags.add("placeholder_json")
            stats["placeholder_json"] += 1

        if m["role"] == "assistant":
            if "<tool_call>" in c:
                rep0, rem0 = stats["tool_calls_repaired"], stats["tool_calls_removed"]
                new = _clean_assistant_tools(c, opts, stats)
                if new != c:
                    c = new
                if stats["tool_calls_repaired"] > rep0:
                    flags.add("tool_calls_repaired")
                if stats["tool_calls_removed"] > rem0:
                    flags.add("tool_calls_removed")
            # think-tag contract: opening tag is often implied, closing required
            opens, closes = c.count(" thinking"), c.count("</think>")
            if closes - opens > 1:
                flags.add("think_stray_close")
                stats["think_stray_close"] += 1
            elif opens > closes:
                flags.add("think_unclosed")
                stats["think_unclosed"] += 1

        m["content"] = c

    # If removing a truncated call emptied an assistant turn, its observation
    # has to go with it. An orphan result teaches the model to invent outcomes
    # before acting — the exact defect that poisoned the v4 agent corpus.
    kept, drop_following_tools = [], False
    for m in rec.messages:
        if m["role"] == "assistant":
            if not m["content"].strip():
                stats["assistant_turn_emptied"] += 1
                flags.add("turn_emptied_by_removal")
                drop_following_tools = True
                continue
            drop_following_tools = False
            kept.append(m)
        elif m["role"] == "tool" and drop_following_tools:
            stats["orphan_observations_removed"] += 1
            flags.add("orphan_observation")
            continue
        else:
            drop_following_tools = False
            if m["content"].strip():
                kept.append(m)
    rec.messages = kept

    # ── structure ───────────────────────────────────────────────────────────
    for p in validate_messages(rec.messages):
        flags.add(p)
    if not rec.messages:
        stats["empty_record"] += 1

    # orphan observation: a tool turn with no preceding tool call
    seen_call = False
    for m in rec.messages:
        if m["role"] == "assistant" and "<tool_call>" in m["content"]:
            seen_call = True
        if m["role"] == "tool" and not seen_call:
            flags.add("orphan_observation")
            stats["orphan_observation"] += 1
            break

    # ── tool vocabulary ─────────────────────────────────────────────────────
    tools = []
    for m in rec.messages:
        if m["role"] != "assistant":
            continue
        for body in TOOL_CALL_RE.findall(m["content"]):
            nm = tool_name(body.strip())
            if nm:
                tools.append(nm)
    if tools:
        rec.meta["tools"] = sorted(set(tools))
        lowered = {t.lower() for t in tools}
        if lowered & INTERNAL_TOOLS:
            flags.add("internal_tool")
            stats["internal_tool"] += 1
        if opts.strict_tools:
            unknown = [t for t in lowered if t not in DEFAULT_SCHEMA_TOOLS]
            if unknown:
                flags.add("unknown_tool")
                stats["unknown_tool"] += 1

    # ── size gates ──────────────────────────────────────────────────────────
    if rec.est_tokens > opts.max_tokens:
        flags.add("oversize")
        stats["oversize"] += 1
    if rec.char_len < opts.min_chars:
        flags.add("short")
        stats["short"] += 1

    # ── duplicates ──────────────────────────────────────────────────────────
    if opts.dedupe != "none":
        ex = rec.dedupe_hash
        if opts.dedupe in ("both", "exact"):
            blob = json.dumps(rec.messages, ensure_ascii=False, sort_keys=True)
            if blob in seen_exact:
                flags.add("duplicate_exact")
                rec.meta["duplicate_of"] = seen_exact[blob]
                stats["duplicate_exact"] += 1
            else:
                seen_exact[blob] = f"{rec.source_file}:{rec.source_line}"
        if opts.dedupe in ("both", "normalized"):
            if ex in seen_norm:
                if "duplicate_exact" not in flags:
                    flags.add("duplicate_normalized")
                    rec.meta["duplicate_of"] = seen_norm[ex]
                    stats["duplicate_normalized"] += 1
            else:
                seen_norm[ex] = f"{rec.source_file}:{rec.source_line}"

    rec.flags = sorted(flags)
    return rec


def clean_records(records: list[Record], opts: CleanOptions | None = None):
    """Clean a list of records. Returns (records, stats)."""
    opts = opts or CleanOptions()
    stats: Counter = Counter()
    seen_exact: dict = {}
    seen_norm: dict = {}
    for rec in records:
        clean_record(rec, opts, stats, seen_exact, seen_norm)
    stats["rows_in"] = len(records)
    stats["rows_flagged"] = sum(1 for r in records if r.flags)
    stats["rows_clean"] = sum(1 for r in records if not r.flags)
    return records, stats


def flag_summary(records: list[Record]) -> dict:
    """Counts per flag — the picture the review UI opens with."""
    counts: Counter = Counter()
    for r in records:
        for f in r.flags:
            counts[f] += 1
    return dict(counts.most_common())
