"""Guards for the kind of front-end breakage tests do not normally see.

An audit found six features rendering completely unstyled: each CSS edit had
anchored on a string an earlier edit already rewrote, so the replace was a
silent no-op. Nothing failed, nothing errored, the markup was simply naked.
These tests would have caught it on the first one.
"""
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "web"
JS = (WEB / "app.js").read_text()
CSS = (WEB / "index.html").read_text()

# Classes that exist only as hooks for querySelector, never styled.
HOOKS = {"figure-hook"}


def _classes_used():
    out = set()
    for m in re.findall(r'class="([^"$]*)"', JS):
        for c in m.split():
            if re.fullmatch(r"[a-z][a-z0-9-]*", c):
                out.add(c)
    return out


def _classes_styled():
    # Any selector mentioning the class counts, including descendant
    # selectors like ".fshd h2" and compound ones like "tr.dim td".
    return set(re.findall(r"\.([a-z][a-z0-9-]*)", CSS))


def test_every_class_the_app_renders_has_a_style():
    missing = sorted(_classes_used() - _classes_styled() - HOOKS)
    assert not missing, f"rendered but unstyled: {missing}"


def test_the_scripts_the_page_loads_exist():
    for src in re.findall(r'<script src="([^"]+)"', CSS):
        if src.startswith("http"):
            continue
        assert (WEB / src).is_file(), f"index.html loads {src}, which is not in web/"


def test_every_view_mode_has_a_way_in():
    """A mode wired into render() with no nav entry is unreachable - which is
    exactly how the backtest sat finished and invisible."""
    modes = set(re.findall(r'MODE === "([a-z]+)"', JS))
    nav = set(re.findall(r'data-mode="([a-z]+)"', CSS))
    # "entity" is reached by opening a profile; "pp" is a map sub-mode.
    unreachable = modes - nav - {"entity", "pp"}
    assert not unreachable, f"no nav entry for: {sorted(unreachable)}"
