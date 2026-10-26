#!/usr/bin/env bash
# Reproduce the round-1 loop end to end.
# Set PYTHON to the MLX environment's interpreter if it is not `python`.
set -euo pipefail
cd "$(dirname "$0")/.."
PY="${PYTHON:-python}"

echo "== freeze =="
$PY -m forge_rsi freeze
python3 tasks/build_tasks.py
python3 tasks/lint_tasks.py

echo "== RSI harness round =="
$PY -m forge_rsi loop --round r1 --iterations 5

echo "== Le-Gates corpora + adapters =="
$PY -m forge_rsi skills-build --skills word_freq,merge_intervals --rows 40
$PY -m forge_rsi skills-train --skills word_freq,merge_intervals --iters 120

echo "== gated evaluation + decision =="
$PY -m forge_rsi skills-eval --splits dev,holdout,skills --run-id legates_candidates
$PY -m forge_rsi skills-decide --run-prefix legates_candidates
$PY -m forge_rsi skills-eval --splits dev,holdout,skills --run-id legates_final

echo "== reports =="
$PY -m forge_rsi skills-report
$PY -m forge_rsi final-report

echo "done. run: $PY -m forge_rsi dashboard"
