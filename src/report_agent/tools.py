from __future__ import annotations

from .models import TextAnalysis
from .store import Store, digest


def material_tools(store: Store, analysis: TextAnalysis, *, owner: str):
    def project_status() -> dict:
        """Read the goal, source coverage, saved materials and unresolved issues."""
        result = store.status()
        store.event("tool", {"name": "project_status"})
        return result

    def read_sources(source_ids: list[str]) -> dict:
        """Read selected source IDs in this project; return original text and coverage."""
        result = store.sources(source_ids)
        store.event("tool", {"name": "read_sources", "source_ids": source_ids})
        return {"sources": result}

    def search_materials(query: str) -> dict:
        """Literal lookup in saved materials and sources. A miss is not missing evidence."""
        found = [a for a in store.artifacts() if query.casefold() in (a["title"] + a["body"]).casefold()]
        sources = [s for s in store.manifest["sources"] if query.casefold() in (s["title"] + s["content"]).casefold()]
        store.event("tool", {"name": "search_materials", "query": query})
        return {"artifacts": found, "sources": sources, "method": "literal substring, not semantic retrieval",
                "no_match_means": "not found by this query, not absent from project"}

    async def analyze_sources(source_ids: list[str], purpose: str) -> dict:
        """Optional bounded LLM analysis of selected sources; no saving or delegation."""
        selected = store.sources(source_ids)
        operation = digest({"purpose": purpose, "sources": selected, "goal": store.manifest["goal"],
                            "model": analysis.model.model, "contract": "text-analysis-v1"})
        cached = store.analysis(operation)
        store.event("tool", {"name": "analyze_sources", "source_ids": source_ids, "reused": cached is not None})
        if cached is not None:
            return {**cached, "reused": True}
        result = await analysis.analyze(purpose, selected, store.manifest["goal"])
        store.analysis(operation, result)
        return {**result, "reused": False}

    def save_material(title: str, body: str, source_ids: list[str]) -> dict:
        """Commit a materials result with source IDs; exact replay returns its receipt."""
        result = store.save_material(title, body, source_ids, owner=owner)
        store.event("tool", {"name": "save_material", "artifact_id": result["artifact"]["id"], "reused": result["reused"]})
        return result

    def select_result(artifact_id: str) -> dict:
        """Select an existing committed artifact as the task's draft result, not reviewed."""
        result = store.select_result(artifact_id)
        store.event("tool", {"name": "select_result", "artifact_id": artifact_id})
        return result

    def report_issue(category: str, description: str, source_ids: list[str]) -> dict:
        """Record source_conflict, source_missing or system_failure. Do not resolve it."""
        if category not in {"source_conflict", "source_missing", "system_failure"}:
            raise ValueError("INVALID_ISSUE_CATEGORY")
        store.sources(source_ids)
        issue = {"category": category, "description": description, "source_ids": source_ids, "resolved": False}
        issues = store.get("issues", [])
        if issue not in issues:
            store.set("issues", issues + [issue])
        store.event("tool", {"name": "report_issue", **issue})
        return {"recorded": True, "resolved": False, "decision": "human for source issues, operator for system failure"}

    return [project_status, read_sources, search_materials, analyze_sources, save_material, select_result, report_issue]
