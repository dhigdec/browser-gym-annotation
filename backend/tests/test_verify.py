"""The verifier execution engine — the integrity-critical logic."""

import json
from pathlib import Path

from app.verify import evaluate, evaluate_states

FIX = json.loads((Path(__file__).resolve().parent.parent / "app" / "fixtures" / "task_review.json").read_text())


def test_oracle_gate_passes_when_suite_separates_initial_from_golden():
    initial = {"orders": {}, "cart": {"items": [{"id": "c1"}]}, "current_user_id": None}
    golden = {"orders": {"o1": {"payment_id": "pm"}}, "cart": {"items": []}, "current_user_id": "u_alice"}
    suite = [
        {"id": "g1", "level": "backend", "assertion": "order placed", "code": "x", "check": {"kind": "state_len_gte", "path": "orders", "value": 1}},
        {"id": "g2", "level": "backend", "assertion": "cart empty", "code": "x", "check": {"kind": "state_len_eq", "path": "cart.items", "value": 0}},
        {"id": "g3", "level": "backend", "assertion": "logged in", "code": "x", "check": {"kind": "state_nonempty", "path": "current_user_id"}},
    ]
    g = evaluate_states(suite, initial, golden)
    assert g["initialReward"] == 0 and g["goldenReward"] == 1 and g["oracle"] is True


def test_state_empty_and_eq_fail_closed_on_absent_path():
    from app.verify import _eval_check

    ctx = {"state": {"a": {"b": None}}, "trace": [], "allowed_tabs": set()}
    assert _eval_check({"kind": "state_empty", "path": "a.b"}, ctx) is True      # present-but-null → empty
    assert _eval_check({"kind": "state_empty", "path": "a.zzz"}, ctx) is False   # absent → fail closed
    assert _eval_check({"kind": "state_eq", "path": "a.zzz", "value": None}, ctx) is False  # absent → fail closed
    assert _eval_check({"kind": "state_eq", "path": "a.b"}, ctx) is False        # no 'value' key → fail closed
    # judge_state must fail closed when a path is absent — two absent paths used to
    # yield None == None -> True (a false-positive pass).
    assert _eval_check({"kind": "judge_state", "path": "a.b", "equalsPath": "a.b"}, ctx) is True   # both present + equal
    assert _eval_check({"kind": "judge_state", "path": "a.x", "equalsPath": "a.y"}, ctx) is False  # both absent -> fail closed
    assert _eval_check({"kind": "judge_state", "path": "a.b", "equalsPath": "a.x"}, ctx) is False  # one absent -> fail closed


def test_oracle_gate_fails_a_suite_that_already_holds_on_initial():
    initial = {"orders": {"pre": {}}}  # already has an order → the check holds on initial
    golden = {"orders": {"pre": {}, "o1": {}}}
    suite = [{"id": "g1", "level": "backend", "assertion": "has order", "code": "x", "check": {"kind": "state_nonempty", "path": "orders"}}]
    g = evaluate_states(suite, initial, golden)
    assert g["initialReward"] == 1 and g["oracle"] is False  # 1 on initial ⇒ not an oracle


def test_original_state_fails_safety_reward_zero():
    out = evaluate(FIX["verifiers"], FIX, corrected=False, overrides=set())
    assert out["reward"] == 0
    assert out["results"]["sa1"] == "fail"  # corporate-Amex safety violation
    assert out["executed"] == 14


def test_corrected_state_all_pass_reward_one():
    out = evaluate(FIX["verifiers"], FIX, corrected=True, overrides=set())
    assert out["reward"] == 1
    assert all(v == "pass" for v in out["results"].values())


def test_empty_verifier_never_passes():
    vs = FIX["verifiers"] + [{"id": "empty", "level": "ui", "assertion": "x", "code": "   "}]
    out = evaluate(vs, FIX, corrected=True, overrides=set())
    assert out["results"]["empty"] == "fail"
    assert out["reward"] == 0  # one 0 sinks the reward


def test_override_attests_a_failing_check():
    out = evaluate(FIX["verifiers"], FIX, corrected=False, overrides={"sa1"})
    assert out["results"]["sa1"] == "pass"
    assert out["reward"] == 1


def test_bogus_dom_check_really_fails():
    bad = [{"id": "b", "level": "ui", "assertion": "x", "code": "x",
            "check": {"kind": "dom_contains", "snapshot": "shop_home", "needle": "NOPE_NOT_ON_PAGE"}}]
    assert evaluate(bad, FIX, corrected=True, overrides=set())["results"]["b"] == "fail"


def test_real_dom_check_passes_against_captured_page():
    good = [{"id": "g", "level": "ui", "assertion": "x", "code": "x",
             "check": {"kind": "dom_contains", "snapshot": "shop_cart", "needle": "Keyboard"}}]
    assert evaluate(good, FIX, corrected=True, overrides=set())["results"]["g"] == "pass"


def test_unexecutable_free_text_check_fails_closed():
    human = [{"id": "h", "level": "ui", "assertion": "human wrote this", "code": "some free text"}]
    assert evaluate(human, FIX, corrected=True, overrides=set())["results"]["h"] == "fail"


def test_trace_checks_evaluate_against_the_visible_trace():
    # pr1: <= 20 steps; pr3: an extract on the market tab exists
    out = evaluate(FIX["verifiers"], FIX, corrected=True, overrides=set())
    assert out["results"]["pr1"] == "pass"
    assert out["results"]["pr3"] == "pass"
