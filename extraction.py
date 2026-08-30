from __future__ import annotations

import dataclasses
import logging
from typing import List

import pdfplumber

logger = logging.getLogger(__name__)

# Try to import OCR dependencies; make them optional so the app works without
# Tesseract installed (embedded-text PDFs work fine without it).
try:
    import pytesseract
    from pdf2image import convert_from_path
    _OCR_AVAILABLE = True
except Exception:
    _OCR_AVAILABLE = False
    logger.warning(
        "pytesseract or pdf2image is not available. "
        "OCR fallback for scanned PDFs is disabled. "
        "PDFs with embedded text will still be processed normally."
    )


class ExtractionError(Exception):
    """Raised when PDF text extraction fails entirely. Maps to HTTP 422/500."""
    def __init__(self, message: str = "File could not be processed"):
        super().__init__(message)
        self.message = message
        self.status_code = 500


@dataclasses.dataclass
class ExtractionResult:
    """Result of extracting text from a single PDF document."""
    text: str
    char_count: int
    warnings: List[str]


def extract(file_path: str) -> ExtractionResult:
    """Extract text from a PDF file, using OCR as a fallback for image pages.

    Opens the PDF with pdfplumber and attempts direct text extraction on every
    page. For any page that yields no text, OCR is applied via pdf2image and
    pytesseract if available. If Tesseract is not installed, image-only pages
    are skipped with a warning instead of crashing.

    Args:
        file_path: Absolute or relative path to the PDF file on disk.

    Returns:
        ExtractionResult with the concatenated text, character count, and any
        warnings about low content or partial extraction failures.

    Raises:
        ExtractionError: If the document exceeds 500 pages, or if all pages
            fail both direct extraction and OCR (or OCR is unavailable and no
            pages have embedded text).
    """
    warnings: List[str] = []
    page_texts: List[str] = []
    failed_ocr_pages: int = 0

    with pdfplumber.open(file_path) as pdf:
        # Step 1: enforce 500-page limit BEFORE processing any pages
        if len(pdf.pages) > 500:
            raise ExtractionError(
                f"Document exceeds the maximum supported page limit of 500 pages "
                f"(document has {len(pdf.pages)} pages)."
            )

        # Steps 2–3: iterate pages, try pdfplumber first, OCR as fallback
        for page in pdf.pages:
            page_text: str | None = page.extract_text()

            if page_text and page_text.strip():
                # Direct extraction succeeded
                page_texts.append(page_text)
            else:
                # No embedded text on this page — try OCR if available
                if _OCR_AVAILABLE:
                    try:
                        images = convert_from_path(
                            file_path,
                            first_page=page.page_number,
                            last_page=page.page_number,
                        )
                        if images:
                            ocr_text = pytesseract.image_to_string(images[0])
                            if ocr_text and ocr_text.strip():
                                page_texts.append(ocr_text)
                            else:
                                # OCR produced no text for this page
                                failed_ocr_pages += 1
                        else:
                            failed_ocr_pages += 1
                    except Exception as exc:
                        # OCR itself raised an exception for this page
                        logger.warning("OCR failed on page %s: %s", page.page_number, exc)
                        failed_ocr_pages += 1
                else:
                    # Tesseract not available — skip this page silently
                    failed_ocr_pages += 1

    # Step 4: if EVERY page failed, raise
    if not page_texts:
        if not _OCR_AVAILABLE:
            raise ExtractionError(
                "No embedded text found in the PDF. "
                "Tesseract OCR is not installed, so scanned pages cannot be processed. "
                "Please use a PDF with selectable text."
            )
        raise ExtractionError("File could not be processed")

    # Step 5: concatenate and compute char_count
    text = "\n".join(page_texts)
    char_count = len(text)

    # Step 6: low-content warning
    if char_count < 100:
        warnings.append(
            "Extracted text is very short (fewer than 100 characters). "
            "The document may not contain sufficient content for analysis."
        )

    # Step 7: partial-extraction warning
    if failed_ocr_pages > 0:
        if _OCR_AVAILABLE:
            warnings.append(
                f"Text extraction failed on {failed_ocr_pages} page(s). "
                "The analysis is based on partially extracted content."
            )
        else:
            warnings.append(
                f"{failed_ocr_pages} page(s) had no embedded text and were skipped "
                "(Tesseract OCR is not installed). Install Tesseract to process scanned pages."
            )

    return ExtractionResult(text=text, char_count=char_count, warnings=warnings)
