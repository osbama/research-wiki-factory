#!/usr/bin/env python3
"""repair_pdf.py — Detect and repair corrupt PDFs in a topic's inbox/papers.

Adapted from learn_and_teach repair_pdf.py for research-wiki-factory.

Flow per PDF:
1. DETECT   - real `pdfimages -png` probe into a temp dir (the same
              operation text extraction performs; `pdfimages -list` is
              NOT a valid probe — it can be silent on files whose
              streams fail during actual decoding).
2. REPAIR   - ghostscript pdfwrite rewrite to a temp file, re-detect;
              if clean, the original is replaced atomically.
3. TOLERATE - corruption that survives gs (undecodable embedded image
              streams) is registered in
              wikis/<topic>/_meta/corrupt_pdfs.json and left in place:
              the text layer usually extracts fine.

Usage:
    python3 repair_pdf.py <topic>                 # scan topic inbox (recursive)
    python3 repair_pdf.py <topic> --file PATH.pdf # single PDF

Exit code: 0 always (tolerated corruption is not an error).
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wf_common import load_config, get_wiki_path, get_inbox_path

GS_CMD = [
    "gs", "-sDEVICE=pdfwrite", "-dCompatibilityLevel=1.5",
    "-dNOPAUSE", "-dQUIET", "-dBATCH",
]


def detect(pdf_path: Path, work_dir: Path) -> tuple:
    """(corrupt: bool, n_warnings: int, exit_code: int)."""
    probe = work_dir / ".repair-probe"
    probe.mkdir(parents=True, exist_ok=True)
    r = None
    try:
        r = subprocess.run(["pdfimages", "-png", str(pdf_path), str(probe / "fig")],
                           capture_output=True, timeout=300)
    except FileNotFoundError:
        print("pdfimages not found (install poppler-utils)", file=sys.stderr)
        sys.exit(1)
    except subprocess.TimeoutExpired:
        return (True, -1, -1)
    finally:
        for f in probe.glob("fig-*"):
            f.unlink(missing_ok=True)
    n = len([l for l in r.stderr.decode("utf-8", errors="ignore").splitlines() if l.strip()])
    return (r.returncode != 0 or n > 0), n, r.returncode


def gs_rewrite(src: Path, dst: Path) -> bool:
    """Rewrite via ghostscript. Returns True on success."""
    try:
        r = subprocess.run(GS_CMD + [f"-sOutputFile={dst}", str(src)],
                           capture_output=True, timeout=600)
        return r.returncode == 0 and dst.exists() and dst.stat().st_size > 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def state_path(topic: str, config: dict) -> Path:
    return Path(get_wiki_path(topic, config)) / "_meta" / "corrupt_pdfs.json"


def load_state(topic: str, config: dict) -> dict:
    p = state_path(topic, config)
    return json.loads(p.read_text()) if p.exists() else {}


def save_state(topic: str, config: dict, state: dict) -> None:
    p = state_path(topic, config)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2))


def process_pdf(pdf_path: Path, state: dict, work_dir: Path) -> str:
    """Returns 'clean' | 'repaired' | 'tolerated'."""
    corrupt, n_warn, code = detect(pdf_path, work_dir)
    if not corrupt:
        state.pop(str(pdf_path.resolve()), None)
        return "clean"

    print(f"CORRUPT {pdf_path.name}: {n_warn} poppler warning(s), exit {code}")
    tmp = pdf_path.with_suffix(".repair-tmp.pdf")
    try:
        if shutil.which("gs") and gs_rewrite(pdf_path, tmp):
            still_corrupt, n2, _ = detect(tmp, work_dir)
            if not still_corrupt:
                os.replace(tmp, pdf_path)
                state.pop(str(pdf_path.resolve()), None)
                print("  REPAIRED via ghostscript rewrite (re-check clean)")
                return "repaired"
            print(f"  gs rewrite did not clear corruption ({n2} warnings remain)")
        else:
            print("  gs rewrite failed or gs unavailable")
    finally:
        tmp.unlink(missing_ok=True)

    state[str(pdf_path.resolve())] = {
        "status": "tolerated",
        "warnings": n_warn,
        "noted_at": datetime.now(timezone.utc).isoformat(),
        "note": "text layer usually extracts fine; warnings expected",
    }
    print("  TOLERATED (registered in _meta/corrupt_pdfs.json)")
    return "tolerated"


def main():
    parser = argparse.ArgumentParser(description="Detect/repair corrupt PDFs for a topic")
    parser.add_argument("topic")
    parser.add_argument("--file", help="single PDF instead of a full inbox scan")
    args = parser.parse_args()

    config = load_config()
    state = load_state(args.topic, config)

    if args.file:
        targets = [Path(args.file)]
    else:
        inbox = Path(get_inbox_path(args.topic, config)).expanduser()
        targets = sorted(inbox.rglob("*.pdf")) if inbox.exists() else []
    if not targets:
        print("No PDFs found.")
        return 0

    counts = {"clean": 0, "repaired": 0, "tolerated": 0}
    work_dir = Path(get_wiki_path(args.topic, config)) / "_meta"
    work_dir.mkdir(parents=True, exist_ok=True)
    for pdf_path in targets:
        outcome = process_pdf(pdf_path, state, work_dir)
        counts[outcome] += 1

    save_state(args.topic, config, state)
    print(f"\nDone: {counts['clean']} clean, {counts['repaired']} repaired, "
          f"{counts['tolerated']} tolerated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
