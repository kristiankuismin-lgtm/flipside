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
    # A sidebar row is not the only front door: data-goto navigates from
    # inside a view, which is where the backtest belongs - next to the
    # ranking it validates rather than as a peer of it.
    inline = set(re.findall(r'data-goto="([a-z]+)"', JS))
    # Four modes are reached by doing something rather than by navigating:
    # "entity" and "fund" by opening a profile from a search result or a table
    # row, "pp" is a map sub-mode, "brief" is where the ask box lands while it
    # reads what the founder brought, and "reach" is where the pick bar goes
    # once funds are ticked. Each has a visible control; none has a front door.
    unreachable = modes - nav - inline - {"entity", "fund", "pp", "brief", "reach"}
    assert not unreachable, f"no nav entry for: {sorted(unreachable)}"


def test_every_shouted_global_the_script_reads_is_declared():
    """An undeclared global is a ReferenceError at the first read of it.

    LENS was one. Its selector was taken out of the UI and three reads of it
    were left in routeAsk, so every question typed into the Ask box threw on
    the first line and the product's main entrance was dead - while the
    server-side /ask endpoint kept answering, so the rehearsal stayed green
    and the orphaned .lensbtn rules passed the class guard, which only
    checks the other direction.
    """
    # Declarations come from the whole file: a name found here that is not
    # really a global only costs a missed warning, never a false alarm.
    declared = set()
    for run in re.findall(r"\b(?:let|const|var)\s+([^;\n]+)", JS):
        for part in run.split(","):
            m = re.match(r"\s*([A-Z][A-Z0-9_]{2,})\s*(?:=|$)", part)
            if m:
                declared.add(m.group(1))
    declared |= set(re.findall(r"\bfunction\s+([A-Z][A-Z0-9_]{2,})", JS))
    declared |= set(re.findall(r"\bwindow\.([A-Z][A-Z0-9_]{2,})", JS))

    # Reads are only counted with the name BEFORE the operator. A banner
    # comment - "/* ===== THE PIPELINE" - otherwise reads as a comparison
    # against an undeclared THE, and there are a dozen of those.
    code = re.sub(r"/\*.*?\*/", " ", JS, flags=re.S)
    read = set(re.findall(r"\b([A-Z][A-Z0-9_]{2,})\s*[=!]==", code))
    read |= set(re.findall(r"(?:if|while)\s*\(\s*!?\s*([A-Z][A-Z0-9_]{2,})\s*[)&|.]",
                           code))

    builtins = {"JSON", "Math", "Object", "Array", "Number", "String", "Date",
                "Map", "Set", "Promise", "RegExp", "Intl", "URL", "NaN",
                "Boolean", "Error", "TypeError", "Infinity", "Symbol"}
    missing = read - declared - builtins
    assert not missing, (
        f"read but never declared, so the first read throws: {sorted(missing)}")


def test_the_role_toggle_knows_every_mode_each_side_can_reach():
    """Switching sides keeps the current view when the other side has it, so
    the mode lists have to match the nav or the toggle throws you out of a
    view that was in fact available."""
    nav = {}
    for role in ("founder", "investor"):
        block = re.search(rf'id="nav{role}"(.*?)</div>', CSS, re.S)
        assert block, f"no nav block for {role}"
        nav[role] = set(re.findall(r'data-mode="([a-z]+)"', block.group(1)))

    declared = dict(re.findall(r'(founder|investor):\s*\[([^\]]*)\]', JS))
    assert declared, "ROLE_MODES not found"
    for role, raw in declared.items():
        listed = set(re.findall(r'"([a-z]+)"', raw))
        missing = nav[role] - listed
        assert not missing, f"{role} nav reaches {sorted(missing)}, not in ROLE_MODES"
