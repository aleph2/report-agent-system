"""Private, text-free failure evidence on the native LangChain callback lifecycle.

Independent files remain writable when the project SQLite store itself fails.
Never serialize exception messages, provider bodies, source lines or frame locals.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from langchain_core.callbacks import BaseCallbackHandler


class FailureDiagnostics(BaseCallbackHandler):
    run_inline = True

    def __init__(self, store):
        self.root = store.root
        self._saved = {}

    def record(self, error, *, phase="native_graph"):
        if id(error) in self._saved:
            return self._saved[id(error)][1]
        from .deep_models import error_data
        chain, seen, current = [], set(), error
        while isinstance(current, BaseException) and id(current) not in seen and len(chain) < 8:
            seen.add(id(current))
            frames, tb = [], current.__traceback__
            while tb is not None:
                code = tb.tb_frame.f_code
                frames.append({"file": code.co_filename, "function": code.co_name,
                               "line": tb.tb_lineno})
                tb = tb.tb_next
            item = {"type": type(current).__name__, "frames": frames}
            if isinstance(current, sqlite3.Error):
                item.update(sqlite_errorcode=getattr(current, "sqlite_errorcode", None),
                            sqlite_errorname=getattr(current, "sqlite_errorname", None))
            chain.append(item)
            current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
        identifier = str(uuid4())
        relative = Path("diagnostics") / "private" / (identifier + ".json")
        payload = {"id": identifier, "at": datetime.now(timezone.utc).isoformat(),
                   "phase": phase, "public_error": error_data(error), "exceptions": chain,
                   "chain_truncated": current is not None,
                   "privacy": "No exception text, source lines, locals, requests or responses."}
        try:
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
        except OSError:
            return None  # Diagnostic failure must not replace the application failure.
        result = {"diagnostic_id": identifier}
        self._saved[id(error)] = (error, result)
        return result

    def on_chain_error(self, error, *, parent_run_id=None, **kwargs):
        if parent_run_id is None:
            self.record(error)
