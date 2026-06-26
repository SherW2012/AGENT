"""Generate styled Word (.docx), PowerPoint (.pptx) and Excel (.xlsx) files.

These are the open Office Open XML (OOXML) formats, standardized as ECMA-376 /
ISO/IEC 29500. We assemble them with the Python standard library only (zipfile +
XML strings): no third-party dependency and no licensing/IP concern -- we ship
none of Microsoft's fonts, templates, or code, only standards-defined markup.

The files are not bare text: they carry real style definitions (heading styles,
colors, bullet lists, table-like header fills, banded rows, slide accent bands)
so the output looks like a designed document, using the app's blue accent.

These are WRITE-risk tools: they create files under the workspace and go through
the same human approval as other writes.
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

# Shared palette (matches the UI's corporate blue theme).
ACCENT = "00408E"
ACCENT_DARK = "1F3A5F"
TEXT_DARK = "1F3A5F"
CODE_BLUE = "0B4C8F"
BAND_LIGHT = "EEF3F9"
BORDER_GREY = "D0D9E6"
EA_FONT = "微软雅黑"  # Microsoft YaHei, for CJK text


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


_R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
_P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
_W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_SHEET_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"


# --------------------------------------------------------------------------- #
# Word (.docx)
# --------------------------------------------------------------------------- #

_DOCX_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
    '<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>'
    '<Override PartName="/word/numbering.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
    "</Types>"
)

_DOCX_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
    "</Relationships>"
)

_DOCX_DOCUMENT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" Target="numbering.xml"/>'
    "</Relationships>"
)

_DOCX_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<w:styles xmlns:w="{_W_NS}">'
    '<w:docDefaults><w:rPrDefault><w:rPr>'
    f'<w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:eastAsia="{EA_FONT}" w:cs="Calibri"/>'
    '<w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr></w:rPrDefault>'
    '<w:pPrDefault><w:pPr><w:spacing w:after="160" w:line="276" w:lineRule="auto"/></w:pPr></w:pPrDefault>'
    '</w:docDefaults>'
    '<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
    '<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/>'
    '<w:pPr><w:spacing w:after="160"/>'
    f'<w:pBdr><w:bottom w:val="single" w:sz="18" w:space="6" w:color="{ACCENT}"/></w:pBdr></w:pPr>'
    f'<w:rPr><w:b/><w:color w:val="{ACCENT}"/><w:sz w:val="48"/><w:szCs w:val="48"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/>'
    '<w:pPr><w:keepNext/><w:spacing w:before="240" w:after="80"/></w:pPr>'
    f'<w:rPr><w:b/><w:color w:val="{ACCENT}"/><w:sz w:val="32"/><w:szCs w:val="32"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/>'
    '<w:pPr><w:keepNext/><w:spacing w:before="200" w:after="60"/></w:pPr>'
    f'<w:rPr><w:b/><w:color w:val="{ACCENT_DARK}"/><w:sz w:val="26"/><w:szCs w:val="26"/></w:rPr></w:style>'
    '<w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/><w:basedOn w:val="Normal"/>'
    '<w:pPr><w:numPr><w:numId w:val="1"/></w:numPr><w:spacing w:after="60"/></w:pPr></w:style>'
    '</w:styles>'
)

_DOCX_NUMBERING = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<w:numbering xmlns:w="{_W_NS}">'
    '<w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:start w:val="1"/>'
    '<w:numFmt w:val="bullet"/><w:lvlText w:val="•"/><w:lvlJc w:val="left"/>'
    '<w:pPr><w:ind w:left="420" w:hanging="220"/></w:pPr>'
    '<w:rPr><w:rFonts w:ascii="Arial" w:hAnsi="Arial" w:hint="default"/></w:rPr></w:lvl></w:abstractNum>'
    '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
    '</w:numbering>'
)

_DOCX_INLINE_RE = re.compile(r"(\*\*[^*]+\*\*|`[^`]+`|\*[^*]+\*)")


def _docx_run(text: str, *, bold: bool = False, italic: bool = False, code: bool = False) -> str:
    inner = ("<w:b/>" if bold else "") + ("<w:i/>" if italic else "")
    if code:
        inner += f'<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/><w:color w:val="{CODE_BLUE}"/>'
    run_props = f"<w:rPr>{inner}</w:rPr>" if inner else ""
    return f'<w:r>{run_props}<w:t xml:space="preserve">{_xml_escape(text)}</w:t></w:r>'


def _docx_runs(text: str) -> str:
    runs: list[str] = []
    for part in _DOCX_INLINE_RE.split(str(text)):
        if not part:
            continue
        if part.startswith("**") and part.endswith("**") and len(part) >= 4:
            runs.append(_docx_run(part[2:-2], bold=True))
        elif part.startswith("`") and part.endswith("`") and len(part) >= 2:
            runs.append(_docx_run(part[1:-1], code=True))
        elif part.startswith("*") and part.endswith("*") and len(part) >= 2:
            runs.append(_docx_run(part[1:-1], italic=True))
        else:
            runs.append(_docx_run(part))
    return "".join(runs) or _docx_run("")


def _docx_paragraph(style: str, text: str) -> str:
    ppr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style and style != "Normal" else ""
    return f"<w:p>{ppr}{_docx_runs(text)}</w:p>"


def create_word_document(
    root: Path,
    path: str,
    title: str = "",
    paragraphs: list[str] | None = None,
) -> dict[str, Any]:
    """Create a styled .docx. Use '# '/'## ' for headings and '- '/'* ' for bullets;
    inline **bold**, *italic* and `code` are rendered."""
    items = list(paragraphs or [])
    if len(items) > MAX_PARAGRAPHS:
        raise ValueError(f"段落数量过多，最多 {MAX_PARAGRAPHS} 段")
    target = _resolve_output_path(root, path, ".docx")

    body_parts: list[str] = []
    if str(title).strip():
        body_parts.append(_docx_paragraph("Title", str(title).strip()))
    for raw in items:
        line = str(raw)[:MAX_TEXT_CHARS]
        stripped = line.strip()
        if line.startswith("## "):
            body_parts.append(_docx_paragraph("Heading2", line[3:].strip()))
        elif line.startswith("# "):
            body_parts.append(_docx_paragraph("Heading1", line[2:].strip()))
        elif stripped.startswith("- ") or stripped.startswith("* "):
            body_parts.append(_docx_paragraph("ListBullet", stripped[2:].strip()))
        else:
            body_parts.append(_docx_paragraph("Normal", line))
    if not body_parts:
        body_parts.append(_docx_paragraph("Normal", ""))

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
            "word/_rels/document.xml.rels": _DOCX_DOCUMENT_RELS,
            "word/styles.xml": _DOCX_STYLES,
            "word/numbering.xml": _DOCX_NUMBERING,
        },
    )
    return {
        "path": target.relative_to(root.resolve()).as_posix(),
        "format": "docx",
        "paragraphs": len(body_parts),
        "bytes": target.stat().st_size,
        "message": "Word 文档已生成（带标题/标题层级/项目符号样式，OOXML 无第三方依赖）。请用 Word/WPS 打开核对。",
    }


# --------------------------------------------------------------------------- #
# PowerPoint (.pptx)
# --------------------------------------------------------------------------- #

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


def _solid_rect(shape_id: int, color: str, x: int, y: int, cx: int, cy: int) -> str:
    return (
        "<p:sp>"
        f'<p:nvSpPr><p:cNvPr id="{shape_id}" name="Accent{shape_id}"/><p:cNvSpPr/><p:nvPr/></p:nvSpPr>'
        f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        f'<a:prstGeom prst="rect"><a:avLst/></a:prstGeom>'
        f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill><a:ln><a:noFill/></a:ln></p:spPr>'
        '<p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody>'
        "</p:sp>"
    )


def _run_props(size: int, *, bold: bool, color: str) -> str:
    return (
        f'<a:rPr lang="zh-CN" altLang="en-US" sz="{size}" b="{1 if bold else 0}">'
        f'<a:solidFill><a:srgbClr val="{color}"/></a:solidFill>'
        f'<a:latin typeface="Calibri"/><a:ea typeface="{EA_FONT}"/></a:rPr>'
    )


def _title_paragraph(text: str, size: int, align: str) -> str:
    return (
        f'<a:p><a:pPr algn="{align}"/>'
        f"<a:r>{_run_props(size, bold=True, color=ACCENT)}<a:t>{_xml_escape(text)}</a:t></a:r></a:p>"
    )


def _bullet_paragraph(text: str) -> str:
    return (
        '<a:p><a:pPr marL="342900" indent="-342900"><a:spcBef><a:spcPts val="600"/></a:spcBef>'
        '<a:buFont typeface="Arial"/><a:buChar char="•"/></a:pPr>'
        f"<a:r>{_run_props(1800, bold=False, color=TEXT_DARK)}<a:t>{_xml_escape(text)}</a:t></a:r></a:p>"
    )


def _text_shape(shape_id: int, name: str, x: int, y: int, cx: int, cy: int, paragraphs_xml: str) -> str:
    return (
        "<p:sp>"
        f'<p:nvSpPr><p:cNvPr id="{shape_id}" name="{name}"/><p:cNvSpPr txBox="1"/><p:nvPr/></p:nvSpPr>'
        f'<p:spPr><a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></p:spPr>'
        f'<p:txBody><a:bodyPr wrap="square"><a:normAutofit/></a:bodyPr><a:lstStyle/>{paragraphs_xml}</p:txBody>'
        "</p:sp>"
    )


def _pptx_slide(title: str, bullets: list[str], is_cover: bool) -> str:
    shapes: list[str] = []
    if is_cover:
        # Centered title slide with a centered accent underline.
        shapes.append(_text_shape(2, "Title", 1219200, 2514600, 9753600, 1200000, _title_paragraph(title, 4400, "ctr")))
        shapes.append(_solid_rect(3, ACCENT, 4495800, 3886200, 3200400, 50800))
    else:
        # Content slide: top accent band, title, accent underline, bullets.
        shapes.append(_solid_rect(2, ACCENT, 0, 0, 12192000, 137160))
        shapes.append(_text_shape(3, "Title", 685800, 411480, 10820400, 900000, _title_paragraph(title, 3200, "l")))
        shapes.append(_solid_rect(4, ACCENT, 685800, 1303020, 3200400, 45720))
        body = "".join(_bullet_paragraph(b) for b in bullets) or _bullet_paragraph("")
        shapes.append(_text_shape(5, "Content", 685800, 1577340, 10820400, 4800600, body))
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<p:sld xmlns:a="{_A_NS}" xmlns:r="{_R_NS}" xmlns:p="{_P_NS}">'
        f'<p:cSld><p:spTree>{_EMPTY_GROUP}{"".join(shapes)}</p:spTree></p:cSld>'
        '</p:sld>'
    )


def create_powerpoint(root: Path, path: str, slides: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Create a styled .pptx. Each slide is {title, bullets:[...]}. The first
    slide with no bullets is rendered as a centered cover slide."""
    deck = list(slides or [])
    if not deck:
        raise ValueError("至少需要一页幻灯片")
    if len(deck) > MAX_SLIDES:
        raise ValueError(f"幻灯片数量过多，最多 {MAX_SLIDES} 页")
    target = _resolve_output_path(root, path, ".pptx")

    normalized: list[tuple[str, list[str], bool]] = []
    for index, item in enumerate(deck):
        if isinstance(item, dict):
            title = str(item.get("title") or "")[:MAX_TEXT_CHARS]
            bullets = [str(b)[:MAX_TEXT_CHARS] for b in (item.get("bullets") or []) if str(b).strip()]
        else:
            title = str(item)[:MAX_TEXT_CHARS]
            bullets = []
        is_cover = index == 0 and not bullets
        normalized.append((title, bullets, is_cover))

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
    for i, (title, bullets, is_cover) in enumerate(normalized):
        parts[f"ppt/slides/slide{i + 1}.xml"] = _pptx_slide(title, bullets, is_cover)
        parts[f"ppt/slides/_rels/slide{i + 1}.xml.rels"] = _PPTX_SLIDE_RELS

    _write_zip(target, parts)
    return {
        "path": target.relative_to(root.resolve()).as_posix(),
        "format": "pptx",
        "slides": count,
        "bytes": target.stat().st_size,
        "message": "PPT 已生成（含封面页、标题强调条与项目符号样式，OOXML 无第三方依赖）。请用 PowerPoint/WPS 打开核对。",
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

# Style indices used below: 0 default, 1 header (white bold on blue, bordered,
# centered), 2 data (bordered), 3 data banded (light fill, bordered).
_XLSX_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    f'<styleSheet xmlns="{_SHEET_NS}">'
    '<fonts count="3">'
    '<font><sz val="11"/><name val="Calibri"/></font>'
    f'<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>'
    f'<font><sz val="11"/><color rgb="FF{TEXT_DARK}"/><name val="Calibri"/></font>'
    '</fonts>'
    '<fills count="4">'
    '<fill><patternFill patternType="none"/></fill>'
    '<fill><patternFill patternType="gray125"/></fill>'
    f'<fill><patternFill patternType="solid"><fgColor rgb="FF{ACCENT}"/><bgColor indexed="64"/></patternFill></fill>'
    f'<fill><patternFill patternType="solid"><fgColor rgb="FF{BAND_LIGHT}"/><bgColor indexed="64"/></patternFill></fill>'
    '</fills>'
    '<borders count="2">'
    '<border><left/><right/><top/><bottom/><diagonal/></border>'
    f'<border><left style="thin"><color rgb="FF{BORDER_GREY}"/></left>'
    f'<right style="thin"><color rgb="FF{BORDER_GREY}"/></right>'
    f'<top style="thin"><color rgb="FF{BORDER_GREY}"/></top>'
    f'<bottom style="thin"><color rgb="FF{BORDER_GREY}"/></bottom><diagonal/></border>'
    '</borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="4">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>'
    '<xf numFmtId="0" fontId="2" fillId="0" borderId="1" xfId="0" applyFont="1" applyBorder="1" applyAlignment="1"><alignment vertical="center"/></xf>'
    '<xf numFmtId="0" fontId="2" fillId="3" borderId="1" xfId="0" applyFont="1" applyFill="1" applyBorder="1" applyAlignment="1"><alignment vertical="center"/></xf>'
    '</cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    '</styleSheet>'
)


def _col_letter(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _xlsx_cell(ref: str, value: Any, style: int) -> str:
    style_attr = f' s="{style}"' if style else ""
    if isinstance(value, bool):
        value = "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"{style_attr}><v>{value}</v></c>'
    text = str(value)
    if text and _NUMERIC_RE.fullmatch(text):
        return f'<c r="{ref}"{style_attr}><v>{text}</v></c>'
    return f'<c r="{ref}"{style_attr} t="inlineStr"><is><t xml:space="preserve">{_xml_escape(text)}</t></is></c>'


def _xlsx_sheet(rows: list[list[Any]]) -> str:
    capped = [list(row)[:MAX_COLS] for row in rows[:MAX_ROWS]]
    max_cols = max((len(row) for row in capped), default=1)
    # Column widths from the longest cell text in each column.
    widths: list[int] = [10] * max_cols
    for row in capped:
        for c_index, value in enumerate(row):
            length = len(str(value)) + 2
            widths[c_index] = max(widths[c_index], min(length, 60))
    cols = "".join(
        f'<col min="{i + 1}" max="{i + 1}" width="{w}" customWidth="1"/>'
        for i, w in enumerate(widths)
    )
    row_xml: list[str] = []
    for r_index, row in enumerate(capped, start=1):
        if r_index == 1:
            style = 1  # header
        else:
            style = 3 if r_index % 2 == 1 else 2  # banded data rows
        cells = "".join(
            _xlsx_cell(f"{_col_letter(c_index)}{r_index}", value, style)
            for c_index, value in enumerate(row)
        )
        row_xml.append(f'<row r="{r_index}">{cells}</row>')
    pane = (
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>'
    )
    auto_filter = ""
    if capped:
        auto_filter = f'<autoFilter ref="A1:{_col_letter(max_cols - 1)}{len(capped)}"/>'
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<worksheet xmlns="{_SHEET_NS}" xmlns:r="{_R_NS}">'
        f'{pane}<sheetFormatPr defaultRowHeight="16.5"/><cols>{cols}</cols>'
        f'<sheetData>{"".join(row_xml)}</sheetData>{auto_filter}</worksheet>'
    )


def create_excel(root: Path, path: str, sheets: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Create a styled .xlsx workbook. `sheets` is a list of {name, rows:[[cell,...],...]}.

    The first row is styled as a header (white bold on blue), data rows are
    bordered with banded shading, columns auto-size, the header is frozen, and an
    autofilter is applied. Numeric-looking strings become real numbers."""
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
            name = str(book.get("name") or f"Sheet{index + 1}")
            rows = book.get("rows") or []
        else:
            name = f"Sheet{index + 1}"
            rows = book
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
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
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
    sheet_count = len(normalized)
    workbook_rels_inner = "".join(
        f'<Relationship Id="rId{i + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        f'Target="worksheets/sheet{i + 1}.xml"/>'
        for i in range(sheet_count)
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{workbook_rels_inner}"
        f'<Relationship Id="rId{sheet_count + 1}" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
        "</Relationships>"
    )

    parts: dict[str, str] = {
        "[Content_Types].xml": content_types,
        "_rels/.rels": _XLSX_ROOT_RELS,
        "xl/workbook.xml": workbook,
        "xl/_rels/workbook.xml.rels": workbook_rels,
        "xl/styles.xml": _XLSX_STYLES,
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
        "message": "Excel 已生成（表头高亮、隔行底纹、边框、冻结首行与筛选，OOXML 无第三方依赖）。请用 Excel/WPS 打开核对。",
    }
