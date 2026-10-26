# SkillForge pipeline — Stage 1 (data)

Turns downloaded data in any shape into one clean training file, with a
line-by-line human review pass in between. No third-party dependencies
(Python 3.11+ standard library only).

```bash
./sf import ~/Downloads/dataset/*.json --session-name "my batch"
./sf stats   sf_20260913_085236
./sf accept  sf_20260913_085236 --all-clean          # keep every clean row
./sf reject  sf_20260913_085236 --where flag=secret
./sf show    42                                      # inspect one line
./sf export  sf_20260913_085236 --out ./exports
```

## What import does

* Reads **many files at once** — JSON arrays, JSONL, nested containers
  (`{"data":[...]}`), whole directories and globs.
* Auto-detects the shape of each row and normalises it: OpenAI `messages`,
  sharegpt `conversations`, `prompt`/`response` pairs, alpaca
  `instruction`/`input`/`output`, and ChatML stored in a `text` field.
* Converts everything to one internal form: a list of `{role, content}` turns
  rendered as Qwen ChatML.
* Flags every defect it finds (see below) instead of silently dropping rows.
* Loads rows it cannot understand into a quarantine table with the reason.

## Defect flags you will review

| flag | meaning | policy |
|---|---|---|
| `tool_calls_removed` | tool call truncated mid-JSON (content lost) | removed with its observation |
| `tool_calls_repaired` | trailing comma / unescaped backslash | repaired, content intact |
| `orphan_observation` | tool result with no preceding call | removed; teaches invented results |
| `secret` + `secret_masked` | API key/token in the row | masked; **rotate the key** |
| `hostpath` | real machine path (users' names, home dirs) | flagged for rewrite |
| `duplicate_exact` / `duplicate_normalized` | repeat row | dropped at export |
| `mojibake`, `lone_surrogate` | broken encoding | flagged / stripped |
| `placeholder_json` | schema placeholder (`{json}`, `<function-name>`) | junk, reject |
| `oversize` | beyond `--max-tokens` (default 4096) | review; do not train truncated targets |
| `no_assistant_turn`, `turn_emptied_by_removal` | structure broken by cleaning | reject |
| `think_stray_close`, `think_unclosed` | malformed reasoning tags | review |
| `internal_tool`, `unknown_tool` (`--strict-tools`) | tool the runtime cannot execute | map or reject |

## Review model

Every import is a **session** in `data/skillforge.db`. Decisions are stored as
data, so review is resumable and every export is reproducible:

* `accept` — kept (`--all-clean` accepts every unflagged pending row at once)
* `reject` — dropped; still recorded, and written to the export's
  `.rejected.jsonl` bundle with the reason
* rejections and quarantines are never deleted

## Export

```bash
./sf export <session> --out ./exports --include accepted --format both --sort domain
```

Writes one auto-named file plus its paperwork:

* `mixed-3dom__1200rows__480ktok__20260913-0900__clean.jsonl`
* `….manifest.json` — sources, config, counts, sha256, validation result
* `….report.md` — human-readable summary of what was exported and why
* `….rejected.jsonl` — every rejected row + everything quarantined at load

`--format messages` (mlx-lm chat), `chatml` (rendered text), or `both`.
Exports are **fail-closed**: if secrets, host paths, invalid tool JSON, orphan
observations, oversize rows, or a broken ChatML render survive into the output,
the command reports the violations and exits non-zero unless you pass
`--allow-flagged` to accept them knowingly.

## Known constraint

Control-token literals such as the ChatML markers are built from parts in
`schema.py` and verified at import time. Terminal/tool output can *display*
those tokens as empty strings, so verify format with lengths and character
codes, not by eye — `python3 -c "import pipeline.schema as s; print(len(s.IM_START))"`
should print 12.

## Review UI (line-by-line)

The UI has four tabs: **Ops** (read-only lab overview), **Data** (curation),
**Forge** (real `mlx_lm.lora` training), and **Playground** (real local server).

```bash
./sf serve                    # http://127.0.0.1:8010
./sf serve --port 8020        # different port
```

For Forge training, run the server under the MLX environment and put its bin on
`PATH` so `mlx_lm.lora` / `mlx_lm.server` are found. If your models live outside
the Hugging Face cache, point `SKILLFORGE_LABS` at the model directory:

```bash
PYTHON=/path/to/mlx-env/bin/python \
PATH=/path/to/mlx-env/bin:$PATH \
SKILLFORGE_LABS=/path/to/MiMo-model \
./sf serve
```

Open the URL, then either paste a path/glob/folder (best for large downloads —
nothing is copied) or drag `.json`/`.jsonl` files onto the drop zone. Click
**Import files**. You land straight in the review queue.

**Keyboard**

| key | action |
|---|---|
| `a` / `r` | accept (keep) / reject (drop) |
| `e` | edit this row's turns, `⌘S` to save |
| `u` | reset row back to pending |
| `d` | toggle the before/after cleaning diff |
| `n` `→` `space` / `p` `←` | next / previous row |
| `f` | focus search |
| `1`–`9` | filter by the Nth flag |
| `?` | help |

Clicking any flag chip on a row filters to that flag — the fastest way to work
through one defect class at a time (e.g. every `secret`, then every
`orphan_observation`).

**Practical flow**

1. Import, then set decision filter to *pending only*.
2. **Accept all clean** — clears the unflagged bulk in one click.
3. Work the flagged rows by flag chip (`1`–`9`), accepting or rejecting each.
4. Export. Check the gate line: `hard gates: PASSED` means no secrets, host
   paths, invalid tool JSON, orphan observations, oversize rows or broken
   ChatML survived into the file.

Everything is stored in `data/skillforge.db`, so you can close the browser and
resume later; every decision is recorded as data and the export can be
reproduced.

## Three stages

The header switches between them; the choice is remembered and each tab is a URL-stable view.

| tab | what it does | honest limit |
|---|---|---|
| **Data** | import → clean → review → export | — |
| **Forge** | prepare a dataset, preview the command, run real `mlx_lm.lora` training | refuses rather than simulating if mlx_lm / model / data is missing |
| **Playground** | chat and probe against a real local server | no server, no reply — nothing is invented |

### Forge

1. **Environment** — mlx, mlx_lm, the `mlx_lm.lora` path, python. If the CLI is
   missing, training is disabled with the reason.
2. **Base model (R1 lock)** — every model this machine can train on, discovered
   by inspection (local HF dirs and the HF cache), with its size. Picking one
   shows the recorded `checksums/base_before.txt` inventory; **Verify checksums**
   hashes each file and compares. Results are cached on (size, mtime), so the
   30 GB bf16 base is only hashed once or when a file changes. Loading the page
   never hashes anything.
3. **Adapters** — everything under `skillforge/adapters/` and the Qwen lab's
   `adapters/`, with format detection:
   * `mlx_lm` — `adapters.safetensors` + `adapter_config.json`; loadable by
     `mlx_lm.server`, so the Playground can test it.
   * `skillforge-onepath` — the custom gated trainer's `onepath.safetensors`.
     **Not** loadable by stock `mlx_lm.server`; it needs the `mimo_gated`
     runtime. The registry says so instead of pretending they're interchangeable.
4. **Dataset** — pick a session and what to include. The rows go through the
   same gates as an export: a dataset carrying secrets, host paths, invalid tool
   JSON or oversize rows is refused unless *allow gated rows* is ticked. Writes
   `runs/<name>/{train,valid,test}.jsonl`.
5. **LoRA config** — rank and alpha are inputs; **scale is derived** (`α/rank`,
   shown live in the header) and written into `lora_config.yaml`, per R6.
6. **Preview command** — prints the exact argv, the generated YAML and the
   checks (mlx present, model present, train/valid row counts, already running?)
   *without running anything*. Pre-register, then commit hours of GPU.
7. **Start training** — spawns `mlx_lm.lora` in its own process group, logs to
   `runs/<name>/train.log`, and the panel parses **real** `Iter …: Train loss …`
   lines into a loss sparkline, it/sec, tokens/sec and peak memory. Stop kills
   the process group.

Run artifacts: `runs/<name>/{train,valid,test}.jsonl`, `lora_config.yaml`,
`command.txt`, `train.log`, `run.json`; the adapter lands in `adapters/<name>/`.

For speed/memory on the M4 Pro, prefer the MLX-converted repos in the HF cache
(`mlx-community/Qwen2.5-Coder-14B-Instruct-8bit`) over the 30 GB bf16 HF dir.

### Playground

* **Endpoints** are probed, never assumed: Ollama on 11434 and `mlx_lm.server`
  on 8080/8081. Whatever answers is listed with its models.
* Embedding models (`nomic-embed-text`, `bge`, `gte`, `e5`) are filtered out of
  the chat picker — they cannot chat, and silently failing on them is a trap.
* Each reply shows the endpoint, model, wall time, TTFT and tokens/sec as
  reported by the server. OpenAI-compatible servers don't expose TTFT without
  streaming, so it shows `—` rather than a made-up number.
* **Robustness probe (R3)** — one greedy sample plus N at temperature 0.3,
  agreement counted on the real normalized outputs, with a Wilson interval and
  every sample listed so divergence is visible rather than summarized away.
* **mlx_lm.server** can be started from here with an adapter attached — the way
  to exercise a trained adapter end to end — and shows its log while it loads.
