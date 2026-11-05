"""Read the text of locally uploaded teaching materials."""

from collections.abc import Iterable, Iterator
from io import BytesIO, StringIO
from pathlib import PurePosixPath
from xml.etree.ElementTree import Element, ParseError
from zipfile import ZIP_DEFLATED, ZIP_STORED, BadZipFile, ZipFile
from zlib import error as ZlibError

from defusedxml import ElementTree
from pypdf import PdfReader, apply_configuration
from pypdf.errors import LimitReachedError

from app.core.errors import AppError

MAX_COURSEWARE_BYTES = 10 * 1024 * 1024
MAX_TEXT_CHARS = 12_000
MAX_OFFICE_BYTES = 32 * 1024 * 1024
MAX_XML_BYTES = 4 * 1024 * 1024
MAX_DOCUMENT_PAGES = 60
SUPPORTED = {".txt", ".md", ".docx", ".pptx", ".pdf"}

WORD_NS = {
    "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "http://purl.oclc.org/ooxml/wordprocessingml/main",
}
PRESENTATION_NS = {
    "http://schemas.openxmlformats.org/presentationml/2006/main",
    "http://purl.oclc.org/ooxml/presentationml/main",
}
DRAWING_NS = {
    "http://schemas.openxmlformats.org/drawingml/2006/main",
    "http://purl.oclc.org/ooxml/drawingml/main",
}
RELATIONSHIP_NS = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "http://purl.oclc.org/ooxml/officeDocument/relationships",
)
PACKAGE_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def _tags(namespaces: Iterable[str], name: str) -> set[str]:
    return {f"{{{namespace}}}{name}" for namespace in namespaces}


def _bounded_text(parts: Iterable[str]) -> str:
    lines = []
    remaining = MAX_TEXT_CHARS
    for part in parts:
        line = part.strip()
        if not line:
            continue
        lines.append(line[:remaining])
        remaining -= len(lines[-1]) + 1
        if remaining <= 0:
            break
    return "\n".join(lines)


def _text_file(content: bytes) -> str:
    if content.startswith((b"%PDF-", b"PK\x03\x04")):
        raise ValueError("Invalid text file")
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        decoded = content.decode("utf-16")
    else:
        try:
            decoded = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            decoded = content.decode("gb18030")

    if any(ord(char) < 32 and char not in "\t\n\r" for char in decoded):
        raise ValueError("Invalid text file")
    return _bounded_text(StringIO(decoded, newline=None))


def _xml(package: ZipFile, name: str) -> Element:
    member = package.getinfo(name)
    if member.file_size > MAX_XML_BYTES:
        raise AppError(413, "COURSEWARE_TOO_LARGE", "Office 文档的文字结构过大，请拆分后上传。")
    if member.flag_bits & 1 or member.compress_type not in (ZIP_STORED, ZIP_DEFLATED):
        raise ValueError("Unsupported archive entry")
    return ElementTree.fromstring(package.read(member), forbid_dtd=True)


def _paragraphs(root: Element, namespaces: set[str]) -> Iterator[str]:
    paragraph_tags = _tags(namespaces, "p")
    text_tags = _tags(namespaces, "t")
    line_break_tags = _tags(namespaces, "br")
    tab_tags = _tags(namespaces, "tab")
    for paragraph in root.iter():
        if paragraph.tag not in paragraph_tags:
            continue
        parts = []
        for item in paragraph.iter():
            if item.tag in text_tags:
                parts.append(item.text or "")
            elif item.tag in line_break_tags:
                parts.append("\n")
            elif item.tag in tab_tags:
                parts.append("\t")
        yield "".join(parts)


def _slides(package: ZipFile) -> Iterator[Element]:
    presentation = _xml(package, "ppt/presentation.xml")
    if presentation.tag not in _tags(PRESENTATION_NS, "presentation"):
        raise ValueError("Invalid presentation XML")

    relationships = _xml(package, "ppt/_rels/presentation.xml.rels")
    targets = {}
    for rel in relationships.findall(f"{{{PACKAGE_REL_NS}}}Relationship"):
        if rel.get("TargetMode") == "External" or not rel.get("Type", "").endswith("/slide"):
            continue
        target = rel.get("Target", "")
        path = PurePosixPath(target.lstrip("/") if target.startswith("/") else f"ppt/{target}")
        if path.parent != PurePosixPath("ppt/slides") or path.suffix != ".xml":
            raise ValueError("Invalid slide path")
        targets[rel.get("Id")] = path.as_posix()

    slide_list_tags = _tags(PRESENTATION_NS, "sldIdLst")
    slide_list = next((child for child in presentation if child.tag in slide_list_tags), None)
    if slide_list is None:
        return
    if len(slide_list) > MAX_DOCUMENT_PAGES:
        raise AppError(413, "COURSEWARE_TOO_LARGE", "PPTX 最多支持 60 页，请拆分后上传。")

    for slide in slide_list:
        relationship_id = next(
            (slide.get(f"{{{namespace}}}id") for namespace in RELATIONSHIP_NS if slide.get(f"{{{namespace}}}id")),
            None,
        )
        yield _xml(package, targets[relationship_id])


def _office(content: bytes, suffix: str) -> str:
    if not content.startswith(b"PK\x03\x04"):
        raise ValueError("Invalid Office archive")
    with ZipFile(BytesIO(content)) as package:
        members = package.infolist()
        if len(members) > 2_000 or sum(member.file_size for member in members) > MAX_OFFICE_BYTES:
            raise AppError(413, "COURSEWARE_TOO_LARGE", "Office 文档内部内容过大，请拆分后上传。")
        package.getinfo("[Content_Types].xml")
        if suffix == ".docx":
            document = _xml(package, "word/document.xml")
            if document.tag not in _tags(WORD_NS, "document"):
                raise ValueError("Invalid Word document XML")
            return _bounded_text(_paragraphs(document, WORD_NS))
        return _bounded_text(part for slide in _slides(package) for part in _paragraphs(slide, DRAWING_NS))


def _pdf(content: bytes) -> str:
    if not content.startswith(b"%PDF-"):
        raise ValueError("Invalid PDF header")
    try:
        with apply_configuration(
            maximum_declared_stream_length=MAX_COURSEWARE_BYTES,
            array_based_stream_maximum_output_length=MAX_XML_BYTES,
            zlib_maximum_output_length=MAX_XML_BYTES,
            zlib_maximum_recovery_input_length=1_000_000,
            lzw_maximum_output_length=MAX_XML_BYTES,
            run_length_maximum_output_length=MAX_XML_BYTES,
            brotli_maximum_output_length=MAX_XML_BYTES,
            stream_decoding_work_maximum_length=12_000_000,
            stream_parsing_work_maximum_count=100_000,
            xform_maximum_invocations_per_extraction=256,
            page_tree_maximum_entries=10_000,
            page_tree_maximum_page_entries=100_000,
            jbig2dec_binary=None,
        ):
            reader = PdfReader(BytesIO(content), strict=True, xref_stream_maximum_entries=100_000)
            if reader.is_encrypted:
                raise AppError(422, "INVALID_COURSEWARE", "PDF 已加密，请上传解密后的版本。")
            if len(reader.pages) > MAX_DOCUMENT_PAGES:
                raise AppError(413, "COURSEWARE_TOO_LARGE", "PDF 最多支持 60 页，请拆分后上传。")
            return _bounded_text(page.extract_text() or "" for page in reader.pages)
    except AppError:
        raise
    except LimitReachedError:
        raise AppError(413, "COURSEWARE_TOO_LARGE", "PDF 的解析内容过大，请拆分后上传。") from None
    except Exception:
        raise ValueError("Invalid PDF structure") from None


def extract_courseware(filename: str, content: bytes) -> str:
    """Return bounded, nonempty text suitable for drafting teaching slides."""
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix not in SUPPORTED:
        raise AppError(415, "UNSUPPORTED_COURSEWARE", "请选择 TXT、MD、DOCX、PPTX 或有文字的 PDF。")
    if not content:
        raise AppError(422, "EMPTY_COURSEWARE", "文件为空，请上传含有教学内容的文件。")
    if len(content) > MAX_COURSEWARE_BYTES:
        raise AppError(413, "COURSEWARE_TOO_LARGE", "教学材料不能超过 10 MB。")

    try:
        if suffix == ".pdf":
            text = _pdf(content)
        elif suffix in {".docx", ".pptx"}:
            text = _office(content, suffix)
        else:
            text = _text_file(content)
    except (BadZipFile, KeyError, OSError, ParseError, RuntimeError, ValueError, ZlibError):
        raise AppError(422, "INVALID_COURSEWARE", "文件格式有误或无法读取，请检查文件后重新上传。") from None
    if not text and suffix == ".pdf":
        raise AppError(422, "COURSEWARE_PDF_NO_TEXT", "没有读到 PDF 文字，请上传文字可复制的 PDF 或 DOCX。")
    if not text:
        raise AppError(422, "EMPTY_COURSEWARE", "没有读到教学文字，请上传含有教学内容的文件。")
    return text
