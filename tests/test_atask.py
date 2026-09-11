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
        ok, hid = h_escalate(root, "a-need", "which API key?", "SECRET",
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

    def test_ask_gate_refuses_non_boundary(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-lib")
        ok, msg = h_escalate(root, "a-lib", "which python library?", "VIBES")
        self.assertFalse(ok)
        self.assertIn("not a human boundary", msg)
        ok, hid = h_escalate(root, "a-lib", "which region?", "PREFERENCE",
                             ["eu", "us"], "eu")
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
        h_escalate(root, "a-h", "decide?", "PREFERENCE")
        rep = driver_pulse(root)
        self.assertIn("open_h", rep)
        self.assertEqual(len(rep["open_h"]), 1)
        self.assertIn("goal", rep)
        self.assertIn("spent", rep)


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
        h_escalate(root, "a-need", "pick one?", "PREFERENCE", ["aa", "bb"], "aa")
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
        h_escalate(root, "a-need", "pick?", "PREFERENCE", ["aa", "bb"], "bb")
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
        h_escalate(root, "a-need", "pick?", "AMBIGUITY", ["aa"], "aa")
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
        h_escalate(root, "a-t", "say something?", "SECRET")
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
        h_escalate(root, "a-s", "give input", "SECRET")
        rep = run("7", session="s1", root=root,
                  payloads={"7": "my api_key: hunter2hunter2"})
        self.assertFalse(rep["results"][0]["ok"])
        self.assertIn("secret-refused", rep["results"][0]["action"])

    def test_ok_no_deny(self):
        from instrument import run
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-t2")
        h_escalate(root, "a-t2", "approve?", "AUTHORIZATION")
        rep = run("5", session="s1", root=root)
        self.assertIn("approved", rep["results"][0]["close"])
        add_task(root, "a-t3")
        h_escalate(root, "a-t3", "approve?", "AUTHORIZATION")
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

    def test_spend_is_recorded_context(self):
        root = fresh_root(self)
        driver_boot(root)
        add_task(root, "a-c")
        atask.alog("a-c", "work", [0], root, "x", "")
        q = os.path.join(root, "tasks.jsonl")
        recs = atask.load(q)
        recs[0]["spent_usd"] = 0.72
        atask.save_all(recs, q)
        from driver import spent_totals
        self.assertAlmostEqual(spent_totals(root)["spent_usd"], 0.72)

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
        h_escalate(root, "a-h", "pick?", "PREFERENCE", ["aa", "bb"], "aa")
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
        atask.set_status("a-c", "EXECUTING", root)
        atask.alog("a-c", "work", [0], root, "x", "")
        q = os.path.join(root, "tasks.jsonl")
        recs = atask.load(q)
        recs[0]["spent_usd"] = 0.03
        atask.save_all(recs, q)
        # CLI path emits resource.used
        import subprocess as _sp
        r = _sp.run([sys.executable, os.path.join(HERE, "atask.py"),
                     "log", "--dir", root, "--id", "a-c",
                     "--covers", "0", "--cost", "0.01", "--tokens", "50"],
                    capture_output=True, text=True, cwd=HERE)
        self.assertEqual(r.returncode, 0, r.stderr)
        res = eread(root, "resource.used")
        self.assertEqual(len(res), 1)
        self.assertAlmostEqual(res[0]["cost_usd"], 0.01)

    def test_run_dataclass_mono_timing(self):
        from runs import Run
        r = Run(task_id="a-x")
        r.note(cost_usd=0.02, tokens=100, tools=3)
        snap = r.finish("validated")
        self.assertEqual(snap["outcome"], "validated")
        self.assertAlmostEqual(snap["spent_usd"], 0.02)
        self.assertGreaterEqual(snap["elapsed_ms"], 0)

    def test_bats_block_with_remaining(self):
        from driver import resources
        root = fresh_root(self)
        driver_boot(root)
        goal_set(root, "g", ["x"], budget_usd=1.0, token_budget=1000,
                 deadline_min=30)
        add_task(root, "a-c")
        atask.set_status("a-c", "EXECUTING", root)
        atask.alog("a-c", "work", [0], root, "x", "")
        q = os.path.join(root, "tasks.jsonl")
        recs = atask.load(q)
        recs[0]["spent_usd"] = 0.25
        recs[0]["spent_tokens"] = 100
        atask.save_all(recs, q)
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
        h_escalate(root, "a-need", "pick?", "PREFERENCE", ["aa", "bb"], "aa")
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


        self.assertEqual(bad, [])


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
        h_escalate(root, "a-b", "pick?", "PREFERENCE", ["x", "y"], "x")
        run("0", session="s-audit", root=root)  # a-b: PAUSED -> EXECUTING
        atask.set_status("a-a", "EXECUTING", root)
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


if __name__ == "__main__":
    unittest.main()
