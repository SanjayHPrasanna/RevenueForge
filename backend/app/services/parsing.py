"""Document parsing: turns PDF / DOCX / XLSX / CSV / PPTX / TXT into an ordered list of
blocks, each tagged with the page it came from and the section heading it sits under.

Every downstream stage (requirement extraction, onboarding, matching) works on these
blocks, so traceability back to a source page is preserved end to end.
"""
from __future__ import annotations

import csv
import io
import re
from collections import Counter
from dataclasses import dataclass, field, asdict
from pathlib import Path

BULLET_RE = re.compile(r"^\s*(?:[•●▪◦‣❖➢►■□\-–—*·]|\(?[a-zA-Z]\)|\(?[ivxIVX]{1,4}\)|\d{1,2}[.)](?!\d))\s*")
NUMBERED_HEADING_RE = re.compile(r"^\s*(?:section\s*[–-]?\s*\d+|part\s+\d+|\d+(?:\.\d+){0,3}\.?)\s+[A-Z][^.]{2,90}$", re.I)
REQ_ID_RE = re.compile(r"^[A-Z]{1,5}[-_ ]?\d{1,3}(?:\.\d+)?$")
WORDS_PER_PAGE = 450


@dataclass
class Block:
    idx: int
    page: int
    kind: str  # heading | para | bullet | table_row
    text: str
    section: str = ""
    ref: str = ""  # explicit requirement id from the document, e.g. BB-02

    def to_dict(self):
        return asdict(self)


@dataclass
class ParsedDocument:
    filename: str
    pages: int
    blocks: list[Block] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)  # raw tables (for spreadsheets)

    @property
    def text(self) -> str:
        return "\n".join(b.text for b in self.blocks)

    def page_texts(self) -> dict[int, str]:
        out: dict[int, list[str]] = {}
        for b in self.blocks:
            out.setdefault(b.page, []).append(b.text)
        return {p: "\n".join(t) for p, t in out.items()}


def _clean(s: str) -> str:
    s = s.replace("‑", "-").replace(" ", " ").replace("​", "")
    s = re.sub(r"[ \t]+", " ", s)
    return s.strip()


def _norm_for_repeat(s: str) -> str:
    return re.sub(r"\d+", "#", s.lower()).strip()


def _is_heading_text(t: str) -> bool:
    t = t.strip()
    if not t or len(t) > 110 or t.endswith((".", ",", ";")):
        return False
    if NUMBERED_HEADING_RE.match(t):
        return True
    words = t.split()
    return 1 <= len(words) <= 9 and t[0].isupper() and t.endswith(":") is False and sum(w[0].isupper() for w in words if w[0].isalpha()) >= max(1, len(words) * 0.6)


# --------------------------------------------------------------------------- PDF
def _table_rows(page, t) -> list[list[str]]:
    """Each cell's text, read word by word inside the cell's box. PyMuPDF's own table text drops the spaces between words
    in some PDFs ("Contractperiod | 9monthsbuild+24monthssupport"), which broke dates, terms and client-name masking."""
    import pymupdf

    try:
        fallback = t.extract()
    except Exception:
        fallback = []
    out = []
    for i, row in enumerate(t.rows):
        cells = []
        for j, box in enumerate(row.cells):
            text = ""
            if box is not None:
                words = page.get_text("words", clip=pymupdf.Rect(box))
                lines: dict[tuple, list] = {}
                for w in sorted(words, key=lambda w: (w[5], w[6], w[7])):
                    lines.setdefault((w[5], w[6]), []).append(w[4])
                text = "\n".join(" ".join(ws) for ws in lines.values())
            if not text.strip():
                try:
                    text = fallback[i][j] or ""
                except (IndexError, TypeError):
                    text = ""
            cells.append(_clean(text))
        out.append(cells)
    return out


def parse_pdf(data: bytes, filename: str) -> ParsedDocument:
    import pymupdf

    doc = pymupdf.open(stream=data, filetype="pdf")
    n_pages = len(doc)
    page_lines: list[list[dict]] = []
    page_tables: list[list[tuple[float, list[list[str]]]]] = []

    for pno, page in enumerate(doc):
        height = page.rect.height
        tables = []
        rects = []
        try:
            for t in page.find_tables().tables:
                rows = _table_rows(page, t)
                tables.append((t.bbox[1], rows))
                rects.append(pymupdf.Rect(t.bbox))
        except Exception:
            pass
        lines = []
        d = page.get_text("dict")
        for b in d["blocks"]:
            for ln in b.get("lines", []):
                text = _clean("".join(sp["text"] for sp in ln["spans"]))
                if not text:
                    continue
                bbox = pymupdf.Rect(ln["bbox"])
                if any(r.intersects(bbox) and (r & bbox).get_area() > 0.5 * bbox.get_area() for r in rects):
                    continue
                spans = [sp for sp in ln["spans"] if sp["text"].strip()]
                size = max((sp["size"] for sp in spans), default=10)
                bold = all(("Bold" in sp["font"] or sp["flags"] & 16) for sp in spans) if spans else False
                lines.append({"text": text, "x": bbox.x0, "y": bbox.y0, "y1": bbox.y1, "size": size,
                              "bold": bold, "margin": bbox.y0 < height * 0.09 or bbox.y1 > height * 0.88})
        # Sort top-to-bottom, treating lines within 3pt vertically as the same row (bullet glyph + text).
        lines.sort(key=lambda l: l["y"])
        rows_, cur_row = [], []
        for l in lines:
            if cur_row and l["y"] > min(x["y1"] for x in cur_row) - 4:
                rows_.append(cur_row)
                cur_row = []
            cur_row.append(l)
        if cur_row:
            rows_.append(cur_row)
        lines = []
        for r in rows_:
            top = min(x["y"] for x in r)
            for l in sorted(r, key=lambda l: l["x"]):
                l["oy"] = top + l["x"] / 10000
                lines.append(l)
        page_lines.append(lines)
        page_tables.append(tables)

    # Remove running headers / footers: margin lines that repeat on many pages.
    counts = Counter()
    for lines in page_lines:
        for k in {_norm_for_repeat(l["text"]) for l in lines if l["margin"]}:
            counts[k] += 1
    table_counts = Counter()
    for tables in page_tables:
        for _, rows in tables:
            for r in rows:
                table_counts[_norm_for_repeat(" ".join(c for c in r if c))] += 1
    thresh = max(2, int(n_pages * 0.4))
    repeated = {k for k, c in counts.items() if c >= thresh}
    repeated_rows = {k for k, c in table_counts.items() if c >= thresh}

    sizes = Counter(round(l["size"]) for lines in page_lines for l in lines)
    body_size = sizes.most_common(1)[0][0] if sizes else 11

    blocks: list[Block] = []
    section = ""
    for pno, (lines, tables) in enumerate(zip(page_lines, page_tables), start=1):
        items = [("line", l["oy"], l) for l in lines if not (l["margin"] and _norm_for_repeat(l["text"]) in repeated)]
        items += [("table", y, rows) for y, rows in tables]
        items.sort(key=lambda it: it[1])
        cur: dict | None = None
        prev_line = None
        last_head = None

        def flush():
            nonlocal cur
            if cur and cur["text"].strip():
                t = _clean(cur["text"])
                if len(t) > 1:
                    blocks.append(Block(len(blocks), pno, cur["kind"], t, section))
            cur = None

        for kind, _, obj in items:
            if kind == "table":
                flush()
                last_head = None
                last: dict[int, str] = {}
                header = None
                for r in obj:
                    key = _norm_for_repeat(" ".join(c for c in r if c))
                    if not key or key in repeated_rows:
                        continue
                    first_val = next((i for i, c in enumerate(r) if c), len(r))
                    cells = []
                    for i, c in enumerate(r):
                        if c:
                            cells.append(c.replace("\n", " ").strip())
                        elif i < first_val and header is not None and last.get(i):
                            cells.append(last[i])  # vertically merged leading cell
                    if header is not None:
                        for i, c in enumerate(r):
                            if c:
                                last[i] = c.replace("\n", " ").strip()
                            elif c is None and i >= first_val:
                                pass
                    if not cells:
                        continue
                    if header is None and all(len(c) < 40 for c in cells):
                        header = cells
                        blocks.append(Block(len(blocks), pno, "table_row", " | ".join(cells), section, "header"))
                        continue
                    header = header or []
                    ref = cells[0] if REQ_ID_RE.match(cells[0]) else ""
                    text = " | ".join(cells[1:] if ref else cells)
                    blocks.append(Block(len(blocks), pno, "table_row", text, section, ref))
                prev_line = None
                continue

            l = obj
            t = l["text"]
            is_heading = (l["bold"] and _is_heading_text(t)) or (l["size"] >= body_size + 1.5 and len(t) < 110) \
                or (NUMBERED_HEADING_RE.match(t) and len(t) < 80 and not t.endswith("."))
            numbered_bold = l["bold"] and len(t) < 90 and not t.endswith((".", ",", ";")) and re.match(r"^\d{1,2}[.)]\s+[A-Z]", t)
            if is_heading and (not BULLET_RE.match(t) or numbered_bold):
                flush()
                # A long title or heading wraps onto a second line in the same size, straight below: join it back
                # ("Digital Patient Engagement and" + "Integration Platform") instead of keeping only the first line.
                lh = last_head
                if lh is not None and blocks and blocks[-1].idx == lh["idx"] and abs(lh["size"] - l["size"]) < 0.6 \
                        and -l["size"] * 0.5 <= l["y"] - lh["y1"] < l["size"] * 0.7 and not NUMBERED_HEADING_RE.match(t) and len(blocks[-1].text) + len(t) < 200:
                    blocks[-1].text = f"{blocks[-1].text} {t}"
                    blocks[-1].section = section = blocks[-1].text.rstrip(":")
                    last_head = {**lh, "y1": l["y1"]}
                    prev_line = None
                    continue
                section = t.rstrip(":")
                blocks.append(Block(len(blocks), pno, "heading", t, section))
                last_head = {"idx": blocks[-1].idx, "size": l["size"], "y1": l["y1"]}
                prev_line = None
                continue
            last_head = None
            bullet_only = BULLET_RE.fullmatch(t + " ") is not None and len(t) <= 4
            if bullet_only:
                flush()
                cur = {"kind": "bullet", "text": ""}
                prev_line = l
                continue
            m = BULLET_RE.match(t)
            if m and m.end() < len(t) and (len(t) > m.end() + 3):
                flush()
                cur = {"kind": "bullet", "text": t[m.end():]}
                prev_line = l
                continue
            gap_break = prev_line is not None and (l["y"] - prev_line["y1"]) > max(8, l["size"] * 0.9)
            ends_sentence = prev_line is not None and prev_line["text"].rstrip().endswith((".", ":", ";"))
            dedent = prev_line is not None and cur is not None and cur["kind"] == "bullet" and l["x"] < prev_line["x"] - 12
            if cur is None or gap_break or dedent or (ends_sentence and l["x"] < (prev_line["x"] if prev_line else 0) - 12):
                flush()
                cur = {"kind": "para", "text": t}
            else:
                cur["text"] += " " + t
            prev_line = l
        flush()
    return ParsedDocument(filename, n_pages, _postprocess(blocks))


TOC_RE = re.compile(r"\.{5,}|…{3,}")


def _postprocess(blocks: list[Block]) -> list[Block]:
    """Drop table-of-contents lines and stitch paragraphs broken across lines/pages."""
    out: list[Block] = []
    for b in blocks:
        if TOC_RE.search(b.text) or re.fullmatch(r"(table of )?contents?", b.text.strip().lower()):
            continue
        prev = out[-1] if out else None
        if (prev is not None and b.kind in ("para", "bullet") and prev.kind in ("para", "bullet")
                and b.text[:1].islower() and not prev.text.rstrip().endswith((".", ":", ";", "?", "!"))):
            prev.text = f"{prev.text} {b.text}"
            continue
        out.append(b)
    # Short label paragraphs right before a table act as sub-headings.
    for i, b in enumerate(out[:-1]):
        if b.kind == "para" and len(b.text) < 70 and not b.text.endswith(".") and out[i + 1].kind == "table_row":
            b.kind = "heading"
    section = ""
    for i, b in enumerate(out):
        b.idx = i
        if b.kind == "heading":
            section = b.text.rstrip(":")
        b.section = section
    return out


# --------------------------------------------------------------------------- DOCX
def parse_docx(data: bytes, filename: str) -> ParsedDocument:
    import docx
    from docx.oxml.ns import qn

    d = docx.Document(io.BytesIO(data))
    body = d.element.body
    blocks: list[Block] = []
    section = ""
    page = 1
    words = 0
    has_rendered_breaks = b"lastRenderedPageBreak" in data or True  # checked per paragraph

    def page_for(el) -> None:
        nonlocal page, words
        xml_breaks = len(el.findall(".//" + qn("w:lastRenderedPageBreak")))
        hard = sum(1 for br in el.findall(".//" + qn("w:br")) if br.get(qn("w:type")) == "page")
        page += xml_breaks + hard

    from docx.table import Table
    from docx.text.paragraph import Paragraph

    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            p = Paragraph(child, d)
            page_for(child)
            text = _clean(p.text)
            if not text:
                continue
            style = (p.style.name if p.style is not None else "") or ""
            is_list = child.find(".//" + qn("w:numPr")) is not None or "List" in style
            runs = [r for r in p.runs if r.text.strip()]
            bold = bool(runs) and all(r.bold or (r.style is not None and r.style.font.bold) for r in runs)
            if style.lower().startswith(("heading", "title")) or (bold and _is_heading_text(text) and not is_list) \
                    or (NUMBERED_HEADING_RE.match(text) and len(text) < 80 and not text.endswith(".")):
                section = text.rstrip(":")
                blocks.append(Block(len(blocks), page, "heading", text, section))
            elif is_list or BULLET_RE.match(text):
                m = BULLET_RE.match(text)
                blocks.append(Block(len(blocks), page, "bullet", text[m.end():] if m and m.end() < len(text) else text, section))
            else:
                # Short line ending with ':' acts as a sub-heading for following bullets.
                if text.endswith(":") and len(text) < 90:
                    section = text.rstrip(":")
                    blocks.append(Block(len(blocks), page, "heading", text, section))
                else:
                    blocks.append(Block(len(blocks), page, "para", text, section))
            words += len(text.split())
        elif child.tag == qn("w:tbl"):
            t = Table(child, d)
            page_for(child)
            header_done = False
            for row in t.rows:
                cells = []
                seen = set()
                for c in row.cells:
                    if id(c._tc) in seen:
                        continue
                    seen.add(id(c._tc))
                    cells.append(_clean(c.text.replace("\n", " ")))
                cells = [c for c in cells if c]
                if not cells:
                    continue
                if not header_done and all(len(c) < 40 for c in cells):
                    header_done = True
                    blocks.append(Block(len(blocks), page, "table_row", " | ".join(cells), section, "header"))
                    continue
                header_done = True
                ref = cells[0] if REQ_ID_RE.match(cells[0]) else ""
                text = " | ".join(cells[1:] if ref else cells)
                blocks.append(Block(len(blocks), page, "table_row", text, section, ref))
                words += len(text.split())

    # If Word never rendered page breaks (generated files), estimate from word count.
    if page == 1 and words > WORDS_PER_PAGE:
        running = 0
        for b in blocks:
            running += len(b.text.split())
            b.page = 1 + running // WORDS_PER_PAGE
        page = blocks[-1].page if blocks else 1
    return ParsedDocument(filename, max(page, 1), _postprocess(blocks))


# --------------------------------------------------------------------------- spreadsheets
def parse_xlsx(data: bytes, filename: str) -> ParsedDocument:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    tables, blocks = [], []
    for ws in wb.worksheets:
        rows = []
        for r in ws.iter_rows(values_only=True):
            vals = ["" if v is None else str(v).strip() for v in r]
            while vals and vals[-1] == "":
                vals.pop()
            if any(vals):
                rows.append(vals)
        if rows:
            tables.append(rows)
            blocks.append(Block(len(blocks), len(tables), "heading", ws.title, ws.title))
            for r in rows:
                blocks.append(Block(len(blocks), len(tables), "table_row", " | ".join(c for c in r if c), ws.title))
    return ParsedDocument(filename, len(tables), blocks, tables)


def parse_csv(data: bytes, filename: str) -> ParsedDocument:
    text = data.decode("utf-8-sig", errors="replace")
    rows = [[c.strip() for c in r] for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    blocks = [Block(i, 1, "table_row", " | ".join(r), "") for i, r in enumerate(rows)]
    return ParsedDocument(filename, 1, blocks, [rows])


def parse_pptx(data: bytes, filename: str) -> ParsedDocument:
    from pptx import Presentation

    prs = Presentation(io.BytesIO(data))
    blocks = []
    for sno, slide in enumerate(prs.slides, start=1):
        title = ""
        if slide.shapes.title is not None and slide.shapes.title.has_text_frame:
            title = _clean(slide.shapes.title.text_frame.text)
            if title:
                blocks.append(Block(len(blocks), sno, "heading", title, title))
        for shape in slide.shapes:
            if shape == slide.shapes.title:
                continue
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    t = _clean("".join(r.text for r in para.runs))
                    if t:
                        blocks.append(Block(len(blocks), sno, "bullet" if para.level > 0 or len(t) < 160 else "para", t, title))
            if getattr(shape, "has_table", False) and shape.has_table:
                for row in shape.table.rows:
                    cells = [_clean(c.text) for c in row.cells if _clean(c.text)]
                    if cells:
                        blocks.append(Block(len(blocks), sno, "table_row", " | ".join(cells), title))
    return ParsedDocument(filename, len(prs.slides), blocks)


def parse_txt(data: bytes, filename: str) -> ParsedDocument:
    text = data.decode("utf-8", errors="replace")
    blocks, section = [], ""
    for para in re.split(r"\n\s*\n", text):
        t = _clean(para.replace("\n", " "))
        if not t:
            continue
        if _is_heading_text(t):
            section = t
            blocks.append(Block(len(blocks), 1, "heading", t, section))
        else:
            blocks.append(Block(len(blocks), 1, "para", t, section))
    return ParsedDocument(filename, 1, blocks)


def parse_document(data: bytes, filename: str) -> ParsedDocument:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return parse_pdf(data, filename)
    if ext in (".docx", ".docm", ".dotx"):
        return parse_docx(data, filename)
    if ext in (".xlsx", ".xlsm"):
        return parse_xlsx(data, filename)
    if ext == ".csv":
        return parse_csv(data, filename)
    if ext == ".pptx":
        return parse_pptx(data, filename)
    if ext in (".txt", ".md"):
        return parse_txt(data, filename)
    raise ValueError(f"Unsupported file type: {ext}. Upload PDF, Word, Excel, CSV, PowerPoint or text.")
