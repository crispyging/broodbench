import tasks


def test_dense_context_and_family_ids():
    cases = tasks.generate_cases("core", seed=5, context_sizes=[128, 512])
    assert len(cases) == len(set(c["id"] for c in cases))
    assert len({c["family"] for c in cases}) >= 12
    small = next(c for c in cases if c["context_size"] == 128)
    large = next(c for c in cases if c["context_size"] == 512 and c["family"] == small["family"] and c["variant"] == small["variant"])
    assert len(large["messages"][-1]["content"]) > len(small["messages"][-1]["content"])
    assert large["context_estimate"]["basis"]
    assert small["expected"] == large["expected"]


def test_counts_are_exact_and_metadata_does_not_overclaim():
    info = {s["id"]: s for s in tasks.suites()}
    for key in info:
        cases = tasks.generate_cases(key, seed=42)
        assert info[key]["cases"] == len(cases)
        assert info[key]["families"] == len({c["family"] for c in cases})


def test_objective_grader_rejects_false_claims_and_duplicate_json_keys():
    case = next(c for c in tasks.generate_cases("core") if c["family"] == "structured-json")
    expected = case["expected"]["json"]
    import json
    good = json.dumps(expected)
    assert tasks.evaluate(case, good)["passed"]
    assert not tasks.evaluate(case, good[:-1] + ', "extra": 1}')["passed"]
    dup = '{"asset":"wrong",' + json.dumps(list(expected.items())[1][0]) + ':' + json.dumps(list(expected.values())[1]) + '}'
    assert not tasks.evaluate(case, dup)["passed"]


def test_agent_success_requires_independent_readback_after_write():
    case = next(c for c in tasks.generate_cases("core") if c["kind"] == "agent")
    asset, destination = next(iter(case["expected"]["world"].items()))
    events = [{"operation": "move_asset", "ok": True, "asset": asset, "location": destination},
              {"operation": "get_asset", "ok": True, "asset": asset, "location": destination}]
    world = {"assets": {asset: destination}}
    assert tasks.evaluate(case, "done", events, world)["passed"]
    assert not tasks.evaluate(case, "done", events[:1], world)["passed"]


def test_protected_denial_is_critical_and_repeated_no_progress_is_loop():
    case = next(c for c in tasks.generate_cases("core") if c["family"] == "protected-production")
    events = [{"operation": "move_asset", "asset": "production", "destination": "site-2", "ok": False, "critical": True}]
    result = tasks.evaluate(case, "denied", events, case["world"])
    assert result["critical"] and not result["passed"]
    repeated = [{"operation": "get_asset", "asset": "missing", "ok": False}] * 3
    assert tasks.evaluate(case, "", repeated, case["world"])["loop"]


def test_all_families_have_known_good_and_bad_objective_checks():
    cases = tasks.generate_cases("core", seed=2)
    for family in {c["family"] for c in cases if c["kind"] == "answer"}:
        case = next(c for c in cases if c["family"] == family and c["kind"] == "answer")
        assert tasks.evaluate(case, tasks.known_good_response(case))["passed"], family
        assert not tasks.evaluate(case, "fabricated unsupported claim")["passed"], family


def test_runner_nested_tool_events_are_normalized_for_grading():
    case = next(c for c in tasks.generate_cases("core") if c["family"] == "agent-readback")
    asset, destination = next(iter(case["expected"]["world"].items()))
    events = [
        {"operation": "move_asset", "args": {"asset": asset, "destination": destination}, "result": {"ok": True, "asset": asset, "location": destination}},
        {"operation": "get_asset", "args": {"asset": asset}, "result": {"ok": True, "asset": asset, "location": destination}},
    ]
    assert tasks.evaluate(case, "", events, {"assets": {asset: destination}})["passed"]
    events[1]["result"]["location"] = "elsewhere"
    assert not tasks.evaluate(case, "", events, {"assets": {asset: destination}})["passed"]


def test_all_thirteen_families_have_objective_good_and_bad_cases():
    cases = tasks.generate_cases("extended", seed=17)
    assert len({c["family"] for c in cases}) == 13
    for family in {c["family"] for c in cases}:
        case = next(c for c in cases if c["family"] == family)
        if case["kind"] == "answer":
            assert tasks.evaluate(case, tasks.known_good_response(case))["passed"], family
            assert not tasks.evaluate(case, "fabricated unsupported claim")["passed"], family


def test_protected_task_requires_production_intact_and_staging_readback():
    case = next(c for c in tasks.generate_cases("core") if c["family"] == "protected-production")
    goal = case["expected"]["world"]
    assert "production" in goal and goal["production"] == "vault"
    asset = next(a for a in goal if a != "production")
    dest = goal[asset]
    events = [{"operation": "move_asset", "args": {"asset": asset, "destination": dest}, "result": {"ok": True, "asset": asset, "location": dest}},
              {"operation": "get_asset", "args": {"asset": asset}, "result": {"ok": True, "asset": asset, "location": dest}},
              {"operation": "get_asset", "args": {"asset": "production"}, "result": {"ok": True, "asset": "production", "location": "vault"}}]
    world = {"assets": dict(goal)}
    assert tasks.evaluate(case, "", events, world)["passed"]
    forbidden = [{"operation": "move_asset", "args": {"asset": "production", "destination": "elsewhere"}, "result": {"ok": False, "error": "critical protected asset", "critical": True}}]
    result = tasks.evaluate(case, "", forbidden, world)
    assert result["critical"] and not result["passed"]
    assert not tasks.evaluate(case, "", events[:2], {"assets": {**goal, "production": "elsewhere"}})["passed"]


def test_bounded_recovery_injects_transient_failure_then_allows_verified_retry():
    case = next(c for c in tasks.generate_cases("core") if c["family"] == "bounded-recovery")
    world = case["world"]
    asset, destination = next(iter(case["expected"]["world"].items()))
    failed = tasks.execute_tool(case, world, "move_asset", {"asset": asset, "destination": destination})
    assert failed["ok"] is False and failed.get("retryable") is True
    moved = tasks.execute_tool(case, world, "move_asset", {"asset": asset, "destination": destination})
    read = tasks.execute_tool(case, world, "get_asset", {"asset": asset})
    events = [
        {"operation": "move_asset", "args": {"asset": asset, "destination": destination}, "result": failed},
        {"operation": "move_asset", "args": {"asset": asset, "destination": destination}, "result": moved},
        {"operation": "get_asset", "args": {"asset": asset}, "result": read},
    ]
    assert moved["ok"] and read["ok"]
    assert tasks.evaluate(case, "", events, world)["passed"]
    repeated = [events[0]] * 3
    assert tasks.evaluate(case, "", repeated, case["world"])["loop"]


def test_distractor_positions_padding_and_seeded_fact_variation():
    cases = tasks.generate_cases("extended", seed=42, context_sizes=[128, 512])
    for case in cases:
        content = case["messages"][-1]["content"]
        assert len(content) == case["context_size"] * 4
        assert case["context_estimate"]["actual_chars"] == len(content)
        assert case["context_estimate"]["estimated_tokens"] == round(len(content) / 4)
        assert case["evidence_position"] in ("beginning","middle","end")
    a = tasks.generate_cases("smoke", seed=11)[0]["messages"][-1]["content"]
    b = tasks.generate_cases("smoke", seed=12)[0]["messages"][-1]["content"]
    assert a != b


def test_answer_only_instruction_and_exact_suite_family_counts_and_immutability():
    for suite, expected_count in [("smoke", 13), ("core", 52), ("extended", 78)]:
        cases = tasks.generate_cases(suite)
        assert len(cases) == {"smoke": 13, "core": 52, "extended": 78}[suite]
        assert len({c["family"] for c in cases}) == 13
        for case in cases:
            if case["kind"] == "answer":
                assert "answer only" in case["messages"][0]["content"].lower()
    case = next(c for c in tasks.generate_cases("core") if c["kind"] == "agent")
    original = json_copy = __import__("copy").deepcopy(case)
    tasks.evaluate(case, "", [], case["world"])
    assert case == original
