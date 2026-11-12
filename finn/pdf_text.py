"""Extract PDF text in one disposable process, with progress and a hard timeout.

PDFium calls never share an application thread/process with another extraction.
The worker reads a bounded local original and publishes no partial searchable data.
"""
import json
from contextlib import closing
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

MAX_TEXT_CHARS = 8_000_000


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, path)


def worker(source, output, progress, max_pages):
    try:
        import pypdfium2 as pdfium
        from pypdf import PdfReader
    except ImportError:
        write_json(output, {"error": "The fast PDF parser is unavailable. Rebuild FINN with the updated requirements.txt."})
        return
    try:
        # Preserve explicit encryption/page-count errors, using metadata only.
        with PdfReader(source) as probe:
            if probe.is_encrypted:
                raise ValueError("The PDF is encrypted. Use an unencrypted, text-searchable original.")
            total = len(probe.pages)
            if total > max_pages:
                raise ValueError(f"The PDF has {total} pages; FINN supports at most {max_pages} pages per document.")
        rows, characters = [], 0
        write_json(progress, [0, total])
        last = time.monotonic()
        with pdfium.PdfDocument(source) as document:
            for index in range(total):
                with closing(document[index]) as page:
                    with closing(page.get_textpage()) as textpage:
                        if characters + textpage.count_chars() > MAX_TEXT_CHARS:
                            raise ValueError("The PDF text exceeds FINN's 8-million-character indexing limit.")
                        # Include text outside the CropBox too; a default page-box
                        # extraction silently clips long lines in some originals.
                        body = " ".join(textpage.get_text_bounded(
                            left=-float("inf"), bottom=-float("inf"),
                            right=float("inf"), top=float("inf")).split())
                if body:
                    characters += len(body)
                    if characters > MAX_TEXT_CHARS:
                        raise ValueError("The PDF text exceeds FINN's 8-million-character indexing limit.")
                    rows.append([index + 1, body])
                if (index + 1) % 25 == 0 or index + 1 == total or time.monotonic() - last >= 1:
                    write_json(progress, [index + 1, total])
                    last = time.monotonic()
        if not rows:
            raise ValueError("This PDF has no selectable text. Import a text-searchable original.")
        write_json(output, {"pages": rows, "total_pages": total})
    except ValueError as exc:
        write_json(output, {"error": str(exc)})
    except Exception:
        write_json(output, {"error": "The PDF could not be decoded by the fast text reader. Existing indexed evidence was preserved."})


def extract(source, max_pages, *, progress=None, timeout=180):
    """Return all accepted text pages; a failed worker cannot replace old evidence."""
    with tempfile.TemporaryDirectory(prefix="finn-text-") as folder:
        output, state = Path(folder) / "result.json", Path(folder) / "progress.json"
        if isinstance(source, bytes):
            source_path = Path(folder) / "original.pdf"
            source_path.write_bytes(source)
        else:
            source_path = Path(source).resolve()
        # PDF parsing needs runtime paths/locales, never provider credentials.
        environment = {key: value for key, value in os.environ.items() if key in {
            "PATH", "SYSTEMROOT", "WINDIR", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH",
            "LANG", "LC_ALL", "PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}}
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), str(source_path),
                                    str(output), str(state), str(max_pages)],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, env=environment)
        started, previous = time.monotonic(), None
        try:
            while process.poll() is None:
                if time.monotonic() - started > timeout:
                    raise ValueError(f"PDF text extraction exceeded {timeout:g} seconds. Existing indexed evidence was preserved; try a smaller original.")
                if state.is_file():
                    current = json.loads(state.read_text(encoding="utf-8"))
                    if progress and current != previous:
                        progress(*current)
                    previous = current
                time.sleep(.05)
            if process.returncode != 0 or not output.is_file():
                raise ValueError("The PDF worker stopped before extraction finished. Existing indexed evidence was preserved.")
            result = json.loads(output.read_text(encoding="utf-8"))
            if result.get("error"):
                raise ValueError(result["error"])
            if progress:
                progress(result["total_pages"], result["total_pages"])
            return result["pages"]
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    worker(sys.argv[1], Path(sys.argv[2]), Path(sys.argv[3]), int(sys.argv[4]))
