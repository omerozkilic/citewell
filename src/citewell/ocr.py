"""OCR for scanned PDF pages (``CITEWELL_OCR=auto``).

Only pages without a text layer are sent to Tesseract, so PDFs with real text are never slowed
down. Pages are rendered with pypdfium2 and recognised with the local ``tesseract`` binary:
nothing leaves the machine and no network is needed. OCR text is, of course, an approximation of
the printed text; documents record which pages came from OCR so that this stays visible.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


class OcrUnavailableError(RuntimeError):
    """OCR was requested but the Python packages, the tesseract binary or a language are missing."""


@dataclass(frozen=True, slots=True)
class OcrOptions:
    languages: str = "tur+eng"
    dpi: int = 300
    timeout_s: int = 120
    max_pages: int = 500  # 0 = no limit


class OcrSession:
    """Renders and recognises pages of one PDF; open it once per document."""

    def __init__(self, data: bytes, options: OcrOptions):
        try:
            import pypdfium2
            import pytesseract
        except ImportError as exc:
            raise OcrUnavailableError("OCR requires: pip install 'citewell[ocr]'") from exc
        self.options = options
        self._tesseract: Any = pytesseract
        self._pdf: Any = pypdfium2.PdfDocument(data)

    def page_text(self, index: int) -> str:
        """Recognised text of the 0-based page ``index`` (empty if the page times out)."""
        page = self._pdf[index]
        try:
            image = page.render(scale=self.options.dpi / 72).to_pil()
            return str(
                self._tesseract.image_to_string(
                    image, lang=self.options.languages, timeout=self.options.timeout_s
                )
            )
        except self._tesseract.TesseractNotFoundError as exc:
            raise OcrUnavailableError(
                "the tesseract binary was not found: install tesseract-ocr and tesseract-ocr-tur"
            ) from exc
        except self._tesseract.TesseractError as exc:
            raise OcrUnavailableError(f"tesseract failed: {exc}") from exc
        except RuntimeError:  # pytesseract signals a timeout with a plain RuntimeError
            log.warning("OCR of page %s timed out after %ss", index + 1, self.options.timeout_s)
            return ""
        finally:
            page.close()

    def close(self) -> None:
        self._pdf.close()


def check_available(options: OcrOptions) -> str:
    """Raise ``OcrUnavailableError`` unless OCR can run; returns a short description when it can."""
    try:
        import pypdfium2  # noqa: F401
        import pytesseract
    except ImportError as exc:
        raise OcrUnavailableError("OCR requires: pip install 'citewell[ocr]'") from exc
    try:
        version = pytesseract.get_tesseract_version()
        installed = set(pytesseract.get_languages())
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrUnavailableError(
            "the tesseract binary was not found: install tesseract-ocr and tesseract-ocr-tur"
        ) from exc
    missing = [lang for lang in options.languages.split("+") if lang and lang not in installed]
    if missing:
        raise OcrUnavailableError(
            f"tesseract has no language data for {', '.join(missing)}: install tesseract-ocr-{missing[0]}"
        )
    return f"tesseract {version}, languages {options.languages}"
