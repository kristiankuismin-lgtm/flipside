from app import outreach as O

LEADY = {
    "investor": "Balderton Capital",
    "backs": [],
    "signals": {
        "lead_rate": {"label": "🟢", "value": 0.667, "text": "led 6 of 9 series a rounds (67%)"},
        "dry_powder": {"label": "🟢", "text": "13 new investments in 6 months"},
        "warm_path": {"label": "⚪", "text": None},
        "conflict": {"label": "🟢", "text": "backs no named competitor"},
    },
    "portfolio": [{"name": "Taktile", "sector": "FinTech / Risk Decisioning"},
                  {"name": "Neko Health", "sector": "Health / Clinical AI"}],
}


def test_a_fund_backing_a_competitor_gets_no_pitch():
    inv = {**LEADY, "backs": ["Tandem Health"],
           "signals": {**LEADY["signals"], "conflict": {"label": "🔴", "text": "backs Tandem Health"}}}
    b = O.brief(company="Gosta Labs", stage="series a", investor=inv)
    assert b["blocked"] and "Tandem Health" in b["reason"] and not b["sentences"]


def test_the_warm_route_outranks_the_syndicate_pattern():
    inv = {**LEADY, "signals": {**LEADY["signals"],
                                "warm_path": {"label": "🟢", "text": "via Voima Ventures"}}}
    syn = {"rounds_led": 11, "members": [{"name": "Creandum", "joined": 3, "share": 0.273}]}
    b = O.brief(company="Gosta Labs", stage="series a", investor=inv, syndicate=syn)
    assert "Voima Ventures" in b["body"]
    assert "Creandum" not in b["body"]        # the stronger fact wins the slot


def test_the_syndicate_pattern_is_used_when_no_warm_route_exists():
    syn = {"rounds_led": 11, "members": [{"name": "Creandum", "joined": 3, "share": 0.273}]}
    b = O.brief(company="Gosta Labs", stage="series a", investor=LEADY, syndicate=syn)
    assert "Creandum" in b["body"] and "3 of the 11 rounds" in b["body"]
    assert any(e["kind"] == "syndicate" for e in b["evidence"])


def test_every_sentence_carries_its_number():
    b = O.brief(company="Gosta Labs", stage="series a", investor=LEADY)
    assert "67%" in b["body"]                      # the lead rate, not a vibe
    assert "13 new investments" in b["body"]
    assert "led led" not in b["body"]              # the lead text is quoted, not re-narrated
    # No warm route, no syndicate and no competitor list means no hook exists.
    # Two true sentences beat three with one invented.
    assert len(b["sentences"]) == 2
    assert b["subject"].startswith("Gosta Labs × Balderton Capital")


def test_sector_overlap_is_the_fallback_hook():
    b = O.brief(company="Gosta Labs", stage="series a", investor=LEADY,
                competitors=[{"name": "Abridge", "what": "Health / Clinical AI scribing"}])
    assert "Neko Health" in b["body"]
    assert any(e["kind"] == "portfolio" for e in b["evidence"])


def test_unknown_signals_never_become_claims():
    bare = {"investor": "Quiet Fund", "backs": [], "signals": {
        "lead_rate": {"label": "⚪", "value": None, "text": None},
        "dry_powder": {"label": "⚪", "text": None},
        "warm_path": {"label": "⚪", "text": None},
        "conflict": {"label": "⚪", "text": None}}}
    b = O.brief(company="Gosta Labs", stage="seed", investor=bare)
    assert not b["blocked"]
    assert "None" not in b["body"] and "%" not in b["body"]
    assert "Slush 2026" in b["body"]


def test_a_quoted_signal_does_not_capitalise_mid_sentence():
    inv = {**LEADY, "signals": {**LEADY["signals"],
           "lead_rate": {"label": "🟢", "value": .67, "text": "Led 6 of 9 series a rounds (67%)"},
           "dry_powder": {"label": "🟢", "text": "13 new investments in 6 months (prior pace 2.7)"}}}
    b = O.brief(company="Gosta Labs", stage="series a", investor=inv)
    assert "You led 6 of 9" in b["body"] and "You Led" not in b["body"]
    # The working parenthetical is evidence, not sentence.
    assert "prior pace" not in b["body"]
    assert "prior pace" in next(e["detail"] for e in b["evidence"] if e["kind"] == "dry_powder")


def test_evidence_depth_labels_are_the_ones_the_scorer_checks():
    """These strings are a contract between two functions, not display text.

    They were Finnish once. Renaming them without renaming the comparison in
    analyze_one() silently scored funds we have almost no evidence for.
    """
    from app import api
    assert api.evidence_depth(api.GOOD_EVIDENCE) == "good"
    assert api.evidence_depth(api.MIN_ROUNDS_TO_RANK) == "thin"
    assert api.evidence_depth(api.MIN_ROUNDS_TO_RANK - 1) == "insufficient"
    src = (api.__file__ and open(api.__file__).read()) or ""
    assert 'depth == "insufficient"' in src


def test_out_of_credits_is_not_a_rate_limit():
    """402 clears by topping up; 429 clears by waiting. Collapsing the two
    sends the user to wait out a limit that will never lift."""
    import inspect

    from app import cala_client
    src = inspect.getsource(cala_client._request)
    assert "402" in src and "credits exhausted" in src.lower()
    # and it must be raised before the generic 4xx branch swallows it
    assert src.index("r.status_code == 402") < src.index("r.status_code >= 400")
