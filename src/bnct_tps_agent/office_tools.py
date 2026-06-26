"""Generate Word (.docx) and PowerPoint (.pptx) files using only the stdlib.

.docx/.pptx are the open Office Open XML (OOXML) format, standardized as
ECMA-376 / ISO/IEC 29500. Producing them is just writing a small set of XML
parts into a ZIP container, so there is no third-party dependency and no
licensing or intellectual-property concern -- we ship none of Microsoft's
fonts, templates, or code, only standards-defined markup.

These are WRITE-risk tools: they create files under the workspace and therefore
go through the same human approval as other writes.
"""
from __future__ import annotations

import re
import zipfile
from pathlib import Path
from typing import Any


MAX_PARAGRAPHS = 400
MAX_SLIDES = 60
MAX_TEXT_CHARS = 20_000
MAX_SHEETS = 12
MAX_ROWS = 5_000
MAX_COLS = 256
_NUMERIC_RE = re.compile(r"-?\d+(?:\.\d+)?")


def _xml_escape(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _resolve_output_path(root: Path, path: str, suffix: str) -> Path:
    raw = str(path or "").strip()
    if not raw:
        raise ValueError("path 不能为空")
    candidate = (root / raw).expanduser()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("只能写入工作目录内的路径") from exc
    if resolved.suffix.lower() != suffix:
        resolved = resolved.with_suffix(suffix)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    return resolved


def _write_zip(target: Path, parts: dict[str, str]) -> None:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in parts.items():
            archive.writestr(name, content)


# --------------------------------------------------------------------------- #
# Word (.docx)
# --------------------------------------------------------------------------- #

_DOCX_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_DOCX_ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx_paragraph(text: str, *, bold: bool = False, size_half_points: int | None = None) -> str:
    run_props = ""
    if bold or size_half_points:
        inner = ("<w:b/>" if bold else "") + (
            f'<w:sz w:val="{int(size_half_points)}"/>' if size_half_points else ""
        )
        run_props = f"<w:rPr>{inner}</w:rPr>"
    safe = _xml_escape(text)
    return (
        "<w:p>"
        f"<w:r>{run_props}<w:t xml:space=\"preserve\">{safe}</w:t></w:r>"
        "</w:p>"
    )


def create_word_document(
    root: Path,
    path: str,
    title: str = "",
    paragraphs: list[str] | None = None,
) -> dict[str, Any]:
    """Create a .docx. Paragraphs starting with '# ' / '## ' become headings."""
    items = list(paragraphs or [])
    if len(items) > MAX_PARAGRAPHS:
        raise ValueError(f"段落数量过多，最多 {MAX_PARAGRAPHS} 段")
    target = _resolve_output_path(root, path, ".docx")

    body_parts: list[str] = []
    if str(title).strip():
        body_parts.append(_docx_paragraph(str(title).strip(), bold=True, size_half_points=36))
    for raw in items:
        line = str(raw)
        if len(line) > MAX_TEXT_CHARS:
            line = line[:MAX_TEXT_CHARS]
        if line.startswith("## "):
            body_parts.append(_docx_paragraph(line[3:].strip(), bold=True, size_half_points=26))
        elif line.startswith("# "):
            body_parts.append(_docx_paragraph(line[2:].strip(), bold=True, size_half_points=32))
        else:
            body_parts.append(_docx_paragraph(line))
    if not body_parts:
        body_parts.append(_docx_paragraph(""))

    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{_W_NS}"><w:body>'
        + "".join(body_parts)
        + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1440" w:right="1440" w:bottom="1440" w:left="1440" '
        'w:header="708" w:footer="708" w:gutter="0"/></w:sectPr>'
        "</w:body></w:document>"
    )
    _write_zip(
        target,
        {
            "[Content_Types].xml": _DOCX_CONTENT_TYPES,
            "_rels/.rels": _DOCX_ROOT_RELS,
            "word/document.xml": document,
        },
    )
    return {
        "path": target.relative_to(root.resolve()).as_posix(),
        "format": "docx",
        "paragraphs": len(body_parts),
        "bytes": target.stat().st_size,
        "message": "Word 文档已生成（OOXML，无第三方依赖）。请用 Word/WPS 打开核对。",
    }


# --------------------------------------------------------------------------- #
# PowerPoint (.pptx)
# --------------------------------------------------------------------------- #

_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

_EMPTY_GROUP = (
    '<p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>'
    '<p:grpSpPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/>'
    '<a:chOff x="0" y="0"/><a:chExt cx="0" cy="0"/></a:xfrm></p:grpSpPr>'
)

_PPTX_THEME = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<a:theme xmlns:a="{_A_NS}" name="Office Theme"><a:themeElements>'
    '<a:clrScheme name="Office">'
    '<a:dk1><a:sysClr val="windowText" lastClr="000000"/></a:dk1>'
    '<a:lt1><a:sysClr val="window" lastClr="FFFFFF"/></a:lt1>'
    '<a:dk2><a:srgbClr val="1F2D3D"/></a:dk2><a:lt2><a:srgbClr val="EEF2F8"/></a:lt2>'
    '<a:accent1><a:srgbClr val="00408E"/></a:accent1><a:accent2><a:srgbClr val="2D9DD0"/></a:accent2>'
    '<a:accent3><a:srgbClr val="4F8A69"/></a:accent3><a:accent4><a:srgbClr val="A87228"/></a:accent4>'
    '<a:accent5><a:srgbClr val="7469B6"/></a:accent5><a:accent6><a:srgbClr val="B95555"/></a:accent6>'
    '<a:hlink><a:srgbClr val="0563C1"/></a:hlink><a:folHlink><a:srgbClr val="954F72"/></a:folHlink>'
    '</a:clrScheme>'
    '<a:fontScheme name="Office">'
    '<a:majorFont><a:latin typeface="Calibri Light"/><a:ea typeface=""/><a:cs typeface=""/></a:majorFont>'
    '<a:minorFont><a:latin typeface="Calibri"/><a:ea typeface=""/><a:cs typeface=""/></a:minorFont>'
    '</a:fontScheme>'
    '<a:fmtScheme name="Office">'
    '<a:fillStyleLst>'
    '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    '</a:fillStyleLst>'
    '<a:lnStyleLst>'
    '<a:ln w="6350" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:prstDash val="solid"/></a:ln>'
    '<a:ln w="12700" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:prstDash val="solid"/></a:ln>'
    '<a:ln w="19050" cap="flat" cmpd="sng" algn="ctr"><a:solidFill><a:schemeClr val="phClr"/></a:solidFill><a:prstDash val="solid"/></a:ln>'
    '</a:lnStyleLst>'
    '<a:effectStyleLst>'
    '<a:effectStyle><a:effectLst/></a:effectStyle>'
    '<a:effectStyle><a:effectLst/></a:effectStyle>'
    '<a:effectStyle><a:effectLst/></a:effectStyle>'
    '</a:effectStyleLst>'
    '<a:bgFillStyleLst>'
    '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    '<a:solidFill><a:schemeClr val="phClr"/></a:solidFill>'
    '</a:bgFillStyleLst>'
    '</a:fmtScheme>'
    '</a:themeElements></a:theme>'
)

_PPTX_SLIDE_MASTER = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<p:sldMaster xmlns:a="{_A_NS}" xmlns:r="{_R_NS}" xmlns:p="{_P_NS}">'
    f'<p:cSld><p:bg><p:bgRef idx="1001"><a:schemeClr val="bg1"/></p:bgRef></p:bg>'
    f'<p:spTree>{_EMPTY_GROUP}</p:spTree></p:cSld>'
    '<p:clrMap bg1="lt1" tx1="dk1" bg2="lt2" tx2="dk2" accent1="accent1" accent2="accent2" '
    'accent3="accent3" accent4="accent4" accent5="accent5" accent6="accent6" hlink="hlink" folHlink="folHlink"/>'
    '<p:sldLayoutIdLst><p:sldLayoutId id="2147483649" r:id="rId1"/></p:sldLayoutIdLst>'
    '</p:sldMaster>'
)

_PPTX_SLIDE_MASTER_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="../theme/theme1.xml"/>'
    '</Relationships>'
)

_PPTX_SLIDE_LAYOUT = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<p:sldLayout xmlns:a="{_A_NS}" xmlns:r="{_R_NS}" xmlns:p="{_P_NS}" type="blank" preserve="1">'
    f'<p:cSld name="Blank"><p:spTree>{_EMPTY_GROUP}</p:spTree></p:cSld>'
    '<p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>'
    '</p:sldLayout>'
)

_PPTX_SLIDE_LAYOUT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="../slideMasters/slideMaster1.xml"/>'
    '</Relationships>'
)

_PPTX_SLIDE_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideLayout" Target="../slideLayouts/slideLayout1.xml"/>'
    '</Relationships>'
)


def _pptx_text_shape(shape_id: int, name: str, x: int, y: int, cx: int, cy: int, paragraphs_xml: str) -> str:
    return (
        "<p:sp>"
        f'<p:nvSpPr><p:cNvPr id="{shape_id}" name="{name}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
        f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
        f'<p:txBody><a:bodyPr wrap="square"/><a:lstStyle/>{paragraphs_xml}</p:txBody>'
        "</p:sp>"
    )


def _pptx_paragraph(text: str, *, size: int, bold: bool) -> str:
    return (
        "<a:p>"
        f'<a:r><a:rPr lang="zh-CN" altLang="en-US" sz="{size}" b="{1 if bold else 0}"/>'
        f"<a:t>{_xml_escape(text)}</a:t></a:r>"
        "</a:p>"
    )


def _pptx_slide(title: str, bullets: list[str]) -> str:
    shapes = []
    shapes.append(
        _pptx_text_shape(
            2, "Title", 685800, 381000, 10820400, 1143000,
            _pptx_paragraph(str(title), size=3200, bold=True),
        )
    )
    body = "".join(_pptx_paragraph(str(b), size=1800, bold=False) for b in bullets) or _pptx_paragraph("", size=1800, bold=False)
    shapes.append(_pptx_text_shape(3, "Content", 685800, 1676400, 10820400, 4525963, body))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:sld xmlns:a="{_A_NS}" xmlns:r="{_R_NS}" xmlns:p="{_P_NS}">'
        f'<p:cSld><p:spTree>{_EMPTY_GROUP}{"".join(shapes)}</p:spTree></p:cSld>'
        '</p:sld>'
    )


def create_powerpoint(root: Path, path: str, slides: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Create a .pptx. `slides` is a list of {title, bullets:[...]} objects."""
    deck = list(slides or [])
    if not deck:
        raise ValueError("至少需要一页幻灯片")
    if len(deck) > MAX_SLIDES:
        raise ValueError(f"幻灯片数量过多，最多 {MAX_SLIDES} 页")
    target = _resolve_output_path(root, path, ".pptx")

    normalized: list[tuple[str, list[str]]] = []
    for item in deck:
        if isinstance(item, dict):
            title = str(item.get("title") or "")
            bullets = [str(b)[:MAX_TEXT_CHARS] for b in (item.get("bullets") or []) if str(b).strip()]
        else:
            title = str(item)
            bullets = []
        normalized.append((title[:MAX_TEXT_CHARS], bullets))

    count = len(normalized)
    slide_overrides = "".join(
        f'<Override PartName="/ppt/slides/slide{i + 1}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml"/>'
        for i in range(count)
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/ppt/presentation.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.presentation.main+xml"/>'
        '<Override PartName="/ppt/slideMasters/slideMaster1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideMaster+xml"/>'
        '<Override PartName="/ppt/slideLayouts/slideLayout1.xml" ContentType="application/vnd.openxmlformats-officedocument.presentationml.slideLayout+xml"/>'
        '<Override PartName="/ppt/theme/theme1.xml" ContentType="application/vnd.openxmlformats-officedocument.theme+xml"/>'
        f"{slide_overrides}"
        "</Types>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="ppt/presentation.xml"/>'
        "</Relationships>"
    )
    sld_id_lst = "".join(f'<p:sldId id="{256 + i}" r:id="rId{i + 2}"/>' for i in range(count))
    presentation = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:presentation xmlns:a="{_A_NS}" xmlns:r="{_R_NS}" xmlns:p="{_P_NS}">'
        '<p:sldMasterIdLst><p:sldMasterId id="2147483648" r:id="rId1"/></p:sldMasterIdLst>'
        f'<p:sldIdLst>{sld_id_lst}</p:sldIdLst>'
        '<p:sldSz cx="12192000" cy="6858000" type="screen16x9"/>'
        '<p:notesSz cx="6858000" cy="9144000"/>'
        '</p:presentation>'
    )
    slide_rels = "".join(
        f'<Relationship Id="rId{i + 2}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slide" '
        f'Target="slides/slide{i + 1}.xml"/>'
        for i in range(count)
    )
    presentation_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/slideMaster" Target="slideMasters/slideMaster1.xml"/>'
        f"{slide_rels}"
        f'<Relationship Id="rId{count + 2}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/theme" Target="theme/theme1.xml"/>'
        "</Relationships>"
    )

    parts: dict[str, str] = {
        "[Content_Types].xml": content_types,
        "_rels/.rels": root_rels,
        "ppt/presentation.xml": presentation,
        "ppt/_rels/presentation.xml.rels": presentation_rels,
        "ppt/theme/theme1.xml": _PPTX_THEME,
        "ppt/slideMasters/slideMaster1.xml": _PPTX_SLIDE_MASTER,
        "ppt/slideMasters/_rels/slideMaster1.xml.rels": _PPTX_SLIDE_MASTER_RELS,
        "ppt/slideLayouts/slideLayout1.xml": _PPTX_SLIDE_LAYOUT,
        "ppt/slideLayouts/_rels/slideLayout1.xml.rels": _PPTX_SLIDE_LAYOUT_RELS,
    }
    for i, (title, bullets) in enumerate(normalized):
        parts[f"ppt/slides/slide{i + 1}.xml"] = _pptx_slide(title, bullets)
        parts[f"ppt/slides/_rels/slide{i + 1}.xml.rels"] = _PPTX_SLIDE_RELS

    _write_zip(target, parts)
    return {
        "path": target.relative_to(root.resolve()).as_posix(),
        "format": "pptx",
        "slides": count,
        "bytes": target.stat().st_size,
        "message": "PPT 已生成（OOXML，无第三方依赖）。请用 PowerPoint/WPS 打开核对。",
    }


# --------------------------------------------------------------------------- #
# Excel (.xlsx)
# --------------------------------------------------------------------------- #

_XLSX_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    '</Relationships>'
)

_SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


def _col_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _xlsx_cell(ref: str, value: Any) -> str:
    if isinstance(value, bool):
        value = "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"><v>{value}</v></c>'
    text = str(value)
    if text and _NUMERIC_RE.fullmatch(text):
        return f'<c r="{ref}"><v>{text}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{_xml_escape(text)}</t></is></c>'


def _xlsx_sheet(rows: list[list[Any]]) -> str:
    row_xml: list[str] = []
    for r_index, row in enumerate(rows[:MAX_ROWS], start=1):
        cells = "".join(
            _xlsx_cell(f"{_col_letter(c_index)}{r_index}", value)
            for c_index, value in enumerate(list(row)[:MAX_COLS])
        )
        row_xml.append(f'<row r="{r_index}">{cells}</row>')
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{_SHEET_NS}"><sheetData>{"".join(row_xml)}</sheetData></worksheet>'
    )


def create_excel(root: Path, path: str, sheets: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Create a .xlsx workbook. `sheets` is a list of {name, rows:[[cell,...],...]}.

    Cells may be strings or numbers; numeric-looking strings become numbers."""
    books = list(sheets or [])
    if not books:
        raise ValueError("至少需要一个工作表")
    if len(books) > MAX_SHEETS:
        raise ValueError(f"工作表数量过多，最多 {MAX_SHEETS} 个")
    target = _resolve_output_path(root, path, ".xlsx")

    normalized: list[tuple[str, list[list[Any]]]] = []
    used_names: set[str] = set()
    for index, book in enumerate(books):
        if isinstance(book, dict):
            name = str(book.get("name") or f"Sheet{index + 1}").strip()[:31] or f"Sheet{index + 1}"
            rows = book.get("rows") or []
        else:
            name = f"Sheet{index + 1}"
            rows = book
        # Excel forbids duplicate sheet names and a few characters.
        name = re.sub(r"[\\/?*\[\]:]", " ", name).strip()[:31] or f"Sheet{index + 1}"
        base = name
        suffix = 2
        while name.lower() in used_names:
            name = f"{base[:28]}_{suffix}"
            suffix += 1
        used_names.add(name.lower())
        normalized.append((name, [list(r) for r in rows]))

    sheet_overrides = "".join(
        f'<Override PartName="/xl/worksheets/sheet{i + 1}.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        for i in range(len(normalized))
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        f"{sheet_overrides}"
        "</Types>"
    )
    sheet_entries = "".join(
        f'<sheet name="{_xml_escape(name)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>'
        for i, (name, _rows) in enumerate(normalized)
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<workbook xmlns="{_SHEET_NS}" xmlns:r="{_R_NS}">'
        f'<sheets>{sheet_entries}</sheets></workbook>'
    )
    workbook_rels_inner = "".join(
        f'<Relationship Id="rId{i + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{i + 1}.xml"/>'
        for i in range(len(normalized))
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{workbook_rels_inner}</Relationships>"
    )

    parts: dict[str, str] = {
        "[Content_Types].xml": content_types,
        "_rels/.rels": _XLSX_ROOT_RELS,
        "xl/workbook.xml": workbook,
        "xl/_rels/workbook.xml.rels": workbook_rels,
    }
    total_rows = 0
    for i, (_name, rows) in enumerate(normalized):
        parts[f"xl/worksheets/sheet{i + 1}.xml"] = _xlsx_sheet(rows)
        total_rows += min(len(rows), MAX_ROWS)

    _write_zip(target, parts)
    return {
        "path": target.relative_to(root.resolve()).as_posix(),
        "format": "xlsx",
        "sheets": len(normalized),
        "rows": total_rows,
        "bytes": target.stat().st_size,
        "message": "Excel 已生成（OOXML，无第三方依赖）。请用 Excel/WPS 打开核对。",
    }
