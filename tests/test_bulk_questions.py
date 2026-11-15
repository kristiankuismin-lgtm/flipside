"""A refused question is not a question with no answer.

These exist because the distinction was missing and it cost a whole run.
ask() returned 0 both when the graph answered with an empty table and when
the rate limiter turned the request away, and the driver only reported
non-zero results - so a harvest printed "868/868" while 554 of those had
never reached the server. One question, "priors", was asked zero times and
was recorded in the notes as a shape Cala could not answer. It answers it:
sixteen rows for the first firm tried once the bucket was free.
"""
import pytest

from app import bulk, factories


def test_a_refused_question_raises_rather_than_reporting_nothing(monkeypatch):
    def refuse(*a, **k):
        raise RuntimeError("Rate limit")
    monkeypatch.setattr(bulk.cala, "query", refuse)
    with pytest.raises(bulk.Unanswered):
        bulk.ask("priors", "A Firm That Was Never Asked")


def test_a_refused_question_is_not_marked_as_asked(monkeypatch):
    """Otherwise the retry never happens and the gap is permanent."""
    q = bulk.KINDS["priors"]["q"].format(s="Never Reached Ltd")
    monkeypatch.setattr(bulk.cala, "query",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("429")))
    with pytest.raises(bulk.Unanswered):
        bulk.ask("priors", "Never Reached Ltd")
    assert not bulk.asked(q)


def test_an_empty_answer_is_marked_so_it_is_not_asked_twice(monkeypatch):
    q = bulk.KINDS["priors"]["q"].format(s="Firm With No Founders")
    monkeypatch.setattr(bulk.cala, "query", lambda *a, **k: {"results": []})
    assert bulk.ask("priors", "Firm With No Founders") == 0
    assert bulk.asked(q)


def test_a_question_about_a_person_keeps_the_person_as_the_subject(monkeypatch):
    """The career table names companies; the person is who we asked about."""
    monkeypatch.setattr(bulk.cala, "query", lambda *a, **k: {"results": [
        {"company": "Wolt", "role": "CEO", "years": "2014-2022"}]})
    bulk.ask("bio", "A Test Person")
    got = [r for r in bulk.rows_of("bio") if r["person"] == "A Test Person"]
    assert got and got[0]["org"] == "Wolt" and got[0]["role"] == "CEO"


# --------------------------------------------- the employer is a name
# The answers write the prior employer as prose, and splitting it yielded
# "Veteran with AAA console" and "mobile" as employers of founders.

@pytest.mark.parametrize("fragment", [
    "Veteran with AAA console", "free-to-play gaming experience", "mobile",
    "Student at Stockholm School of Economics", "Co-founder of Trade Republic",
    "previously a partner", "x",
])
def test_a_sentence_fragment_is_not_an_employer(fragment):
    assert factories._is_employer(fragment, None) is False


@pytest.mark.parametrize("name", [
    "F-Secure", "VTT Technical Research Centre of Finland", "Tink",
    "McKinsey & Company", "Goldman Sachs", "23andMe",
])
def test_a_real_company_survives_the_filter(name):
    assert factories._is_employer(name, None) is True


def test_founding_a_company_is_not_having_worked_there():
    assert factories._is_employer("Atlar", "Atlar") is False
    assert factories._is_employer("Tink", "Atlar") is True
