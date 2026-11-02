"""Immutable-content references and safe local document access."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_hash(value: object) -> str:
    return digest(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                             allow_nan=False).encode("utf-8"))


def contained(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("Expected a relative document path")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError("Document is missing or outside the packet directory")
    return path


def read_document(path: Path) -> dict:
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("Document exceeds the 20 MiB prototype limit")
    raw = path.read_bytes()
    if len(raw) > 20 * 1024 * 1024:
        raise ValueError("Document exceeds the 20 MiB prototype limit")
    words = []
    if path.suffix.lower() == ".pdf":
        binary = shutil.which("pdftotext")
        if not binary:
            raise ValueError("PDF ingestion requires Poppler's pdftotext; text files need no dependency")
        try:
            result = subprocess.run([binary, "-bbox-layout", str(path), "-"], capture_output=True,
                                    check=True, timeout=30)
            root = ET.fromstring(result.stdout)
        except (subprocess.SubprocessError, ET.ParseError) as exc:
            raise ValueError("PDF extraction failed; source review is required") from exc
        parts, pos = [], 0
        pages = [e for e in root.iter() if e.tag.split("}")[-1] == "page"]
        for page_no, page in enumerate(pages, 1):
            for line in page.iter():
                if line.tag.split("}")[-1] != "line":
                    continue
                for word in line:
                    if word.tag.split("}")[-1] != "word":
                        continue
                    text = "".join(word.itertext())
                    if not text:
                        continue
                    words.append({"start": pos, "end": pos + len(text), "page": page_no,
                                  "bbox": [float(word.attrib[k]) for k in ("xMin", "yMin", "xMax", "yMax")]})
                    parts.append(text + " ")
                    pos += len(text) + 1
                parts.append("\n")
                pos += 1
        text = "".join(parts)
        if not text.strip():
            raise ValueError("Image-only PDF: OCR is not implemented; review or supply a text transcription")
    else:
        text = raw.decode("utf-8")
    return {"sha256": digest(raw), "text_sha256": digest(text.encode()), "text": text, "words": words}


def span(document_id: str, document: dict, quote: str, clause: str = "") -> dict:
    text = document["text"]
    if not quote or text.count(quote) != 1:
        raise ValueError("Evidence quote must occur exactly once in its source")
    start = text.index(quote)
    end = start + len(quote)
    coordinates = [w for w in document.get("words", []) if w["start"] < end and w["end"] > start]
    return {"document_id": document_id, "document_sha256": document["sha256"],
            "text_sha256": document["text_sha256"], "clause": clause,
            "start": start, "end": end, "offset_unit": "unicode_codepoints",
            "start_line": text.count("\n", 0, start) + 1,
            "end_line": text.count("\n", 0, end) + 1, "quote": quote,
            "coordinates": coordinates}


def validate_span(reference: dict, documents: dict) -> None:
    if not isinstance(reference, dict):
        raise ValueError("Missing evidence reference")
    doc = documents.get(reference.get("document_id"))
    if doc is None:
        raise ValueError("Evidence refers to an unknown document")
    if reference.get("document_sha256") != doc["sha256"] or reference.get("text_sha256") != doc["text_sha256"]:
        raise ValueError("Source hash differs from the approved evidence")
    start, end = reference.get("start"), reference.get("end")
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(doc["text"]):
        raise ValueError("Invalid evidence coordinates")
    if reference.get("offset_unit") != "unicode_codepoints" or doc["text"][start:end] != reference.get("quote"):
        raise ValueError("Evidence span does not reproduce the cited quote")
    expected_coordinates = [w for w in doc.get("words", []) if w["start"] < end and w["end"] > start]
    if (reference.get("start_line") != doc["text"].count("\n", 0, start) + 1
            or reference.get("end_line") != doc["text"].count("\n", 0, end) + 1
            or reference.get("coordinates") != expected_coordinates):
        raise ValueError("Evidence line or PDF coordinates differ from the source")


def suspect_instructions(text: str) -> bool:
    patterns = [r"ignore\s+(?:all\s+|previous\s+|the\s+)?(?:instructions|caps|rules)",
                r"system\s*(?:prompt|message)\s*:", r"bypass\s+(?:review|approval)"]
    return any(re.search(p, text, re.I) for p in patterns)
