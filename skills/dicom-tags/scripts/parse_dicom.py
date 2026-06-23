from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Any


LONG_VR = {"OB", "OD", "OF", "OL", "OW", "SQ", "UC", "UR", "UT", "UN"}
STRING_VR = {"AE", "AS", "CS", "DA", "DS", "DT", "IS", "LO", "LT", "PN", "SH", "ST", "TM", "UI", "UR", "UT"}
SENSITIVE_TAGS = {
    (0x0008, 0x0050),
    (0x0008, 0x0080),
    (0x0008, 0x0090),
    (0x0008, 0x1048),
    (0x0008, 0x1050),
    (0x0008, 0x1070),
    (0x0010, 0x0010),
    (0x0010, 0x0020),
    (0x0010, 0x0030),
    (0x0010, 0x0032),
    (0x0010, 0x0040),
    (0x0010, 0x1010),
    (0x0010, 0x1000),
    (0x0010, 0x1001),
    (0x0010, 0x2160),
    (0x0020, 0x0010),
}


TAG_NAMES: dict[tuple[int, int], tuple[str, str]] = {
    (0x0002, 0x0000): ("FileMetaInformationGroupLength", "UL"),
    (0x0002, 0x0001): ("FileMetaInformationVersion", "OB"),
    (0x0002, 0x0002): ("MediaStorageSOPClassUID", "UI"),
    (0x0002, 0x0003): ("MediaStorageSOPInstanceUID", "UI"),
    (0x0002, 0x0010): ("TransferSyntaxUID", "UI"),
    (0x0002, 0x0012): ("ImplementationClassUID", "UI"),
    (0x0002, 0x0013): ("ImplementationVersionName", "SH"),
    (0x0008, 0x0008): ("ImageType", "CS"),
    (0x0008, 0x0016): ("SOPClassUID", "UI"),
    (0x0008, 0x0018): ("SOPInstanceUID", "UI"),
    (0x0008, 0x0020): ("StudyDate", "DA"),
    (0x0008, 0x0021): ("SeriesDate", "DA"),
    (0x0008, 0x0022): ("AcquisitionDate", "DA"),
    (0x0008, 0x0023): ("ContentDate", "DA"),
    (0x0008, 0x0030): ("StudyTime", "TM"),
    (0x0008, 0x0031): ("SeriesTime", "TM"),
    (0x0008, 0x0032): ("AcquisitionTime", "TM"),
    (0x0008, 0x0033): ("ContentTime", "TM"),
    (0x0008, 0x0050): ("AccessionNumber", "SH"),
    (0x0008, 0x0060): ("Modality", "CS"),
    (0x0008, 0x0070): ("Manufacturer", "LO"),
    (0x0008, 0x0080): ("InstitutionName", "LO"),
    (0x0008, 0x0090): ("ReferringPhysicianName", "PN"),
    (0x0008, 0x1030): ("StudyDescription", "LO"),
    (0x0008, 0x103E): ("SeriesDescription", "LO"),
    (0x0008, 0x1090): ("ManufacturerModelName", "LO"),
    (0x0010, 0x0010): ("PatientName", "PN"),
    (0x0010, 0x0020): ("PatientID", "LO"),
    (0x0010, 0x0030): ("PatientBirthDate", "DA"),
    (0x0010, 0x0040): ("PatientSex", "CS"),
    (0x0010, 0x1010): ("PatientAge", "AS"),
    (0x0018, 0x0015): ("BodyPartExamined", "CS"),
    (0x0018, 0x0050): ("SliceThickness", "DS"),
    (0x0018, 0x0060): ("KVP", "DS"),
    (0x0018, 0x0088): ("SpacingBetweenSlices", "DS"),
    (0x0018, 0x0090): ("DataCollectionDiameter", "DS"),
    (0x0018, 0x1020): ("SoftwareVersions", "LO"),
    (0x0018, 0x1100): ("ReconstructionDiameter", "DS"),
    (0x0018, 0x1110): ("DistanceSourceToDetector", "DS"),
    (0x0018, 0x1111): ("DistanceSourceToPatient", "DS"),
    (0x0018, 0x1120): ("GantryDetectorTilt", "DS"),
    (0x0018, 0x1130): ("TableHeight", "DS"),
    (0x0018, 0x1150): ("ExposureTime", "IS"),
    (0x0018, 0x1151): ("XRayTubeCurrent", "IS"),
    (0x0018, 0x1152): ("Exposure", "IS"),
    (0x0018, 0x1210): ("ConvolutionKernel", "SH"),
    (0x0018, 0x5100): ("PatientPosition", "CS"),
    (0x0020, 0x000D): ("StudyInstanceUID", "UI"),
    (0x0020, 0x000E): ("SeriesInstanceUID", "UI"),
    (0x0020, 0x0010): ("StudyID", "SH"),
    (0x0020, 0x0011): ("SeriesNumber", "IS"),
    (0x0020, 0x0013): ("InstanceNumber", "IS"),
    (0x0020, 0x0032): ("ImagePositionPatient", "DS"),
    (0x0020, 0x0037): ("ImageOrientationPatient", "DS"),
    (0x0020, 0x0052): ("FrameOfReferenceUID", "UI"),
    (0x0020, 0x1041): ("SliceLocation", "DS"),
    (0x0028, 0x0002): ("SamplesPerPixel", "US"),
    (0x0028, 0x0004): ("PhotometricInterpretation", "CS"),
    (0x0028, 0x0010): ("Rows", "US"),
    (0x0028, 0x0011): ("Columns", "US"),
    (0x0028, 0x0030): ("PixelSpacing", "DS"),
    (0x0028, 0x0100): ("BitsAllocated", "US"),
    (0x0028, 0x0101): ("BitsStored", "US"),
    (0x0028, 0x0102): ("HighBit", "US"),
    (0x0028, 0x0103): ("PixelRepresentation", "US"),
    (0x0028, 0x1050): ("WindowCenter", "DS"),
    (0x0028, 0x1051): ("WindowWidth", "DS"),
    (0x0028, 0x1052): ("RescaleIntercept", "DS"),
    (0x0028, 0x1053): ("RescaleSlope", "DS"),
    (0x0028, 0x1054): ("RescaleType", "LO"),
    (0x7FE0, 0x0010): ("PixelData", "OW"),
}

TRANSFER_SYNTAX_NAMES = {
    "1.2.840.10008.1.2": "Implicit VR Little Endian",
    "1.2.840.10008.1.2.1": "Explicit VR Little Endian",
    "1.2.840.10008.1.2.1.99": "Deflated Explicit VR Little Endian",
    "1.2.840.10008.1.2.2": "Explicit VR Big Endian",
    "1.2.840.10008.1.2.4.50": "JPEG Baseline",
    "1.2.840.10008.1.2.4.70": "JPEG Lossless",
    "1.2.840.10008.1.2.4.90": "JPEG 2000 Lossless",
    "1.2.840.10008.1.2.4.91": "JPEG 2000",
}


@dataclass(frozen=True)
class DataElement:
    group: int
    element: int
    vr: str
    name: str
    length: int
    value: str

    @property
    def tag(self) -> str:
        return f"({self.group:04X},{self.element:04X})"


def looks_like_dicom(data: bytes) -> bool:
    return len(data) >= 132 and data[128:132] == b"DICM"


def _unpack(fmt: str, data: bytes) -> Any:
    return struct.unpack(fmt, data)[0]


def _tag_name(group: int, element: int) -> tuple[str, str]:
    return TAG_NAMES.get((group, element), ("Unknown", "UN"))


def _decode_text(value: bytes) -> str:
    text = value.rstrip(b"\x00 ").decode("utf-8", errors="replace")
    text = text.replace("\x00", "").replace("\r", " ").replace("\n", " ")
    return "\\".join(part.strip() for part in text.split("\\"))


def _decode_value(group: int, element: int, vr: str, value: bytes, endian: str) -> str:
    if (group, element) in SENSITIVE_TAGS:
        return "[已脱敏]"
    if len(value) > 256:
        return f"<{len(value)} bytes>"
    if vr in STRING_VR:
        return _decode_text(value)
    try:
        if vr == "US" and len(value) % 2 == 0:
            return "\\".join(str(item) for item in struct.unpack(endian + "H" * (len(value) // 2), value))
        if vr == "SS" and len(value) % 2 == 0:
            return "\\".join(str(item) for item in struct.unpack(endian + "h" * (len(value) // 2), value))
        if vr == "UL" and len(value) % 4 == 0:
            return "\\".join(str(item) for item in struct.unpack(endian + "I" * (len(value) // 4), value))
        if vr == "SL" and len(value) % 4 == 0:
            return "\\".join(str(item) for item in struct.unpack(endian + "i" * (len(value) // 4), value))
        if vr == "FL" and len(value) % 4 == 0:
            return "\\".join(f"{item:g}" for item in struct.unpack(endian + "f" * (len(value) // 4), value))
        if vr == "FD" and len(value) % 8 == 0:
            return "\\".join(f"{item:g}" for item in struct.unpack(endian + "d" * (len(value) // 8), value))
    except struct.error:
        pass
    if not value:
        return ""
    return value.hex(" ", 1)[:160]


def _read_explicit(data: bytes, offset: int, endian: str) -> tuple[int, int, str, int, int] | None:
    if offset + 8 > len(data):
        return None
    group = _unpack(endian + "H", data[offset : offset + 2])
    element = _unpack(endian + "H", data[offset + 2 : offset + 4])
    vr = data[offset + 4 : offset + 6].decode("ascii", errors="replace")
    if vr in LONG_VR:
        if offset + 12 > len(data):
            return None
        length = _unpack(endian + "I", data[offset + 8 : offset + 12])
        value_offset = offset + 12
    else:
        length = _unpack(endian + "H", data[offset + 6 : offset + 8])
        value_offset = offset + 8
    return group, element, vr, length, value_offset


def _read_implicit(data: bytes, offset: int, endian: str) -> tuple[int, int, str, int, int] | None:
    if offset + 8 > len(data):
        return None
    group = _unpack(endian + "H", data[offset : offset + 2])
    element = _unpack(endian + "H", data[offset + 2 : offset + 4])
    _name, vr = _tag_name(group, element)
    length = _unpack(endian + "I", data[offset + 4 : offset + 8])
    return group, element, vr, length, offset + 8


def parse_dicom_tags(data: bytes, max_tags: int = 220) -> dict[str, Any]:
    if not data:
        raise ValueError("DICOM attachment is empty")
    offset = 132 if looks_like_dicom(data) else 0
    tags: list[DataElement] = []
    transfer_syntax_uid = ""
    endian = "<"
    explicit = True

    while offset + 8 <= len(data):
        parsed = _read_explicit(data, offset, "<")
        if parsed is None:
            break
        group, element, vr, length, value_offset = parsed
        if group != 0x0002 or length == 0xFFFFFFFF or value_offset + length > len(data):
            break
        name, fallback_vr = _tag_name(group, element)
        used_vr = vr if len(vr) == 2 and vr.isalpha() else fallback_vr
        value = data[value_offset : value_offset + length]
        decoded = _decode_value(group, element, used_vr, value, "<")
        tags.append(DataElement(group, element, used_vr, name, length, decoded))
        if (group, element) == (0x0002, 0x0010):
            transfer_syntax_uid = decoded
        offset = value_offset + length

    if transfer_syntax_uid == "1.2.840.10008.1.2":
        explicit = False
        endian = "<"
    elif transfer_syntax_uid == "1.2.840.10008.1.2.2":
        explicit = True
        endian = ">"
    else:
        explicit = True
        endian = "<"

    while offset + 8 <= len(data) and len(tags) < max_tags:
        parsed = _read_explicit(data, offset, endian) if explicit else _read_implicit(data, offset, endian)
        if parsed is None:
            break
        group, element, vr, length, value_offset = parsed
        if group == 0xFFFE:
            break
        name, fallback_vr = _tag_name(group, element)
        if not vr.isalpha() or len(vr) != 2:
            vr = fallback_vr
        if (group, element) == (0x7FE0, 0x0010):
            tags.append(DataElement(group, element, vr, name, length, "<Pixel Data omitted>"))
            break
        if length == 0xFFFFFFFF:
            tags.append(DataElement(group, element, vr, name, length, "<Undefined length sequence omitted>"))
            break
        if length < 0 or value_offset + length > len(data):
            break
        value = data[value_offset : value_offset + length]
        tags.append(DataElement(group, element, vr, name, length, _decode_value(group, element, vr, value, endian)))
        offset = value_offset + length

    tag_dict = {item.tag: item for item in tags}
    empty = DataElement(0, 0, "", "", 0, "")
    return {
        "transferSyntaxUID": transfer_syntax_uid,
        "transferSyntaxName": TRANSFER_SYNTAX_NAMES.get(transfer_syntax_uid, transfer_syntax_uid or "Unknown"),
        "explicitVR": explicit,
        "littleEndian": endian == "<",
        "tagsParsed": len(tags),
        "truncated": len(tags) >= max_tags,
        "summary": {
            "Modality": tag_dict.get("(0008,0060)", empty).value,
            "SOPClassUID": tag_dict.get("(0008,0016)", empty).value,
            "StudyDescription": tag_dict.get("(0008,1030)", empty).value,
            "SeriesDescription": tag_dict.get("(0008,103E)", empty).value,
            "Rows": tag_dict.get("(0028,0010)", empty).value,
            "Columns": tag_dict.get("(0028,0011)", empty).value,
            "PixelSpacing": tag_dict.get("(0028,0030)", empty).value,
            "SliceThickness": tag_dict.get("(0018,0050)", empty).value,
            "ImagePositionPatient": tag_dict.get("(0020,0032)", empty).value,
            "ImageOrientationPatient": tag_dict.get("(0020,0037)", empty).value,
        },
        "tags": [
            {
                "tag": item.tag,
                "name": item.name,
                "vr": item.vr,
                "length": item.length if item.length != 0xFFFFFFFF else "undefined",
                "value": item.value,
            }
            for item in tags
        ],
    }


def _escape_table(value: Any) -> str:
    return str(value).replace("|", "\\|")


def render_dicom_markdown(name: str, size: int, parsed: dict[str, Any]) -> str:
    lines = [
        f"DICOM 附件已由 `dicom-tags` skill 解析：`{name}`",
        "",
        f"- 文件大小：{size} bytes",
        f"- Transfer Syntax：{parsed['transferSyntaxName']}",
        f"- 编码：{'Explicit VR' if parsed['explicitVR'] else 'Implicit VR'}，{'Little Endian' if parsed['littleEndian'] else 'Big Endian'}",
        f"- 已解析 tag 数：{parsed['tagsParsed']}",
        "- 直接患者标识符已自动脱敏；Pixel Data 未发送给模型。",
        "",
        "## 关键影像信息",
        "",
        "| 字段 | 值 |",
        "| --- | --- |",
    ]
    for key, value in parsed["summary"].items():
        if value:
            lines.append(f"| {key} | {_escape_table(value)} |")
    lines.extend(["", "## DICOM Tags", "", "| Tag | Name | VR | Value |", "| --- | --- | --- | --- |"])
    for item in parsed["tags"]:
        value = _escape_table(item["value"])
        if len(value) > 220:
            value = value[:220] + "..."
        lines.append(f"| {item['tag']} | {item['name']} | {item['vr']} | {value} |")
    if parsed.get("truncated"):
        lines.append("")
        lines.append("> tag 列表达到 skill 解析上限，已截断。")
    return "\n".join(lines)


def process_attachment(attachment: dict[str, Any], _context: dict[str, Any]) -> dict[str, Any]:
    data = attachment.get("data")
    if not isinstance(data, (bytes, bytearray)):
        raise ValueError("dicom-tags skill requires binary attachment data")
    name = str(attachment.get("name") or "attachment.dcm")
    original_size = int(attachment.get("original_size") or len(data))
    parsed = parse_dicom_tags(bytes(data))
    content = render_dicom_markdown(name, original_size, parsed)
    return {
        "kind": "dicom",
        "content": content,
        "stored": {
            "kind": "dicom",
            "tags": parsed["tagsParsed"],
            "transferSyntax": parsed["transferSyntaxName"],
            "uploadedBytes": len(data),
            "originalSize": original_size,
        },
    }
