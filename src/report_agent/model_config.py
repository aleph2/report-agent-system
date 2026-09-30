"""Explicit provider bundles; credentials never fall across provider boundaries."""
import os
from dotenv import dotenv_values


def load_mixed_services(env_file):
    config = dotenv_values(env_file)
    bundles = {}
    for provider, prefix in (("deepseek", "HIGHWAY_MODEL_DEEPSEEK_"), ("glm", "HIGHWAY_MODEL_")):
        bundle = {k: config.get(prefix + k) for k in ("NAME", "BASE_URL", "API_KEY")}
        if not all(bundle.values()):
            raise ValueError("INCOMPLETE_MODEL_CONFIGURATION: " + provider)
        bundles[provider] = bundle
    if bundles["deepseek"]["NAME"] != "deepseek-flash" or bundles["deepseek"]["BASE_URL"].rstrip("/") != "https://api.deepseek.com":
        raise ValueError("OFFICIAL_DEEPSEEK_CONFIGURATION_REQUIRED")
    if bundles["glm"]["NAME"] != "glm-5.3" or not bundles["glm"]["BASE_URL"].startswith("https://"):
        raise ValueError("AUTHORIZED_GLM53_CONFIGURATION_REQUIRED")
    # Validate both complete bundles before changing the process configuration.
    for role, provider in ((None, "deepseek"), ("COORDINATOR", "deepseek"),
                           ("REVIEWER", "deepseek"), ("TEXT_TOOL", "deepseek"), ("WRITER", "glm")):
        prefix = "REPORT_" if role is None else "REPORT_" + role + "_"
        for target, source in (("MODEL", "NAME"), ("BASE_URL", "BASE_URL"), ("API_KEY", "API_KEY")):
            os.environ[prefix + target] = bundles[provider][source]
    os.environ.pop("REPORT_GRADER_MODEL", None)
    os.environ["REPORT_REASONING_EFFORT"] = "max"
    os.environ["REPORT_DEEPSEEK_STRICT"] = "1"
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
    return tuple(os.environ.get("REPORT_" + k, "") for k in ("MODEL", "BASE_URL", "API_KEY"))


def bind_role_services(store):
    """Record effective role identities, never credentials; disallow silent resume switching."""
    effective = {role: {"model": role_service(role)[0].removeprefix("openai/"), "base_url": role_service(role)[1].rstrip("/")}
                 for role in ("coordinator", "reviewer", "writer", "text_tool")}
    effective["review_entrypoint"] = store.manifest.get("review_entrypoint", "delegated-reviewer-v1")
    previous = store.get("role_model_services")
    if previous and previous != effective:
        raise RuntimeError("ROLE_MODEL_SWITCH_REQUIRES_FRESH_PROJECT")
    if previous is None:
        store.set("role_model_services", effective)
