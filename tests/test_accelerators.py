"""Batch lists, and the column that matters: what the graph does not hold."""
from app import accelerators as AC

TABLE = """
# Summer 2026

231 companies in this class

| Icon | Name | URL | Class | Status | Description |
| --- | --- | --- | --- | --- | --- |
| | [6thSense](https://yclist.com/s26/6thsense/) | [https://6thsense.dev](https://6thsense.dev) | S26 | Active | Nervous System for Physical AI |
| | [Wolt](https://yclist.com/s26/wolt/) | [https://wolt.com](https://wolt.com) | S26 | Active | Delivery |
| | [Dead Co](https://yclist.com/s26/dead/) | | S26 | Inactive | Gone |
"""


def test_a_markdown_table_becomes_rows():
    rows = AC.parse(TABLE, batch="s26", accelerator="Y Combinator")
    assert [r["name"] for r in rows] == ["6thSense", "Wolt", "Dead Co"]
    assert rows[0]["website"] == "https://6thsense.dev"
    assert rows[0]["description"] == "Nervous System for Physical AI"
    assert rows[0]["batch"] == "S26"
    assert rows[2]["status"] == "Inactive"


def test_the_separator_row_is_not_a_company():
    rows = AC.parse(TABLE, batch="s26", accelerator="Y Combinator")
    assert all(set(r["name"]) - set("-: ") for r in rows)


def test_prose_around_the_table_is_ignored():
    rows = AC.parse("no table here\njust words\n", batch="s26",
                    accelerator="Y Combinator")
    assert rows == []


def test_the_scrape_envelope_is_unwrapped():
    assert AC._markdown({"requested": True, "success": True,
                         "data": "# hi"}) == "# hi"
    assert AC._markdown("# hi") == "# hi"
    assert AC._markdown({"markdown": None, "code": "NOT_REQUESTED"}) == ""


def test_the_split_is_against_normalised_names():
    rows = AC.parse(TABLE, batch="s26", accelerator="Y Combinator")
    index = {"c1": {"id": "c1", "entity_type": "Company", "name": "Wolt Oy"}}
    out = AC.against_cala(rows, index)
    assert out["counts"] == {"total": 3, "in_cala": 1, "new": 2}
    assert [r["name"] for r in out["new_to_cala"]] == ["6thSense", "Dead Co"]


def test_a_person_in_the_graph_is_not_a_company_match():
    rows = AC.parse(TABLE, batch="s26", accelerator="Y Combinator")
    index = {"p1": {"id": "p1", "entity_type": "Person", "name": "Wolt"}}
    out = AC.against_cala(rows, index)
    assert out["counts"]["in_cala"] == 0


def test_a_batch_dedupes_on_the_normalised_name():
    """A list page can name the same company twice; the batch cannot."""
    dupes = TABLE + "| | [6th Sense](x) | | S26 | Active | again |\n"
    rows = AC.batch("yc", "s26", fetcher=lambda *a, **k: {
        "markdown": {"data": dupes}})
    assert [r["name"] for r in rows] == ["6thSense", "Wolt", "Dead Co"]


def test_a_source_that_does_not_answer_yields_no_rows_rather_than_raising():
    def dead(*a, **k):
        raise RuntimeError("scrape failed")
    assert AC.batch("yc", "s26", fetcher=dead) == []


def test_an_unknown_accelerator_is_empty_not_an_error():
    assert AC.batch("nope", "s26") == []


def test_the_same_company_written_two_ways_is_one_company():
    """norm.name keeps internal spaces, so this match had to be tightened."""
    assert AC._key("6thSense") == AC._key("6th Sense")
    assert AC._key("Wolt Oy") == AC._key("WOLT")


def test_a_name_that_is_only_a_legal_suffix_still_gets_a_key():
    """norm.name returns empty for these, which once made rows vanish."""
    assert AC._key("Co.") != ""
    assert AC._key("Co.") != AC._key("Oy")


def test_a_batch_row_matches_its_cala_record_spelled_differently():
    rows = AC.parse(TABLE, batch="s26", accelerator="Y Combinator")
    index = {"c1": {"id": "c1", "entity_type": "Company", "name": "6th Sense"}}
    out = AC.against_cala(rows, index)
    assert out["rows"][0]["in_cala"] is True


LINKS = """
[VCbacked](https://www.vcbacked.co/)
[Offe Market\\\\ \\\\ October 2026\\\\ \\\\ A low-cost retail marketplace](https://www.vcbacked.co/company/offe-market)
[Research](https://www.vcbacked.co/ai-1000)
[Intuitivo\\\\ \\\\ October 2026\\\\ \\\\ Digital assessment for teachers](https://www.vcbacked.co/company/intuitivo)
"""

RF = """
1. [SSnapp AISR006](https://recentfunding.com/companies/snapp-ai/)
2. [SSyncerePre-seed · SR006](https://recentfunding.com/companies/syncere/)
3. [PE firms](https://recentfunding.com/pe-firms/)
"""


def test_site_chrome_is_excluded_by_url_shape_not_by_name():
    """A blocklist would have to grow per site and still let Research through."""
    rows = AC.parse_links(LINKS, accelerator="Techstars",
                          company_url=r"vcbacked\.co/company/")
    assert [r["name"] for r in rows] == ["Offe Market", "Intuitivo"]
    assert rows[0]["description"] == "A low-cost retail marketplace"


def test_without_a_url_filter_the_navigation_comes_too():
    """Why the filter exists, stated as a test rather than a comment."""
    rows = AC.parse_links(LINKS, accelerator="Techstars")
    assert len(rows) > 2


def test_a_glued_batch_code_is_stripped_from_the_name():
    """"SSnapp AISR006" has no word boundary before the batch code."""
    rows = AC.parse_links(RF, accelerator="a16z speedrun",
                          company_url=r"recentfunding\.com/companies/")
    assert [r["name"] for r in rows] == ["Snapp AI", "Syncere"]


def test_a_glued_stage_is_stripped_too():
    rows = AC.parse_links("[SSyncerePre-seed · SR006](https://recentfunding.com/companies/x/)",
                          accelerator="a", company_url=r"recentfunding\.com/companies/")
    assert rows[0]["name"] == "Syncere"
