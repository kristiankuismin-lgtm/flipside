"""The deck, held somewhere a link can point at it."""
import importlib

import pytest


@pytest.fixture()
def DK(tmp_path, monkeypatch):
    monkeypatch.setenv("DECK_DB", str(tmp_path / "d.sqlite"))
    from app import deck
    return importlib.reload(deck)


def test_a_deck_comes_back_byte_for_byte(DK):
    rec = DK.put("plan.pdf", b"%PDF-1.4 hello")
    assert DK.get(rec["id"])["body"] == b"%PDF-1.4 hello"


def test_ids_are_not_walkable(DK):
    """A link nobody can guess is not a password, and it is also not a
    sequence anyone can enumerate."""
    a = DK.put("a.pdf", b"x")["id"]
    b = DK.put("b.pdf", b"y")["id"]
    assert a != b and len(a) > 12 and not a.isdigit()


def test_an_empty_file_is_refused(DK):
    with pytest.raises(ValueError):
        DK.put("empty.pdf", b"")


def test_an_oversized_file_says_how_big_it_was(DK):
    with pytest.raises(ValueError) as e:
        DK.put("huge.pdf", b"x" * (DK.MAX_BYTES + 1))
    assert "MB" in str(e.value)


def test_a_missing_id_is_none_not_an_error(DK):
    assert DK.get("nothing-here") is None


def test_the_content_type_follows_the_extension(DK):
    assert DK.mime_of("a.pdf") == "application/pdf"
    assert "presentationml" in DK.mime_of("a.pptx")
    assert DK.mime_of("a.weird") == "application/octet-stream"


def test_a_filename_cannot_break_out_of_the_header(DK):
    """It goes into a Content-Disposition, so quotes and newlines are out."""
    assert '"' not in DK.safe_name('ev"il\nname.pdf')
    assert "\n" not in DK.safe_name('ev"il\nname.pdf')
    assert DK.safe_name("../../etc/passwd") == ".._.._etc_passwd"


def test_a_nameless_file_still_gets_a_name(DK):
    assert DK.safe_name("") == "deck"


# ------------------------------------------------------------ preview
def test_a_pdf_is_left_to_the_browser(DK):
    o = DK.outline("plan.pdf", b"%PDF-1.4")
    assert o["render"] == "browser"


def test_a_powerpoint_is_read_out_slide_by_slide(DK, deck_bytes):
    o = DK.outline("deck.pptx", deck_bytes)
    assert o["render"] == "outline" and o["page_count"] >= 2
    assert o["pages"][0]["where"].startswith("slide")
    assert any("Gosta Labs" in l for l in o["pages"][0]["lines"])


def test_an_unreadable_deck_says_so_and_does_not_raise(DK):
    o = DK.outline("deck.pptx", b"not a zip at all")
    assert o["render"] == "none" and o["error"]


def test_the_preview_reads_the_same_text_the_intake_does(DK, deck_bytes):
    """One pass over one file: the fields we extracted and the preview a
    founder checks them against cannot disagree."""
    from app import intake
    o = DK.outline("deck.pptx", deck_bytes)
    doc = intake.read(deck_bytes, "deck.pptx")
    shown = [l for p in o["pages"] for l in p["lines"]]
    assert all(line in shown for _, line in doc.lines[:4])
