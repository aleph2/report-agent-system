"""Rank only the tool metadata supplied by the current role."""
from contextlib import closing, contextmanager
from contextvars import ContextVar
import inspect
import hashlib
import json
import math
from typing import Annotated, Literal, NotRequired

from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain.agents.middleware.types import PrivateStateAttr
from langchain.tools import ToolRuntime, tool
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.utils.function_calling import convert_to_openai_tool
from langgraph.types import Command

from langchain_core.tools import BaseTool, StructuredTool
import re
import sqlite3
import unicodedata


def _terms(value, *, unique=True):
    value = unicodedata.normalize("NFKC", value).casefold()
    result = re.findall(r"[a-z0-9]+", value)
    for text in re.findall(r"[\u3400-\u9fff]+", value):
        result.extend(text)
        result.extend(text[i:i+2] for i in range(len(text)-1))
    return list(dict.fromkeys(result)) if unique else result


def _native(value):
    return value if isinstance(value, BaseTool) else StructuredTool.from_function(
        coroutine=value if inspect.iscoroutinefunction(value) else None,
        func=None if inspect.iscoroutinefunction(value) else value)


def _merge_discovered(left, right):
    return {**(left or {}), **(right or {})}


class DiscoveryState(AgentState):
    _discovered_tools: NotRequired[Annotated[dict[str, str], PrivateStateAttr, _merge_discovered]]


class DiscoverySelectionState(AgentState):
    _discovered_tools: NotRequired[Annotated[dict[str, str], PrivateStateAttr]]


class ToolCatalog:
    @classmethod
    def from_registered(cls, tools):
        by_name = {}
        for tool in tools:
            name = getattr(tool, "name", None) or getattr(tool, "__name__", None)
            if name in by_name and by_name[name] is not tool:
                raise ValueError("Conflicting duplicate registered tool")
            by_name[name] = tool
        entries = []
        for name, tool in by_name.items():
            native = _native(tool)
            schema = native.tool_call_schema
            exposed = schema if isinstance(schema, dict) else schema.model_json_schema(by_alias=True)
            parameters = exposed.get("properties", {})
            entries.append({"name": name,
                "description": getattr(tool, "description", None) or getattr(tool, "__doc__", "") or "",
                "keywords": " ".join(key for key in parameters if key not in {"runtime", "config"})})
        return cls(entries)

    def __init__(self, tools, *, embedder=None):
        self.embedder = embedder
        self._vectors = None
        self.tools = {}
        self.keywords = {}
        for entry in tools:
            name, description = entry["name"], entry["description"]
            if not isinstance(name, str) or not name or name in self.tools or not isinstance(description, str):
                raise ValueError("Invalid or duplicate tool metadata")
            self.tools[name] = description
            keywords = entry.get("keywords", "")
            if not isinstance(keywords, str):
                raise ValueError("Invalid tool keywords")
            self.keywords[name] = keywords

    def search(self, query: str = "", offset: int = 0, limit: int = 10, mode: Literal["lexical", "hybrid"] = "lexical") -> dict:
        if (not isinstance(query, str) or len(query) > 500 or type(offset) is not int or offset < 0
                or type(limit) is not int or not 1 <= limit <= 50 or not isinstance(mode, str)
                or mode not in {"lexical", "hybrid"}):
            raise ValueError("Invalid search arguments")
        normalized = unicodedata.normalize("NFKC", query).casefold().strip()
        if not normalized:
            names = sorted(self.tools)
        else:
            terms = _terms(normalized)
            if len(terms) > 100:
                raise ValueError("Too many search terms")
            names = []
            if terms:
                with closing(sqlite3.connect(":memory:")) as db:
                    db.execute("CREATE VIRTUAL TABLE tools USING fts5(name UNINDEXED, content)")
                    db.executemany("INSERT INTO tools(name,content) VALUES (?,?)",
                                   [(name, " ".join(_terms(name + " " + description + " " + self.keywords[name], unique=False)))
                                    for name, description in self.tools.items()])
                    match = " OR ".join('"' + term + '"' for term in terms)
                    names = [row[0] for row in db.execute(
                        "SELECT name FROM tools WHERE tools MATCH ? ORDER BY bm25(tools), name", (match,))]
                names.sort(key=lambda name: unicodedata.normalize("NFKC", name).casefold() != normalized)
        lexical_match_count = len(names)
        if normalized and mode == "hybrid" and self.tools:
            try:
                if self.embedder is None:
                    from .embeddings import LocalEmbedding
                    self.embedder = LocalEmbedding(local_only=True)
                documents = list(self.tools)
                if self._vectors is None:
                    self._vectors = self.embedder.embed_documents([name + "\n" + self.tools[name] for name in documents])
                vector = self.embedder.embed_query(query)
                if len(self._vectors) != len(documents) or not vector or not all(math.isfinite(x) for x in vector):
                    raise ValueError("Invalid embedding")
                norm = math.sqrt(sum(x*x for x in vector))
                if not norm:
                    raise ValueError("Invalid embedding")
                scores = []
                for name, row in zip(documents, self._vectors):
                    if len(row) != len(vector) or not all(math.isfinite(x) for x in row):
                        raise ValueError("Invalid embedding")
                    row_norm = math.sqrt(sum(x*x for x in row))
                    if not row_norm:
                        raise ValueError("Invalid embedding")
                    scores.append((name, sum(a*b for a,b in zip(vector,row))/(norm*row_norm)))
                semantic = [name for name,_ in sorted(scores,key=lambda pair:(-pair[1],pair[0]))]
                ranks = {name:1/(60+i) for i,name in enumerate(names,1)}
                for i,name in enumerate(semantic,1):
                    ranks[name] = ranks.get(name,0) + 1/(60+i)
                names = sorted(ranks,key=lambda name:(unicodedata.normalize("NFKC",name).casefold()!=normalized,-ranks[name],name))
            except Exception as exc:
                raise ValueError("SEMANTIC_SEARCH_UNAVAILABLE") from exc
        selected = names[offset:offset+limit]
        result = {"matches": [{"name": name, "description": self.tools[name].split("\n",1)[0]}
                              for name in selected], "total": len(names),
                  "next_offset": offset + len(selected) if offset + len(selected) < len(names) else None}
        if normalized and mode == "hybrid":
            result["semantic_candidates_are_not_proof"] = True
            result["lexical_match_count"] = lexical_match_count
        return result


class ToolDiscovery(AgentMiddleware):
    """Expose original role tools after the agent searches their metadata."""
    state_schema = DiscoveryState

    def __init__(self, registered, *, profile="agent-search-v1"):
        super().__init__()
        if profile not in {"agent-search-v1", "agent-search-v2"}:
            raise ValueError("Unknown discovery profile")
        self.profile = profile
        if profile == "agent-search-v2":
            self.state_schema = DiscoverySelectionState
        self.catalog = ToolCatalog.from_registered(registered)
        self.fingerprints = {}
        for value in registered:
            native = _native(value)
            schema = convert_to_openai_tool(native)
            self.fingerprints[native.name] = hashlib.sha256(
                json.dumps(schema, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        catalog, fingerprints = self.catalog, self.fingerprints

        @tool
        def search_tools(query: str = "", offset: int = 0, limit: int = 10,
                         mode: Literal["lexical", "hybrid"] = "lexical",
                         runtime: ToolRuntime = None) -> Command:
            """Find available tools by name or purpose; an empty query browses the catalog.

            Query is at most 500 characters and 100 unique terms; offset is nonnegative,
            and limit is 1 to 50. Hybrid mode uses local semantic similarity as well as
            lexical matching; semantic candidates can be unrelated and are not proof.
            The lexical match count is reported separately. Search grants no authority.
            """
            from .errors import ActionRejected
            try:
                result = catalog.search(query, offset, limit, mode)
            except ValueError as exc:
                code = "SEMANTIC_SEARCH_UNAVAILABLE" if str(exc) == "SEMANTIC_SEARCH_UNAVAILABLE" else "INVALID_TOOL_SEARCH_ARGUMENTS"
                raise ActionRejected(code) from exc
            update = {"messages": [ToolMessage(content=json.dumps(result, ensure_ascii=False),
                                                tool_call_id=runtime.tool_call_id)]}
            if profile == "agent-search-v1":
                update["_discovered_tools"] = {item["name"]: fingerprints[item["name"]] for item in result["matches"]}
            return Command(update=update)
        self.tools = [search_tools]
        if profile == "agent-search-v2":
            @tool
            def select_tools(names: list[str], runtime: ToolRuntime = None) -> Command:
                """Replace the currently shown business tool schemas with these exact registered names.

                Search is optional. An empty list clears the selection; original permissions remain in force.
                """
                from .errors import ActionRejected
                if len(names) != len(set(names)) or any(name not in fingerprints for name in names):
                    raise ActionRejected("INVALID_TOOL_SELECTION")
                selected = {name: fingerprints[name] for name in names}
                return Command(update={"_discovered_tools": selected,
                    "messages": [ToolMessage(content=json.dumps({"selected": names}), tool_call_id=runtime.tool_call_id)]})
            self.tools.append(select_tools)

    async def awrap_model_call(self, request, handler):
        discovered = request.state.get("_discovered_tools") or {}
        visible = [item for item in request.tools if getattr(item, "name", None) not in self.fingerprints
                   or discovered.get(item.name) == self.fingerprints[item.name]]
        return await handler(request.override(tools=visible))

    async def awrap_tool_call(self, request, handler):
        if self.profile == "agent-search-v2" and request.tool_call.get("name") == "select_tools":
            messages = request.state.get("messages", [])
            latest = messages[-1] if messages else None
            if isinstance(latest, AIMessage) and (sum(call.get("name") == "select_tools" for call in latest.tool_calls) > 1
                    or any(call.get("name") in self.fingerprints for call in latest.tool_calls)):
                return ToolMessage(content="CONCURRENT_TOOL_SELECTION: choose tools in one separate call before business calls.",
                                   tool_call_id=request.tool_call["id"], name="select_tools", status="error")
        return await handler(request)

    async def aafter_model(self, state, runtime):
        if self.profile != "agent-search-v2" or not state.get("messages"):
            return None
        message = state["messages"][-1]
        if not isinstance(message, AIMessage):
            return None
        selected = state.get("_discovered_tools") or {}
        used = {call.get("name") for call in message.tool_calls}
        remaining = {name: fingerprint for name, fingerprint in selected.items() if name not in used}
        # Pending calls retain their tool node and exact arguments; only future schema exposure changes.
        return {"_discovered_tools": remaining} if remaining != selected else None


def bind_profile(store, profile):
    """Bind opt-in discovery before opening a fresh native checkpoint."""
    from .errors import ActionRejected
    if profile not in (None, "agent-search-v1", "agent-search-v2"):
        raise ActionRejected("UNKNOWN_TOOL_DISCOVERY_PROFILE")
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT value FROM state WHERE key=?", ("tool_discovery_binding",)).fetchone()
        if row is not None:
            if json.loads(row[0]) != profile:
                raise ActionRejected("TOOL_DISCOVERY_PROFILE_MISMATCH")
        elif profile is not None:
            if (store.root / "checkpoints.db").exists():
                raise ActionRejected("TOOL_DISCOVERY_REQUIRES_FRESH_CASE")
            db.execute("INSERT INTO state VALUES (?,?)", ("tool_discovery_binding", json.dumps(profile)))


_registry_compat = ContextVar('exact_registry_compatibility', default=None)


@contextmanager
def exact_registry_compatibility(store, *, old_runtime_ref, changes, checkpoint_ns, checkpoint_id,
                                 parent_checkpoint_id, diagnostic_id, diagnostic_sha256,
                                 expected_new_registry_digest, root_checkpoint_id=None):
    """One host-reviewed compatibility binding; never alter an old registry."""
    from .errors import ActionRejected
    from pathlib import Path
    root_checkpoint_id = parent_checkpoint_id if root_checkpoint_id is None else root_checkpoint_id
    names={'supervision_plugins.py','tool_discovery.py'}
    allowed_sets=(names,names | {'deep_runtime.py'})
    valid=lambda v:isinstance(v,str) and re.fullmatch(r'[0-9a-f]{64}',v) is not None
    if (not isinstance(changes,dict) or set(changes) not in allowed_sets or not valid(expected_new_registry_digest)
            or any(not isinstance(v,dict) or set(v)!={'old','new'} or not valid(v['old'])
                   or not valid(v['new']) or v['old']==v['new'] for v in changes.values())
            or not isinstance(old_runtime_ref,str) or not isinstance(checkpoint_ns,str)
            or not checkpoint_ns.startswith('tools:') or not checkpoint_id or not parent_checkpoint_id
            or not isinstance(root_checkpoint_id,str) or not root_checkpoint_id):
        raise ActionRejected('TOOL_DISCOVERY_COMPATIBILITY_INVALID')
    path=store.root/'diagnostics'/'private'/(diagnostic_id+'.json')
    try:
        if path.resolve().parent != (store.root/'diagnostics'/'private').resolve():
            raise ValueError()
        raw=path.read_bytes();diag=json.loads(raw)
        if (hashlib.sha256(raw).hexdigest()!=diagnostic_sha256 or diag.get('id')!=diagnostic_id
                or diag.get('phase')!='native_graph' or diag.get('public_error',{}).get('type')!='RequestBudgetExceeded'
                or diag.get('public_error',{}).get('message')!='HOST_TECHNICAL_FAILURE_PENDING'):
            raise ValueError()
        cpath=store.root/'checkpoints.db'
        with closing(sqlite3.connect(cpath.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            root=db.execute("SELECT checkpoint_id FROM checkpoints WHERE thread_id='report' AND checkpoint_ns='' ORDER BY checkpoint_id DESC LIMIT 1").fetchone()
            child=db.execute("SELECT checkpoint_id,metadata FROM checkpoints WHERE thread_id='report' AND checkpoint_ns=? ORDER BY checkpoint_id DESC LIMIT 1",(checkpoint_ns,)).fetchone()
        if not root or root[0]!=root_checkpoint_id or not child or child[0]!=checkpoint_id or json.loads(child[1]).get('parents',{}).get('')!=parent_checkpoint_id:
            raise ValueError()
    except (OSError,ValueError,TypeError,KeyError,sqlite3.Error) as exc:
        raise ActionRejected('TOOL_DISCOVERY_COMPATIBILITY_INVALID') from exc
    permit={'root':str(store.root.resolve()),'old_runtime_ref':old_runtime_ref,'changes':changes,
            'checkpoint_ns':checkpoint_ns,'checkpoint_id':checkpoint_id,'parent_checkpoint_id':parent_checkpoint_id,
            'root_checkpoint_id':root_checkpoint_id,
            'diagnostic_id':diagnostic_id,'diagnostic_sha256':diagnostic_sha256,
            'expected_new_registry_digest':expected_new_registry_digest,'used':False}
    token=_registry_compat.set(permit)
    try:
        yield
    finally:
        _registry_compat.reset(token)



def _compatibility_pins_unchanged(store, permit):
    try:
        path=store.root/'diagnostics'/'private'/(permit['diagnostic_id']+'.json')
        if path.resolve().parent != (store.root/'diagnostics'/'private').resolve() or hashlib.sha256(path.read_bytes()).hexdigest()!=permit['diagnostic_sha256']:
            return False
        cpath=store.root/'checkpoints.db'
        with closing(sqlite3.connect(cpath.resolve().as_uri()+'?mode=ro',uri=True)) as db:
            db.execute('PRAGMA query_only=ON')
            root=db.execute("SELECT checkpoint_id FROM checkpoints WHERE thread_id='report' AND checkpoint_ns='' ORDER BY checkpoint_id DESC LIMIT 1").fetchone()
            child=db.execute("SELECT checkpoint_id,metadata FROM checkpoints WHERE thread_id='report' AND checkpoint_ns=? ORDER BY checkpoint_id DESC LIMIT 1",(permit['checkpoint_ns'],)).fetchone()
        return bool(root and root[0]==permit['root_checkpoint_id'] and child and child[0]==permit['checkpoint_id'] and json.loads(child[1]).get('parents',{}).get('')==permit['parent_checkpoint_id'])
    except (OSError,ValueError,TypeError,KeyError,sqlite3.Error):
        return False


def _registry_compatible(db, store, fingerprints, identity, versions, stored_digest, new_digest, runtime_ref):
    permit=_registry_compat.get()
    if (not permit or permit['used'] or permit['root']!=str(store.root.resolve())
            or new_digest!=permit['expected_new_registry_digest'] or not runtime_ref
            or not _compatibility_pins_unchanged(store,permit)):
        return False
    old_row=db.execute('SELECT value FROM state WHERE key=?',(permit['old_runtime_ref'],)).fetchone()
    if not old_row or not isinstance(identity,dict):
        return False
    try:
        old=json.loads(old_row[0]); old_files=old['source_files'];new_files=identity['source_files']
        if (not isinstance(old_files,dict) or set(old_files)!=set(new_files)
                or old['project_file_sha256']!=identity['project_file_sha256']):
            return False
        actual={k for k in old_files if old_files[k]!=new_files[k]}
        if actual!=set(permit['changes']) or any(old_files[k]!=v['old'] or new_files[k]!=v['new'] for k,v in permit['changes'].items()):
            return False
        old_identity={'source_files':old_files,'project_file_sha256':old['project_file_sha256'],'framework_versions':versions}
        old_digest=hashlib.sha256(json.dumps({'tools':fingerprints,'runtime':old_identity},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        if old_digest!=stored_digest:
            return False
        audit={'old_registry_digest':stored_digest,'new_registry_digest':new_digest,
               'old_runtime_ref':permit['old_runtime_ref'],'new_runtime_ref':runtime_ref,
               'changes':permit['changes'],'checkpoint_ns':permit['checkpoint_ns'],
               'checkpoint_id':permit['checkpoint_id'],'parent_checkpoint_id':permit['parent_checkpoint_id'],
               'root_checkpoint_id':permit['root_checkpoint_id'],
               'diagnostic_id':permit['diagnostic_id'],'diagnostic_sha256':permit['diagnostic_sha256']}
        db.execute('INSERT INTO events(kind,data) VALUES (?,?)',('tool_discovery_exact_compatibility',json.dumps(audit,sort_keys=True)))
        permit['used']=True
        return True
    except (ValueError,TypeError,KeyError):
        return False


def bind_registry(store, fingerprints, *, runtime_ref=None):
    """Fence native checkpoint reuse against changed role tools and source."""
    from .errors import ActionRejected
    identity = None
    versions = None
    if runtime_ref is not None:
        capture = store.get(runtime_ref)
        files = capture.get("source_files") if isinstance(capture, dict) else None
        project = capture.get("project_file_sha256") if isinstance(capture, dict) else None
        valid_hash = lambda value: isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None
        if not isinstance(files, dict) or not files or not all(isinstance(k, str) and valid_hash(v) for k, v in files.items()) or not valid_hash(project):
            raise ActionRejected("TOOL_DISCOVERY_RUNTIME_IDENTITY_UNAVAILABLE")
        from importlib import metadata
        try:
            versions = {name: metadata.version(name) for name in (
                "deepagents", "langchain", "langchain-core", "langgraph",
                "langgraph-checkpoint", "langchain-openai")}
        except metadata.PackageNotFoundError as exc:
            raise ActionRejected("TOOL_DISCOVERY_RUNTIME_IDENTITY_UNAVAILABLE") from exc
        identity = {"source_files": files, "project_file_sha256": project, "framework_versions": versions}
    digest = hashlib.sha256(json.dumps({"tools": fingerprints, "runtime": identity}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        profile = db.execute("SELECT value FROM state WHERE key=?", ("tool_discovery_binding",)).fetchone()
        if profile is None or json.loads(profile[0]) not in {"agent-search-v1", "agent-search-v2"}:
            raise ActionRejected("TOOL_DISCOVERY_PROFILE_MISMATCH")
        row = db.execute("SELECT value FROM state WHERE key=?", ("tool_discovery_registry",)).fetchone()
        if row is None:
            db.execute("INSERT INTO state VALUES (?,?)", ("tool_discovery_registry", json.dumps(digest)))
        elif json.loads(row[0]) != digest:
            if not _registry_compatible(db, store, fingerprints, identity, versions, json.loads(row[0]), digest, runtime_ref):
                raise ActionRejected("TOOL_DISCOVERY_REGISTRY_MISMATCH")
