"""Explicit provider bundles; credentials never fall across provider boundaries."""
import os
import sqlite3
from urllib.parse import urlparse
from dotenv import dotenv_values

COORDINATOR_EFFORT = 'REPORT_COORDINATOR_REASONING_EFFORT'
REVIEWER_EFFORT = 'REPORT_REVIEWER_REASONING_EFFORT'


def _effort(value):
    if value not in {'low', 'high', 'max'}:
        raise RuntimeError('DEEPSEEK_REASONING_EFFORT_INVALID')
    return value


def load_mixed_services(env_file):
    config = dotenv_values(env_file)
    overrides = {key: config.get(key, os.environ.get(key))
                 for key in (COORDINATOR_EFFORT, REVIEWER_EFFORT)}
    for override in overrides.values():
        if override is not None:
            try:
                _effort(override)
            except RuntimeError as exc:
                raise ValueError(str(exc)) from None
    bundles = {}
    for provider, prefix in (("deepseek", "HIGHWAY_MODEL_DEEPSEEK_"), ("glm", "HIGHWAY_MODEL_")):
        bundle = {k: config.get(prefix + k) for k in ("NAME", "BASE_URL", "API_KEY")}
        if not all(bundle.values()):
            raise ValueError("INCOMPLETE_MODEL_CONFIGURATION: " + provider)
        bundles[provider] = bundle
    endpoint = urlparse(bundles["deepseek"]["BASE_URL"])
    if endpoint.scheme != "https" or not endpoint.netloc:
        raise ValueError("DEEPSEEK_HTTPS_CONFIGURATION_REQUIRED")
    if bundles["glm"]["NAME"] != "glm-5.3" or not bundles["glm"]["BASE_URL"].startswith("https://"):
        raise ValueError("AUTHORIZED_GLM53_CONFIGURATION_REQUIRED")
    # Validate both complete bundles before changing the process configuration.
    for role, provider in ((None, "deepseek"), ("COORDINATOR", "deepseek"),
                           ("REVIEWER", "deepseek"), ("TEXT_TOOL", "deepseek"),
                           ("VISION", "deepseek"), ("RUBRIC_GRADER", "deepseek"),
                           ("GRADER_DIAGNOSTIC", "deepseek"), ("WRITER", "glm")):
        prefix = "REPORT_" if role is None else "REPORT_" + role + "_"
        for target, source in (("MODEL", "NAME"), ("BASE_URL", "BASE_URL"), ("API_KEY", "API_KEY")):
            os.environ[prefix + target] = bundles[provider][source]
    os.environ.pop("REPORT_GRADER_MODEL", None)
    os.environ["REPORT_REASONING_EFFORT"] = "max"
    for key, override in overrides.items():
        if override is not None:
            os.environ[key] = override
    # The official beta wire protocol is not a generic compatible API feature.
    os.environ["REPORT_DEEPSEEK_STRICT"] = "1" if endpoint.hostname == "api.deepseek.com" else "0"
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    return {role: {"model": bundles[provider]["NAME"], "base_url": bundles[provider]["BASE_URL"]}
            for role, provider in (("coordinator", "deepseek"), ("reviewer", "deepseek"), ("writer", "glm"))}


def role_service(role):
    prefix = "REPORT_" + role.upper() + "_"
    names = [prefix + k for k in ("MODEL", "BASE_URL", "API_KEY")]
    if any(k in os.environ for k in names):
        if not all(os.environ.get(k) for k in names):
            raise RuntimeError("INCOMPLETE_ROLE_SERVICE: " + role)
        return tuple(os.environ[k] for k in names)
    if role == "layout":
        # Presentation production uses the writer service unless explicitly configured.
        return role_service("writer")
    return tuple(os.environ.get("REPORT_" + k, "") for k in ("MODEL", "BASE_URL", "API_KEY"))


def bind_role_services(store):
    """Record effective role identities, never credentials; disallow silent resume switching."""
    effective = {role: {"model": role_service(role)[0].removeprefix("openai/"), "base_url": role_service(role)[1].rstrip("/")}
                 for role in ("coordinator", "reviewer", "writer", "text_tool", "layout")}
    effective["review_entrypoint"] = store.manifest.get("review_entrypoint", "delegated-reviewer-v1")
    previous = store.get("role_model_services")
    if previous and previous != effective:
        raise RuntimeError("ROLE_MODEL_SWITCH_REQUIRES_FRESH_PROJECT")
    generation = None
    if any(os.environ.get(key) is not None for key in (COORDINATOR_EFFORT, REVIEWER_EFFORT)) or store.get('role_generation') is not None:
        generation = {role: role_generation(store, role, *role_service(role)[:2])
                      for role in ('coordinator', 'reviewer', 'writer', 'text_tool', 'layout')}
    if previous is None:
        store.set("role_model_services", effective)
    if generation is not None and store.get('role_generation') is None:
        store.set('role_generation', generation)


def _execution_history(store):
    with store.connect() as db:
        if db.execute("SELECT 1 FROM events WHERE kind IN "
                      "('deep_model_request','model_transport_call','model_invocation_outcome') LIMIT 1").fetchone():
            return True
    path = store.root / 'checkpoints.db'
    if path.exists():
        try:
            with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='checkpoints'").fetchone():
                    return db.execute('SELECT 1 FROM checkpoints LIMIT 1').fetchone() is not None
        except sqlite3.DatabaseError:
            raise RuntimeError('ROLE_GENERATION_HISTORY_REQUIRES_FRESH_PROJECT') from None
    return False


def role_generation(store, role, name, url):
    """Resolve immutable factory options; providers encode their own wire fields."""
    deepseek = name.removeprefix('openai/').startswith('deepseek-')
    official = deepseek and urlparse(url).hostname == 'api.deepseek.com'
    setting = {'coordinator': COORDINATOR_EFFORT, 'reviewer': REVIEWER_EFFORT}.get(role)
    override = os.environ.get(setting) if setting else None
    if override is not None:
        _effort(override)
        if not deepseek or official:
            raise RuntimeError(role.upper() + '_GENERATION_OVERRIDE_REQUIRES_COMPATIBLE_DEEPSEEK')
    effort = (_effort(override if override is not None else
                      os.environ.get('REPORT_REASONING_EFFORT', 'max' if official else 'high'))
              if deepseek else 'high')
    effective = {'reasoning_effort': effort,
                 'max_tokens': 131072 if official and effort == 'max' else 65536,
                 'disable_streaming': True,
                 'extra_body': ({'thinking': {'type': 'enabled'}} if official else
                                {'enable_thinking': True} if deepseek else
                                {'thinking': {'type': 'enabled', 'clear_thinking': False}})}
    bound = store.get('role_generation')
    if bound is not None:
        if role in bound and bound[role] != effective:
            raise RuntimeError('ROLE_GENERATION_SWITCH_REQUIRES_FRESH_PROJECT')
        return dict(bound.get(role, effective))
    if override is not None and _execution_history(store):
        raise RuntimeError('ROLE_GENERATION_SWITCH_REQUIRES_FRESH_PROJECT')
    return effective
