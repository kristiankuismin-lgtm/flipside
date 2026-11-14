"""A watchlist that can tell you what is new."""
import os
import time

import pytest


@pytest.fixture()
def WL(tmp_path, monkeypatch):
    monkeypatch.setenv("WATCH_DB", str(tmp_path / "w.sqlite"))
    import importlib
    from app import watchlist
    return importlib.reload(watchlist)


def move(company, kind="new_venture"):
    return {"kind": kind, "company": company, "months_ago": 2}


def story(url, title):
    return {"url": url, "title": title, "domain": "x.com"}


def test_the_first_check_is_a_baseline_not_a_pile_of_alerts(WL):
    """Everything about a newly watched person is new to us and none of it
    is new to the world."""
    WL.add("p1", "A Person")
    fresh = WL.record("p1", [move("Newthing")], [story("http://a", "A raises")])
    assert fresh == []
    assert WL.unread("p1") == []


def test_something_that_appears_later_is_an_alert(WL):
    WL.add("p1", "A Person")
    WL.record("p1", [], [])                      # baseline
    fresh = WL.record("p1", [move("Newthing")], [])
    assert len(fresh) == 1 and "founded Newthing" in fresh[0]["text"]
    assert len(WL.unread("p1")) == 1


def test_the_same_thing_twice_is_not_two_alerts(WL):
    WL.add("p1", "A Person")
    WL.record("p1", [], [])
    WL.record("p1", [move("Newthing")], [])
    again = WL.record("p1", [move("Newthing")], [])
    assert again == []
    assert len(WL.unread("p1")) == 1


def test_an_edited_headline_is_not_a_new_story(WL):
    """Keyed on the link, because the text changes and the story does not."""
    WL.add("p1", "A Person")
    WL.record("p1", [], [])
    WL.record("p1", [], [story("http://a", "A raises 4M")])
    again = WL.record("p1", [], [story("http://a", "A raises €4 million")])
    assert again == []


def test_acknowledging_clears_it(WL):
    WL.add("p1", "A Person")
    WL.record("p1", [], [])
    WL.record("p1", [move("Newthing")], [])
    assert WL.ack("p1") == 1
    assert WL.unread("p1") == []


def test_unwatching_forgets_everything_about_them(WL):
    """Removing someone from a watchlist is not supposed to leave a file
    about them behind."""
    WL.add("p1", "A Person")
    WL.record("p1", [], [])
    WL.record("p1", [move("Newthing")], [])
    WL.remove("p1")
    assert WL.unread("p1") == [] and WL.watching() == []


def test_recording_for_someone_not_watched_does_nothing(WL):
    assert WL.record("ghost", [move("X")], []) == []
    assert WL.unread() == []


def test_watching_lists_who_and_when(WL):
    WL.add("p1", "A Person")
    w = WL.watching()
    assert w[0]["name"] == "A Person" and w[0]["checked"] is None
    WL.record("p1", [], [])
    assert WL.watching()[0]["checked"] is not None
