"""People shipping things who have not founded a company yet.

Nothing here touches the network. The scoring tests exist because the first
version said "a pattern of shipping beats one post that did well" in a
comment and then let a single 736-point post tie someone who had shipped
twice.
"""
import time
from datetime import date

from app import builders as B

TODAY = date(2026, 11, 15)


def post(author, title, *, days_ago=5, points=10, url=None, comments=0, oid="1"):
    return {"author": author, "title": title, "points": points,
            "num_comments": comments, "url": url, "objectID": oid,
            "created_at_i": int(time.mktime(
                (TODAY.replace(day=1)).timetuple())) - days_ago * 86400}


def feed(posts):
    seen = {"n": 0}

    def fetcher(params):
        seen["n"] += 1
        return {"hits": posts if seen["n"] == 1 else []}
    return fetcher


# ---------------------------------------------------------- shaping
def test_the_show_hn_prefix_is_not_part_of_what_they_built():
    rows = B.group([post("a", "Show HN: A terminal game in Rust")], today=TODAY)
    assert rows[0]["shipped"][0]["what"] == "A terminal game in Rust"


def test_a_github_link_gives_the_handle():
    rows = B.group([post("a", "Show HN: Thing",
                         url="https://github.com/marktbaldridge/paintpot/")], today=TODAY)
    assert rows[0]["github"] == "marktbaldridge"


def test_a_non_github_link_gives_no_handle():
    rows = B.group([post("a", "Show HN: Thing", url="https://tryenzo.ai")], today=TODAY)
    assert rows[0]["github"] is None


def test_everything_one_handle_shipped_is_one_row():
    rows = B.group([post("a", "Show HN: One", oid="1"),
                    post("a", "Show HN: Two", oid="2")], today=TODAY)
    assert len(rows) == 1 and rows[0]["count"] == 2


def test_the_newest_thing_is_first():
    rows = B.group([post("a", "Show HN: Old", days_ago=120, oid="1"),
                    post("a", "Show HN: New", days_ago=2, oid="2")], today=TODAY)
    assert rows[0]["shipped"][0]["what"] == "New"


# ---------------------------------------------------------- scoring
def test_shipping_twice_beats_one_post_that_went_viral():
    """The habit is the thing being looked for. One viral weekend is a good
    weekend."""
    viral, _ = B.score({"count": 1, "best_points": 736, "months_since": 0.5,
                        "github": "x"})
    repeat, _ = B.score({"count": 2, "best_points": 3, "months_since": 0.5,
                         "github": "x"})
    assert repeat > viral


def test_shipping_saturates():
    many, _ = B.score({"count": 40, "months_since": 1})
    full, _ = B.score({"count": B.SHIPPED_FULL, "months_since": 1})
    assert many == full


def test_reception_saturates():
    huge, _ = B.score({"count": 1, "best_points": 5000, "months_since": 1})
    full, _ = B.score({"count": 1, "best_points": B.RECEPTION_FULL,
                       "months_since": 1})
    assert huge == full


def test_something_shipped_long_ago_scores_no_recency():
    old, _ = B.score({"count": 2, "months_since": 11})
    new, _ = B.score({"count": 2, "months_since": 0.5})
    assert new > old


def test_an_undated_post_is_not_treated_as_recent():
    pts, why = B.score({"count": 2, "months_since": None})
    assert not any("month" in w for w in why)


def test_every_point_says_why():
    pts, why = B.score({"count": 3, "best_points": 90, "months_since": 0.5,
                        "github": "x"})
    assert any("shipped 3" in w for w in why)
    assert any("90 points" in w for w in why)
    assert any("code is public" in w for w in why)


def test_a_single_post_says_so_without_scoring_for_it():
    pts, why = B.score({"count": 1})
    assert why == ["shipped one thing"] and pts == 0


# ------------------------------------------------------------ ranking
def test_people_we_can_already_see_as_founders_are_dropped(monkeypatch):
    monkeypatch.setattr(B, "_cached", lambda k: None)
    monkeypatch.setattr(B, "_store", lambda k, v: None)
    out = B.rank(fetcher=feed([post("known", "Show HN: A"),
                               post("fresh", "Show HN: B")]),
                 known=lambda h, titles: h == "known", today=TODAY)
    assert [b["handle"] for b in out["builders"]] == ["fresh"]
    assert out["coverage"]["already_known"] == 1


def test_coverage_says_what_it_read(monkeypatch):
    monkeypatch.setattr(B, "_cached", lambda k: None)
    monkeypatch.setattr(B, "_store", lambda k, v: None)
    out = B.rank(fetcher=feed([post("a", "Show HN: A"), post("b", "Show HN: B")]),
                 today=TODAY)
    assert out["coverage"]["posts_read"] == 2
    assert out["coverage"]["handles"] == 2


def test_a_post_with_no_author_or_no_title_is_skipped():
    rows = B.group([{"author": "", "title": "Show HN: X"},
                    {"author": "a", "title": ""}], today=TODAY)
    assert rows == []


def test_a_future_date_is_not_negative_months():
    assert B._months_ago("2099-01-01", TODAY) is None
