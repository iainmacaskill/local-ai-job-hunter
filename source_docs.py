"""Store and read raw source CVs the user uploads as drafting context (Source CV tab).

Old CVs, LinkedIn exports, cover letters — anything with real career facts. More
than strictly needed is fine on purpose: profile_builder extracts only what is
literally stated across them, so extra source material just gives it more to
draw from, never anything to invent.

Local only: files live in ``source_docs/`` beside profile.json, gitignored,
never leave the machine.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

from docx import Document

REPO = Path(__file__).resolve().parent
SOURCE_DIR = Path(os.environ.get("CVDRAFTER_SOURCE_DIR", REPO / "source_docs"))

SUPPORTED_SUFFIXES = (".docx", ".pdf", ".txt")


def save_upload(name: str, data: bytes) -> Path:
    """Save an uploaded file's raw bytes under SOURCE_DIR. Returns its path.

    Deduplicated by content hash against what is already on disk, not just an
    in-session guard: Streamlit's file_uploader keeps resubmitting an already-
    selected file on reruns/reconnects (e.g. after an app restart), and a
    session-only guard does not survive that. Re-submitting the same file
    content just returns the existing path rather than creating another copy.
    """
    SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    digest = hashlib.md5(data).hexdigest()
    for existing in SOURCE_DIR.iterdir():
        if existing.is_file() and hashlib.md5(existing.read_bytes()).hexdigest() == digest:
            return existing
    safe = "".join(c for c in name if c not in '\\/:*?"<>|').strip() or "document"
    path = SOURCE_DIR / safe
    stem, suffix = path.stem, path.suffix
    n = 1
    while path.exists():
        path = SOURCE_DIR / f"{stem} ({n}){suffix}"
        n += 1
    path.write_bytes(data)
    return path


def extract_text(path: Path) -> str:
    """Best-effort plain text from a .docx/.pdf/.txt source file.

    Never raises: a file that cannot be read returns an empty string, so one
    bad upload does not sink extraction across the rest.
    """
    try:
        suffix = path.suffix.lower()
        if suffix == ".txt":
            return path.read_text(encoding="utf-8", errors="replace")
        if suffix == ".docx":
            doc = Document(str(path))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        if suffix == ".pdf":
            import pypdf

            reader = pypdf.PdfReader(str(path))
            return "\n".join((page.extract_text() or "") for page in reader.pages)
    except Exception:  # noqa: BLE001 - a bad file must not break the tab
        return ""
    return ""


def list_source_paths() -> list[Path]:
    """Saved source file paths. Cheap: no text extraction, just a directory scan."""
    if not SOURCE_DIR.is_dir():
        return []
    return sorted(p for p in SOURCE_DIR.iterdir() if p.suffix.lower() in SUPPORTED_SUFFIXES)


def list_sources() -> list[dict]:
    """Every saved source file with its extracted character count."""
    if not SOURCE_DIR.is_dir():
        return []
    out = []
    for path in sorted(SOURCE_DIR.iterdir()):
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        text = extract_text(path)
        out.append({"path": path, "name": path.name, "chars": len(text), "text": text})
    return out


def delete_source(path: Path) -> None:
    Path(path).unlink(missing_ok=True)


def combined_text(max_chars: int = 40_000) -> str:
    """All saved sources concatenated, each labelled, for one extraction call."""
    parts = []
    for s in list_sources():
        if s["text"].strip():
            parts.append(f"--- SOURCE: {s['name']} ---\n{s['text']}")
    return "\n\n".join(parts)[:max_chars]
