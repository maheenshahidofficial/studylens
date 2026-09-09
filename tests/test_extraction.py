"""
test_extraction.py — Unit tests for the extraction engine (Task 16.4).
All pdfplumber and OCR calls are mocked — no real PDF or Tesseract needed.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parent.parent))

from unittest.mock import MagicMock, patch
import pytest

from extraction import extract, ExtractionError


def _make_pdf_mock(pages_text_list):
    """Build a pdfplumber context-manager mock.

    pages_text_list: list where each entry is the string returned by
    page.extract_text(), or None for an image-only page.
    """
    pages = []
    for i, text in enumerate(pages_text_list):
        page = MagicMock()
        page.page_number = i + 1
        page.extract_text.return_value = text
        pages.append(page)

    pdf_ctx = MagicMock()
    pdf_ctx.pages = pages
    pdf_ctx.__enter__ = MagicMock(return_value=pdf_ctx)
    pdf_ctx.__exit__ = MagicMock(return_value=False)
    return pdf_ctx


# ---------------------------------------------------------------------------
# 16.4-a: Embedded text — OCR must NOT be called
# ---------------------------------------------------------------------------

def test_extract_embedded_text_no_ocr():
    long_text = "Hello world. " * 20  # well over 100 chars
    pdf_mock = _make_pdf_mock([long_text])
    with patch("extraction.pdfplumber.open", return_value=pdf_mock), \
         patch("extraction._OCR_AVAILABLE", True), \
         patch("extraction.convert_from_path") as mock_ocr:
        result = extract("fake.pdf")
    mock_ocr.assert_not_called()
    assert long_text.strip() in result.text
    assert result.char_count > 0
    assert result.warnings == []


# ---------------------------------------------------------------------------
# 16.4-b: Image-only PDF — OCR path used
# ---------------------------------------------------------------------------

def test_extract_image_only_uses_ocr():
    pdf_mock = _make_pdf_mock([None])
    ocr_text = "OCR extracted content from scanned image page."
    mock_image = MagicMock()
    with patch("extraction.pdfplumber.open", return_value=pdf_mock), \
         patch("extraction._OCR_AVAILABLE", True), \
         patch("extraction.convert_from_path", return_value=[mock_image]) as mock_cfp, \
         patch("extraction.pytesseract.image_to_string", return_value=ocr_text):
        result = extract("fake.pdf")
    mock_cfp.assert_called_once()
    assert ocr_text in result.text


# ---------------------------------------------------------------------------
# 16.4-c: Mixed PDF — both embedded and OCR paths used
# ---------------------------------------------------------------------------

def test_extract_mixed_pdf_uses_both_paths():
    embedded = "Embedded text on page one."
    pdf_mock = _make_pdf_mock([embedded, None])
    ocr_text = "OCR text on page two."
    mock_image = MagicMock()
    with patch("extraction.pdfplumber.open", return_value=pdf_mock), \
         patch("extraction._OCR_AVAILABLE", True), \
         patch("extraction.convert_from_path", return_value=[mock_image]), \
         patch("extraction.pytesseract.image_to_string", return_value=ocr_text):
        result = extract("fake.pdf")
    assert embedded in result.text
    assert ocr_text in result.text


# ---------------------------------------------------------------------------
# 16.4-d: All pages fail → ExtractionError
# ---------------------------------------------------------------------------

def test_extract_all_pages_fail_raises_extraction_error():
    pdf_mock = _make_pdf_mock([None])
    mock_image = MagicMock()
    with patch("extraction.pdfplumber.open", return_value=pdf_mock), \
         patch("extraction._OCR_AVAILABLE", True), \
         patch("extraction.convert_from_path", return_value=[mock_image]), \
         patch("extraction.pytesseract.image_to_string", return_value=""):
        with pytest.raises(ExtractionError):
            extract("fake.pdf")


# ---------------------------------------------------------------------------
# 16.4-e: Low-content extraction → warning present
# ---------------------------------------------------------------------------

def test_extract_low_content_produces_warning():
    short_text = "Hi"  # 2 chars — under the 100-char threshold
    pdf_mock = _make_pdf_mock([short_text])
    with patch("extraction.pdfplumber.open", return_value=pdf_mock), \
         patch("extraction._OCR_AVAILABLE", False):
        result = extract("fake.pdf")
    assert result.char_count < 100
    assert any(
        "short" in w.lower() or "fewer" in w.lower() or "100" in w
        for w in result.warnings
    )


# ---------------------------------------------------------------------------
# 16.4-f: Page count > 500 → ExtractionError raised immediately
# ---------------------------------------------------------------------------

def test_extract_over_500_pages_raises():
    pdf_mock = _make_pdf_mock(["text"] * 501)
    with patch("extraction.pdfplumber.open", return_value=pdf_mock), \
         patch("extraction._OCR_AVAILABLE", False):
        with pytest.raises(ExtractionError) as exc_info:
            extract("fake.pdf")
    assert "500" in exc_info.value.message or "page" in exc_info.value.message.lower()


# ---------------------------------------------------------------------------
# 16.4-g: Partial OCR failure → extraction continues, warning produced
# ---------------------------------------------------------------------------

def test_extract_partial_ocr_failure_continues_with_warning():
    # Page 1: embedded; Page 2: OCR succeeds; Page 3: OCR returns empty
    pdf_mock = _make_pdf_mock(["Page one embedded text.", None, None])
    mock_image = MagicMock()
    ocr_returns = iter(["Page two OCR content.", ""])  # page3 empty

    with patch("extraction.pdfplumber.open", return_value=pdf_mock), \
         patch("extraction._OCR_AVAILABLE", True), \
         patch("extraction.convert_from_path", return_value=[mock_image]), \
         patch("extraction.pytesseract.image_to_string", side_effect=list(ocr_returns)):
        result = extract("fake.pdf")

    assert "Page one embedded text." in result.text
    assert "Page two OCR content." in result.text
    # Must have a partial-extraction warning
    assert len(result.warnings) > 0
    assert any("1" in w for w in result.warnings)  # mentions 1 failed page
