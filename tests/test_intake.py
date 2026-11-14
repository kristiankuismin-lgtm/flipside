"""Reading what a founder brings.

The fixtures are a real .pptx and a real .xlsx, built in conftest rather than
mocked, because the thing most likely to break here is the file format - not
our parsing of a dict we wrote ourselves.
"""
import pytest

from app import intake


# ------------------------------------------------------------- amounts
@pytest.mark.parametrize("text,euros", [
    ("raising 4,5 M EUR", 4_500_000),          # Helsinki decimal comma
    ("raising $2.5 million", 2_500_000),
    ("we are raising €3m", 3_000_000),
    ("raising 1,250,000 USD", 1_250_000),      # thousands separators
    ("raising 800k", 800_000),
])
def test_round_sizes_people_actually_write(text, euros):
    assert intake._amount(text)[0] == euros


def test_a_slide_number_is_not_a_round_size():
    assert intake._amount("14 hospitals live") is None
    assert intake._amount("page 3 of 20") is None


def test_currency_is_kept_not_assumed():
    assert intake._amount("raising $2m")[1] == "USD"
    assert intake._amount("raising £2m")[1] == "GBP"
    assert intake._amount("raising 2m")[1] == "EUR"


# ------------------------------------------------------------- websites
def test_the_companys_own_host_wins_over_the_footer():
    """Every deck footer has LinkedIn in it. None of them are the company."""
    p = intake.profile("Gosta Labs, gostalabs.com\nfollow us linkedin.com/company/x", [])
    assert p["website"] == "gostalabs.com"


def test_a_personal_email_host_is_not_a_company_website():
    p = intake.profile("reach me at someone@gmail.com", [])
    assert "website" not in p


def test_a_work_email_is_a_website():
    p = intake.profile("reach me at team@gostalabs.com", [])
    assert p["website"] == "gostalabs.com"


# --------------------------------------------------------------- stages
def test_the_round_being_raised_wins_over_the_one_already_raised():
    """"We raised a seed, now raising Series A" means Series A."""
    p = intake.profile("We raised a seed in 2024. Now raising our Series A.", [])
    assert p["stage"] == "series a"


def test_pre_seed_is_not_read_as_seed():
    assert intake.profile("raising a pre-seed", [])["stage"] == "pre-seed"


# ------------------------------------------------------------ provenance
def test_every_field_says_where_it_came_from():
    p = intake.profile("Gosta Labs\nRaising a 4.5M Series A at gostalabs.com", [])
    for f in ("name", "website", "stage", "round_size"):
        assert p["sources"][f]["quote"], f"{f} has no quote behind it"


# ------------------------------------------------------------- bad files
def test_an_unreadable_format_is_a_message_not_an_exception():
    d = intake.read(b"\x00\x01", "logo.png")
    assert d.error and "png" in d.error


def test_a_corrupt_deck_is_a_message_not_an_exception():
    d = intake.read(b"not a zip file at all", "deck.pptx")
    assert d.error and "paste" in d.error.lower()


def test_an_image_only_deck_says_so_rather_than_returning_nothing():
    """A deck exported from Figma has no text layer. Silence would look
    like our bug; it is the file."""
    import io
    from pptx import Presentation
    prs = Presentation()
    prs.slides.add_slide(prs.slide_layouts[6])
    buf = io.BytesIO(); prs.save(buf)
    d = intake.read(buf.getvalue(), "pictures.pptx")
    assert d.error and "images" in d.error


# ---------------------------------------------------------- real files
def test_reads_a_real_deck(deck_bytes):
    d = intake.read(deck_bytes, "deck.pptx")
    assert d.error is None and d.kind == "deck"
    assert any("Gosta Labs" in t for _, t in d.lines)
    assert all(w.startswith("slide ") for w, _ in d.lines)


def test_reads_a_real_spreadsheet(sheet_bytes):
    d = intake.read(sheet_bytes, "metrics.xlsx")
    assert d.error is None and d.kind == "spreadsheet"
    assert any("820000" in t for _, t in d.lines)
    assert any(w.startswith("Metrics!") for w, _ in d.lines)


def test_a_deck_alone_is_enough_to_screen_from(deck_bytes, sheet_bytes):
    docs = [intake.read(deck_bytes, "deck.pptx"),
            intake.read(sheet_bytes, "metrics.xlsx")]
    p = intake.profile("", docs)
    assert p["name"] == "Gosta Labs"
    assert p["website"] == "gostalabs.com"
    assert p["stage"] == "series a"
    assert p["round_size"] == 4_500_000
    assert "health" in p["markets"]
    # and it can point at the slide it read each one off
    assert p["sources"]["name"]["where"].startswith("slide")


def test_what_the_founder_typed_outranks_the_title_slide(deck_bytes):
    docs = [intake.read(deck_bytes, "deck.pptx")]
    p = intake.profile("Nightingale Health", docs)
    assert p["name"] == "Nightingale Health"


def test_a_one_pager_heading_is_the_company_name():
    """Reading only decks sent a .txt one-pager's name to the website slug
    and screened "Nightingalehealth" instead of Nightingale Health."""
    d = intake.read(b"Nightingale Health\nBlood test diagnostics for prevention.\n"
                    b"Raising 12M EUR Series B. nightingalehealth.com", "onepager.txt")
    p = intake.profile("", [d])
    assert p["name"] == "Nightingale Health"
    assert p["website"] == "nightingalehealth.com"


def test_a_sentence_at_the_top_is_not_a_company_name():
    d = intake.read(b"We build clinical documentation software for doctors.\n"
                    b"gostalabs.com", "notes.txt")
    p = intake.profile("", [d])
    assert p["name"] != "We build clinical documentation software for doctors."


def test_a_deck_title_still_wins_over_another_file(deck_bytes):
    docs = [intake.read(b"Some Other Heading\nmore text", "notes.txt"),
            intake.read(deck_bytes, "deck.pptx")]
    assert intake.profile("", docs)["name"] == "Gosta Labs"
