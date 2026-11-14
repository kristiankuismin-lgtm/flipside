from app import progress as P


def test_steps_accumulate_with_timings():
    k = P.key_for("Gosta Labs", "series a")
    P.start(k, "Gosta Labs")
    P.step(k, "Resolved Gosta Labs", "3 rounds, 5 investors")
    P.step(k, "Screened 14 funds")
    s = P.get(k)
    assert s["found"] and not s["done"] and len(s["steps"]) == 2
    assert s["steps"][0]["detail"] == "3 rounds, 5 investors"
    assert all("t" in x for x in s["steps"])


def test_done_closes_the_run_and_later_steps_are_ignored():
    k = P.key_for("X")
    P.start(k)
    P.done(k, "Finished")
    P.step(k, "too late")
    s = P.get(k)
    assert s["done"] and [x["text"] for x in s["steps"]] == ["Finished"]


def test_an_unknown_key_is_empty_not_an_error():
    s = P.get("nobody|")
    assert s["found"] is False and s["steps"] == []


def test_progress_never_raises_into_the_analysis():
    """A broken progress log must not take the screen down with it."""
    P.step("never-started", "x")
    P.done("never-started")


def test_old_runs_are_dropped():
    for i in range(P.MAX_RUNS + 6):
        P.start(P.key_for(f"co{i}"))
    assert len(P._RUNS) <= P.MAX_RUNS
