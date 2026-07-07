#!/usr/bin/env python3
"""
Nubli: local-first document anonymizer.

It extracts Markdown/text from common office formats and applies replacement
rules without sending data to any web service. OCR is optional and local.
"""

from __future__ import annotations

import argparse
import csv
from difflib import SequenceMatcher
import importlib
import io
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


TEXT_EXTS = {".txt", ".md", ".markdown", ".html", ".htm", ".json", ".xml", ".yml", ".yaml", ".log"}
CSV_EXTS = {".csv", ".tsv"}
DOCX_EXTS = {".docx"}
XLSX_EXTS = {".xlsx", ".xlsm", ".xltx", ".xltm"}
PDF_EXTS = {".pdf"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}

TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)

PII_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE), "persona@demo.local"),
    ("phone", re.compile(r"(?<!\w)(?:\+?507[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?\d{4}|\d{4}[\s.-]?\d{4})(?!\w)"), "TEL-0000"),
    ("id_or_ruc", re.compile(r"(?<!\w)\d{1,2}-\d{1,4}-\d{1,7}(?!\w)"), "ID-0000"),
]

# Keep this list boring on purpose. These are common report headings that look
# like person names to a cheap regex; avoiding noisy suggestions matters because
# users will ignore the safety panel if it cries wolf too often.
COMMON_NAME_FALSE_POSITIVES = {
    "Demo Company",
    "Empresa Demo",
    "Persona Demo",
    "Estados Financieros",
    "Estado De",
    "Notas A",
    "República De",
    "Ciudad De",
    "Panamá",
    "Total Activos",
    "Total Pasivos",
}

SAFE_PLACEHOLDER_DOMAINS = (".local", "example.com", "example.org", "example.net")


@dataclass
class Rule:
    source: str
    target: str
    case_sensitive: bool = False
    smart: bool = True
    preserve_case: bool = True
    fuzzy_threshold: float = 0.88


@dataclass
class Suggestion:
    kind: str
    value: str
    target: str
    reason: str


@dataclass
class WordBox:
    text: str
    left: float
    top: float
    right: float
    bottom: float
    confidence: float = 100.0


def die(message: str, code: int = 2) -> None:
    print(f"nubli: {message}", file=sys.stderr)
    raise SystemExit(code)


def require_import(module_name: str, install_hint: str):
    try:
        return importlib.import_module(module_name)
    except ImportError as exc:
        die(f"missing dependency '{module_name}'. Install it with: {install_hint}")
        raise exc


def normalize_token(value: str, case_sensitive: bool = False) -> str:
    cleaned = re.sub(r"[\W_]+", "", value, flags=re.UNICODE)
    return cleaned if case_sensitive else cleaned.casefold()


def source_tokens(value: str) -> list[str]:
    return [token for token in TOKEN_RE.findall(value) if token]


def similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


def prompt_yes_no(message: str, default: bool = False) -> bool:
    marker = "Y/n" if default else "y/N"
    answer = input(f"{message} [{marker}] ").strip().lower()
    if not answer:
        return default
    return answer in {"y", "yes", "s", "si", "sí"}


def redact_preview(value: str, keep: int = 3) -> str:
    value = value.strip()
    if len(value) <= keep * 2:
        return "*" * len(value)
    return f"{value[:keep]}…{value[-keep:]}"


def safe_placeholder(kind: str, value: str) -> bool:
    lowered = value.casefold()
    if kind == "email" and "@" in lowered:
        domain = lowered.rsplit("@", 1)[1]
        return domain.endswith(SAFE_PLACEHOLDER_DOMAINS)
    return lowered in {"tel-0000", "id-0000", "persona demo", "empresa demo", "demo company"}


def suggest_sensitive_content(text: str, max_items: int = 80) -> list[Suggestion]:
    suggestions: list[Suggestion] = []
    seen: set[tuple[str, str]] = set()

    for kind, pattern, target in PII_PATTERNS:
        for match in pattern.finditer(text):
            value = match.group(0).strip()
            if safe_placeholder(kind, value):
                continue
            key = (kind, value.casefold())
            if key in seen:
                continue
            seen.add(key)
            suggestions.append(Suggestion(kind=kind, value=value, target=target, reason="pattern match"))
            if len(suggestions) >= max_items:
                return suggestions

    # This is intentionally a heuristic, not a NER model. Nubli's core should
    # stay light and offline; the goal is to nudge the user to review, not to
    # pretend we can perfectly identify every person name.
    name_pattern = re.compile(
        r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}(?:[ \t]+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}){1,3}\b"
    )
    for match in name_pattern.finditer(text):
        value = match.group(0).strip()
        if value in COMMON_NAME_FALSE_POSITIVES:
            continue
        key = ("possible_person", value.casefold())
        if key in seen:
            continue
        seen.add(key)
        suggestions.append(
            Suggestion(kind="possible_person", value=value, target="Persona Demo", reason="capitalized name-like phrase")
        )
        if len(suggestions) >= max_items:
            break

    return suggestions


def print_suggestions(suggestions: list[Suggestion]) -> None:
    if not suggestions:
        return
    print("\nNubli found possible sensitive values still present:", file=sys.stderr)
    for suggestion in suggestions[:20]:
        print(
            f"  - {suggestion.kind}: {redact_preview(suggestion.value)} -> suggest '{suggestion.target}' ({suggestion.reason})",
            file=sys.stderr,
        )
    if len(suggestions) > 20:
        print(f"  ... and {len(suggestions) - 20} more suggestions", file=sys.stderr)


def cleanup_paths(paths: Iterable[Path]) -> None:
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def enforce_safety(args: argparse.Namespace, engine: "ReplacementEngine", suggestions: list[Suggestion], written: Iterable[Path] = ()) -> None:
    total_matches = sum(engine.counts) + engine.visual_redactions
    problems: list[str] = []
    if total_matches == 0 and not args.allow_zero_replacements:
        problems.append("zero replacements/redactions matched")
    if args.require_all_rules:
        missing = [rule.source for rule, count in zip(engine.rules, engine.counts) if count == 0]
        if missing:
            problems.append("rules with zero matches: " + ", ".join(missing[:5]))

    if suggestions:
        print_suggestions(suggestions)
        if args.strict_pii:
            problems.append(f"{len(suggestions)} possible sensitive values still present")

    if not problems:
        return

    message = "Nubli safety check: " + "; ".join(problems)
    if args.interactive and sys.stdin.isatty():
        print(f"\n{message}", file=sys.stderr)
        if prompt_yes_no("Keep/write output anyway?", default=False):
            print("nubli: continuing because user confirmed interactively", file=sys.stderr)
            return

    # Fail closed. A false negative here can leak a client name; a false
    # positive only asks the user to be explicit.
    cleanup_paths(written)
    die(message + "; refused to write output")


def title_like(value: str) -> bool:
    words = [w for w in source_tokens(value) if any(ch.isalpha() for ch in w)]
    return bool(words) and all(w[:1].isupper() and w[1:].islower() for w in words if len(w) > 1)


def custom_case(value: str) -> bool:
    letters = [ch for ch in value if ch.isalpha()]
    if not letters:
        return False
    return not (value.upper() == value or value.lower() == value or title_like(value))


def adapt_case(original: str, replacement: str) -> str:
    has_alpha = any(ch.isalpha() for ch in original)
    if not has_alpha:
        return replacement
    if custom_case(replacement) and original.upper() != original:
        return replacement
    if original.upper() == original:
        return replacement.upper()
    if original.lower() == original:
        return replacement.lower()
    if title_like(original):
        return replacement.title() if replacement.lower() == replacement else replacement
    return replacement


def build_pattern(source: str, smart: bool) -> str:
    if not smart:
        return re.escape(source)

    tokens = source_tokens(source)
    if not tokens:
        return re.escape(source)

    # Allows "Acme S.A.", "ACME, S. A.", "Acme - S A", etc.
    sep = r"[\s\W_]*"
    body = sep.join(re.escape(token) for token in tokens)
    return rf"(?<![\w]){body}(?![\w])"


class ReplacementEngine:
    def __init__(self, rules: Iterable[Rule]):
        self.rules = list(rules)
        self.counts = [0 for _ in self.rules]
        self.visual_redactions = 0
        self.compiled: list[tuple[Rule, re.Pattern[str]]] = []

        for rule in self.rules:
            flags = 0 if rule.case_sensitive else re.IGNORECASE
            self.compiled.append((rule, re.compile(build_pattern(rule.source, rule.smart), flags)))

    def apply(self, text: str) -> str:
        for index, (rule, regex) in enumerate(self.compiled):
            def replace(match: re.Match[str]) -> str:
                self.counts[index] += 1
                if rule.preserve_case:
                    return adapt_case(match.group(0), rule.target)
                return rule.target

            text = regex.sub(replace, text)
            text = self.apply_fuzzy(text, index, rule)
        return text

    def apply_fuzzy(self, text: str, rule_index: int, rule: Rule) -> str:
        if rule.fuzzy_threshold <= 0:
            return text

        # Fuzzy matching is deliberately conservative and token-window based.
        # It catches small OCR/typing mistakes without trying to rewrite whole
        # paragraphs that merely look similar.
        target = "".join(normalize_token(token, case_sensitive=rule.case_sensitive) for token in source_tokens(rule.source))
        if len(target) < 5:
            return text

        replacement_norm = "".join(
            normalize_token(token, case_sensitive=rule.case_sensitive) for token in source_tokens(rule.target)
        )
        token_matches = list(TOKEN_RE.finditer(text))
        replacements: list[tuple[int, int, str]] = []
        used_ranges: list[tuple[int, int]] = []
        max_window = min(8, max(1, len(source_tokens(rule.source)) + 3))

        for start in range(len(token_matches)):
            collected = ""
            for end in range(start, min(len(token_matches), start + max_window)):
                collected += normalize_token(token_matches[end].group(0), case_sensitive=rule.case_sensitive)
                if len(collected) > max(len(target) + 6, int(len(target) * 1.45)):
                    break
                if collected == replacement_norm:
                    continue
                if similarity(collected, target) >= rule.fuzzy_threshold:
                    span = (token_matches[start].start(), token_matches[end].end())
                    if any(not (span[1] <= old[0] or span[0] >= old[1]) for old in used_ranges):
                        continue
                    original = text[span[0]:span[1]]
                    value = adapt_case(original, rule.target) if rule.preserve_case else rule.target
                    replacements.append((span[0], span[1], value))
                    used_ranges.append(span)
                    self.counts[rule_index] += 1
                    break

        for start, end, value in reversed(replacements):
            text = text[:start] + value + text[end:]
        return text

    def replacement_for_box(self, rule_index: int, original: str) -> str:
        rule = self.rules[rule_index]
        self.counts[rule_index] += 1
        if rule.preserve_case:
            return adapt_case(original, rule.target)
        return rule.target

    def report(self) -> list[dict[str, object]]:
        return [
            {
                "source": rule.source,
                "target": rule.target,
                "matches": self.counts[index],
                "smart": rule.smart,
                "case_sensitive": rule.case_sensitive,
                "fuzzy_threshold": rule.fuzzy_threshold,
            }
            for index, rule in enumerate(self.rules)
        ]


def escape_md_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", r"\|").replace("\r\n", "\n").replace("\n", "<br>")


def markdown_table(rows: list[list[object]], engine: ReplacementEngine) -> str:
    if not rows:
        return ""

    width = max(len(row) for row in rows)
    normalized = [list(row) + [""] * (width - len(row)) for row in rows]
    escaped = [[engine.apply(escape_md_cell(cell)) for cell in row] for row in normalized]

    header = escaped[0]
    body = escaped[1:]
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(["---"] * width) + " |",
    ]
    lines.extend("| " + " | ".join(row) + " |" for row in body)
    return "\n".join(lines)


def trim_empty_edges(rows: list[list[object]]) -> list[list[object]]:
    while rows and all(cell in (None, "") for cell in rows[-1]):
        rows.pop()
    if not rows:
        return []

    max_width = max(len(row) for row in rows)
    while max_width > 0:
        if any(len(row) >= max_width and row[max_width - 1] not in (None, "") for row in rows):
            break
        max_width -= 1
    return [row[:max_width] for row in rows]


def text_file_to_markdown(path: Path, engine: ReplacementEngine) -> str:
    text = path.read_text(encoding="utf-8", errors="replace")
    return engine.apply(text)


def csv_to_markdown(path: Path, engine: ReplacementEngine) -> str:
    delimiter = "\t" if path.suffix.lower() == ".tsv" else ","
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as handle:
        rows = list(csv.reader(handle, delimiter=delimiter))
    return f"# {path.name}\n\n" + markdown_table(rows, engine) + "\n"


def docx_to_markdown(path: Path, engine: ReplacementEngine) -> str:
    docx = require_import("docx", "python -m pip install python-docx")
    from docx.document import Document as DocxDocument
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    document = docx.Document(str(path))

    def blocks(parent):
        parent_elm = parent.element.body if isinstance(parent, DocxDocument) else parent._tc
        for child in parent_elm.iterchildren():
            if isinstance(child, CT_P):
                yield Paragraph(child, parent)
            elif isinstance(child, CT_Tbl):
                yield Table(child, parent)

    parts = [f"# {path.name}", ""]
    for block in blocks(document):
        if isinstance(block, Paragraph):
            text = block.text.strip()
            if text:
                parts.append(engine.apply(text))
                parts.append("")
        elif isinstance(block, Table):
            rows = [[cell.text.strip() for cell in row.cells] for row in block.rows]
            table_md = markdown_table(rows, engine)
            if table_md:
                parts.append(table_md)
                parts.append("")

    return "\n".join(parts).strip() + "\n"


def xlsx_to_markdown(path: Path, engine: ReplacementEngine) -> str:
    openpyxl = require_import("openpyxl", "python -m pip install openpyxl")
    workbook = openpyxl.load_workbook(str(path), data_only=True, read_only=True)
    parts = [f"# {path.name}", ""]

    for sheet in workbook.worksheets:
        rows = trim_empty_edges([list(row) for row in sheet.iter_rows(values_only=True)])
        parts.append(f"## {engine.apply(sheet.title)}")
        parts.append("")
        if rows:
            parts.append(markdown_table(rows, engine))
        else:
            parts.append("_Empty sheet._")
        parts.append("")

    return "\n".join(parts).strip() + "\n"


def render_pdf_page_to_pil(page, dpi: int):
    fitz = require_import("fitz", "python -m pip install pymupdf")
    Image = require_import("PIL.Image", "python -m pip install pillow")
    scale = dpi / 72
    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
    return Image.open(io.BytesIO(pix.tobytes("png")))


def ocr_image_to_text(image, lang: str) -> str:
    pytesseract = require_import("pytesseract", "python -m pip install pytesseract pillow")
    return pytesseract.image_to_string(image, lang=lang)


def pdf_to_markdown(path: Path, engine: ReplacementEngine, ocr: bool, force_ocr: bool, lang: str, dpi: int) -> str:
    fitz = require_import("fitz", "python -m pip install pymupdf")
    doc = fitz.open(str(path))
    parts = [f"# {path.name}", ""]

    for index, page in enumerate(doc, start=1):
        used_ocr = False
        text = "" if force_ocr else page.get_text("text").strip()
        if not text:
            if ocr or force_ocr:
                image = render_pdf_page_to_pil(page, dpi=dpi)
                text = ocr_image_to_text(image, lang=lang).strip()
                used_ocr = True
            else:
                text = "[No text layer found. Re-run with --ocr after installing Tesseract.]"

        parts.append(f"## Page {index}")
        if used_ocr:
            parts.append("")
            parts.append("<!-- OCR page: review accuracy before sharing. -->")
        parts.append("")
        parts.append(engine.apply(text))
        parts.append("")

    return "\n".join(parts).strip() + "\n"


def image_to_markdown(path: Path, engine: ReplacementEngine, lang: str) -> str:
    Image = require_import("PIL.Image", "python -m pip install pillow pytesseract")
    image = Image.open(str(path))
    text = ocr_image_to_text(image, lang=lang).strip()
    return f"# {path.name}\n\n<!-- OCR image: review accuracy before sharing. -->\n\n{engine.apply(text)}\n"


def to_markdown(path: Path, engine: ReplacementEngine, ocr: bool, force_ocr: bool, lang: str, dpi: int) -> str:
    ext = path.suffix.lower()
    if ext in TEXT_EXTS:
        return text_file_to_markdown(path, engine)
    if ext in CSV_EXTS:
        return csv_to_markdown(path, engine)
    if ext in DOCX_EXTS:
        return docx_to_markdown(path, engine)
    if ext in XLSX_EXTS:
        return xlsx_to_markdown(path, engine)
    if ext in PDF_EXTS:
        return pdf_to_markdown(path, engine, ocr=ocr, force_ocr=force_ocr, lang=lang, dpi=dpi)
    if ext in IMAGE_EXTS:
        return image_to_markdown(path, engine, lang=lang)
    die(f"unsupported input type '{ext}'")


def pdf_text_layer_boxes(page, dpi: int) -> list[WordBox]:
    scale = dpi / 72
    words = page.get_text("words")
    words.sort(key=lambda item: (item[5], item[6], item[7], item[1], item[0]))
    return [
        WordBox(
            text=str(word[4]),
            left=float(word[0]) * scale,
            top=float(word[1]) * scale,
            right=float(word[2]) * scale,
            bottom=float(word[3]) * scale,
            confidence=100.0,
        )
        for word in words
        if str(word[4]).strip()
    ]


def ocr_word_boxes(image, lang: str, min_conf: float) -> list[WordBox]:
    pytesseract = require_import("pytesseract", "python -m pip install pytesseract pillow")
    data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)
    boxes: list[WordBox] = []

    for index, text in enumerate(data.get("text", [])):
        text = str(text).strip()
        if not text:
            continue
        try:
            confidence = float(data["conf"][index])
        except (ValueError, KeyError):
            confidence = -1
        if confidence >= 0 and confidence < min_conf:
            continue
        left = float(data["left"][index])
        top = float(data["top"][index])
        width = float(data["width"][index])
        height = float(data["height"][index])
        boxes.append(WordBox(text=text, left=left, top=top, right=left + width, bottom=top + height, confidence=confidence))

    return boxes


def matching_box_groups(words: list[WordBox], rule: Rule) -> list[list[int]]:
    target = "".join(normalize_token(token, case_sensitive=rule.case_sensitive) for token in source_tokens(rule.source))
    if not target:
        return []

    normalized = [(index, normalize_token(word.text, case_sensitive=rule.case_sensitive)) for index, word in enumerate(words)]
    normalized = [(index, token) for index, token in normalized if token]
    matches: list[list[int]] = []
    used: set[int] = set()

    for start in range(len(normalized)):
        actual_indices: list[int] = []
        collected = ""
        for cursor in range(start, len(normalized)):
            word_index, token = normalized[cursor]
            if word_index in used:
                break
            collected += token
            actual_indices.append(word_index)
            is_match = collected == target
            if not is_match and len(target) >= 5 and rule.fuzzy_threshold > 0:
                is_match = similarity(collected, target) >= rule.fuzzy_threshold
            if is_match:
                matches.append(actual_indices)
                used.update(actual_indices)
                break
            if len(collected) > max(len(target) + 6, int(len(target) * 1.45)):
                break
            if rule.fuzzy_threshold <= 0 and not target.startswith(collected):
                break

    return matches


def parse_hex_color(value: str) -> tuple[int, int, int]:
    value = value.strip().lstrip("#")
    if len(value) != 6:
        die(f"invalid color '#{value}'. Use RRGGBB hex.")
    try:
        return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        die(f"invalid color '#{value}'. Use RRGGBB hex.")


def load_font(size: int):
    ImageFont = require_import("PIL.ImageFont", "python -m pip install pillow")
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def draw_fitted_text(draw, box: tuple[int, int, int, int], text: str, fill: tuple[int, int, int]) -> None:
    left, top, right, bottom = box
    max_width = max(1, right - left - 6)
    max_height = max(1, bottom - top - 4)
    size = max(8, int(max_height * 0.85))
    font = load_font(size)

    while size > 6:
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width and bbox[3] - bbox[1] <= max_height:
            break
        size -= 1
        font = load_font(size)

    draw.text((left + 3, top + 2), text, fill=fill, font=font)


def parse_region(value: str) -> tuple[int, int, int, int, str]:
    raw_box, _, label = value.partition("=")
    parts = [part.strip() for part in raw_box.split(",")]
    if len(parts) != 4:
        die("invalid --redact-region. Use x,y,width,height or x,y,width,height=Label")
    try:
        x, y, width, height = [int(float(part)) for part in parts]
    except ValueError:
        die("invalid --redact-region numbers. Use x,y,width,height")
    if width <= 0 or height <= 0:
        die("invalid --redact-region size. width/height must be positive")
    return x, y, x + width, y + height, label.strip() or "REDACTED"


def apply_visual_redactions(
    image,
    engine: ReplacementEngine,
    redact_header: float,
    header_text: str,
    regions: list[str] | None,
    fill_color: tuple[int, int, int],
    text_color: tuple[int, int, int],
):
    if not redact_header and not regions:
        return image
    ImageDraw = require_import("PIL.ImageDraw", "python -m pip install pillow")
    image = image.convert("RGB")
    draw = ImageDraw.Draw(image)

    if redact_header:
        if redact_header <= 1:
            header_height = int(image.height * redact_header)
        else:
            header_height = int(redact_header)
        header_height = max(1, min(image.height, header_height))
        draw.rectangle((0, 0, image.width, header_height), fill=fill_color)
        if header_text:
            draw_fitted_text(draw, (8, 4, image.width - 8, header_height - 4), header_text, text_color)
        engine.visual_redactions += 1

    for region in regions or []:
        left, top, right, bottom, label = parse_region(region)
        left = max(0, min(image.width, left))
        right = max(0, min(image.width, right))
        top = max(0, min(image.height, top))
        bottom = max(0, min(image.height, bottom))
        draw.rectangle((left, top, right, bottom), fill=fill_color)
        if label:
            draw_fitted_text(draw, (left, top, right, bottom), label, text_color)
        engine.visual_redactions += 1

    return image


def redact_image_with_boxes(
    image,
    words: list[WordBox],
    engine: ReplacementEngine,
    fill_color: tuple[int, int, int],
    text_color: tuple[int, int, int],
):
    ImageDraw = require_import("PIL.ImageDraw", "python -m pip install pillow")
    image = image.convert("RGB")
    draw = ImageDraw.Draw(image)

    for rule_index, rule in enumerate(engine.rules):
        for group in matching_box_groups(words, rule):
            selected = [words[index] for index in group]
            original = " ".join(word.text for word in selected)
            replacement = engine.replacement_for_box(rule_index, original)
            left = int(max(0, min(word.left for word in selected) - 3))
            top = int(max(0, min(word.top for word in selected) - 2))
            right = int(min(image.width, max(word.right for word in selected) + 3))
            bottom = int(min(image.height, max(word.bottom for word in selected) + 2))
            draw.rectangle((left, top, right, bottom), fill=fill_color)
            draw_fitted_text(draw, (left, top, right, bottom), replacement, text_color)

    return image


def render_images(
    path: Path,
    output_dir: Path,
    engine: ReplacementEngine,
    ocr: bool,
    force_ocr: bool,
    lang: str,
    dpi: int,
    min_conf: float,
    image_fill: str,
    image_text: str,
    redact_header: float,
    header_text: str,
    redact_regions: list[str] | None,
    progress: bool = False,
) -> list[Path]:
    ext = path.suffix.lower()
    fill_color = parse_hex_color(image_fill)
    text_color = parse_hex_color(image_text)
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    if ext in PDF_EXTS:
        fitz = require_import("fitz", "python -m pip install pymupdf")
        doc = fitz.open(str(path))
        for index, page in enumerate(doc, start=1):
            image = render_pdf_page_to_pil(page, dpi=dpi)
            boxes = [] if force_ocr else pdf_text_layer_boxes(page, dpi=dpi)
            if not boxes:
                if not ocr and not force_ocr:
                    die("page has no text boxes. Re-run with --ocr for scanned PDFs.")
                boxes = ocr_word_boxes(image, lang=lang, min_conf=min_conf)
            redacted = redact_image_with_boxes(image, boxes, engine, fill_color, text_color)
            redacted = apply_visual_redactions(redacted, engine, redact_header, header_text, redact_regions, fill_color, text_color)
            out_path = output_dir / f"{path.stem}-page-{index:03d}.png"
            redacted.save(str(out_path))
            written.append(out_path)
            if progress:
                print(f"  page {index}: wrote {out_path.name}", file=sys.stderr)
        return written

    if ext in IMAGE_EXTS:
        Image = require_import("PIL.Image", "python -m pip install pillow pytesseract")
        image = Image.open(str(path))
        boxes = ocr_word_boxes(image, lang=lang, min_conf=min_conf)
        redacted = redact_image_with_boxes(image, boxes, engine, fill_color, text_color)
        redacted = apply_visual_redactions(redacted, engine, redact_header, header_text, redact_regions, fill_color, text_color)
        out_path = output_dir / f"{path.stem}-nubli.png"
        redacted.save(str(out_path))
        written.append(out_path)
        if progress:
            print(f"  image: wrote {out_path.name}", file=sys.stderr)
        return written

    die("--format images only supports PDF or image inputs")


def parse_rule_text(raw: str, case_sensitive: bool, smart: bool, preserve_case: bool, fuzzy_threshold: float) -> Rule:
    if "=" not in raw:
        die(f"invalid --replace '{raw}'. Use: 'private=public'")
    source, target = raw.split("=", 1)
    source = source.strip()
    target = target.strip()
    if not source:
        die("replacement source cannot be empty")
    return Rule(source=source, target=target, case_sensitive=case_sensitive, smart=smart, preserve_case=preserve_case, fuzzy_threshold=fuzzy_threshold)


def load_rules(args: argparse.Namespace) -> list[Rule]:
    rules: list[Rule] = []

    for raw in args.replace or []:
        rules.append(
            parse_rule_text(
                raw,
                case_sensitive=args.case_sensitive,
                smart=not args.exact,
                preserve_case=not args.no_preserve_case,
                fuzzy_threshold=0.0 if args.no_fuzzy else args.fuzzy_threshold,
            )
        )

    if args.rules:
        data = json.loads(Path(args.rules).read_text(encoding="utf-8"))
        items = data.items() if isinstance(data, dict) else data
        for item in items:
            if isinstance(item, tuple):
                source, target = item
                item_options = {}
            else:
                source = item.get("source", item.get("from"))
                target = item.get("target", item.get("to"))
                item_options = item
            if not source:
                die("every JSON rule needs 'source'/'from'")
            if target is None:
                die("every JSON rule needs 'target'/'to'")
            rules.append(
                Rule(
                    source=str(source),
                    target=str(target),
                    case_sensitive=bool(item_options.get("case_sensitive", args.case_sensitive)),
                    smart=bool(item_options.get("smart", not args.exact)),
                    preserve_case=bool(item_options.get("preserve_case", not args.no_preserve_case)),
                    fuzzy_threshold=float(item_options.get("fuzzy_threshold", 0.0 if args.no_fuzzy else args.fuzzy_threshold)),
                )
            )

    if not rules and not (args.redact_header or args.redact_region):
        die("add at least one --replace rule or --rules file")
    return rules


def resolve_text_output(input_path: Path, output: str | None, suffix: str) -> Path:
    if output is None:
        return input_path.with_name(f"{input_path.stem}.nubli{suffix}")
    out = Path(output)
    if out.suffix:
        return out
    return out / f"{input_path.stem}.nubli{suffix}"


def resolve_image_output(input_path: Path, output: str | None) -> Path:
    if output is None:
        return input_path.with_name(f"{input_path.stem}.nubli-images")
    return Path(output)


NUBLI_BANNER = """
┌─ Nubli ───────────────────────────────┐
│ local-first document anonymizer        │
└───────────────────────────────────────┘
"""

NUBLI_PET = "  /ᐠ｡ꞈ｡ᐟ\\  redact before you chat"


def print_install_help() -> None:
    print(NUBLI_BANNER.rstrip())
    print("Install / download Nubli CLI\n")
    print("If you already have this repo/folder:")
    print("  cd nubli")
    print("  ./install.sh")
    print("\nAfter install:")
    print("  nubli")
    print("  nubli --help")
    print("\nFor a future GitHub release:")
    print("  git clone <repo-url> nubli")
    print("  cd nubli")
    print("  ./install.sh")
    print("\nHide installer mascot:")
    print("  NUBLI_NO_PET=1 ./install.sh")
    print("  ./install.sh --no-pet")


def ui(args: argparse.Namespace, message: str = "") -> None:
    if not getattr(args, "quiet", False):
        print(message, file=sys.stderr)


def show_run_header(args: argparse.Namespace, input_path: Path, menu_opened: bool) -> None:
    if args.quiet:
        return
    if not menu_opened:
        print(NUBLI_BANNER.rstrip(), file=sys.stderr)
        if not args.no_pet:
            print(NUBLI_PET, file=sys.stderr)
    print("nubli: private docs stay local", file=sys.stderr)
    print(f"[1/5] input   : {input_path}", file=sys.stderr)
    print(f"      format  : {args.format}", file=sys.stderr)
    if args.output:
        print(f"      output  : {args.output}", file=sys.stderr)
    if args.ocr or args.force_ocr:
        print(f"      OCR     : {'force' if args.force_ocr else 'fallback'} ({args.ocr_lang})", file=sys.stderr)


def show_rule_summary(args: argparse.Namespace, rules: list[Rule]) -> None:
    if args.quiet:
        return
    print(f"[2/5] rules   : {len(rules)} replacement rule(s)", file=sys.stderr)
    if args.rules:
        print(f"      file    : {args.rules}", file=sys.stderr)
    if rules:
        print(f"      fuzzy   : {'off' if args.no_fuzzy else args.fuzzy_threshold}", file=sys.stderr)
    if args.redact_header:
        print(f"      header  : redact {args.redact_header}", file=sys.stderr)
    for region in args.redact_region or []:
        print(f"      region  : {region}", file=sys.stderr)


def show_match_summary(args: argparse.Namespace, engine: ReplacementEngine) -> None:
    if args.quiet:
        return
    print("[4/5] matches :", file=sys.stderr)
    if not engine.rules:
        print("      no text rules; visual redaction only", file=sys.stderr)
    for rule, count in zip(engine.rules, engine.counts):
        print(f"      {rule.source!r} -> {rule.target!r}: {count}", file=sys.stderr)
    if engine.visual_redactions:
        print(f"      visual redactions: {engine.visual_redactions}", file=sys.stderr)


def show_done(args: argparse.Namespace, paths: list[Path], report_path: Path | None = None) -> None:
    if args.quiet:
        return
    print("[5/5] done    : anonymized output ready", file=sys.stderr)
    for path in paths:
        print(f"      output  : {path}", file=sys.stderr)
    if report_path:
        print(f"      report  : {report_path}", file=sys.stderr)


def interactive_menu() -> list[str]:
    print(NUBLI_BANNER.rstrip())
    print(NUBLI_PET)
    print("Private docs stay local. Choose an action:\n")
    print("  1) Anonymize a file")
    print("  2) Show install/download help")
    print("  3) Show quick examples")
    print("  4) Exit")
    choice = input("\nSelect [1-4] (default: 1): ").strip() or "1"

    if choice == "2":
        print()
        print_install_help()
        raise SystemExit(0)
    if choice == "3":
        print("\nQuick examples:\n")
        print('  nubli document.pdf --replace "Acme S A=Demo Company" -o out.md')
        print('  nubli document.pdf --format images --redact-header 0.12 -o out-pages')
        print('  nubli document.docx --rules rules.json --strict-pii -o out.md')
        raise SystemExit(0)
    if choice == "4":
        raise SystemExit(0)

    print("\nStep 1 — Input")
    input_path = input("File to anonymize: ").strip().strip('"')
    if not input_path:
        die("input file is required")

    print("\nStep 2 — Output format")
    print("  1) markdown  (best for AI/chat)")
    print("  2) text")
    print("  3) images    (best for PDFs with logos/headers)")
    fmt_choice = input("Select [1-3] (default: 1): ").strip() or "1"
    fmt = {"1": "markdown", "2": "text", "3": "images"}.get(fmt_choice, fmt_choice.lower())
    if fmt not in {"markdown", "text", "images"}:
        fmt = "markdown"

    print("\nStep 3 — Output path")
    output_path = input("Output file/folder (blank = auto): ").strip().strip('"')

    argv = [input_path, "--format", fmt]
    if output_path:
        argv.extend(["-o", output_path])

    print("\nStep 4 — Replacement rules")
    rules_path = input("Rules JSON path (blank = type rules manually): ").strip().strip('"')
    if rules_path:
        argv.extend(["--rules", rules_path])

    print("Add rules like: Acme S A=Demo Company")
    print("Leave blank when done.")
    while True:
        rule = input("Rule (blank to finish): ").strip()
        if not rule:
            break
        argv.extend(["--replace", rule])

    print("\nStep 5 — Safety")
    if prompt_yes_no("Require every rule to match?", default=True):
        argv.append("--require-all-rules")
    if prompt_yes_no("Block output if possible emails/phones/names remain?", default=True):
        argv.append("--strict-pii")

    if fmt == "images":
        print("\nStep 6 — PDF/image visual options")
        if prompt_yes_no("Use OCR fallback for scanned/image-only pages?", default=True):
            argv.append("--ocr")
        if prompt_yes_no("Redact top header area too? Useful for logos/company names.", default=False):
            pct = input("Header height percent (default 0.12): ").strip() or "0.12"
            argv.extend(["--redact-header", pct])
            label = input("Header replacement text (default REDACTED): ").strip()
            if label:
                argv.extend(["--header-text", label])
        while prompt_yes_no("Add a manual logo/region redaction?", default=False):
            region = input("Region x,y,width,height=Label: ").strip()
            if region:
                argv.extend(["--redact-region", region])

    print("\nRunning Nubli...\n")

    return argv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nubli",
        description="Local-first anonymizer for PDF, image, DOCX, XLSX, CSV and Markdown files.",
    )
    parser.add_argument("input", nargs="?", help="Input file path. Omit to open the interactive menu.")
    parser.add_argument("--help-install", action="store_true", help="Show CLI install/download instructions")
    parser.add_argument("-o", "--output", help="Output file or folder")
    parser.add_argument("--format", choices=["markdown", "text", "images"], default="markdown", help="Output format")
    parser.add_argument("--replace", action="append", help='Replacement rule: "Private Name=Public Name"')
    parser.add_argument("--rules", help="JSON rules file. Accepts object or list of {from/source,to/target}.")
    parser.add_argument("--ocr", action="store_true", help="Use local OCR fallback for scanned PDFs/images")
    parser.add_argument("--force-ocr", action="store_true", help="Ignore PDF text layer and OCR every PDF page")
    parser.add_argument("--ocr-lang", default="eng+spa", help="Tesseract languages, e.g. eng, spa, eng+spa")
    parser.add_argument("--dpi", type=int, default=220, help="PDF render DPI for OCR/image output")
    parser.add_argument("--min-ocr-conf", type=float, default=45, help="Minimum OCR word confidence for image redaction")
    parser.add_argument("--case-sensitive", action="store_true", help="Make CLI --replace rules case-sensitive")
    parser.add_argument("--exact", action="store_true", help="Use literal matching instead of smart punctuation/space matching")
    parser.add_argument("--fuzzy-threshold", type=float, default=0.88, help="Fuzzy typo-match threshold from 0.0 to 1.0")
    parser.add_argument("--no-fuzzy", action="store_true", help="Disable fuzzy typo matching")
    parser.add_argument("--no-preserve-case", action="store_true", help="Always use target exactly as typed")
    parser.add_argument("--report", help="Write JSON replacement report")
    parser.add_argument("--quiet", action="store_true", help="Print only output paths/errors; hides banner and progress UI")
    parser.add_argument("--no-pet", action="store_true", help="Hide the Nubli cat mascot but keep progress UI")
    parser.add_argument("--require-all-rules", action="store_true", help="Fail/ask if any replacement rule had zero matches")
    parser.add_argument("--strict-pii", action="store_true", help="Fail/ask if output still looks like it contains emails, phones, IDs or names")
    parser.add_argument("--no-suggest-pii", dest="suggest_pii", action="store_false", help="Disable automatic sensitive-data suggestions")
    parser.set_defaults(suggest_pii=True, interactive=True)
    parser.add_argument("--no-interactive", dest="interactive", action="store_false", help="Never ask questions; fail closed instead")
    parser.add_argument(
        "--allow-zero-replacements",
        action="store_true",
        help="Allow output even when no replacement rule matched. By default Nubli fails closed to avoid sharing un-anonymized files.",
    )
    parser.add_argument("--image-fill", default="#ffffff", help="Redaction fill color for image output")
    parser.add_argument("--image-text", default="#111111", help="Replacement text color for image output")
    parser.add_argument("--redact-header", type=float, default=0.0, help="For image output, redact the top header by percent (0.12) or pixels (160)")
    parser.add_argument("--header-text", default="REDACTED", help="Text to write inside --redact-header area")
    parser.add_argument("--redact-region", action="append", help="For image output, redact x,y,width,height or x,y,width,height=Label. Repeatable for logos/seals.")
    return parser


def main(argv: list[str] | None = None) -> int:
    raw_argv = sys.argv[1:] if argv is None else argv
    menu_opened = False
    if not raw_argv:
        menu_opened = True
        raw_argv = interactive_menu()

    args = build_parser().parse_args(raw_argv)
    if args.help_install:
        print_install_help()
        return 0

    if not args.input:
        menu_opened = True
        raw_argv = interactive_menu()
        args = build_parser().parse_args(raw_argv)
        if args.help_install:
            print_install_help()
            return 0

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        die(f"input file does not exist: {input_path}")

    if not 0 <= args.fuzzy_threshold <= 1:
        die("--fuzzy-threshold must be between 0.0 and 1.0")

    show_run_header(args, input_path, menu_opened)
    rules = load_rules(args)
    show_rule_summary(args, rules)

    engine = ReplacementEngine(rules)
    suggestions: list[Suggestion] = []
    output_paths: list[Path] = []

    if args.format in {"markdown", "text"}:
        suffix = ".md" if args.format == "markdown" else ".txt"
        out_path = resolve_text_output(input_path, args.output, suffix).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        ui(args, "[3/5] process : extracting text and applying replacements")
        content = to_markdown(
            input_path,
            engine,
            ocr=args.ocr,
            force_ocr=args.force_ocr,
            lang=args.ocr_lang,
            dpi=args.dpi,
        )
        suggestions = suggest_sensitive_content(content) if args.suggest_pii else []
        show_match_summary(args, engine)
        enforce_safety(args, engine, suggestions)
        out_path.write_text(content, encoding="utf-8")
        output_paths.append(out_path)
        if args.quiet:
            print(out_path)
    else:
        output_dir = resolve_image_output(input_path, args.output).resolve()
        ui(args, "[3/5] process : rendering pages and applying visual redactions")
        written = render_images(
            input_path,
            output_dir,
            engine,
            ocr=args.ocr,
            force_ocr=args.force_ocr,
            lang=args.ocr_lang,
            dpi=args.dpi,
            min_conf=args.min_ocr_conf,
            image_fill=args.image_fill,
            image_text=args.image_text,
            redact_header=args.redact_header,
            header_text=args.header_text,
            redact_regions=args.redact_region,
            progress=not args.quiet,
        )
        show_match_summary(args, engine)
        enforce_safety(args, engine, suggestions, written=written)
        for path in written:
            output_paths.append(path)
            if args.quiet:
                print(path)

    report_path: Path | None = None
    if args.report:
        report_path = Path(args.report).expanduser().resolve()
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report = {
            "rules": engine.report(),
            "total_rule_matches": sum(engine.counts),
            "visual_redactions": engine.visual_redactions,
            "suggestions": [suggestion.__dict__ for suggestion in suggestions],
        }
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if args.quiet:
            print(report_path)

    show_done(args, output_paths, report_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
