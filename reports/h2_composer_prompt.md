# Exact composer prompt (reconstructed from the frozen inputs)

The teacher chat template adds the assistant prefill `{`; the system and mission below are exactly the text inputs. No hidden tests or private holdout appear here.

## SYSTEM

```
You are a harness optimizer for a local coding agent. You improve the agent's prompt-level harness. You output only a JSON object.
```

## MISSION

```
You are composing THE final harness from a base and several candidate harnesses. You may MERGE edits, ADOPT one candidate wholesale, or KEEP BASE. Do not concatenate conflicting instructions.

The table below is measured on the same dev tasks. Use task-level contrasts, not just aggregate scores. Every decision must cite a task or a repeated pattern. Do not mention task ids, tests, holdout, or eval sets in the harness.

BASE HARNESS:
{
  "version": "h0",
  "role": "You are a Python engineer. You write correct, self-contained functions and nothing else.",
  "contract": {
    "output": "exactly one fenced ```python block containing the complete solution; no prose outside the block",
    "must": [
      "complete function(s) with the exact requested name",
      "standard library only"
    ],
    "must_not": [
      "tests",
      "example calls",
      "assertions",
      "markdown explanation"
    ]
  },
  "hops": [
    {
      "name": "implement",
      "instruction": "Read the task carefully, then write the complete solution."
    }
  ],
  "tools": [],
  "selection": {
    "policy": "first",
    "k": 1
  },
  "budget": {
    "max_turns": 1,
    "max_output_tokens": 900
  }
}

CANDIDATE HARNESSES:
{
  "inv1": {
    "version": "h2a_inv1",
    "role": "You are a Python engineer. You write correct, self-contained functions and nothing else.",
    "contract": {
      "output": "exactly one fenced ```python block containing the complete solution; no prose outside the block",
      "must": [
        "complete function(s) with the exact requested name",
        "standard library only",
        "handle edge cases explicitly (e.g., empty inputs, malformed data, boundary conditions)"
      ],
      "must_not": [
        "tests",
        "example calls",
        "assertions",
        "markdown explanation"
      ]
    },
    "hops": [
      {
        "name": "implement",
        "instruction": "Read the task carefully. Identify edge cases and constraints. Write the complete solution."
      }
    ],
    "tools": [],
    "selection": {
      "policy": "first",
      "k": 1
    },
    "budget": {
      "max_turns": 1,
      "max_output_tokens": 900
    }
  },
  "inv2": {
    "version": "h2a_inv2",
    "role": "You are a Python engineer. You write correct, self-contained functions and nothing else.",
    "contract": {
      "output": "exactly one fenced ```python block containing the complete solution; no prose outside the block",
      "must": [
        "complete function(s) with the exact requested name",
        "standard library only",
        "handle edge cases (empty inputs, malformed data) gracefully or raise ValueError as specified"
      ],
      "must_not": [
        "tests",
        "example calls",
        "assertions",
        "markdown explanation"
      ]
    },
    "hops": [
      {
        "name": "implement",
        "instruction": "Read the task carefully, then write the complete solution. Ensure all edge cases are handled and the logic matches the specification exactly."
      }
    ],
    "tools": [],
    "selection": {
      "policy": "first",
      "k": 1
    },
    "budget": {
      "max_turns": 1,
      "max_output_tokens": 900
    }
  },
  "dom1": {
    "version": "h2a_dom1",
    "role": "You are a Python engineer. You write correct, self-contained functions and nothing else.",
    "contract": {
      "output": "exactly one fenced ```python block containing the complete solution; no prose outside the block",
      "must": [
        "complete function(s) with the exact requested name",
        "standard library only",
        "handle empty input gracefully",
        "lowercase text before splitting or comparing unless specified otherwise",
        "sort intervals by start time before merging or processing",
        "preserve existing helper functions if adding new ones"
      ],
      "must_not": [
        "tests",
        "example calls",
        "assertions",
        "markdown explanation"
      ]
    },
    "hops": [
      {
        "name": "implement",
        "instruction": "Read the task carefully, then write the complete solution. Ensure edge cases like empty inputs are handled. If text processing is involved, normalize case as needed. For matrix operations, ensure dimensions are handled correctly."
      }
    ],
    "tools": [],
    "selection": {
      "policy": "first",
      "k": 1
    },
    "budget": {
      "max_turns": 1,
      "max_output_tokens": 900
    }
  },
  "dom2": {
    "version": "h2a_dom2",
    "role": "You are a Python engineer. You write correct, self-contained functions and nothing else.",
    "contract": {
      "output": "exactly one fenced ```python block containing the complete solution; no prose outside the block",
      "must": [
        "complete function(s) with the exact requested name",
        "standard library only",
        "handle empty or edge-case inputs gracefully",
        "preserve helper functions if mentioned or implied",
        "normalize strings (e.g., lowercase) before processing if case-insensitivity is implied or standard",
        "sort intervals or ranges by start time before merging or processing if applicable",
        "return new objects rather than mutating inputs unless specified"
      ],
      "must_not": [
        "tests",
        "example calls",
        "assertions",
        "markdown explanation"
      ]
    },
    "hops": [
      {
        "name": "implement",
        "instruction": "Read the task carefully, then write the complete solution. Pay attention to edge cases like empty inputs, case sensitivity, and mutation requirements."
      }
    ],
    "tools": [],
    "selection": {
      "policy": "first",
      "k": 1
    },
    "budget": {
      "max_turns": 1,
      "max_output_tokens": 900
    }
  }
}

CONTRAST TABLE:
task | skill | base | h2a_inv1 | h2a_inv2 | h2a_dom1 | h2a_dom2
--- | --- | --- | --- | --- | --- | ---
hard_001 | unclassified | PASS/none | PASS/none | PASS/none | PASS/none | PASS/none
hard_002 | unclassified | PASS/none | PASS/none | PASS/none | PASS/none | PASS/none
hard_003 | merge_intervals | PASS/none | PASS/none | PASS/none | PASS/none | PASS/none
hard_004 | word_freq | fail/assertion | fail/assertion | fail/assertion | fail/assertion | fail/assertion
hard_005 | word_freq | PASS/none | PASS/none | PASS/none | PASS/none | PASS/none
hard_006 | unclassified | fail/assertion | PASS/none | PASS/none | PASS/none | PASS/none
hard_007 | unclassified | PASS/none | PASS/none | PASS/none | PASS/none | PASS/none
hard_008 | unclassified | PASS/none | PASS/none | PASS/none | PASS/none | PASS/none
hard_009 | unclassified | PASS/none | PASS/none | PASS/none | PASS/none | PASS/none
hard_010 | unclassified | fail/runtime | PASS/none | PASS/none | PASS/none | PASS/none
hard_011 | unclassified | PASS/none | PASS/none | PASS/none | PASS/none | PASS/none
hard_012 | unclassified | PASS/none | fail/assertion | PASS/none | PASS/none | PASS/none
hard_013 | unclassified | PASS/none | PASS/none | PASS/none | PASS/none | PASS/none
hard_014 | unclassified | PASS/none | PASS/none | PASS/none | PASS/none | PASS/none
hard_015 | merge_intervals | PASS/none | PASS/none | PASS/none | PASS/none | PASS/none
hard_016 | unclassified | PASS/none | PASS/none | PASS/none | PASS/none | PASS/none
hard_017 | unclassified | PASS/none | PASS/none | fail/assertion | PASS/none | PASS/none
hard_018 | unclassified | fail/assertion | fail/assertion | fail/assertion | fail/assertion | fail/assertion
hard_019 | word_freq | fail/assertion | PASS/none | fail/assertion | fail/assertion | fail/assertion
hard_020 | unclassified | PASS/none | PASS/none | PASS/none | fail/timeout | fail/timeout

AGGREGATES
- h2a_inv1: score 0.85 · passed 17/20 · delta +0.10 · cost/solved 157.4
- h2a_inv2: score 0.8 · passed 16/20 · delta +0.05 · cost/solved 171.2
- h2a_dom1: score 0.8 · passed 16/20 · delta +0.05 · cost/solved 147.2
- h2a_dom2: score 0.8 · passed 16/20 · delta +0.05 · cost/solved 147.0

DISAGREEMENT: 20.00% of tasks; diversity Jaccard 0.6923

MEASURED CUE → HARNESS TABLE (use it to choose a harness when the failure signature matches):
[
  {
    "cue": {
      "skill": "unclassified",
      "error_class": "runtime"
    },
    "harness": "h2a_inv1",
    "confidence": 0.20654329147389294,
    "evidence": {
      "n": 1,
      "base_passes": 0,
      "candidate_passes": 1,
      "task_ids": [
        "hard_010"
      ]
    },
    "lesson": "when the failure cue is unclassified/runtime, prefer harness h2a_inv1"
  },
  {
    "cue": {
      "skill": "unclassified",
      "error_class": "assertion"
    },
    "harness": "h2a_inv1",
    "confidence": 0.09452865480086611,
    "evidence": {
      "n": 2,
      "base_passes": 0,
      "candidate_passes": 1,
      "task_ids": [
        "hard_006",
        "hard_018"
      ]
    },
    "lesson": "when the failure cue is unclassified/assertion, prefer harness h2a_inv1"
  },
  {
    "cue": {
      "skill": "word_freq",
      "error_class": "assertion"
    },
    "harness": "h2a_inv1",
    "confidence": 0.09452865480086611,
    "evidence": {
      "n": 2,
      "base_passes": 0,
      "candidate_passes": 1,
      "task_ids": [
        "hard_004",
        "hard_019"
      ]
    },
    "lesson": "when the failure cue is word_freq/assertion, prefer harness h2a_inv1"
  }
]

Return ONLY the final harness JSON with keys: version, role, contract, hops, tools, selection, budget.
```
