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


def add_task(root, tid, accept=("done-state",), blocked=(),
             ev=("command:echo ok",)):
    q = os.path.join(root, "tasks.jsonl")
    recs = atask.load(q)
    reqs = []
    for e in ev:
        k, s = e.split(":", 1)
        reqs.append({"kind": k, "spec": s})
    recs.append({"id": tid, "tier": "A", "summary": f"task {tid}",
                 "acceptance": list(accept), "evidence_required": reqs,
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


def earn(root, tid, marker=None):
    """Earn escalation rights: 2 attempts + failed checkable evidence.
    Never demotes (no EXECUTING->JUSTIFIED): second attempt comes from a
    run start, like a real worker claiming again. With marker: the probe
    `test -f marker` is red until the test touches the file (= the fix),
    so the task can still promote afterwards."""
    atask.set_status(tid, "EXECUTING", root)
    atask.main(["run", "start", "--dir", root, "--id", tid,
                "--worker", "test", "--model", "test"])
    ev = (f"command:test -f {marker}" if marker
          else "command:python3 -c \"import sys; sys.exit(9)\"")
    atask.alog(tid, "work", [0], root, "tried blocked-op", ev)


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

    def test_goal_rotation_clears_stale_mappings(self):
        root = fresh_root(self)
        driver_boot(root)
        goal_set(root, "old", ["a", "b"])
        add_task(root, "a-x")
        recs = atask.load(os.path.join(root, "tasks.jsonl"))
        recs[0]["covers_goal"] = [0, 1]
        recs[0]["status"] = "DONE"
        atask.save_all(recs, os.path.join(root, "tasks.jsonl"))
        self.assertTrue(goal_check(root)["goal_done"])
        goal_set(root, "new", ["c", "d"])
        rep = goal_check(root)
        self.assertFalse(rep["goal_done"])
        self.assertEqual(rep["items"][0]["mapped"], [])


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
        earn(root, "a-need")
        ok, hid = h_escalate(root, "a-need", "which API key?", "SECRET",
                             ["key-a", "key-b"], "key-a",
                             predicted={"key": "key-a"}, operation="op-key")
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

    def test_ask_gate_refuses_non_boundary(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-lib")
        ok, msg = h_escalate(root, "a-lib", "which python library?", "VIBES")
        self.assertFalse(ok)
        self.assertIn("not a human boundary", msg)
        earn(root, "a-lib")
        ok, hid = h_escalate(root, "a-lib", "which region?", "PREFERENCE",
                             ["eu", "us"], "eu", operation="op-region")
        self.assertTrue(ok, hid)
        hs = {h["id"]: h for h in atask.hload(root)}
        self.assertEqual(hs[hid]["kind"], "PREFERENCE")


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
        earn(root, "a-h")
        h_escalate(root, "a-h", "decide?", "PREFERENCE", operation="op-decide")
        rep = driver_pulse(root)
        self.assertIn("open_h", rep)
        self.assertEqual(len(rep["open_h"]), 1)
        self.assertIn("goal", rep)
        self.assertIn("spent", rep)


class TestCLIDirOrder(unittest.TestCase):
    def test_dir_before_and_after_subcommand(self):
        # Same code path as the CLI, no process spawn: main(argv) in-process.
        from driver import main as driver_main
        from atask import main as atask_main
        root = fresh_root(self)
        self.assertEqual(driver_main(["--dir", root, "boot"]), 0)
        self.assertEqual(atask_main(["--dir", root, "goal", "set",
                                     "--statement", "s", "--accept", "x"]), 0)
        self.assertEqual(atask_main(["goal", "set", "--dir", root,
                                     "--statement", "s2", "--accept", "y"]), 0)
        self.assertTrue(os.path.isfile(os.path.join(root, "goal.json")))


class TestControlHarness(unittest.TestCase):
    def test_chain_grammar(self):
        from chain import describe, parse
        acts = parse("20841")
        self.assertEqual([(a["key"], a["name"], a["arg"]) for a in acts],
                         [("2", "ZOOM", None), ("0", "ACCEPT", None),
                          ("8", "MORE", None), ("4", "PICK", 1)])
        self.assertIn("ZOOM", describe(acts))
        with self.assertRaises(ValueError):
            parse("4")  # PICK needs a digit
        with self.assertRaises(ValueError):
            parse("2x9")

    def test_press_row_carries_question_and_context(self):
        from instrument import run
        from press import read as press_read
        root = fresh_root(self)
        driver_boot(root)
        goal_set(root, "g", ["x"])
        add_task(root, "a-need")
        recs = atask.load(os.path.join(root, "tasks.jsonl"))
        recs[0]["covers_goal"] = [0]
        atask.save_all(recs, os.path.join(root, "tasks.jsonl"))
        earn(root, "a-need")
        h_escalate(root, "a-need", "pick one?", "PREFERENCE", ["aa", "bb"], "aa",
                   operation="op-pick")
        rep = run("0", session="s1", root=root)  # ACCEPT = recommended
        self.assertTrue(rep["results"][0]["ok"], rep)
        rows = press_read(root)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["picked_text"], "ACCEPT")
        self.assertEqual(row["context"]["mode"], "question")
        q = row["context"]["question"]
        self.assertEqual(q["kind"], "PREFERENCE")
        self.assertEqual(q["options"], ["aa", "bb"])
        self.assertEqual(q["recommended"], "aa")
        self.assertIn("goal_progress", row["context"]["context"])
        self.assertIn("spent_usd", row["context"]["context"])
        by_h = {h["id"]: h for h in atask.hload(root)}
        self.assertEqual(list(by_h.values())[0]["answer"],
                         "accepted recommendation: aa")

    def test_zero_is_go_when_idle(self):
        from instrument import run
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-r")
        atask.set_status("a-r", "JUSTIFIED", root)
        rep = run("0", session="s1", root=root)
        self.assertIn("a-r", rep["results"][0]["close"])

    def test_pick_options_1_to_7(self):
        from instrument import run
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-need")
        earn(root, "a-need")
        h_escalate(root, "a-need", "pick?", "PREFERENCE", ["aa", "bb"], "bb",
                   operation="op-pick")
        rep = run("41", session="s1", root=root)  # PICK#1
        self.assertTrue(rep["results"][0]["ok"], rep)
        self.assertIn("option 1", rep["results"][0]["close"])
        rep = run("49", session="s1", root=root)  # nothing open now
        self.assertFalse(rep["results"][0]["ok"])

    def test_eight_expands_nine_halts(self):
        from instrument import run
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-need")
        earn(root, "a-need")
        h_escalate(root, "a-need", "pick?", "AMBIGUITY", ["aa"], "aa",
                   operation="op-pick")
        rep = run("8", session="s1", root=root)
        self.assertEqual(rep["results"][0]["action"], "expand")
        self.assertIn("AMBIGUITY", rep["results"][0]["close"])
        rep = run("9", session="s1", root=root)
        self.assertIn("halted", rep["results"][0]["close"])
        rep = run("1", session="s1", root=root)
        self.assertFalse(rep["results"][0]["ok"])  # executing refused
        rep = run("2", session="s1", root=root)
        self.assertTrue(rep["results"][0]["ok"])  # readonly survives
        rep = run("9", session="s1", root=root)
        self.assertIn("resumed", rep["results"][0]["close"])

    def test_seven_answers_or_files_correction(self):
        from instrument import run
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-t")
        earn(root, "a-t")
        h_escalate(root, "a-t", "say something?", "SECRET", operation="op-say")
        rep = run("7", session="s1", root=root, payloads={"7": "hello human"})
        self.assertEqual(rep["results"][0]["action"], "tell")
        rep = run("7", session="s1", root=root, payloads={"7": "note: retry later"})
        self.assertEqual(rep["results"][0]["action"], "fix")
        self.assertIn("correction", rep["results"][0]["close"])

    def test_tell_refuses_secrets(self):
        from instrument import run
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-s")
        earn(root, "a-s")
        h_escalate(root, "a-s", "give input", "SECRET", operation="op-input")
        rep = run("7", session="s1", root=root,
                  payloads={"7": "my api_key: hunter2hunter2"})
        self.assertFalse(rep["results"][0]["ok"])
        self.assertIn("secret-refused", rep["results"][0]["action"])

    def test_ok_no_deny(self):
        from instrument import run
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-t2")
        earn(root, "a-t2")
        h_escalate(root, "a-t2", "approve?", "AUTHORIZATION", operation="op-appr")
        rep = run("5", session="s1", root=root)
        self.assertIn("approved", rep["results"][0]["close"])
        add_task(root, "a-t3")
        earn(root, "a-t3")
        h_escalate(root, "a-t3", "approve?", "AUTHORIZATION", operation="op-appr")
        rep = run("6", session="s1", root=root)
        self.assertIn("denied", rep["results"][0]["close"])
        by_h = {h["id"]: h for h in atask.hload(root)}
        denied = [h for h in by_h.values() if h.get("status") == "denied"]
        self.assertEqual(len(denied), 1)

    def test_digest_closes_session_with_outcome(self):
        from instrument import digest, run
        root = fresh_root(self)
        driver_boot(root)
        goal_set(root, "g", ["x"])
        add_task(root, "a-r")
        recs = atask.load(os.path.join(root, "tasks.jsonl"))
        recs[0]["covers_goal"] = [0]
        atask.save_all(recs, os.path.join(root, "tasks.jsonl"))
        run("2", session="s9", root=root)
        out = digest(root, "s9")
        self.assertEqual(out["session"], "s9")
        self.assertIn("goal_done", out["outcome"])
        self.assertIn("spent_usd", out["outcome"])
        self.assertEqual(out["outcome"]["presses"], 1)

    def test_spend_comes_only_from_runs(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-c")
        atask.alog("a-c", "work", [0], root, "x", "")
        atask.main(["run", "start", "--dir", root, "--id", "a-c"])
        from runs import list_open
        rid = list_open(root, "a-c")[0]["run_id"]
        atask.main(["run", "usage", "--dir", root, "--run", rid,
                    "--input-tokens", "7000", "--output-tokens", "700",
                    "--cost", "0.72"])
        atask.main(["run", "finish", "--dir", root, "--run", rid,
                    "--result", "completed"])
        from driver import spent_totals
        tot = spent_totals(root)
        self.assertAlmostEqual(tot["spent_usd"], 0.72)
        self.assertEqual(tot["spent_tokens"], 7700)

    def test_mcp_seven_verbs(self):
        import subprocess as _sp
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-m")
        atask.set_status("a-m", "JUSTIFIED", root)
        proc = _sp.Popen(
            [sys.executable, os.path.join(HERE, "mcp_server.py"),
             "--dir", root],
            stdin=_sp.PIPE, stdout=_sp.PIPE, text=True, cwd=HERE)
        try:
            def rpc(mid, method, params=None):
                proc.stdin.write(json.dumps(
                    {"jsonrpc": "2.0", "id": mid, "method": method,
                     "params": params or {}}) + "\n")
                proc.stdin.flush()
                return json.loads(proc.stdout.readline())
            self.assertEqual(rpc(1, "initialize")["result"]["serverInfo"]["name"], "atask")
            tools = rpc(2, "tools/list")["result"]["tools"]
            names = {t["name"] for t in tools}
            self.assertEqual(names, {"a_goal", "a_status", "a_task",
                                     "a_proof", "a_ask"})
            out = rpc(3, "tools/call",
                      {"name": "a_task",
                       "arguments": {"status": "READY"}})["result"]
            self.assertIn("a-m", out["content"][0]["text"])
            ask = rpc(4, "tools/call",
                      {"name": "a_ask", "arguments": {}})["result"]
            self.assertIn("[]", ask["content"][0]["text"])
            err = rpc(5, "tools/call",
                      {"name": "nope", "arguments": {}})["error"]
            self.assertIn("unknown verb", err["message"])
        finally:
            proc.kill()


class TestEventSubstrate(unittest.TestCase):
    def test_transitions_emit_events_with_mono_clock(self):
        from events import read as eread
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-e")
        atask.set_status("a-e", "EXECUTING", root)
        rows = eread(root)
        kinds = [r["event"] for r in rows]
        self.assertIn("run.started", kinds)
        self.assertIn("task.status", kinds)
        self.assertTrue(all("mono_ns" in r and "ts" in r for r in rows))
        monos = [r["mono_ns"] for r in rows]
        self.assertEqual(monos, sorted(monos))

    def test_attempts_count_and_run_finished_on_done(self):
        from events import read as eread
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-e2")
        atask.set_status("a-e2", "EXECUTING", root)
        atask.set_status("a-e2", "EXECUTING", root)  # same state: no new attempt
        finish_task(root, "a-e2")  # re-enters EXECUTING from JUSTIFIED: attempt 2
        driver_pulse(root)
        by_id = {r["id"]: r for r in
                 atask.load(os.path.join(root, "tasks.jsonl"))}
        self.assertEqual(by_id["a-e2"]["attempts"], 2)
        kinds = [r["event"] for r in eread(root)]
        self.assertIn("run.finished", kinds)

    def test_human_ask_and_choice_events(self):
        from events import read as eread
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-h")
        earn(root, "a-h")
        h_escalate(root, "a-h", "pick?", "PREFERENCE", ["aa", "bb"], "aa",
                   operation="op-pick")
        h_answer(root, [h["id"] for h in open_h(root)][0], "aa")
        by_kind = {}
        for r in eread(root):
            by_kind.setdefault(r["event"], []).append(r)
        self.assertEqual(by_kind["human.asked"][0]["kind"], "PREFERENCE")
        self.assertEqual(by_kind["human.choice"][0]["selected"], "aa")

    def test_resource_used_event(self):
        from events import read as eread
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-c")
        atask.main(["run", "start", "--dir", root, "--id", "a-c"])
        from runs import list_open
        rid = list_open(root, "a-c")[0]["run_id"]
        rc = atask.main(["run", "usage", "--dir", root, "--run", rid,
                         "--input-tokens", "100", "--output-tokens", "50",
                         "--cost", "0.01"])
        self.assertEqual(rc, 0)
        res = eread(root, "resource.used")
        self.assertEqual(len(res), 1)
        self.assertAlmostEqual(res[0]["cost_usd"], 0.01)

    def test_run_dataclass_mono_timing(self):
        from runs import Run
        r = Run(task_id="a-x")
        r.note(cost_usd=0.02, tokens=100, tools=3)
        snap = r.finish("completed")
        self.assertEqual(snap["result"], "completed")
        self.assertAlmostEqual(snap["spent_usd"], 0.02)
        self.assertGreaterEqual(snap["elapsed_ms"], 0)
        with self.assertRaises(ValueError):
            Run(task_id="a-x").finish("validated")  # workers can't self-validate

    def test_run_unknown_tokens_stay_null(self):
        from runs import Run
        r = Run(task_id="a-x")
        snap = r.finish("failed", "pytest")
        self.assertIsNone(snap["input_tokens"])
        self.assertEqual(snap["token_source"], "unknown")
        with self.assertRaises(ValueError):
            r.usage(token_source="guess")
        with self.assertRaises(ValueError):
            Run(task_id="a-x", result="maybe")

    def test_bats_block_with_remaining(self):
        from driver import resources
        root = fresh_root(self)
        driver_boot(root)
        goal_set(root, "g", ["x"], budget_usd=1.0, token_budget=1000,
                 deadline_min=30)
        add_task(root, "a-c")
        atask.main(["run", "start", "--dir", root, "--id", "a-c"])
        from runs import list_open
        rid = list_open(root, "a-c")[0]["run_id"]
        atask.main(["run", "usage", "--dir", root, "--run", rid,
                    "--input-tokens", "50", "--output-tokens", "50",
                    "--cost", "0.25"])
        atask.main(["run", "finish", "--dir", root, "--run", rid,
                    "--result", "completed"])
        res = resources(root)
        self.assertAlmostEqual(res["remaining_usd"], 0.75)
        self.assertEqual(res["remaining_tokens"], 900)
        self.assertIn("remaining_min", res)
        self.assertEqual(res["attempts"], 1)

    def test_goal_done_emitted_once(self):
        from events import read as eread
        root = fresh_root(self)
        driver_boot(root)
        goal_set(root, "g", ["x"])
        add_task(root, "a-r")
        recs = atask.load(os.path.join(root, "tasks.jsonl"))
        recs[0]["covers_goal"] = [0]
        atask.save_all(recs, os.path.join(root, "tasks.jsonl"))
        finish_task(root, "a-r")
        driver_pulse(root)
        driver_pulse(root)
        self.assertEqual(len(eread(root, "goal.done")), 1)

    def test_digit_choice_emits_human_choice(self):
        from events import read as eread
        from instrument import run
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-need")
        earn(root, "a-need")
        h_escalate(root, "a-need", "pick?", "PREFERENCE", ["aa", "bb"], "aa",
                   operation="op-pick")
        run("0", session="s1", root=root)
        rows = eread(root, "human.choice")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "PREFERENCE")
        self.assertIn("aa", rows[0]["selected"])

    def test_kernel_has_no_heavy_deps(self):
        import re as _re
        banned = _re.compile(r"^\s*(import|from)\s+(pydantic|opentelemetry|otel|phoenix|logfire|duckdb)\b", _re.M)
        bad = []
        for fn in os.listdir(HERE):
            if not fn.endswith(".py") or fn.startswith("test"):
                continue
            src = open(os.path.join(HERE, fn)).read()
            if banned.search(src):
                bad.append(fn)
        self.assertEqual(bad, [])


class TestAdversarial(unittest.TestCase):
    def test_tampered_receipt_refused_at_done_gate(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-t")
        for st in ("JUSTIFIED", "EXECUTING"):
            atask.set_status("a-t", st, root)
        atask.alog("a-t", "work", [0], root, "x", "command:echo ok")
        rr = write_report(root, "a-t")
        vr = write_receipt(root, "a-t")
        # Tamper the receipt file in place (id no longer matches content).
        import json as _json
        rp = os.path.join(root, "runs", vr.replace(":", "_") + ".json")
        body = _json.loads(open(rp).read())
        body["content"]["payload"] = "forged"
        open(rp, "w").write(_json.dumps(body))
        ok, msg = atask.set_status("a-t", "REPORTED", root,
                                   report_ref=rr, validation_ref=vr)
        self.assertTrue(ok, msg)  # REPORTED carries no proof requirement
        ok, msg = atask.set_status("a-t", "DONE", root,
                                   report_ref=rr, validation_ref=vr)
        self.assertFalse(ok)
        self.assertIn("TAMPERED", msg)

    def test_verify_all_flags_tampered_ledger(self):
        root = fresh_root(self)
        driver_boot(root)
        vr = write_receipt(root, "a-x")
        import json as _json
        rp = os.path.join(root, "runs", vr.replace(":", "_") + ".json")
        body = _json.loads(open(rp).read())
        body["content"]["payload"] = "forged"
        open(rp, "w").write(_json.dumps(body))
        rep = runs.verify_all(os.path.join(root, "runs"))
        self.assertEqual(rep["valid"], 0)
        self.assertEqual(len(rep["invalid"]), 1)

    def test_concurrent_pulses_stay_valid(self):
        import subprocess as _sp
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-c")
        finish_task(root, "a-c")
        procs = [_sp.Popen([sys.executable, os.path.join(HERE, "driver.py"),
                            "pulse", "--dir", root],
                           stdout=_sp.PIPE, stderr=_sp.PIPE, text=True, cwd=HERE)
                 for _ in range(2)]
        outs = [p.communicate() for p in procs]
        self.assertTrue(all(json.loads(o[0])["promoted"] == ["a-c"] or
                            json.loads(o[0])["promoted"] == [] for o in outs),
                        outs)
        recs = atask.load(os.path.join(root, "tasks.jsonl"))
        done = [r for r in recs if r["id"] == "a-c" and r["status"] == "DONE"]
        self.assertEqual(len(done), 1)  # exactly one DONE record, never dup
        self.assertEqual(acheck_check(root), [])

    def test_repulse_is_idempotent(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-i")
        finish_task(root, "a-i")
        first = driver_pulse(root)
        self.assertEqual(first["promoted"], ["a-i"])
        second = driver_pulse(root)
        self.assertEqual(second["promoted"], [])
        self.assertTrue(second["halt_legal"])


LEGAL_EDGES = {
    "PROPOSED": {"JUSTIFIED", "REJECTED"},
    "JUSTIFIED": {"EXECUTING", "REJECTED", "PAUSED"},
    "EXECUTING": {"REPORTED", "PAUSED", "REJECTED", "EXECUTING"},
    "PAUSED": {"EXECUTING", "REJECTED"},
    "REPORTED": {"DONE", "EXECUTING", "REJECTED"},
    "DONE": set(),
    "REJECTED": {"PROPOSED"},
    "": {"PROPOSED", "JUSTIFIED", "EXECUTING", "PAUSED", "REPORTED", "DONE"},
}


def audit_event_stream(root) -> list[str]:
    """Invariant audit over events.jsonl. Empty = clean stream."""
    from events import read as eread
    rows = eread(root)
    bad = []
    monos = [r.get("mono_ns", 0) for r in rows]
    if monos != sorted(monos):
        bad.append("mono_ns not non-decreasing")
    asked = {r.get("hid") for r in rows if r.get("event") == "human.asked"}
    for r in rows:
        if r.get("event") == "human.choice" and r.get("hid") not in asked:
            bad.append(f"choice without ask: {r.get('hid')}")
    started = {(r.get("task_id")) for r in rows if r.get("event") == "run.started"}
    for r in rows:
        if r.get("event") == "run.finished" and r.get("task_id") not in started:
            bad.append(f"finish without start: {r.get('task_id')}")
    if len([r for r in rows if r.get("event") == "goal.done"]) > 1:
        bad.append("goal.done emitted more than once")
    for r in rows:
        if r.get("event") == "task.status":
            if r.get("to") not in LEGAL_EDGES.get(r.get("from", ""), set()):
                bad.append(f"illegal edge {r.get('from')} -> {r.get('to')}")
    done = {r.get("task_id") for r in rows if r.get("event") == "run.finished"}
    passed = {r.get("task_id") for r in rows if r.get("event") == "validator.passed"}
    for t in done:
        if t not in passed:
            bad.append(f"DONE without validator.passed: {t}")
    return bad


class TestEventAudit(unittest.TestCase):
    def test_scripted_build_audits_clean(self):
        from events import read as eread
        from instrument import digest, run
        root = fresh_root(self)
        driver_boot(root)
        goal_set(root, "g", ["a runs", "b set"])
        add_task(root, "a-a", accept=("a runs",))
        add_task(root, "a-b", accept=("b set",))
        recs = atask.load(os.path.join(root, "tasks.jsonl"))
        recs[0]["covers_goal"] = [0]
        recs[1]["covers_goal"] = [1]
        atask.save_all(recs, os.path.join(root, "tasks.jsonl"))
        for tid in ("a-a", "a-b"):
            atask.set_status(tid, "JUSTIFIED", root)
        earn(root, "a-b", os.path.join(root, "fixed-a-b"))
        h_escalate(root, "a-b", "pick?", "PREFERENCE", ["x", "y"], "x",
                   operation="op-pick")
        run("0", session="s-audit", root=root)  # a-b: PAUSED -> EXECUTING
        atask.set_status("a-a", "EXECUTING", root)
        open(os.path.join(root, "fixed-a-b"), "w").write("fixed")
        for tid in ("a-a", "a-b"):
            atask.alog(tid, "work", [0], root, "x", "command:echo ok")
            rr, vr = write_report(root, tid), write_receipt(root, tid)
            atask.set_status(tid, "REPORTED", root,
                             report_ref=rr, validation_ref=vr)
        rep = driver_pulse(root)
        self.assertEqual(rep["promoted"], ["a-a", "a-b"])
        digest(root, "s-audit")
        rows = eread(root)
        self.assertGreater(len(rows), 10)
        self.assertEqual(audit_event_stream(root), [])
        kinds = {r["event"] for r in rows}
        self.assertTrue({"run.started", "run.finished", "validator.passed",
                         "human.asked", "human.choice", "goal.done",
                         "session.outcome", "task.status"} <= kinds)

    def test_audit_catches_illegal_edge(self):
        from events import emit as eemit
        root = fresh_root(self)
        driver_boot(root)
        eemit(root, "task.status", task_id="a-x", **{"from": "DONE", "to": "EXECUTING"})
        bad = audit_event_stream(root)
        self.assertTrue(any("illegal edge" in b for b in bad))


class TestBudgetEnforced(unittest.TestCase):
    def test_crossing_call_completes_next_refused(self):
        from budget import Budget, BudgetExceeded
        b = Budget(max_usd=0.05)
        b.record(cost=0.03, label="call-1")
        with self.assertRaises(BudgetExceeded):
            b.record(cost=0.03, label="call-2")  # completes, then refuses
        with self.assertRaises(BudgetExceeded):
            b.check("call-3")

    def test_caps_persist_and_advertise(self):
        from budget import FileBudget
        root = fresh_root(self)
        driver_boot(root)
        FileBudget(root).set_caps(1.0, None)
        FileBudget(root).record(cost=0.25, tokens=100, label="x")
        b2 = FileBudget(root)
        self.assertAlmostEqual(b2.spent_usd, 0.25)
        self.assertEqual(b2.advertise()["ATASK_BUDGET_USD"], "0.75")

    def test_usage_charges_and_warns_on_crossing(self):
        from budget import FileBudget
        from runs import list_open
        root = fresh_root(self)
        driver_boot(root)
        FileBudget(root).set_caps(0.05, None)
        add_task(root, "a-c")
        atask.main(["run", "start", "--dir", root, "--id", "a-c"])
        rid = list_open(root, "a-c")[0]["run_id"]
        rc = atask.main(["run", "usage", "--dir", root, "--run", rid,
                         "--input-tokens", "100", "--output-tokens", "50",
                         "--cost", "0.05"])
        self.assertEqual(rc, 0)  # crossing call still records
        self.assertAlmostEqual(FileBudget(root).spent_usd, 0.05)
        self.assertTrue(FileBudget(root).exhausted())

    def test_pulse_refuses_when_exhausted(self):
        from budget import BudgetExceeded, FileBudget
        root = fresh_root(self)
        driver_boot(root)
        FileBudget(root).set_caps(0.01, None)
        with self.assertRaises(BudgetExceeded):
            FileBudget(root).record(cost=0.01, label="burn")
        rep = driver_pulse(root)
        self.assertIn("error", rep)
        self.assertIn("budget", rep["error"].lower())
        self.assertFalse(rep["halt_legal"])


class TestARun(unittest.TestCase):
    def test_start_usage_finish_lifecycle(self):
        from runs import list_open, read_runs, task_run_stats
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-r")
        rc = atask.main(["run", "start", "--dir", root, "--id", "a-r",
                         "--worker", "opencode", "--model", "mimo-v2.5",
                         "--provider", "openrouter"])
        self.assertEqual(rc, 0)
        by_id = {r["id"]: r for r in
                 atask.load(os.path.join(root, "tasks.jsonl"))}
        self.assertEqual(by_id["a-r"]["status"], "EXECUTING")
        self.assertEqual(by_id["a-r"]["attempts"], 1)
        opens = list_open(root, "a-r")
        self.assertEqual(len(opens), 1)
        rid = opens[0]["run_id"]
        rc = atask.main(["run", "usage", "--dir", root, "--run", rid,
                         "--input-tokens", "48321", "--output-tokens", "7132",
                         "--cached-tokens", "22100", "--token-source", "provider",
                         "--cost", "0.0831"])
        self.assertEqual(rc, 0)
        rc = atask.main(["run", "finish", "--dir", root, "--run", rid,
                         "--result", "failed", "--validator", "pytest"])
        self.assertEqual(rc, 0)
        self.assertEqual(list_open(root, "a-r"), [])
        rows = read_runs(root, "a-r")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["result"], "failed")
        self.assertEqual(rows[0]["input_tokens"], 48321)
        self.assertEqual(rows[0]["token_source"], "provider")
        self.assertAlmostEqual(rows[0]["reported_cost_usd"], 0.0831)
        self.assertGreaterEqual(rows[0]["duration_ms"], 0)
        st = task_run_stats(root, "a-r")
        self.assertEqual(st["attempts"], 1)
        self.assertEqual(st["input_tokens"], 48321)
        self.assertTrue(st["tokens_known"])

    def test_three_runs_aggregate(self):
        from runs import task_run_stats
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-m")
        for res, cost in (("failed", 0.02), ("failed", 0.03), ("completed", 0.05)):
            atask.main(["run", "start", "--dir", root, "--id", "a-m",
                        "--model", "mimo-v2.5"])
            from runs import list_open
            rid = list_open(root, "a-m")[0]["run_id"]
            atask.main(["run", "usage", "--dir", root, "--run", rid,
                        "--input-tokens", "1000", "--output-tokens", "100",
                        "--cost", str(cost)])
            atask.main(["run", "finish", "--dir", root, "--run", rid,
                        "--result", res])
        st = task_run_stats(root, "a-m")
        self.assertEqual(st["attempts"], 3)
        self.assertEqual(st["input_tokens"], 3000)
        self.assertAlmostEqual(st["cost_usd"], 0.10)
        self.assertEqual(st["results"], ["failed", "failed", "completed"])
        self.assertEqual(st["last_result"], "completed")

    def test_from_session_wiring(self):
        import tempfile
        import shutil
        from meters.opencode_db import calibration, message_usage, session_totals
        import sqlite3
        tmp = tempfile.mkdtemp(prefix="meters-test-")
        self.addCleanup(shutil.rmtree, tmp, True)
        dbp = os.path.join(tmp, "t.db")
        db = sqlite3.connect(dbp)
        db.execute("create table session (id text, title text, model text, agent text,"
                   " tokens_input int, tokens_output int, tokens_reasoning int,"
                   " tokens_cache_read int, tokens_cache_write int, cost real)")
        db.execute("create table message (id text, session_id text, time_created int,"
                   " time_updated int, data text)")
        import json as _j, time as _t
        db.execute("insert into session values (?,?,?,?,?,?,?,?,?,?)",
                   ("ses_1", "t", "{}", "build", 1000, 200, 0, 0, 0, 0.05))
        now_ms = int(_t.time() * 1000)
        assistant = _j.dumps({"role": "assistant", "cost": 0.01,
                              "tokens": {"input": 500, "output": 100, "reasoning": 0}})
        db.execute("insert into message values (?,?,?,?,?)",
                   ("m1", "ses_1", now_ms, now_ms, assistant))
        db.execute("insert into message values (?,?,?,?,?)",
                   ("m2", "ses_1", now_ms, now_ms, _j.dumps({"role": "user"})))
        db.commit()
        db.close()
        st = session_totals("ses_1", dbp)
        self.assertTrue(st["found"])
        self.assertEqual(st["tokens_input"], 1000)
        self.assertFalse(session_totals("ses_nope", dbp)["found"])
        mu = message_usage("ses_1", 0, dbp)
        self.assertEqual(mu["messages"], 1)  # user message excluded
        self.assertEqual(mu["in"], 500)
        cal = calibration("ses_1", dbp)
        self.assertIsNotNone(cal["ratio_est_over_actual"])
        # end-to-end through run usage against the real store
        # (skipped where the fixture session doesn't exist: other machines)
        from meters.opencode_db import session_totals as _st
        try:
            live = _st("ses_f70dff82bffe12tRcOu9iGDgSW")["found"]
        except Exception:
            live = False
        if not live:
            self.skipTest("fixture opencode session absent on this box")
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-m")
        rc = atask.main(["run", "start", "--dir", root, "--id", "a-m"])
        self.assertEqual(rc, 0)
        from runs import list_open
        rid = list_open(root, "a-m")[0]["run_id"]
        rc = atask.main(["run", "usage", "--dir", root, "--run", rid,
                         "--from-session", "ses_f70dff82bffe12tRcOu9iGDgSW",
                         "--since", "120"])
        self.assertEqual(rc, 0)
        run = list_open(root, "a-m")[0]
        self.assertEqual(run["token_source"], "provider")
        self.assertGreater(run["input_tokens"], 100000)  # real session volume
        rc = atask.main(["run", "usage", "--dir", root, "--run", rid,
                         "--from-session", "ses_nope"])
        self.assertEqual(rc, 1)  # unknown session refused, no silent zeros

    def test_abandon_and_unknown_run_refused(self):
        from runs import list_open, read_runs
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-q")
        atask.main(["run", "start", "--dir", root, "--id", "a-q"])
        from runs import list_open as _lo
        rid = _lo(root, "a-q")[0]["run_id"]
        rc = atask.main(["run", "finish", "--dir", root, "--run", rid,
                         "--result", "abandoned"])
        self.assertEqual(rc, 0)
        self.assertEqual(read_runs(root, "a-q")[0]["result"], "abandoned")
        rc = atask.main(["run", "finish", "--dir", root, "--run", "r-deadbeef",
                         "--result", "completed"])
        self.assertEqual(rc, 1)
        self.assertEqual(list_open(root), [])

    def test_pulse_orders_carry_run_stats(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-o")
        atask.main(["run", "start", "--dir", root, "--id", "a-o",
                    "--model", "mimo-v2.5"])
        from runs import list_open
        rid = list_open(root, "a-o")[0]["run_id"]
        atask.main(["run", "usage", "--dir", root, "--run", rid,
                    "--input-tokens", "500", "--output-tokens", "50",
                    "--cost", "0.01"])
        atask.main(["run", "finish", "--dir", root, "--run", rid,
                    "--result", "failed", "--validator", "pytest"])
        atask.set_status("a-o", "EXECUTING", root)
        rep = driver_pulse(root)
        self.assertEqual(len(rep["orders"]), 1)
        o = rep["orders"][0]
        self.assertEqual(o["attempts"], 1)
        self.assertEqual(o["tokens"]["in"], 500)
        self.assertEqual(o["cost_usd"], 0.01)


class TestMinimalPass(unittest.TestCase):
    """The six final-pass fixes: bypasses closed, accounting single-sourced."""

    def test_done_cannot_bypass_stoplight(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-b")
        for st in ("JUSTIFIED", "EXECUTING", "REPORTED"):
            atask.set_status("a-b", st, root)
        rr, vr = write_report(root, "a-b"), write_receipt(root, "a-b")
        # Proof files attached but acceptance uncovered + no evidence:
        # direct DONE must refuse with the stoplight reason.
        ok, msg = atask.set_status("a-b", "DONE", root,
                                   report_ref=rr, validation_ref=vr)
        self.assertFalse(ok)
        self.assertIn("stoplight", msg)
        self.assertIn("uncovered", msg)
        by_id = {r["id"]: r for r in
                 atask.load(os.path.join(root, "tasks.jsonl"))}
        self.assertEqual(by_id["a-b"]["status"], "REPORTED")  # restored, not dirty

    def test_evidence_required_gates(self):
        root = fresh_root(self)
        driver_boot(root)
        q = os.path.join(root, "tasks.jsonl")
        recs = atask.load(q)
        recs.append({"id": "a-e", "tier": "A", "summary": "e",
                     "acceptance": ["done"], "evidence_required": [
                         {"kind": "command", "spec": "echo proven"},
                         {"kind": "file", "spec": "reports/a-e.md"}],
                     "blocked_by": [], "status": "REPORTED",
                     "report_ref": "", "validation_ref": ""})
        atask.save_all(recs, q)
        atask.alog("a-e", "work", [0], root, "x", "")
        write_report(root, "a-e")
        recs = atask.load(q)
        recs[0]["report_ref"] = "reports/a-e.md"
        recs[0]["validation_ref"] = write_receipt(root, "a-e")
        atask.save_all(recs, q)
        sl = atask.stoplight("a-e", root)
        self.assertTrue(sl["go"], sl)  # echo runs green, file exists
        recs = atask.load(q)
        recs[0]["evidence_required"] = [
            {"kind": "command", "spec": "python3 -c \"import sys; sys.exit(9)\""}]
        atask.save_all(recs, q)
        sl = atask.stoplight("a-e", root)
        self.assertFalse(sl["go"])
        self.assertTrue(any("required[0]" in m for m in sl["missing"]))

    def test_evidence_required_malformed_refused(self):
        root = fresh_root(self)
        driver_boot(root)
        rc = atask.main(["add", "--dir", root, "--id", "a-x",
                         "--summary", "x", "--evidence", "vibes"])
        self.assertEqual(rc, 1)

    def test_alog_refuses_unknown_task(self):
        root = fresh_root(self)
        driver_boot(root)
        with self.assertRaises(ValueError):
            atask.alog("a-ghost", "work", [0], root, "x", "")
        rc = atask.main(["log", "--dir", root, "--id", "a-ghost",
                         "--covers", "0"])
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(os.path.join(root, "a-logs", "a-ghost.jsonl")))

    def test_single_run_class_with_full_schema(self):
        import runs
        src = open(os.path.join(HERE, "runs.py")).read()
        self.assertEqual(src.count("@dataclass\nclass Run:"), 1)
        r = runs.Run(task_id="a-x")
        for f in ("input_tokens", "output_tokens", "cached_tokens",
                  "token_source", "reported_cost_usd", "provider", "model",
                  "worker", "ended_at", "duration_ms"):
            self.assertIn(f, r.snapshot())

    def test_mono_reboot_falls_back_to_wall(self):
        import time as _t
        from runs import Run
        r = Run(task_id="a-x")
        r.started_mono_ns = _t.monotonic_ns() + 10 ** 15  # simulated reboot
        _t.sleep(0.02)
        snap = r.finish("completed")
        self.assertGreaterEqual(snap["duration_ms"], 0)
        self.assertLess(snap["duration_ms"], 60000)  # wall-based, not garbage

    def test_no_trust_only_tasks(self):
        root = fresh_root(self)
        driver_boot(root)
        rc = atask.main(["add", "--dir", root, "--id", "a-naked",
                         "--summary", "x", "--accept", "y"])
        self.assertEqual(rc, 1)
        rc = atask.main(["add", "--dir", root, "--id", "a-ok",
                         "--summary", "x", "--accept", "y",
                         "--evidence", "command:echo ok"])
        self.assertEqual(rc, 0)
        add_task(root, "a-par", accept=(), ev=())
        rc = atask.main(["spawn", "--dir", root, "--parent", "a-par",
                         "--id", "a-kid", "--summary", "x",
                         "--accept", "y"])
        self.assertEqual(rc, 1)
        # verify flags grandfathered trust-only records
        q = os.path.join(root, "tasks.jsonl")
        recs = atask.load(q)
        recs.append({"id": "a-old", "tier": "A", "summary": "old",
                     "acceptance": ["y"], "evidence_required": [],
                     "blocked_by": [], "status": "PROPOSED",
                     "report_ref": "", "validation_ref": ""})
        atask.save_all(recs, q)
        self.assertTrue(any("no trust-only" in f for f in atask.verify(root)))

    def test_reject_and_refile(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-bad")
        atask.set_status("a-bad", "REPORTED", root)
        rc = atask.main(["reject", "--dir", root, "--id", "a-bad",
                         "--reasons", "wrong approach"])
        self.assertEqual(rc, 0)
        by_id = {r["id"]: r for r in
                 atask.load(os.path.join(root, "tasks.jsonl"))}
        self.assertEqual(by_id["a-bad"]["status"], "REJECTED")
        self.assertIn("wrong approach", by_id["a-bad"].get("reasons", ""))
        # rejected tasks leave the missing set (dogfood-proven path)
        rep = driver_pulse(root)
        self.assertTrue(rep["halt_legal"])


class TestPromotionProof(unittest.TestCase):
    def _tried(self, root, tid, red=True):
        add_task(root, tid)
        atask.set_status(tid, "EXECUTING", root)
        atask.set_status(tid, "JUSTIFIED", root)
        atask.set_status(tid, "EXECUTING", root)  # 2 attempts
        ev = ("command:python3 -c \"import sys; sys.exit(9)\"" if red
              else "command:echo ok")
        atask.alog(tid, "work", [0], root, "tried", ev)

    def test_untried_escalation_refused(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-fresh")
        ok, msg = h_escalate(root, "a-fresh", "stuck?", "AMBIGUITY")
        self.assertFalse(ok)
        self.assertIn("attempt", msg)

    def test_attempts_without_failure_refused(self):
        root = fresh_root(self)
        driver_boot(root)
        self._tried(root, "a-clean", red=False)
        ok, msg = h_escalate(root, "a-clean", "stuck?", "PREFERENCE",
                             ["a", "b"], "a")
        self.assertFalse(ok)
        self.assertIn("no failed checkable attempt", msg)

    def test_red_evidence_allows(self):
        root = fresh_root(self)
        driver_boot(root)
        self._tried(root, "a-red", red=True)
        ok, hid = h_escalate(root, "a-red", "stuck?", "SECRET", operation="op-red")
        self.assertTrue(ok, hid)

    def test_validator_failed_event_allows(self):
        from events import emit as eemit
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-vf")
        atask.set_status("a-vf", "EXECUTING", root)
        atask.set_status("a-vf", "JUSTIFIED", root)
        atask.set_status("a-vf", "EXECUTING", root)
        atask.alog("a-vf", "work", [0], root, "tried", "")
        eemit(root, "validator.failed", task_id="a-vf", reasons=["x"])
        ok, hid = h_escalate(root, "a-vf", "stuck?", "AUTHORIZATION", operation="op-vf")
        self.assertTrue(ok, hid)

    def test_physical_exempt(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-sign")
        ok, hid = h_escalate(root, "a-sign", "sign here", "PHYSICAL")
        self.assertTrue(ok, hid)

    def test_flapping_farms_nothing(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-flap")
        for _ in range(5):  # status-flap with no a-log and no failure
            atask.set_status("a-flap", "EXECUTING", root)
            atask.set_status("a-flap", "JUSTIFIED", root)
        ok, msg = h_escalate(root, "a-flap", "stuck?", "AMBIGUITY")
        self.assertFalse(ok)  # attempts high, but no log + no failure


class TestBlockClaim(unittest.TestCase):
    def test_operation_required(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-b")
        earn(root, "a-b")
        ok, msg = h_escalate(root, "a-b", "stuck?", "SECRET")
        self.assertFalse(ok)
        self.assertIn("operation", msg)

    def test_block_carries_runtime_evidence(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-b")
        earn(root, "a-b")
        ok, hid = h_escalate(root, "a-b", "need key?", "SECRET",
                             operation="op-vault.read",
                             alternatives=["local-vault:unsupported"])
        self.assertTrue(ok, hid)
        hs = {h["id"]: h for h in atask.hload(root)}
        blk = hs[hid]["block"]
        self.assertEqual(blk["operation"], "op-vault.read")
        self.assertEqual(blk["verdict"], "H_BLOCK")
        self.assertTrue(any("red" in e for e in blk["evidence"]),
                        blk["evidence"])
        self.assertEqual(blk["alternatives_checked"],
                         [{"route": "local-vault", "status": "unsupported"}])

    def test_exempt_needs_no_operation(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-s")
        ok, hid = h_escalate(root, "a-s", "sign?", "PHYSICAL")
        self.assertTrue(ok, hid)
        self.assertEqual(atask.hload(root)[0]["block"]["evidence"], [])


class TestMTask(unittest.TestCase):
    def test_request_needs_counterfactuals(self):
        from atask import mrequest
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-m")
        ok, mid = mrequest(root, "a-m", "gpt-5.6", 17, 0.71, 0.0, 0.92, 0.17,
                           "need 90% bar")
        self.assertTrue(ok, mid)
        ms = {m["id"]: m for m in atask.mload(root)}
        self.assertEqual(ms[mid]["marginal_gain_pp"], 21.0)
        self.assertEqual(ms[mid]["status"], "open")

    def test_bad_probability_refused(self):
        from atask import mrequest
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-m")
        ok, msg = mrequest(root, "a-m", "x", 5, 1.5, 0.0, 0.9, 0.1)
        self.assertFalse(ok)
        self.assertIn("probability", msg)

    def test_resolve_records_decision(self):
        from atask import mrequest, mresolve, open_m
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-m")
        ok, mid = mrequest(root, "a-m", "gpt-5.6", 17, 0.71, 0.0, 0.92, 0.17)
        self.assertTrue(ok)
        ok, msg = mresolve(root, mid, "approved-once", "one shot")
        self.assertTrue(ok, msg)
        self.assertEqual(open_m(root), [])
        ok, msg = mresolve(root, mid, "denied")
        self.assertFalse(ok)  # decided m-tasks don't reopen


class TestQuiet(unittest.TestCase):
    def test_quiet_prints_close_lines_only(self):
        import io as _io
        from contextlib import redirect_stdout as _ro
        root = fresh_root(self)
        driver_boot(root)
        buf = _io.StringIO()
        with _ro(buf):
            rc = atask.main(["--quiet", "goal", "set", "--dir", root,
                             "--statement", "s", "--accept", "x"])
        self.assertEqual(rc, 0)
        add_task(root, "a-q")
        buf = _io.StringIO()
        with _ro(buf):
            rc = atask.main(["run", "start", "--quiet", "--dir", root,
                             "--id", "a-q"])
        self.assertEqual(rc, 0)
        rid = buf.getvalue().strip()
        self.assertRegex(rid, r"^r-[0-9a-f]+$")  # id only, no JSON blob
        buf = _io.StringIO()
        with _ro(buf):
            rc = atask.main(["run", "finish", "-q", "--dir", root,
                             "--run", rid, "--result", "completed"])
        self.assertEqual(rc, 0)
        self.assertNotIn("input_tokens", buf.getvalue())
        buf = _io.StringIO()
        with _ro(buf):
            from driver import main as driver_main
            rc = driver_main(["pulse", "-q", "--dir", root])
        self.assertEqual(rc, 0)
        self.assertNotIn("{", buf.getvalue())


class TestIncremental(unittest.TestCase):
    def test_second_read_scans_only_new_rows(self):
        import sqlite3
        import tempfile
        import shutil
        from meters.opencode_db import message_usage_since
        tmp = tempfile.mkdtemp(prefix="meters-inc-")
        self.addCleanup(shutil.rmtree, tmp, True)
        dbp = os.path.join(tmp, "t.db")
        state = os.path.join(tmp, "ckpt.json")
        db = sqlite3.connect(dbp)
        db.execute("create table message (id text, session_id text,"
                   " time_created int, time_updated int, data text)")
        import json as _j
        mk = lambda i, n: (_j.dumps({"role": "assistant", "cost": 0.01,
                                     "tokens": {"input": n, "output": 1}}))
        for i in range(1, 4):
            db.execute("insert into message values (?,?,?,?,?)",
                       (f"m{i}", "s", i * 1000, i * 1000, mk(i, 100)))
        db.commit()
        first = message_usage_since("s", state, dbp)
        self.assertEqual(first["messages"], 3)
        self.assertEqual(first["rows_scanned"], 3)
        db.execute("insert into message values (?,?,?,?,?)",
                   ("m4", "s", 4000, 4000, mk(4, 100)))
        db.commit()
        db.close()
        second = message_usage_since("s", state, dbp)
        self.assertEqual(second["messages"], 1)  # only the new row
        self.assertEqual(second["rows_scanned"], 1)
        self.assertEqual(second["in"], 100)


if __name__ == "__main__":
    unittest.main()
