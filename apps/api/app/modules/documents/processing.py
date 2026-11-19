"""Real document text extraction: PDF, images (OCR), DOCX, XLSX, CSV and plain text."""

from __future__ import annotations

import csv
import io
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.config.settings import settings
from app.core.errors import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

MAX_PAGES = 200
MAX_CHARS_PER_PAGE = 200_000
MAX_OCR_BOXES = 1500


class DocumentProcessingError(AppError):
    status_code = 422
    code = "document_processing_failed"
    message = "The document could not be processed."


@dataclass(slots=True)
class PageResult:
    page_number: int
    text: str
    has_text_layer: bool = True
    ocr_confidence: float | None = None
    width: float | None = None
    height: float | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedDocument:
    pages: list[PageResult]
    parser: str
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def full_text(self) -> str:
        return "\n\n".join(f"[page {page.page_number}]\n{page.text}" for page in self.pages)

    @property
    def char_count(self) -> int:
        return sum(len(page.text) for page in self.pages)

    @property
    def ocr_confidence(self) -> float | None:
        values = [page.ocr_confidence for page in self.pages if page.ocr_confidence is not None]
        return round(sum(values) / len(values), 3) if values else None


_ocr_state: tuple[bool, str] | None = None
_language_state: str | None = None


def _configured_tesseract() -> str | None:
    """Resolve the Tesseract binary, including the default Windows install path."""
    if settings.TESSERACT_CMD:
        return settings.TESSERACT_CMD
    found = shutil.which("tesseract")
    if found:
        return found
    for candidate in (
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    ):
        if Path(candidate).is_file():
            return candidate
    return None


def ocr_languages() -> str:
    """Requested OCR languages narrowed to the traineddata actually installed."""
    global _language_state
    if _language_state is not None:
        return _language_state
    requested = [part.strip() for part in settings.OCR_LANGUAGE.split("+") if part.strip()]
    try:
        import pytesseract

        available = set(pytesseract.get_languages(config=""))
    except Exception:  # noqa: BLE001 - reported by ocr_status() instead
        return settings.OCR_LANGUAGE
    chosen = [language for language in requested if language in available]
    if not chosen:
        chosen = ["eng"] if "eng" in available else sorted(available)[:1]
    _language_state = "+".join(chosen) or "eng"
    if set(chosen) != set(requested):
        logger.warning(
            "ocr_language_fallback",
            requested=requested,
            using=_language_state,
            installed=sorted(available),
        )
    return _language_state


def ocr_status() -> tuple[bool, str]:
    global _ocr_state
    if _ocr_state is not None:
        return _ocr_state
    if not settings.OCR_ENABLED or settings.OCR_PROVIDER == "none":
        _ocr_state = (False, "OCR is disabled by configuration (OCR_ENABLED=false).")
        return _ocr_state
    try:
        import pytesseract

        command = _configured_tesseract()
        if command:
            pytesseract.pytesseract.tesseract_cmd = command
        version = pytesseract.get_tesseract_version()
        _ocr_state = (True, f"Tesseract {version}")
    except Exception as exc:  # noqa: BLE001 - missing binary raises several error types
        _ocr_state = (
            False,
            "OCR engine unavailable: Tesseract is not installed or not on PATH. "
            "Set TESSERACT_CMD or install tesseract-ocr.",
        )
        logger.warning("ocr_unavailable", error=str(exc))
    return _ocr_state


def _ocr_image(image) -> tuple[str, float, list[dict[str, Any]]]:  # type: ignore[no-untyped-def]
    import pytesseract
    from pytesseract import Output

    available, reason = ocr_status()
    if not available:
        raise DocumentProcessingError(reason, code="ocr_unavailable")
    command = _configured_tesseract()
    if command:
        pytesseract.pytesseract.tesseract_cmd = command
    language = ocr_languages()
    data = pytesseract.image_to_data(
        image,
        output_type=Output.DICT,
        lang=language,
        config="--psm 6",
        timeout=settings.OCR_TIMEOUT_SECONDS,
    )
    words: list[str] = []
    confidences: list[float] = []
    boxes: list[dict[str, Any]] = []
    last_block = None
    for index, word in enumerate(data.get("text", [])):
        text = (word or "").strip()
        if not text:
            continue
        try:
            confidence = float(data["conf"][index])
        except (KeyError, TypeError, ValueError):
            confidence = -1.0
        if confidence >= 0:
            confidences.append(confidence / 100.0)
        box = {
            "text": text,
            "left": int(data["left"][index]),
            "top": int(data["top"][index]),
            "width": int(data["width"][index]),
            "height": int(data["height"][index]),
        }
        if len(boxes) < MAX_OCR_BOXES:
            boxes.append(box)
        block = (data.get("block_num", [0] * len(data["text"])))[index]
        if last_block is not None and block != last_block:
            words.append("\n")
        words.append(text)
        last_block = block
    text = " ".join(words).replace(" \n ", "\n").replace(" \n", "\n")
    confidence = round(sum(confidences) / len(confidences), 3) if confidences else 0.0
    return text[:MAX_CHARS_PER_PAGE], confidence, boxes


def _extract_pdf(data: bytes) -> ParsedDocument:
    import pymupdf

    pages: list[PageResult] = []
    metadata: dict[str, Any] = {}
    try:
        document = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001
        raise DocumentProcessingError(f"PDF could not be opened: {exc}", code="invalid_pdf") from exc
    try:
        if document.needs_pass:
            raise DocumentProcessingError("Password-protected PDFs are not supported.", code="encrypted_pdf")
        metadata = {
            "title": document.metadata.get("title"),
            "author": document.metadata.get("author"),
            "producer": document.metadata.get("producer"),
        }
        for index, page in enumerate(document):
            if index >= MAX_PAGES:
                metadata["truncated"] = True
                break
            text = (page.get_text("text") or "").strip()
            page_result: PageResult
            if len(text) < settings.OCR_MIN_TEXT_CHARS_PER_PAGE:
                available, reason = ocr_status()
                if available:
                    try:
                        from PIL import Image

                        pixmap = page.get_pixmap(dpi=settings.PDF_RENDER_DPI)
                        image = Image.open(io.BytesIO(pixmap.tobytes("png")))
                        ocr_text, confidence, boxes = _ocr_image(image)
                        page_result = PageResult(
                            page_number=index + 1,
                            text=ocr_text,
                            has_text_layer=False,
                            ocr_confidence=confidence,
                            width=float(page.rect.width),
                            height=float(page.rect.height),
                            extra={"ocr_boxes": boxes, "ocr_language": ocr_languages()},
                        )
                    except DocumentProcessingError:
                        page_result = PageResult(
                            page_number=index + 1,
                            text=text,
                            has_text_layer=bool(text),
                            extra={"ocr_skipped": reason},
                        )
                else:
                    page_result = PageResult(
                        page_number=index + 1,
                        text=text,
                        has_text_layer=bool(text),
                        extra={"ocr_skipped": reason, "low_text": True},
                    )
            else:
                page_result = PageResult(
                    page_number=index + 1,
                    text=text[:MAX_CHARS_PER_PAGE],
                    has_text_layer=True,
                    width=float(page.rect.width),
                    height=float(page.rect.height),
                )
            pages.append(page_result)
        metadata["page_count"] = len(pages)
        metadata["ocr_used"] = any(page.ocr_confidence is not None for page in pages)
        return ParsedDocument(pages=pages, parser="pymupdf", metadata=metadata)
    finally:
        document.close()


def _extract_image(data: bytes) -> ParsedDocument:
    from PIL import Image, UnidentifiedImageError

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise DocumentProcessingError("Image file could not be opened.", code="invalid_image") from exc
    if image.width * image.height > 40_000_000:
        raise DocumentProcessingError("Image dimensions are too large.", code="image_too_large")
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    text, confidence, boxes = _ocr_image(image)
    return ParsedDocument(
        pages=[
            PageResult(
                page_number=1,
                text=text,
                has_text_layer=False,
                ocr_confidence=confidence,
                width=float(image.width),
                height=float(image.height),
                extra={"ocr_boxes": boxes, "ocr_language": ocr_languages()},
            )
        ],
        parser="tesseract",
        metadata={"ocr_used": True, "width": image.width, "height": image.height},
    )


def _assert_zip_safe(data: bytes, *, label: str) -> None:
    """Reject archive bombs before handing bytes to parsers."""
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            entries = archive.infolist()
            if len(entries) > 20_000:
                raise DocumentProcessingError(
                    f"{label} archive contains too many entries.", code="archive_too_large"
                )
            total = sum(entry.file_size for entry in entries)
            limit = settings.MAX_DECOMPRESSED_MB * 1024 * 1024
            if total > limit:
                raise DocumentProcessingError(
                    f"{label} archive expands to {total // (1024 * 1024)} MB (limit {settings.MAX_DECOMPRESSED_MB} MB).",
                    code="archive_too_large",
                )
    except zipfile.BadZipFile as exc:
        raise DocumentProcessingError(f"{label} archive is invalid.", code="invalid_archive") from exc


def _extract_docx(data: bytes) -> ParsedDocument:
    import docx

    _assert_zip_safe(data, label="DOCX")

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise DocumentProcessingError("DOCX file could not be opened.", code="invalid_docx") from exc
    blocks: list[str] = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells]
            if any(cells):
                blocks.append(" | ".join(cells))
    text = "\n".join(blocks)
    return ParsedDocument(
        pages=[PageResult(page_number=1, text=text[:MAX_CHARS_PER_PAGE])],
        parser="python-docx",
        metadata={"paragraphs": len(document.paragraphs), "tables": len(document.tables)},
    )


def _extract_xlsx(data: bytes) -> ParsedDocument:
    from openpyxl import load_workbook

    _assert_zip_safe(data, label="XLSX")

    try:
        workbook = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise DocumentProcessingError("XLSX file could not be opened.", code="invalid_xlsx") from exc
    pages: list[PageResult] = []
    sheets: list[dict[str, Any]] = []
    try:
        for index, name in enumerate(workbook.sheetnames):
            sheet = workbook[name]
            rows: list[list[str]] = []
            for row in sheet.iter_rows(values_only=True):
                values = ["" if value is None else str(value) for value in row]
                if any(value.strip() for value in values):
                    rows.append(values)
                if len(rows) >= 5000:
                    break
            text = "\n".join(" | ".join(values) for values in rows)
            pages.append(
                PageResult(
                    page_number=index + 1,
                    text=text[:MAX_CHARS_PER_PAGE],
                    extra={"sheet": name, "rows": len(rows)},
                )
            )
            sheets.append({"name": name, "rows": len(rows), "columns": len(rows[0]) if rows else 0})
    finally:
        workbook.close()
    return ParsedDocument(pages=pages, parser="openpyxl", metadata={"sheets": sheets})


def _extract_csv(data: bytes) -> ParsedDocument:
    for encoding in ("utf-8-sig", "utf-8", "cp874", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise DocumentProcessingError("CSV encoding could not be detected.", code="invalid_csv")
    rows = list(csv.reader(io.StringIO(text)))
    rendered = "\n".join(" | ".join(cell.strip() for cell in row) for row in rows[:5000])
    return ParsedDocument(
        pages=[PageResult(page_number=1, text=rendered[:MAX_CHARS_PER_PAGE])],
        parser="csv",
        metadata={"rows": len(rows), "encoding": "utf-8/cp874"},
    )


def _extract_text(data: bytes) -> ParsedDocument:
    for encoding in ("utf-8-sig", "utf-8", "cp874", "latin-1"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise DocumentProcessingError("Text file encoding could not be detected.", code="invalid_text")
    return ParsedDocument(
        pages=[PageResult(page_number=1, text=text[:MAX_CHARS_PER_PAGE])],
        parser="text",
        metadata={"encoding": "utf-8/cp874"},
    )


def parse_document(data: bytes, *, mime_type: str, filename: str) -> ParsedDocument:
    mime = (mime_type or "").lower()
    suffix = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    if mime == "application/pdf" or suffix == "pdf":
        return _extract_pdf(data)
    if mime.startswith("image/") or suffix in {"png", "jpg", "jpeg"}:
        return _extract_image(data)
    if suffix == "docx" or mime in {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    }:
        return _extract_docx(data)
    if suffix == "xlsx" or mime in {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}:
        return _extract_xlsx(data)
    if suffix == "csv" or mime == "text/csv":
        return _extract_csv(data)
    if suffix == "txt" or mime == "text/plain":
        return _extract_text(data)
    raise DocumentProcessingError(
        f"Unsupported document type: {mime or suffix or 'unknown'}.", code="unsupported_document_type"
    )


def system_capabilities() -> dict[str, Any]:
    available, detail = ocr_status()
    return {"ocr_available": available, "ocr_detail": detail, "parser": "pymupdf/openpyxl/python-docx/csv"}
