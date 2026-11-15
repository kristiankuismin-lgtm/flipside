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


def feed(items=(), hits=(), software=(), gitlab=(), models=(), atom=""):
    """One fetcher standing in for every source rank() reads.

    Each source has its own response shape - GitHub and HN return objects,
    GitLab and Hugging Face return bare lists, arXiv returns Atom text - so
    a stub that answers them all has to be shaped per source rather than
    returning one convenient dict.
    """
    def fetcher(url, params, *, kind, **kw):
        if kind == "gh":
            return {"items": list(items)}
        if kind == "hn":
            return {"hits": list(hits)}
        if kind == "gl":
            return list(gitlab)
        if kind == "hf":
            return list(models)
        if kind == "ax":
            return atom
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
        return feed()(url, params, kind=kind, **kw)
    out = pb.rank(thesis="carbon ledger", today=TODAY, fetcher=fetcher)
    assert out["rows"] == []
    assert "github" not in out["sources_read"]
    assert any("rate limited" in m for m in out["sources_missing"])


# ------------------------------------------------- what Cala itself claims

def _person(name, gh=None, founded=False):
    e = {"id": "p1", "entity_type": "Person", "name": name,
         "relationships": {"outgoing": ({"FOUNDED": [{"id": "c"}]} if founded else
                                        {"WORKS_AT": [{"id": "c"}]})}}
    if gh:
        e["properties"] = {"github_url": {"value": gh, "sources": []}}
    return e


def test_cala_github_url_beats_a_name_guess_for_the_same_handle():
    """A login Cala stores is the person. A rearranged name is a lead."""
    index = {"a": _person("Quiet Dev"), "b": _person("Someone Else",
                                                     gh="https://github.com/quietdev")}
    idx = pb._people_by_handle(index)
    assert idx["quietdev"]["name"] == "Someone Else"
    assert idx["quietdev"]["_claimed"] is True


def test_a_claimed_identity_is_stated_as_fact_and_scores_for_it():
    index = {"b": _person("Quiet Dev", gh="https://github.com/quietdev")}
    out = pb.rank(thesis="carbon ledger", today=TODAY, index=index,
                  fetcher=feed([repo("quietdev", "carbon-ledger",
                                     created="2026-08-01", pushed="2026-11-14",
                                     desc="carbon ledger")]))
    hit = out["rows"][0]["known_to_cala"]
    assert hit["claimed"] is True
    assert "Cala records" in hit["confidence"]
    assert any("Cala records this account as Quiet Dev" in w
               for w in out["rows"][0]["why"])


def test_an_unclaimed_name_match_is_still_marked_unverified():
    index = {"a": _person("Quiet Dev")}
    out = pb.rank(thesis="carbon ledger", today=TODAY, index=index,
                  fetcher=feed([repo("quietdev", "carbon-ledger",
                                     created="2026-08-01", pushed="2026-11-14",
                                     desc="carbon ledger")]))
    hit = out["rows"][0]["known_to_cala"]
    assert hit["claimed"] is False and "unverified" in hit["confidence"]


def test_a_claimed_founder_is_still_dropped_from_this_cohort():
    index = {"b": _person("Quiet Dev", gh="https://github.com/quietdev",
                          founded=True)}
    out = pb.rank(thesis="carbon ledger", today=TODAY, index=index,
                  fetcher=feed([repo("quietdev", "carbon-ledger",
                                     created="2026-08-01", pushed="2026-11-14",
                                     desc="carbon ledger")]))
    assert out["rows"] == []


def test_a_github_url_with_no_login_in_it_is_ignored():
    index = {"b": _person("Quiet Dev", gh="not a url")}
    assert "quietdev" in pb._people_by_handle(index)
    assert pb._people_by_handle(index)["quietdev"]["_claimed"] is False


# ------------------------------------------------- the rest of the internet

def gl(handle, path, *, activity="2026-11-10", desc="", kind="user", stars=0):
    return {"namespace": {"kind": kind, "path": handle},
            "path_with_namespace": f"{handle}/{path}", "path": path,
            "description": desc, "topics": [], "star_count": stars,
            "created_at": "2026-08-01T00:00:00Z",
            "last_activity_at": activity + "T00:00:00Z",
            "web_url": f"https://gitlab.com/{handle}/{path}"}


def test_gitlab_groups_are_companies_not_people():
    rows = pb.gitlab(["carbon ledger"], today=TODAY,
                     fetcher=lambda u, p, *, kind, **k: [
                         gl("acme", "carbon-ledger", kind="group"),
                         gl("dev", "carbon-ledger")])
    assert [r["handle"] for r in rows] == ["dev"]
    assert rows[0]["host"] == "gitlab"


def test_a_loud_gitlab_project_is_not_private():
    rows = pb.gitlab(["carbon ledger"], today=TODAY,
                     fetcher=lambda u, p, *, kind, **k: [
                         gl("dev", "carbon-ledger", stars=900)])
    assert rows == []


def test_huggingface_models_carry_the_owner_as_the_handle():
    rows = pb.models(["carbon ledger"], fetcher=lambda u, p, *, kind, **k: [
        {"id": "someone/carbon-ledger-v2", "likes": 3, "downloads": 40,
         "tags": ["carbon"], "lastModified": "2026-11-01T00:00:00Z"}])
    assert rows[0]["handle"] == "someone"
    assert rows[0]["host"] == "huggingface"
    assert rows[0]["url"] == "https://huggingface.co/someone/carbon-ledger-v2"


ATOM = """<feed><entry><title>A Carbon Ledger for Supply Chains</title>
<id>http://arxiv.org/abs/2611.00001</id><published>2026-11-10T00:00:00Z</published>
<author><name>Ada Lovelace</name></author><author><name>Bob Stone</name></author>
<author><name>Carol Diaz</name></author><author><name>Dan Fourth</name></author>
</entry></feed>"""


def test_only_the_front_of_an_author_list_becomes_a_row():
    """A six-author paper is not six people about to start a company."""
    idx = pb.papers(["carbon ledger"], fetcher=lambda u, p, *, kind, **k: ATOM)
    assert set(idx) == {"ada lovelace", "bob stone", "carol diaz"}
    assert idx["ada lovelace"][0]["position"] == 0


def test_first_author_outranks_a_third_author_on_the_same_paper():
    idx = pb.papers(["carbon ledger"], fetcher=lambda u, p, *, kind, **k: ATOM)
    rows = {r["handle"]: r for r in pb.group([], {}, {}, today=TODAY,
                                             paper_idx=idx)}
    assert pb.score(rows["Ada Lovelace"])[0] > pb.score(rows["Carol Diaz"])[0]
    assert any("first author" in w for w in pb.score(rows["Ada Lovelace"])[1])


def test_researcher_scores_do_not_all_tie():
    """The same failure as the repository ranking: everyone at exactly 20.0."""
    idx = pb.papers(["carbon ledger"], fetcher=lambda u, p, *, kind, **k: ATOM)
    idx["ada lovelace"].append(dict(idx["ada lovelace"][0], title="Second"))
    rows = pb.group([], {}, {}, today=TODAY, paper_idx=idx)
    assert len({pb.score(r)[0] for r in rows}) == len(rows)


def test_a_paper_author_lands_on_a_repo_handle_that_is_already_here():
    """Two identity spaces, one person. Publishing on the thesis and pushing
    code for it is the strongest thing this module can find."""
    repo_rows = pb.repos(["carbon ledger"], today=TODAY, fetcher=feed([
        repo("adalovelace", "carbon-ledger", created="2026-08-01",
             pushed="2026-11-14", desc="carbon ledger")]))
    idx = pb.papers(["carbon ledger"], fetcher=lambda u, p, *, kind, **k: ATOM)
    rows = pb.group(repo_rows, {}, {}, today=TODAY, paper_idx=idx)
    merged = [r for r in rows if r["repos"] and r["papers"]]
    assert len(merged) == 1
    assert set(merged[0]["sources"]) == {"github", "arxiv"}


def test_the_same_paper_found_by_two_queries_counts_once():
    """Queries overlap by design, so a paper comes back more than once.
    Counting it twice inflates both the claim and the score."""
    idx = pb.papers(["carbon ledger", "carbon"],
                    fetcher=lambda u, p, *, kind, **k: ATOM)
    assert len(idx["ada lovelace"]) == 1
