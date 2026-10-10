"""Load the policy PDFs into Firestore as searchable chunks.

    uv run --group ingest python scripts/ingest.py --dry-run   # parse and print, no API calls
    uv run --group ingest python scripts/ingest.py             # parse, embed, write to Firestore

What it does, per PDF in data/policies/:
  1. Read the header: policy ID, title, department, version, effective date.
  2. Split the page into numbered sections ("1. Purpose and scope") and read each
     section's "Applies to:" line. Access is decided per section, not per document,
     because one document can hold rules for employees and contractors side by side.
  3. Pull tables out whole with pdfplumber, and turn each row into its own chunk with
     the column headers repeated ("Leave type: Earned leave; Days per year: 18; ...").
     Splitting tables by character count would cut rows in half and lose the headers.
  4. Check the parsed sections against data/policies/manifest.json and stop on any mismatch.
  5. Embed every chunk and write it to the Firestore collection `policy_chunks`, with
     for_employee / for_contractor flags that the search filters on.

Re-running is safe: chunk IDs are fixed (HR-001-s2-t1-r3), so documents are overwritten.
"""
import argparse
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber
from dotenv import load_dotenv

load_dotenv()

POLICY_DIR = Path("data/policies")
COLLECTION = "policy_chunks"
DIMENSIONS = 768                       # must match the Firestore vector index
EMBED_BATCH = 50

TITLE_RE = re.compile(r"^([A-Z]+-\d{3}): (.+)$")
META_RE = re.compile(r"Department: (\w+).*Version: ([\d.]+).*Effective: ([\d-]+)")
HEADING_RE = r"^\d+\. [A-Z].*$"
APPLIES_RE = re.compile(r"^Applies to: (.+)$")


@dataclass
class Section:
    number: int
    heading: str
    page: int
    audiences: set[str] = field(default_factory=set)   # {"employee", "contractor"}
    lines: list[str] = field(default_factory=list)
    tables: list[list[list[str]]] = field(default_factory=list)


@dataclass
class Chunk:
    id: str
    content: str
    data: dict


def audiences_from(text: str) -> set[str]:
    """'Employees, Contractors' -> {'employee', 'contractor'}"""
    return {a.strip().lower().rstrip("s") for a in text.split(",") if a.strip()}


def parse_pdf(path: Path) -> tuple[dict, list[Section]]:
    """Return the document header and its sections, with prose and tables kept apart."""
    doc: dict = {}
    sections: list[Section] = []
    with pdfplumber.open(path) as pdf:
        for page_no, page in enumerate(pdf.pages, 1):
            # Tables are found first, so their area can be left out of the prose.
            found = page.find_tables()

            def outside_tables(obj) -> bool:
                return not any(x0 <= obj.get("x0", 0) <= x1 and top <= obj.get("top", 0) <= bottom
                               for x0, top, x1, bottom in (t.bbox for t in found))

            # Prose lines top to bottom. A heading line opens a new section; every other
            # line belongs to the section above it (or to one carried over from the last page).
            starts: list[tuple[float, Section]] = []
            for line in page.filter(outside_tables).extract_text_lines():
                text, top = line["text"].strip(), line["top"]
                if not doc.get("policy_id") and (m := TITLE_RE.match(text)):
                    doc["policy_id"], doc["title"] = m.group(1), m.group(2)
                    continue
                if not doc.get("department") and (m := META_RE.search(text)):
                    doc["department"], doc["version"], doc["effective"] = m.groups()
                    continue
                if re.match(HEADING_RE, text):
                    number, heading = text.split(". ", 1)
                    sec = Section(int(number), heading.strip(), page_no)
                    sections.append(sec)
                    starts.append((top, sec))
                    continue
                if not sections:
                    continue                     # lines above the first section
                if m := APPLIES_RE.match(text):
                    sections[-1].audiences = audiences_from(m.group(1))
                else:
                    sections[-1].lines.append(text)

            # Each table goes to the last section that starts above it.
            carried = sections[-len(starts) - 1] if len(sections) > len(starts) else None
            for t in found:
                owner = carried
                for start_top, sec in starts:
                    if start_top < t.bbox[1]:
                        owner = sec
                rows = [[(c or "").replace("\n", " ").strip() for c in r] for r in t.extract()]
                if owner and rows:
                    owner.tables.append(rows)
    return doc, sections


def build_chunks(path: Path, doc: dict, sections: list[Section]) -> list[Chunk]:
    chunks = []
    for sec in sections:
        if not sec.audiences:
            raise ValueError(f"{path.name} section {sec.number} has no 'Applies to' line")
        label = f"{doc['policy_id']} {doc['title']}, section {sec.number}: {sec.heading}"
        base = {
            "policy_id": doc["policy_id"], "title": doc["title"], "department": doc["department"],
            "version": doc["version"], "effective": doc["effective"], "source": path.name,
            "page": sec.page, "section": sec.number, "heading": sec.heading,
            "applies_to": sorted(sec.audiences),
            "for_employee": "employee" in sec.audiences,
            "for_contractor": "contractor" in sec.audiences,
        }
        prose = " ".join(l for l in sec.lines if l and not l.startswith("Fictional document"))
        if prose:
            chunks.append(Chunk(f"{doc['policy_id']}-s{sec.number}-text",
                                f"{label}\n{prose}", {**base, "kind": "text"}))
        for ti, table in enumerate(sec.tables, 1):
            header, *rows = table
            for ri, row in enumerate(rows, 1):
                cells = "; ".join(f"{h}: {v}" for h, v in zip(header, row) if v)
                chunks.append(Chunk(f"{doc['policy_id']}-s{sec.number}-t{ti}-r{ri}",
                                    f"{label}\n{cells}", {**base, "kind": "table_row"}))
    return chunks


def check_against_manifest(parsed: dict[str, list[Section]]) -> None:
    """Stop if any section's audience differs from the answer key. A wrong tag is a data leak."""
    manifest = json.loads((POLICY_DIR / "manifest.json").read_text())
    problems = []
    for entry in manifest:
        got = {s.number: s for s in parsed.get(entry["policy_id"], [])}
        for expected in entry["sections"]:
            sec = got.get(expected["number"])
            if sec is None:
                problems.append(f"{entry['policy_id']} section {expected['number']} not found")
            elif sec.audiences != set(expected["applies_to"]):
                problems.append(f"{entry['policy_id']} section {sec.number}: parsed "
                                f"{sorted(sec.audiences)}, expected {expected['applies_to']}")
    if problems:
        raise SystemExit("Manifest check failed:\n  " + "\n  ".join(problems))
    print(f"Manifest check passed: {sum(len(e['sections']) for e in manifest)} sections match.")


def embed(texts: list[str]) -> list[list[float]]:
    from google import genai
    from google.genai import types

    client = genai.Client()
    config = types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT", output_dimensionality=DIMENSIONS)
    vectors = []
    for i in range(0, len(texts), EMBED_BATCH):
        result = client.models.embed_content(
            model=os.environ["EMBED_MODEL"], contents=texts[i:i + EMBED_BATCH], config=config)
        vectors.extend(e.values for e in result.embeddings)
    return vectors


def write(chunks: list[Chunk], vectors: list[list[float]]) -> None:
    from google.cloud import firestore
    from google.cloud.firestore_v1.vector import Vector

    db = firestore.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT"))
    batch = db.batch()
    for chunk, vector in zip(chunks, vectors, strict=True):
        batch.set(db.collection(COLLECTION).document(chunk.id),
                  {**chunk.data, "content": chunk.content, "embedding": Vector(vector)})
    batch.commit()                       # one batch is enough below 500 documents


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="parse and print; no API calls")
    args = parser.parse_args()

    chunks: list[Chunk] = []
    parsed: dict[str, list[Section]] = {}
    for path in sorted(POLICY_DIR.glob("*.pdf")):
        doc, sections = parse_pdf(path)
        parsed[doc["policy_id"]] = sections
        file_chunks = build_chunks(path, doc, sections)
        chunks.extend(file_chunks)
        print(f"{path.name}: {len(sections)} sections, {len(file_chunks)} chunks")

    check_against_manifest(parsed)
    print(f"{len(chunks)} chunks in total.")

    if args.dry_run:
        for c in chunks:
            who = ",".join(c.data["applies_to"])
            print(f"\n[{c.id}] ({c.data['kind']}, {who})\n{c.content}")
        return

    vectors = embed([c.content for c in chunks])
    write(chunks, vectors)
    print(f"Wrote {len(chunks)} chunks to Firestore collection '{COLLECTION}'.")


if __name__ == "__main__":
    main()
