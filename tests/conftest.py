"""Fixtures shared across the suite."""
import pytest
@pytest.fixture(scope="session")
def deck_bytes():
    """A real .pptx, built here rather than committed as a binary."""
    import io
    from pptx import Presentation
    from pptx.util import Inches
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[5])
    s.shapes.title.text = "Gosta Labs"
    s.shapes.add_textbox(Inches(1), Inches(3), Inches(6), Inches(1)).text_frame.text = (
        "Clinical documentation that writes itself, so doctors stop typing at night.")
    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2.shapes.title.text = "The ask"
    s2.shapes.add_textbox(Inches(1), Inches(3), Inches(6), Inches(1)).text_frame.text = (
        "Raising EUR 4.5M Series A. gostalabs.com")
    buf = io.BytesIO(); prs.save(buf)
    return buf.getvalue()


@pytest.fixture(scope="session")
def sheet_bytes():
    import io
    import openpyxl
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Metrics"
    ws["A1"], ws["B1"] = "ARR", 820000
    ws["A2"], ws["B2"] = "Hospitals live", 14
    ws["A3"], ws["B3"] = "Raising", "4.5M EUR Series A"
    buf = io.BytesIO(); wb.save(buf)
    return buf.getvalue()
