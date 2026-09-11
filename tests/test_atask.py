"""Self-tests for the atask harness. Stdlib only (unittest).

Run:  python3 -m unittest discover tests   (from the atask/ directory)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

import atask
import runs
from acheck import check as acheck_check
from atask import answer as h_answer, escalate as h_escalate, goal_check, goal_set, open_h, spawn
from driver import boot as driver_boot, pulse as driver_pulse


def fresh_root(test):
    root = os.path.join(tempfile.mkdtemp(prefix="atask-test-"), ".atask")
    test.addCleanup(shutil.rmtree, os.path.dirname(root), True)
    return root


REPORT_5 = ("# Claim\nx\n# Evidence\ny\n# Self-review\nz\n"
            "# Needs\nn\n# Cost\n$0\n")


def write_report(root, tid):
    p = os.path.join(root, "reports", f"{tid}.md")
    with open(p, "w") as f:
        f.write(REPORT_5)
    return f"reports/{tid}.md"


def write_receipt(root, tid, payload="ok"):
    r = runs.new_receipt("test", {"task": tid, "payload": payload})
    runs.save(r, os.path.join(root, "runs"))
    return r["run_id"]


def add_task(root, tid, accept=("done-state",), blocked=()):
    q = os.path.join(root, "tasks.jsonl")
    recs = atask.load(q)
    recs.append({"id": tid, "tier": "A", "summary": f"task {tid}",
                 "acceptance": list(accept), "evidence_required": [],
                 "blocked_by": list(blocked), "status": "PROPOSED",
                 "report_ref": "", "validation_ref": ""})
    atask.save_all(recs, q)


class TestInit(unittest.TestCase):
    def test_boot_creates_layout(self):
        root = fresh_root(self)
        rep = driver_boot(root)
        self.assertTrue(rep["booted"] and rep["created"])
        for sub in ("a-logs", "reports", "runs", "validators"):
            self.assertTrue(os.path.isdir(os.path.join(root, sub)))
        self.assertTrue(os.path.isfile(os.path.join(root, "tasks.jsonl")))
        self.assertTrue(os.path.isfile(os.path.join(root, "h-tasks.jsonl")))


class TestOrdering(unittest.TestCase):
    def test_ready_respects_blocked_by(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-first")
        add_task(root, "a-second", blocked=("a-first",))
        recs = atask.load(os.path.join(root, "tasks.jsonl"))
        for r in recs:
            r["status"] = "JUSTIFIED"
        atask.save_all(recs, os.path.join(root, "tasks.jsonl"))
        got = [r["id"] for r in atask.ready(atask.load(os.path.join(root, "tasks.jsonl")))]
        self.assertEqual(got, ["a-first"])


class TestDoneGate(unittest.TestCase):
    def test_done_refused_without_proof(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-naked")
        ok, msg = atask.set_status("a-naked", "DONE", root)
        self.assertFalse(ok)
        self.assertIn("report_ref", msg)

    def test_done_refused_with_missing_report_file(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-ghost")
        ok, msg = atask.set_status("a-ghost", "DONE", root,
                                   report_ref="reports/a-ghost.md",
                                   validation_ref="sha256:" + "0" * 64)
        self.assertFalse(ok)


class TestFullLoop(unittest.TestCase):
    def test_proposed_to_done(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-loop")
        for st in ("JUSTIFIED", "EXECUTING"):
            ok, _ = atask.set_status("a-loop", st, root)
            self.assertTrue(ok)
        atask.alog("a-loop", "work", [0], root, "did it", "command:echo ok")
        rr = write_report(root, "a-loop")
        vr = write_receipt(root, "a-loop")
        ok, _ = atask.set_status("a-loop", "REPORTED", root,
                                 report_ref=rr, validation_ref=vr)
        self.assertTrue(ok)
        sl = atask.stoplight("a-loop", root)
        self.assertTrue(sl["go"], sl)
        ok, msg = atask.set_status("a-loop", "DONE", root,
                                   report_ref=rr, validation_ref=vr)
        self.assertTrue(ok, msg)
        self.assertEqual(acheck_check(root), [])

    def test_stoplight_nogo_when_uncovered(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-bare", accept=("thing one", "thing two"))
        atask.set_status("a-bare", "REPORTED", root)
        sl = atask.stoplight("a-bare", root)
        self.assertFalse(sl["go"])
        self.assertTrue(any("acceptance[0]" in m for m in sl["missing"]))

    def test_red_evidence_blocks_go(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-red")
        atask.set_status("a-red", "REPORTED", root)
        atask.alog("a-red", "work", [0], root, "ran",
                   "command:python3 -c \"import sys; sys.exit(3)\"")
        sl = atask.stoplight("a-red", root)
        self.assertFalse(sl["go"])
        self.assertTrue(any("exit 3" in m for m in sl["missing"]))


class TestReceipts(unittest.TestCase):
    def test_stable_id_ignores_volatile(self):
        a = runs.new_receipt("k", {"x": 1, "elapsed_s": 5.0})
        b = runs.new_receipt("k", {"x": 1, "elapsed_s": 9.0})
        self.assertEqual(a["run_id"], b["run_id"])

    def test_tamper_detected(self):
        r = runs.new_receipt("k", {"x": 1})
        self.assertTrue(runs.verify(r))
        r["content"]["x"] = 2
        self.assertFalse(runs.verify(r))


class TestDriver(unittest.TestCase):
    def test_pulse_promotes_green_reported(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-auto")
        for st in ("JUSTIFIED", "EXECUTING", "REPORTED"):
            atask.set_status("a-auto", st, root)
        atask.alog("a-auto", "work", [0], root, "did it", "command:echo ok")
        atask.set_status("a-auto", "REPORTED", root,
                         report_ref=write_report(root, "a-auto"),
                         validation_ref=write_receipt(root, "a-auto"))
        rep = driver_pulse(root)
        self.assertEqual(rep["promoted"], ["a-auto"])
        self.assertTrue(rep["halt_legal"])

    def test_pulse_leaves_red_reported_with_nogo(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-stuck")
        atask.set_status("a-stuck", "REPORTED", root)
        rep = driver_pulse(root)
        self.assertEqual(rep["promoted"], [])
        self.assertIn("a-stuck", rep["nogo"])
        self.assertFalse(rep["halt_legal"])


class TestAcheck(unittest.TestCase):
    def test_dangling_blocked_by(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-dangle", blocked=("a-ghost",))
        findings = acheck_check(root)
        self.assertTrue(any("dangling" in f for f in findings))

    def test_executing_without_alog_is_stale(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-quiet")
        atask.set_status("a-quiet", "EXECUTING", root)
        findings = acheck_check(root)
        self.assertTrue(any("no a-log" in f for f in findings))


VALIDATOR_PASS = (
    "import json, sys\n"
    "print(json.dumps({\"pass\": True, \"reasons\": []}))\n"
)

VALIDATOR_FAIL = (
    "import json, sys\n"
    "print(json.dumps({\"pass\": False, \"reasons\": [\"alog too thin\"]}))\n"
)


def write_validator(root, tid, body):
    p = os.path.join(root, "validators", f"{tid}.py")
    with open(p, "w") as f:
        f.write(body)
    return p


def finish_task(root, tid):
    for st in ("JUSTIFIED", "EXECUTING"):
        atask.set_status(tid, st, root)
    atask.alog(tid, "work", list(range(len(
        [r for r in atask.load(os.path.join(root, "tasks.jsonl"))
         if r["id"] == tid][0].get("acceptance", []) or [0]))), root,
        "did it", "command:echo ok")
    rr = write_report(root, tid)
    vr = write_receipt(root, tid)
    ok, msg = atask.set_status(tid, "REPORTED", root,
                               report_ref=rr, validation_ref=vr)
    assert ok, msg


class TestGoal(unittest.TestCase):
    def test_goal_maps_and_completes(self):
        root = fresh_root(self)
        driver_boot(root)
        goal_set(root, "ship demo", ["demo runs", "docs exist"])
        add_task(root, "a-run", accept=("runs",))
        add_task(root, "a-docs", accept=("docs",))
        recs = atask.load(os.path.join(root, "tasks.jsonl"))
        for r in recs:
            r["covers_goal"] = [0] if r["id"] == "a-run" else [1]
        atask.save_all(recs, os.path.join(root, "tasks.jsonl"))
        rep = goal_check(root)
        self.assertFalse(rep["goal_done"])
        self.assertTrue(all(len(x["mapped"]) == 1 for x in rep["items"]))
        finish_task(root, "a-run")
        finish_task(root, "a-docs")
        driver_pulse(root)
        rep = goal_check(root)
        self.assertTrue(rep["goal_done"], rep)

    def test_goal_unmapped_acceptance_not_done(self):
        root = fresh_root(self)
        driver_boot(root)
        goal_set(root, "ship demo", ["demo runs", "and a parade"])
        add_task(root, "a-run", accept=("runs",))
        recs = atask.load(os.path.join(root, "tasks.jsonl"))
        recs[0]["covers_goal"] = [0]
        atask.save_all(recs, os.path.join(root, "tasks.jsonl"))
        finish_task(root, "a-run")
        driver_pulse(root)
        rep = goal_check(root)
        self.assertFalse(rep["goal_done"])
        self.assertEqual(rep["items"][1]["mapped"], [])


class TestSpawn(unittest.TestCase):
    def test_child_inherits_parent_blockers_parent_waits(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-base")
        add_task(root, "a-parent", blocked=("a-base",))
        ok, msg = spawn(root, "a-parent", "a-child", "sub work", ["sub done"])
        self.assertTrue(ok, msg)
        by_id = {r["id"]: r for r in
                 atask.load(os.path.join(root, "tasks.jsonl"))}
        self.assertIn("a-base", by_id["a-child"]["blocked_by"])
        self.assertIn("a-child", by_id["a-parent"]["blocked_by"])
        self.assertEqual(by_id["a-child"]["depth"], 1)

    def test_spawn_refuses_done_parent_and_depth(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-done")
        finish_task(root, "a-done")
        driver_pulse(root)
        ok, msg = spawn(root, "a-done", "a-late", "x", ["y"])
        self.assertFalse(ok)
        self.assertIn("DONE", msg)


class TestHumanQueue(unittest.TestCase):
    def test_escalate_answer_reconcile(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-need")
        add_task(root, "a-dep", blocked=("a-need",))
        ok, hid = h_escalate(root, "a-need", "which API key?",
                             ["key-a", "key-b"], "key-a",
                             predicted={"key": "key-a"})
        self.assertTrue(ok, hid)
        by_id = {r["id"]: r for r in
                 atask.load(os.path.join(root, "tasks.jsonl"))}
        self.assertEqual(by_id["a-need"]["status"], "PAUSED")
        self.assertEqual(by_id["a-need"]["paused_on"], hid)
        self.assertEqual(len(open_h(root)), 1)
        # dependent finishes on the prediction while human decides
        finish_task(root, "a-dep")
        ok, msg = h_answer(root, hid, "key-b")
        self.assertTrue(ok, msg)
        by_id = {r["id"]: r for r in
                 atask.load(os.path.join(root, "tasks.jsonl"))}
        self.assertEqual(by_id["a-need"]["status"], "EXECUTING")
        # dependent ran on stale prediction -> must re-verify, not stay DONE
        self.assertEqual(by_id["a-dep"]["status"], "EXECUTING")
        self.assertEqual(acheck_check(root), [])


class TestValidators(unittest.TestCase):
    def test_passing_validator_keeps_go(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-v")
        write_validator(root, "a-v", VALIDATOR_PASS)
        finish_task(root, "a-v")
        sl = atask.stoplight("a-v", root)
        self.assertTrue(sl["go"], sl)

    def test_failing_validator_blocks_go(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-vf")
        write_validator(root, "a-vf", VALIDATOR_FAIL)
        finish_task(root, "a-vf")
        sl = atask.stoplight("a-vf", root)
        self.assertFalse(sl["go"])
        self.assertTrue(any("alog too thin" in m for m in sl["missing"]))

    def test_broken_validator_is_error_not_pass(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-vb")
        write_validator(root, "a-vb", "print('not json')\n")
        finish_task(root, "a-vb")
        sl = atask.stoplight("a-vb", root)
        self.assertFalse(sl["go"])
        self.assertTrue(any("validator error" in m for m in sl["missing"]))

    def test_absent_validator_is_noop(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-nv")
        finish_task(root, "a-nv")
        sl = atask.stoplight("a-nv", root)
        self.assertTrue(sl["go"], sl)


class TestDriverCanon(unittest.TestCase):
    def test_pulse_reports_goal_and_humans(self):
        root = fresh_root(self)
        driver_boot(root)
        goal_set(root, "g", ["x"])
        add_task(root, "a-h")
        h_escalate(root, "a-h", "decide?")
        rep = driver_pulse(root)
        self.assertIn("open_h", rep)
        self.assertEqual(len(rep["open_h"]), 1)
        self.assertIn("goal", rep)


class TestCLIDirOrder(unittest.TestCase):
    def test_dir_before_and_after_subcommand(self):
        import subprocess as _sp
        root = fresh_root(self)
        for argv in (["driver.py", "--dir", root, "boot"],
                     ["atask.py", "--dir", root, "goal", "set",
                      "--statement", "s", "--accept", "x"]):
            exe = os.path.join(HERE, argv[0])
            r = _sp.run([sys.executable, exe] + argv[1:],
                        capture_output=True, text=True, cwd=HERE)
            self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(os.path.isfile(os.path.join(root, "goal.json")))


class TestBudget(unittest.TestCase):
    def test_record_then_refuse_next(self):
        from budget import Budget, BudgetExceeded, FileBudget
        b = Budget(max_usd=0.05)
        b.record(cost=0.03, label="call-1")
        self.assertFalse(b.exhausted())
        with self.assertRaises(BudgetExceeded):
            b.record(cost=0.03, label="call-2")  # crosses: completes, then refuses
        with self.assertRaises(BudgetExceeded):
            b.check("call-3")

    def test_file_budget_survives_restart(self):
        from budget import FileBudget
        root = fresh_root(self)
        driver_boot(root)
        b = FileBudget(root)
        b.set_caps(1.0, None)
        b.record(cost=0.25, tokens=100, label="x")
        b2 = FileBudget(root)  # fresh object, same file
        self.assertAlmostEqual(b2.spent_usd, 0.25)
        self.assertEqual(b2.spent_tokens, 100)
        adv = b2.advertise()
        self.assertEqual(adv["ATASK_BUDGET_USD"], "0.75")

    def test_unpriced_counts_not_charges(self):
        from budget import Budget
        b = Budget(max_usd=0.01)
        b.record(label="cached")  # no cost: invisible spend, counted
        self.assertEqual(b.unpriced, 1)
        self.assertFalse(b.exhausted())

    def test_driver_refuses_when_exhausted(self):
        root = fresh_root(self)
        driver_boot(root)
        from budget import FileBudget
        FileBudget(root).set_caps(0.01, None)
        from budget import BudgetExceeded
        with self.assertRaises(BudgetExceeded):
            FileBudget(root).record(cost=0.01, label="burn")
        rep = driver_pulse(root)
        self.assertIn("error", rep)
        self.assertIn("budget", rep["error"].lower())

    def test_yaml_caps_seed_budget(self):
        root = fresh_root(self)
        driver_boot(root)
        with open(os.path.join(root, "atask.yaml"), "w") as f:
            f.write("budget_usd: 2.5\n")
        from driver import budget_state
        snap = budget_state(root)["snapshot"]
        self.assertEqual(snap["max_usd"], 2.5)


class TestDelegate(unittest.TestCase):
    def test_delegate_freezes_brief_and_pins_sha(self):
        from atask import agents_list, delegate
        root = fresh_root(self)
        driver_boot(root)
        self.assertTrue(any(a["name"] == "coder" for a in agents_list(root)))
        add_task(root, "a-par")
        ok, msg = delegate(root, "a-par", "a-sub", "coder",
                           "implement exactly X with tests")
        self.assertTrue(ok, msg)
        by_id = {r["id"]: r for r in
                 atask.load(os.path.join(root, "tasks.jsonl"))}
        self.assertIn("a-sub", by_id["a-par"]["blocked_by"])
        dg = by_id["a-sub"]["delegate"]
        self.assertEqual(dg["agent"], "coder")
        bp = os.path.join(root, dg["brief_ref"])
        self.assertTrue(os.path.isfile(bp))
        import hashlib as _h
        sha = _h.sha256(open(bp, "rb").read()).hexdigest()[:16]
        self.assertEqual(dg["brief_sha"], sha)

    def test_delegate_unknown_lane_refused(self):
        from atask import delegate
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-par")
        ok, msg = delegate(root, "a-par", "a-sub", "oracle", "do magic")
        self.assertFalse(ok)
        self.assertIn("unknown agent lane", msg)


class TestPolicy(unittest.TestCase):
    def test_prohibited_is_code(self):
        from atask import policy_check
        root = fresh_root(self)
        driver_boot(root)
        self.assertEqual(policy_check(root, "git push --force")["verdict"], "PROHIBITED")
        self.assertEqual(policy_check(root, "rm -rf /")["verdict"], "PROHIBITED")

    def test_routes_spend_and_human(self):
        from atask import policy_check
        root = fresh_root(self)
        driver_boot(root)
        self.assertEqual(policy_check(root, "pay the $5 invoice")["route"], "M")
        self.assertEqual(policy_check(root, "merge the PR")["route"], "H")
        self.assertEqual(policy_check(root, "run pytest tests/ -q")["route"], "A")

    def test_repo_can_extend_prohibited(self):
        from atask import policy_check
        root = fresh_root(self)
        driver_boot(root)
        with open(os.path.join(root, "atask.yaml"), "a") as f:
            f.write("prohibited:\n  - 'fortnite'\n")
        rep = policy_check(root, "deploy fortnite behaviour")
        self.assertEqual(rep["verdict"], "PROHIBITED")


if __name__ == "__main__":
    unittest.main()
