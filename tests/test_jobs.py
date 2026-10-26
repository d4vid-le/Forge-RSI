"""Deterministic checks for the guarded job queue (stdlib unittest)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

from pipeline.jobs import JobError, JobQueue, build_steps


class BuildStepsTest(unittest.TestCase):
    def test_skills_round_is_allowlisted_and_gated(self):
        steps, params = build_steps("skills_round", {
            "skills": "word_freq, merge_intervals", "rows": 40,
            "iters": 120, "run_id": "queue_round_1",
        }, python="/usr/bin/python3")
        self.assertEqual(params["skills"], "word_freq,merge_intervals")
        names = [s["name"] for s in steps]
        self.assertEqual(names, ["build corpora", "train adapters",
                                 "gated evaluation", "promotion decision",
                                 "skill report", "final report"])
        self.assertEqual(steps[1]["guard"], "base")
        self.assertTrue(steps[2]["gate"])
        self.assertIn("--run-id", steps[2]["cmd"])
        self.assertNotIn("shell", " ".join(steps[2]["cmd"]))

    def test_rsi_round_gate_is_after_the_loop(self):
        steps, params = build_steps("rsi_round", {"round": "r3", "iterations": 2})
        self.assertEqual(params, {"round": "r3", "iterations": 2})
        self.assertTrue(steps[0]["gate"])
        self.assertEqual(steps[0]["name"], "harness loop")

    def test_gap_round_is_detection_then_verified_corpus(self):
        steps, params = build_steps("gap_round", {"run_id": "latest", "min_rows": 2},
                                    python="/usr/bin/python3")
        self.assertEqual([s["name"] for s in steps],
                         ["detect gaps", "mine verified corpus"])
        self.assertIn("--min-rows", steps[1]["cmd"])
        self.assertEqual(params, {"run_id": "latest", "min_rows": 2})

    def test_holdout_rotation_is_gated_before_replacement(self):
        steps, params = build_steps("holdout_rotate", {"count": 10, "seed": 3},
                                    python="/usr/bin/python3")
        self.assertTrue(steps[0]["gate"])
        self.assertEqual(steps[0]["name"], "current holdout")
        self.assertIn("holdout-rotate", steps[1]["cmd"])
        self.assertIn("--force", steps[1]["cmd"])
        self.assertEqual(params, {"count": 10, "seed": 3})

    def test_dream_round_collects_then_replays(self):
        steps, params = build_steps("dream_round", {"run_id": "dream_test",
                                                    "samples": 3},
                                    python="/usr/bin/python3")
        self.assertEqual([s["name"] for s in steps],
                         ["collect candidates", "replay policies", "dream report"])
        self.assertIn("--samples", steps[0]["cmd"])
        self.assertIn("harness/h0_baseline.json", steps[0]["cmd"])
        self.assertEqual(params, {"run_id": "dream_test", "samples": 3})

    def test_invalid_inputs_are_rejected(self):
        bad = [
            ("skills_round", {"skills": "../etc", "run_id": "ok"}),
            ("skills_round", {"skills": "word_freq", "run_id": "no spaces"}),
            ("skills_round", {"skills": "word_freq", "run_id": "ok", "rows": 1}),
            ("rsi_round", {"round": "../x"}),
            ("holdout_rotate", {"seed": -1}),
            ("holdout_rotate", {"count": 3}),
            ("dream_round", {"run_id": "bad id"}),
            ("gap_round", {"run_id": "bad id"}),
            ("nonsense", {}),
        ]
        for kind, params in bad:
            with self.assertRaises(JobError, msg=f"{kind} {params}"):
                build_steps(kind, params)

    def test_no_free_form_commands(self):
        steps, _ = build_steps("reports", {}, python="/usr/bin/python3")
        for step in steps:
            self.assertIsInstance(step["cmd"], list)
            self.assertEqual(step["cmd"][:3], ["/usr/bin/python3", "-m", "forge_rsi"])


class QueueStateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "jobs.json"
        self.logs = Path(self.tmp.name) / "logs"
        self.q = JobQueue(self.path, self.logs, autostart=False)

    def tearDown(self):
        self.tmp.cleanup()

    def test_submit_persists(self):
        job = self.q.submit("reports", {})
        self.assertEqual(job["status"], "queued")
        self.assertEqual(len(job["steps"]), 2)
        again = JobQueue(self.path, self.logs, autostart=False)
        self.assertEqual(len(again.list()), 1)
        self.assertEqual(again.list()[0]["id"], job["id"])

    def test_params_must_be_an_object(self):
        with self.assertRaises(JobError):
            self.q.submit("reports", ["not", "an", "object"])

    def test_approval_requires_a_gate(self):
        job = self.q.submit("reports", {})
        with self.assertRaises(JobError):
            self.q.approve(job["id"], True)

    def test_rejection_ends_the_job(self):
        job = self.q.submit("skills_round", {"skills": "word_freq",
                                             "run_id": "gate_test"})
        # put the job at the gate without running a model
        with self.q._lock:
            stored = self.q._find(job["id"])
            stored["status"] = "awaiting_approval"
            self.q._persist()
        rejected = self.q.approve(job["id"], False, "looks wrong")
        self.assertEqual(rejected["status"], "rejected")
        self.assertFalse(rejected["approved"])

    def test_runner_completes_an_allowed_step(self):
        job = self.q.submit("reports", {})
        with self.q._lock:
            stored = self.q._find(job["id"])
            stored["steps"] = [dict(name="noop", cmd=[sys.executable, "-c",
                                                      "print('ok')"],
                                    index=0, status="pending", exit_code=None,
                                    started=None, finished=None)]
            stored["status"] = "queued"
            self.q._persist()
        self.q._run(job["id"])
        done = self.q.get(job["id"])
        self.assertEqual(done["status"], "completed")
        self.assertEqual(done["steps"][0]["exit_code"], 0)
        self.assertIn("ok", self.q.log_tail(job["id"]))


if __name__ == "__main__":
    unittest.main()
