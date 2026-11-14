"""Read what a founder brings: a paragraph, a deck, a spreadsheet, a PDF.

A founder arriving with a round to raise already has the material. Asking
them to retype it into a search box is asking them to summarise themselves
worse than their deck does. So this takes the deck.

The job is not summarisation. It is to pull out the handful of fields the
rest of the product needs to look anything up - who they are, what they
build, what they are raising, where they are - and to say which line of
which file each one came from, because a profile with no provenance is a
guess wearing a suit.

Nothing here calls a model. A deck is a structured document and the fields
we need are the ones founders put in it in a predictable place: the title
slide, the ask slide, the metrics table.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

MAX_BYTES = 20 * 1024 * 1024
MAX_CHARS = 120_000

STAGES = [
    ("pre-seed", re.compile(r"\bpre[-\s]?seed\b", re.I)),
    # "pre-seed" contains "seed", and a hyphen is a word boundary, so a plain
    # \bseed\b reads every pre-seed deck as a seed deck.
    ("seed", re.compile(r"(?<!pre-)(?<!pre )\bseed\b", re.I)),
    ("series a", re.compile(r"\bseries\s*a\b", re.I)),
    ("series b", re.compile(r"\bseries\s*b\b", re.I)),
    ("series c", re.compile(r"\bseries\s*c\b", re.I)),
    ("growth", re.compile(r"\bgrowth\s*(round|equity)?\b", re.I)),
]

# "raising €3m", "$2.5 million seed", "2,5 M€", "1,250,000 USD".
# Currency and multiplier are both optional, so a bare "1250000 USD" matches;
# _amount() then throws away anything that carries neither and is too small
# to be a round, which is how "14 hospitals live" stays out.
_AMOUNT = re.compile(
    r"(?P<cur1>[€$£])?\s*(?P<n>\d[\d.,]*\d|\d)\s*"
    r"(?P<m>k|m|bn|b|million|billion|thousand)?\s*"
    r"(?P<cur2>[€$£]|eur|usd|gbp)?",
    re.I)
_MULT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6,
         "b": 1e9, "bn": 1e9, "billion": 1e9}
_CUR = {"€": "EUR", "$": "USD", "£": "GBP", "eur": "EUR", "usd": "USD", "gbp": "GBP"}

_URL = re.compile(r"\b(?:https?://)?((?:[a-z0-9-]+\.)+(?:com|io|ai|co|fi|se|dk|no|eu|dev|app|xyz|tech|health|org|net))\b", re.I)
# Hosts that are somebody else's: a deck footer is full of them.
_NOT_A_COMPANY_HOST = re.compile(
    r"^(www\.)?(linkedin|twitter|x|github|notion|google|docs\.google|drive\.google|"
    r"youtube|vimeo|calendly|crunchbase|pitchbook|dealroom|slideshare|canva|"
    r"figma|medium|substack|gmail|outlook|apple|microsoft)\.", re.I)

_EMAIL = re.compile(r"\b[\w.+-]+@([\w-]+\.[\w.-]+)\b")


@dataclass
class Source:
    """Where one claim came from, precisely enough to check."""
    file: str
    where: str          # "slide 3", "sheet Metrics!B4", "page 2", "what you wrote"
    quote: str

    def as_dict(self) -> dict:
        return {"file": self.file, "where": self.where, "quote": self.quote[:300]}


@dataclass
class Doc:
    """One file, flattened to located lines."""
    name: str
    kind: str
    lines: list[tuple[str, str]] = field(default_factory=list)   # (where, text)
    error: str | None = None

    @property
    def text(self) -> str:
        return "\n".join(t for _, t in self.lines)


def _clean(s) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


# ------------------------------------------------------------------ readers
def read_pptx(data: bytes, name: str) -> Doc:
    from pptx import Presentation
    d = Doc(name=name, kind="deck")
    prs = Presentation(io.BytesIO(data))
    for i, slide in enumerate(prs.slides, 1):
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    t = _clean("".join(r.text for r in para.runs))
                    if t:
                        d.lines.append((f"slide {i}", t))
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    cells = [_clean(c.text) for c in row.cells]
                    if any(cells):
                        d.lines.append((f"slide {i}", " | ".join(cells)))
    return d


def read_xlsx(data: bytes, name: str) -> Doc:
    import openpyxl
    d = Doc(name=name, kind="spreadsheet")
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    for ws in wb.worksheets:
        for row in ws.iter_rows(max_row=400, max_col=40):
            cells = [(c.coordinate, _clean(c.value)) for c in row if c.value not in (None, "")]
            if not cells:
                continue
            where = f"{ws.title}!{cells[0][0]}"
            d.lines.append((where, " | ".join(v for _, v in cells)))
    wb.close()
    return d


def read_pdf(data: bytes, name: str) -> Doc:
    from pypdf import PdfReader
    d = Doc(name=name, kind="pdf")
    r = PdfReader(io.BytesIO(data))
    for i, page in enumerate(r.pages[:60], 1):
        for line in (page.extract_text() or "").splitlines():
            t = _clean(line)
            if t:
                d.lines.append((f"page {i}", t))
    return d


def read_text(data: bytes, name: str) -> Doc:
    d = Doc(name=name, kind="text")
    for i, line in enumerate(data.decode("utf-8", "replace").splitlines(), 1):
        t = _clean(line)
        if t:
            d.lines.append((f"line {i}", t))
    return d


READERS = {
    "pptx": read_pptx, "ppt": read_pptx,
    "xlsx": read_xlsx, "xlsm": read_xlsx,
    "pdf": read_pdf,
    "txt": read_text, "md": read_text, "csv": read_text,
}


def read(data: bytes, name: str) -> Doc:
    """One file in, located lines out. Never raises: a bad file is a message."""
    ext = (name.rsplit(".", 1)[-1] if "." in name else "").lower()
    fn = READERS.get(ext)
    if fn is None:
        return Doc(name=name, kind=ext or "unknown",
                   error=f"We can read decks, spreadsheets, PDFs and text. "
                         f"{'.' + ext if ext else 'This file'} is not one of those.")
    if len(data) > MAX_BYTES:
        return Doc(name=name, kind=ext,
                   error=f"{len(data) // 1024 // 1024} MB is larger than the "
                         f"{MAX_BYTES // 1024 // 1024} MB we read.")
    try:
        d = fn(data, name)
    except Exception as e:                            # noqa: BLE001
        return Doc(name=name, kind=ext,
                   error=f"Could not read it: {type(e).__name__}. "
                         f"If it is password-protected or a scan, paste the text instead.")
    if not d.lines:
        d.error = ("No text in it. A deck exported as images has nothing to "
                   "read - paste the key lines instead.")
    return d


# ------------------------------------------------------------- extraction
def _amount(text: str) -> tuple[float, str] | None:
    """The first figure in this line that could be a round size.

    Scans every number rather than stopping at the first, because "Series A
    2026: raising 4.5M" leads with a year.
    """
    for m in _AMOUNT.finditer(text or ""):
        n = m.group("n")
        if not n:
            continue
        mult = (m.group("m") or "").lower()
        cur = (m.group("cur1") or m.group("cur2") or "").lower()
        # "2,5" is two and a half in Helsinki and two thousand five hundred
        # in London. A comma with exactly three digits after it is a
        # thousands separator; anything else is a decimal point.
        txt = n.replace(" ", "")
        if re.search(r",\d{3}\b", txt):
            txt = txt.replace(",", "")
        txt = txt.replace(",", ".")
        if txt.count(".") > 1:
            txt = txt.replace(".", "", txt.count(".") - 1)
        try:
            v = float(txt)
        except ValueError:
            continue
        v *= _MULT.get(mult, 1.0)
        # A figure with no currency and no multiplier is a headcount or a
        # slide number until it is large enough not to be.
        if not cur and not mult and v < 10_000:
            continue
        if v < 10_000 or v > 5e9:
            continue
        return v, _CUR.get(cur, "EUR")
    return None


def _domains(lines) -> list[tuple[str, str, str]]:
    """(host, where, quote) for hosts that could be the company's own."""
    out = []
    for where, t in lines:
        for m in _URL.finditer(t):
            host = m.group(1).lower()
            if _NOT_A_COMPANY_HOST.match(host):
                continue
            out.append((host, where, t))
        for m in _EMAIL.finditer(t):
            host = m.group(1).lower()
            if _NOT_A_COMPANY_HOST.match(host) or host in ("gmail.com", "hotmail.com"):
                continue
            out.append((host, where, t))
    return out


def _title_line(docs) -> tuple[str, str, str] | None:
    """The first substantial line of the first deck: the title slide.

    Founders put the company name on slide one. Not a rule we invented -
    it is what every deck does, which is why it is worth reading.
    """
    for d in docs:
        if d.kind != "deck":
            continue
        for where, t in d.lines[:6]:
            if 2 <= len(t) <= 60 and not t.lower().startswith(("confidential", "www.")):
                return t, d.name, where
    return None


# Words that say what market a company is in without naming it. Reused from
# the person cards so a founder's deck and an investor's record are matched
# against the same vocabulary rather than two that nearly agree.
def market_words(text: str) -> list[str]:
    from .person import markets_in
    return sorted(markets_in(text or ""))


def profile(text: str, docs: list[Doc]) -> dict:
    """What the founder told us, each field with where it came from."""
    typed = [("what you wrote", t) for t in
             (ln.strip() for ln in (text or "").splitlines()) if t.strip()]
    all_lines = list(typed)
    for d in docs:
        all_lines += [(f"{d.name} · {w}", t) for w, t in d.lines]

    joined = "\n".join(t for _, t in all_lines)[:MAX_CHARS]
    out: dict = {"sources": {}, "evidence": []}

    def claim(field_name, value, where, quote):
        out[field_name] = value
        out["sources"][field_name] = Source(
            file=where.split(" · ")[0], where=where.split(" · ")[-1],
            quote=quote).as_dict()

    # Website: the strongest identifier a founder can give us, because it is
    # the one thing that resolves to exactly one company in Cala.
    hosts = _domains(all_lines)
    if hosts:
        counts: dict[str, int] = {}
        for h, _, _ in hosts:
            counts[h] = counts.get(h, 0) + 1
        best = max(counts, key=lambda h: (counts[h], -len(h)))
        where, quote = next((w, q) for h, w, q in hosts if h == best)
        claim("website", best, where, quote)

    # Name: what the founder typed first, or the title slide.
    if typed:
        first = typed[0][1]
        if 2 <= len(first) <= 60:
            claim("name", first.rstrip(" .,"), "what you wrote", first)
    if not out.get("name"):
        t = _title_line(docs)
        if t:
            claim("name", t[0], f"{t[1]} · {t[2]}", t[0])
    if not out.get("name") and out.get("website"):
        claim("name", out["website"].split(".")[0].title(),
              out["sources"]["website"]["where"], out["website"])

    # Stage: the latest one mentioned, because a deck that says "we raised a
    # seed, now raising Series A" means the Series A.
    for label, rx in reversed(STAGES):
        m = rx.search(joined)
        if m:
            where, quote = next(((w, q) for w, q in all_lines if rx.search(q)),
                                ("what you wrote", m.group(0)))
            claim("stage", label, where, quote)
            break

    # Round size: only from a line that is about raising.
    for where, t in all_lines:
        if not re.search(r"\b(rais|round|ask|seeking|target)\w*\b", t, re.I):
            continue
        a = _amount(t)
        if a:
            claim("round_size", round(a[0]), where, t)
            out["round_currency"] = a[1]
            break

    # What they build: the longest descriptive line, which is almost always
    # the one-liner founders have already polished.
    desc = [(w, t) for w, t in all_lines
            if 40 <= len(t) <= 300 and " " in t and not t.startswith("|")]
    if desc:
        w, t = max(desc, key=lambda x: len(x[1]))
        claim("description", t, w, t)

    out["markets"] = market_words(joined)
    out["text_chars"] = len(joined)
    out["files"] = [{"name": d.name, "kind": d.kind, "lines": len(d.lines),
                     "error": d.error} for d in docs]
    out["evidence"] = [{"field": k, **v} for k, v in out["sources"].items()]
    return out
