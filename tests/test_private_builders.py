"""The cohort that has not announced itself yet.

Two of these tests exist because the first version of this module shipped
both bugs: every row scored an identical 66.0, and a single-word fallback
query put a desktop wallpaper app at the top of a clinical-AI cohort.
"""
from datetime import date

import pytest

from app import private_builders as pb

TODAY = date(2026, 11, 15)


def repo(handle, name, *, created, pushed, stars=0, size=2000, desc="",
         topics=(), home=None, lic=False, issues=0, fork=False, kind="User"):
    return {"owner": {"login": handle, "type": kind}, "fork": fork,
            "name": name, "full_name": f"{handle}/{name}",
            "html_url": f"https://github.com/{handle}/{name}",
            "description": desc, "topics": list(topics), "language": "Python",
            "stargazers_count": stars, "size": size, "open_issues_count": issues,
            "homepage": home, "license": {"key": "mit"} if lic else None,
            "created_at": created + "T00:00:00Z", "pushed_at": pushed + "T00:00:00Z"}


def feed(items=(), hits=(), software=()):
    def fetcher(url, params, *, kind, **kw):
        if kind == "gh":
            return {"items": list(items)}
        if kind == "hn":
            return {"hits": list(hits)}
        return {"software": list(software)}
    return fetcher


# ---------------------------------------------------------------- queries

def test_queries_never_narrow_to_one_word():
    """A one-word fallback is what put a wallpaper app in a scribe cohort."""
    qs = pb.queries("ambient AI scribe for clinicians")
    assert all(len(q.split()) >= 2 for q in qs), qs
    assert qs[0].split() == ["ambient", "scribe", "clinicians"]


def test_queries_drop_stopwords_and_vc_boilerplate():
    qs = pb.queries("we want to build a company for carbon accounting")
    assert "company" not in " ".join(qs)
    assert "carbon" in qs[0]


def test_queries_survive_a_single_content_word():
    assert pb.queries("robotics") == ["robotics"]


def test_queries_survive_an_empty_thesis():
    assert pb.queries("") == ["ai agents"]


# -------------------------------------------------------------------- fit

def test_fit_does_not_match_across_a_word_boundary():
    """'ambient' must not match the Portuguese 'AMBIENTE-DE-HOMOLOGACAO'."""
    assert pb._fit("AMBIENTE-DE-HOMOLOGA-AO-SF", [], "", "ambient scribe") < 0.5
    assert pb._fit("ambient-scribe-ios", [], "", "ambient scribe") == 1.0


def test_fit_ranks_name_above_description():
    in_name = pb._fit("carbon-ledger", [], "", "carbon ledger")
    in_desc = pb._fit("thing", [], "a carbon ledger for firms", "carbon ledger")
    assert in_name > in_desc


# ----------------------------------------------------------------- repos

def test_repos_rejects_organisations_forks_and_coursework():
    rows = pb.repos(["carbon ledger"], today=TODAY, fetcher=feed([
        repo("acme", "carbon-ledger", created="2026-08-01", pushed="2026-11-10",
             kind="Organization"),
        repo("bob", "carbon-ledger", created="2026-08-01", pushed="2026-11-10",
             fork=True),
        repo("cara", "carbon-ledger-tutorial", created="2026-08-01",
             pushed="2026-11-10"),
        repo("dev", "carbon-ledger", created="2026-08-01", pushed="2026-11-10"),
    ]))
    assert [r["handle"] for r in rows] == ["dev"]


def test_repos_rejects_a_single_loose_word_in_a_description():
    rows = pb.repos(["carbon ledger"], today=TODAY, fetcher=feed([
        repo("x", "unrelated", created="2026-08-01", pushed="2026-11-10",
             desc="a ledger for invoices"),
    ]))
    assert rows == []


# ----------------------------------------------------------------- score

def test_scores_do_not_all_tie():
    """The failure that made the first version useless: every row at 66.0."""
    rows = pb.repos(["carbon ledger"], today=TODAY, fetcher=feed([
        repo("deep", "carbon-ledger", created="2026-05-20", pushed="2026-11-14",
             size=9000, home="https://x.dev", lic=True, issues=6,
             topics=["carbon"], desc="carbon ledger for supply chains"),
        repo("mid", "carbon-ledger-ui", created="2026-09-01", pushed="2026-11-01",
             size=1200, desc="carbon ledger front end"),
        repo("thin", "carbon-ledger-poc", created="2026-11-10",
             pushed="2026-11-11", size=20, desc="carbon ledger poc"),
    ]))
    scored = sorted((pb.score(r)[0] for r in pb.group(rows, {}, {}, today=TODAY)),
                    reverse=True)
    assert len(set(scored)) == 3, scored
    assert scored[0] - scored[-1] > 20


def test_stars_above_the_quiet_line_stop_counting_as_private():
    loud = pb.group(pb.repos(["carbon ledger"], today=TODAY, fetcher=feed([
        repo("a", "carbon-ledger", created="2026-08-01", pushed="2026-11-14",
             stars=250, desc="carbon ledger")])), {}, {}, today=TODAY)[0]
    quiet = pb.group(pb.repos(["carbon ledger"], today=TODAY, fetcher=feed([
        repo("b", "carbon-ledger", created="2026-08-01", pushed="2026-11-14",
             stars=0, desc="carbon ledger")])), {}, {}, today=TODAY)[0]
    assert pb.score(quiet)[0] > pb.score(loud)[0]
    assert not any("star" in w for w in pb.score(loud)[1])


def test_more_than_one_repo_on_the_thesis_outranks_one():
    one = pb.group(pb.repos(["carbon ledger"], today=TODAY, fetcher=feed([
        repo("solo", "carbon-ledger", created="2026-08-01", pushed="2026-11-14",
             desc="carbon ledger")])), {}, {}, today=TODAY)[0]
    many = pb.group(pb.repos(["carbon ledger"], today=TODAY, fetcher=feed([
        repo("busy", "carbon-ledger", created="2026-08-01", pushed="2026-11-14",
             desc="carbon ledger"),
        repo("busy", "carbon-ledger-api", created="2026-08-01",
             pushed="2026-11-14", desc="carbon ledger api")])), {}, {},
        today=TODAY)[0]
    assert pb.score(many)[0] > pb.score(one)[0]


# ----------------------------------------------------------------- joins

def test_a_comment_alone_is_not_evidence_of_building():
    rows = pb.group([], {"talker": [{"handle": "talker", "story": "s",
                                     "url": "u", "said": "x", "query": "q"}]},
                    {}, today=TODAY)
    assert [r["handle"] for r in rows] == []


def test_devpost_reaches_a_github_handle_through_the_project_page():
    """Member names and GitHub logins do not match; the project page is the join."""
    hacks = {"somebody": [{"handle": "somebody", "project": "MediBridge",
                           "url": "https://devpost.com/software/medibridge",
                           "tags": [], "winner": False, "query": "q"}]}
    out = pb.enrich(hacks, fetcher=lambda slug: {
        "repo": "https://github.com/kunal/medibridge", "handle": "kunal",
        "event": "green shift hacks"})
    assert "kunal" in out
    assert out["kunal"][0]["event"] == "green shift hacks"


def test_corroboration_raises_the_score_and_says_so():
    rows = pb.repos(["carbon ledger"], today=TODAY, fetcher=feed([
        repo("kunal", "carbon-ledger", created="2026-08-01", pushed="2026-11-14",
             desc="carbon ledger")]))
    alone = pb.group(rows, {}, {}, today=TODAY)[0]
    both = pb.group(rows, {}, {"kunal": [{"handle": "kunal", "project": "p",
                                          "url": "u", "tags": [], "winner": False,
                                          "query": "q", "event": "junction"}]},
                    today=TODAY)[0]
    assert pb.score(both)[0] > pb.score(alone)[0]
    assert any("junction" in w for w in pb.score(both)[1])


# ------------------------------------------------------------ subtraction

def test_an_announced_handle_is_not_in_this_cohort():
    out = pb.rank(thesis="carbon ledger", today=TODAY, announced={"Shipped"},
                  fetcher=feed([
                      repo("shipped", "carbon-ledger", created="2026-08-01",
                           pushed="2026-11-14", desc="carbon ledger"),
                      repo("quiet", "carbon-ledger", created="2026-08-01",
                           pushed="2026-11-14", desc="carbon ledger")]))
    assert [r["handle"] for r in out["rows"]] == ["quiet"]
    assert out["excluded_announced"] == 1


def test_a_known_founder_is_not_before_anything():
    index = {"p1": {"id": "p1", "entity_type": "Person", "name": "Quiet Dev",
                    "relationships": {"outgoing": {"FOUNDED": [{"id": "c"}]}}}}
    out = pb.rank(thesis="carbon ledger", today=TODAY, index=index,
                  fetcher=feed([repo("quietdev", "carbon-ledger",
                                     created="2026-08-01", pushed="2026-11-14",
                                     desc="carbon ledger")]))
    assert out["rows"] == []


def test_a_cala_person_who_has_not_founded_is_kept_and_flagged_unverified():
    index = {"p1": {"id": "p1", "entity_type": "Person", "name": "Quiet Dev",
                    "relationships": {"outgoing": {"WORKS_AT": [{"id": "c"}]}}}}
    out = pb.rank(thesis="carbon ledger", today=TODAY, index=index,
                  fetcher=feed([repo("quietdev", "carbon-ledger",
                                     created="2026-08-01", pushed="2026-11-14",
                                     desc="carbon ledger")]))
    hit = out["rows"][0]["known_to_cala"]
    assert hit["name"] == "Quiet Dev"
    assert "unverified" in hit["confidence"]


# ------------------------------------------------------------- degrading

def test_a_refusing_source_degrades_instead_of_failing():
    def fetcher(url, params, *, kind, **kw):
        if kind == "gh":
            raise pb.Unavailable("gh: rate limited")
        return {"hits": [], "software": []}
    out = pb.rank(thesis="carbon ledger", today=TODAY, fetcher=fetcher)
    assert out["rows"] == []
    assert "github" not in out["sources_read"]
    assert any("rate limited" in m for m in out["sources_missing"])
