"""Coverage of a firm, including the absence of it."""
from datetime import date

from app import newsfeed as NF

TODAY = date(2026, 11, 15)


def art(title, src, when, url=None):
    return {"title": title, "url": url or f"https://x.test/{title}",
            "source": {"name": src}, "published_at": when,
            "description": "d"}


def feed(*articles, error=None):
    def fetcher(path, payload, **kw):
        if error:
            raise RuntimeError(error)
        return {"data": list(articles)}
    return fetcher


def test_outlets_are_counted_not_articles():
    """Five pieces in one outlet is a relationship; one in five is a story."""
    one = NF.about("A", today=TODAY, fetcher=feed(
        *[art(f"t{i}", "Sifted", "2026-11-01") for i in range(5)]))
    many = NF.about("B", today=TODAY, fetcher=feed(
        *[art(f"t{i}", f"Outlet{i}", "2026-11-01") for i in range(5)]))
    assert one["count"] == many["count"] == 5
    assert one["outlets"] == 1 and many["outlets"] == 5


def test_silence_is_reported_rather_than_left_blank():
    out = NF.about("A", today=TODAY, fetcher=feed(
        art("old", "Sifted", "2024-01-01")))
    assert out["quiet"] is True
    assert out["days_since"] > NF.QUIET_DAYS


def test_recent_coverage_is_not_quiet():
    out = NF.about("A", today=TODAY, fetcher=feed(
        art("new", "Sifted", "2026-11-10")))
    assert out["quiet"] is False and out["days_since"] == 5


def test_no_coverage_at_all_is_a_finding_not_an_error():
    out = NF.about("A", today=TODAY, fetcher=feed())
    assert out["count"] == 0 and out["quiet"] is True and "error" not in out
    assert "No coverage" in NF.line(out)


def test_a_failing_news_layer_does_not_take_the_page_down():
    out = NF.about("A", today=TODAY, fetcher=feed(error="boom"))
    assert out["articles"] == [] and out["error"]
    assert NF.line(out) == "Coverage could not be read."


def test_articles_without_a_title_or_link_are_dropped():
    out = NF.about("A", today=TODAY, fetcher=feed(
        {"title": "", "url": "u", "published_at": "2026-11-01"},
        {"title": "t", "url": None, "published_at": "2026-11-01"},
        art("good", "Sifted", "2026-11-01")))
    assert [a["title"] for a in out["articles"]] == ["good"]


def test_newest_first():
    out = NF.about("A", today=TODAY, fetcher=feed(
        art("old", "S", "2026-01-01"), art("new", "S", "2026-11-01")))
    assert [a["title"] for a in out["articles"]] == ["new", "old"]


def test_an_empty_name_is_refused_without_a_call():
    called = []

    def fetcher(*a, **k):
        called.append(1)
        return {}
    out = NF.about("  ", today=TODAY, fetcher=fetcher)
    assert out["error"] == "no name" and not called


def test_the_line_names_both_counts():
    out = NF.about("A", today=TODAY, fetcher=feed(
        art("a", "Sifted", "2026-11-14"), art("b", "TechCrunch", "2026-11-10")))
    s = NF.line(out)
    assert "2 articles" in s and "2 outlets" in s and "1 days ago" in s
