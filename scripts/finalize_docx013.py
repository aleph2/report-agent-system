"""Update an existing DOCX TOC using installed Windows LibreOffice, never in place.

Run with any Windows Python 3.11+: python finalize_docx013.py INPUT.docx OUTPUT.docx
The installed LibreOffice Python runs the isolated UNO worker; no pip packages.
Also writes OUTPUT.finalize.json. Use --pdf for a separately named QA PDF.
This is a local format tool, not approval, report writing, or a runtime stage.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from xml.etree import ElementTree as ET
from zipfile import ZipFile


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def snapshot(path):
    """Compare visible body/table content, excluding only the TOC field cache."""
    with ZipFile(path) as package:
        for name in package.namelist():
            if name.endswith(".rels"):
                for rel in ET.fromstring(package.read(name)):
                    if rel.get("TargetMode") == "External" and not rel.get("Type", "").endswith("/hyperlink"):
                        raise ValueError("External linked content is not supported by this offline finalizer")
        root = ET.fromstring(package.read("word/document.xml"))
        media_count = sum(name.startswith("word/media/") for name in package.namelist())
    instructions = " ".join(node.text or "" for node in root.iter(W + "instrText"))
    if re.search(r"\b(?:INCLUDETEXT|INCLUDEPICTURE|DDEAUTO|DDE|DATABASE)\b", instructions, re.I):
        raise ValueError("External-data fields are not supported by this offline finalizer")
    fields, paragraphs, visible = [], [], {}
    for paragraph in root.iter(W + "p"):
        text = []
        for node in paragraph.iter():
            if node.tag == W + "fldChar":
                kind = node.get(W + "fldCharType")
                if kind == "begin":
                    fields.append("")
                elif kind == "end" and fields:
                    fields.pop()
            elif node.tag == W + "instrText" and fields:
                fields[-1] += node.text or ""
            elif node.tag in (W + "t", M + "t") and not any(re.match(r"\s*TOC\b", f) for f in fields):
                text.append(node.text or "")
        value = re.sub(r"\s+", "", "".join(text))
        visible[id(paragraph)] = value
        if value:
            paragraphs.append(value)
    tables = [[["".join(visible[id(p)] for p in cell.iter(W + "p"))
                for cell in row.findall(W + "tc")]
               for row in table.findall(W + "tr")]
              for table in root.iter(W + "tbl")]
    return {"paragraphs": paragraphs, "tables": tables, "media_count": media_count}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def worker(args):
    import uno

    def prop(name, value):
        item = uno.createUnoStruct("com.sun.star.beans.PropertyValue")
        item.Name, item.Value = name, value
        return item

    local = uno.getComponentContext()
    resolver = local.ServiceManager.createInstanceWithContext("com.sun.star.bridge.UnoUrlResolver", local)
    deadline = time.monotonic() + 30
    while True:
        try:
            context = resolver.resolve(f"uno:pipe,name={args.pipe};urp;StarOffice.ComponentContext")
            break
        except uno.getClass("com.sun.star.connection.NoConnectException"):
            if time.monotonic() >= deadline:
                raise TimeoutError("Isolated LibreOffice did not become ready")
            time.sleep(0.1)
    desktop = context.ServiceManager.createInstanceWithContext("com.sun.star.frame.Desktop", context)
    print("UNO connected", flush=True)
    document = None

    def open_doc(path):
        return desktop.loadComponentFromURL(Path(path).as_uri(), "_blank", 0, (
            prop("Hidden", True), prop("UpdateDocMode", 0), prop("MacroExecutionMode", 0),
        ))

    def indices(doc):
        all_indices = doc.getDocumentIndexes()
        result = [all_indices.getByIndex(i) for i in range(all_indices.getCount())]
        result = [index for index in result if index.supportsService("com.sun.star.text.ContentIndex")]
        if not result:
            raise ValueError("No existing TOC index found; this tool does not invent a contents page")
        return result

    def layout(doc):
        cursor = doc.getCurrentController().getViewCursor()
        cursor.jumpToLastPage()
        return cursor.getPage()

    def heading_pages(doc):
        cursor = doc.getCurrentController().getViewCursor()
        enumeration = doc.Text.createEnumeration()
        headings = []
        while enumeration.hasMoreElements():
            element = enumeration.nextElement()
            if element.supportsService("com.sun.star.text.Paragraph") and element.OutlineLevel:
                cursor.gotoRange(element.getStart(), False)
                headings.append({"text": element.String, "page": cursor.getPage()})
        return headings

    try:
        document = open_doc(args.input)
        print("Working copy loaded", flush=True)
        if document is None:
            raise ValueError("LibreOffice could not load the working copy")
        previous = None
        for attempt in range(1, 5):
            layout(document)
            for index in indices(document):
                index.update()
            current = (layout(document), [index.getAnchor().String for index in indices(document)])
            print(f"Index pass {attempt}: {current[0]} pages", flush=True)
            if current == previous:
                break
            previous = current
        else:
            raise ValueError("TOC pagination did not stabilize in four passes")
        if not all(text.strip() for text in current[1]):
            raise ValueError("TOC update returned an empty index")
        document.storeToURL(Path(args.output).as_uri(), (
            prop("FilterName", "Office Open XML Text"), prop("Overwrite", False),
        ))
        print("Updated DOCX saved", flush=True)
        document.setModified(False)
        document.close(True)
        document = None
        print("Working copy closed", flush=True)
        document = open_doc(args.output)
        print("Updated DOCX reopened", flush=True)
        reopened = [index.getAnchor().String for index in indices(document)]
        if reopened != current[1]:
            raise ValueError("Saved DOCX did not retain the updated TOC cache")
        result = {"update_passes": attempt, "page_count": layout(document),
                  "toc": reopened, "heading_pages": heading_pages(document),
                  "uno_python": sys.version, "uno_module": uno.__file__}
        if args.pdf:
            document.storeToURL(Path(args.pdf).as_uri(), (
                prop("FilterName", "writer_pdf_Export"), prop("Overwrite", False),
            ))
            print("QA PDF saved", flush=True)
        Path(args.worker_result).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    finally:
        try:
            if document is not None:
                document.setModified(False)
                document.close(True)
        finally:
            desktop.terminate()


def stop_owned(process):
    if process is None:
        return
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        # Popen retains the Windows process handle; no image-name or global process kill.
        process.kill()
        process.wait(timeout=10)


def finalize(args):
    if os.name != "nt":
        raise ValueError("Run this tool with Windows Python; it uses installed Windows LibreOffice")
    source, output = Path(args.input).resolve(strict=True), Path(args.output).resolve()
    record = output.with_suffix(".finalize.json")
    pdf = Path(args.pdf).resolve() if args.pdf else None
    targets = [output, record, *([pdf] if pdf else [])]
    if source.suffix.lower() != ".docx" or output.suffix.lower() != ".docx":
        raise ValueError("Input and output must be .docx")
    if len(set([source, *targets])) != len(targets) + 1 or any(path.exists() for path in targets):
        raise FileExistsError("Input/output/record/PDF must be distinct; existing outputs are never overwritten")
    program = Path(args.lo_program).resolve(strict=True)
    office_bin = program / "soffice.bin"
    interpreters = list(program.glob("python-core-*/bin/python.exe"))
    if len(interpreters) != 1:
        raise ValueError("Expected one installed LibreOffice python-core interpreter")
    uno_python = interpreters[0]
    core = uno_python.parent.parent
    environment = {**os.environ, "PYTHONHOME": str(core),
                   "PYTHONPATH": os.pathsep.join(map(str, (program, core / "lib", core / "lib/site-packages"))),
                   "UNO_PATH": str(program), "URE_BOOTSTRAP": "vnd.sun.star.pathname:" + str(program / "fundamental.ini"),
                   "PATH": str(program) + os.pathsep + os.environ.get("PATH", "")}
    flags = subprocess.CREATE_NO_WINDOW
    version = subprocess.run([str(office_bin), "--version"], capture_output=True, text=True,
                             check=True, timeout=15, creationflags=flags).stdout.strip()
    before_hash, before = sha256(source), snapshot(source)
    for path in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".finalize-docx013-", dir=output.parent) as directory:
        work = Path(directory).resolve()
        if not work.is_relative_to(output.parent) or work == output.parent:
            raise ValueError("Unsafe temporary directory")
        working, candidate, evidence = work / "input.docx", work / "output.docx", work / "worker.json"
        shutil.copyfile(source, working)
        if sha256(working) != before_hash:
            raise ValueError("Input changed while being copied")
        pipe = "finalize_docx013_" + uuid.uuid4().hex
        profile = work / "profile"
        command = [str(office_bin), "-env:UserInstallation=" + profile.as_uri(), "--headless", "--nologo",
                   "--nodefault", "--nofirststartwizard", "--norestore",
                   f"--accept=pipe,name={pipe};urp;StarOffice.ComponentContext"]
        office, client = None, None
        offices = []
        with (work / "office.log").open("wb") as office_log, (work / "worker.log").open("wb") as worker_log:
            try:
                office = subprocess.Popen(command, cwd=program, stdout=office_log, stderr=subprocess.STDOUT,
                                          creationflags=flags, env=environment)
                offices.append(office)
                worker_command = [str(uno_python), str(Path(__file__).resolve()), str(working), str(candidate),
                                  "--worker", "--pipe", pipe, "--worker-result", str(evidence)]
                if pdf:
                    worker_command.extend(["--pdf", str(work / "output.pdf")])
                client = subprocess.Popen(worker_command, cwd=program, stdout=worker_log,
                                          stderr=subprocess.STDOUT, creationflags=flags, env=environment)
                deadline = time.monotonic() + args.timeout
                while client.poll() is None:
                    # LibreOffice exithelper.h: 81 requests a normal profile restart.
                    if office.poll() == 81 and len(offices) == 1:
                        office = subprocess.Popen(command, cwd=program, stdout=office_log,
                                                  stderr=subprocess.STDOUT, creationflags=flags, env=environment)
                        offices.append(office)
                    elif office.poll() not in (None, 0):
                        raise RuntimeError(f"Isolated LibreOffice exited with {office.returncode}")
                    if time.monotonic() >= deadline:
                        raise TimeoutError("UNO finalization exceeded the configured timeout:\n"
                                           + (work / "worker.log").read_text(errors="replace"))
                    time.sleep(0.1)
                if client.returncode:
                    raise RuntimeError("UNO worker failed: " + (work / "worker.log").read_text(errors="replace")
                                       + f"\nOffice exit: {office.poll()}\n"
                                       + (work / "office.log").read_text(errors="replace"))
            finally:
                stop_owned(client)
                for owned in offices:
                    stop_owned(owned)
        after = snapshot(candidate)
        if before != after:
            missing = sum((Counter(before["paragraphs"]) - Counter(after["paragraphs"])).values())
            raise ValueError(f"DOCX preservation check failed ({missing} unmatched body paragraphs); no output published")
        if sha256(source) != before_hash:
            raise ValueError("Immutable input changed during processing; no output published")
        details = json.loads(evidence.read_text(encoding="utf-8"))
        details.update({"status": "finalized_not_engineering_approved", "at": datetime.now(timezone.utc).isoformat(),
                        "input": str(source), "output": str(output), "input_sha256": before_hash,
                        "input_sha256_after": sha256(source), "output_sha256": sha256(candidate),
                        "tool": str(Path(__file__).resolve()), "tool_sha256": sha256(__file__),
                        "libreoffice": version, "controller_python": sys.version,
                        "profile": str(profile), "owned_pids": [p.pid for p in offices] + [client.pid],
                        "owned_processes_exited": all(p.poll() is not None for p in offices) and client.poll() is not None,
                        "preserved_content_sha256": fingerprint(before),
                        "non_toc_paragraphs": len(before["paragraphs"]), "tables": len(before["tables"]),
                        "media_count": before["media_count"],
                        "limits": "Whitespace-normalized body/table preservation; not full style fidelity, Word pagination, or engineering approval."})
        if pdf:
            details.update(pdf=str(pdf), pdf_sha256=sha256(work / "output.pdf"))
        evidence.write_text(json.dumps(details, ensure_ascii=False, indent=2), encoding="utf-8")
        # Windows rename refuses existing destinations, including a race after preflight.
        candidate.rename(output)
        if pdf:
            (work / "output.pdf").rename(pdf)
        evidence.rename(record)
    print(json.dumps({"output": str(output), "record": str(record), "pages": details["page_count"],
                      "input_sha256": before_hash, "output_sha256": details["output_sha256"]}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("--pdf", help="Optional separate QA PDF (must not already exist)")
    parser.add_argument("--lo-program", default="C:/Program Files/LibreOffice/program")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--pipe", help=argparse.SUPPRESS)
    parser.add_argument("--worker-result", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        worker(args) if args.worker else finalize(args)
    except Exception as exc:
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
