# 本轮全部失败、错误与跳过

这是逐项原始结果索引，失败项数不等于独立产品缺陷数；尚未定位的原因保持未定。

## collection skipped: tests.test_gepa_report_adapter_optional

```text
('/mnt/c/Users/dongy/Documents/ChatGPT/report-agent-system/tests/test_gepa_report_adapter_optional.py', 6, "Skipped: could not import 'gepa': No module named 'gepa'")
```

## collection skipped: tests.test_learning_gepa_optional

```text
('/mnt/c/Users/dongy/Documents/ChatGPT/report-agent-system/tests/test_learning_gepa_optional.py', 9, "Skipped: could not import 'dspy': No module named 'dspy'")
```

## failed: tests/test_acceptance_runtime.py::test_standards_before_draft_same_version_in_actual_native_grader

```text
ws = <report_agent.workspace.Workspace object at 0x74b3859cfb90>

    async def test_standards_before_draft_same_version_in_actual_native_grader(ws):
        def grade(messages):
            active = active_criteria(ws)
            text = str(messages)
            assert active["id"] in text and active["criteria"][0]["id"] in text
            assert "selected report" in str(messages[0].content)
            assert "every criterion you cannot positively confirm should be marked failed" not in text
            return verdict(ws, ["satisfied"])
        driver = Driver(coordinator=[save_standards(), save_draft(ws), select, AIMessage(content="Saved.")],
                        rubric_grader=[grade])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_acceptance_runtime.py:87: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3859cfb90>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_acceptance_runtime.py::test_delegated_author_gets_criteria_before_first_generation

```text
ws = <report_agent.workspace.Workspace object at 0x74b385804ad0>

    async def test_delegated_author_gets_criteria_before_first_generation(ws):
        def deliver(messages):
            draft = next(r for r in ws.results() if r["kind"] == "draft")
            return invoke("select_delivery", draft_id=draft["id"])
        driver = Driver(coordinator=[save_standards(), invoke("task", subagent_type="writer",
                             description="Produce the source access report using the shared standards."),
                             deliver, AIMessage(content="Saved.")],
                        writer=[save_draft(ws), AIMessage(content="Draft saved.")],
                        rubric_grader=[lambda m: verdict(ws, ["satisfied"])])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_acceptance_runtime.py:112: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b385804ad0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_acceptance_runtime.py::test_unknown_only_is_terminal_without_author_rewrite

```text
ws = <report_agent.workspace.Workspace object at 0x74b385806ab0>

    async def test_unknown_only_is_terminal_without_author_rewrite(ws):
        driver = Driver(coordinator=[save_standards(), save_draft(ws), select, AIMessage(content="Saved.")],
                        rubric_grader=[lambda m: verdict(ws, ["undetermined"])])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_acceptance_runtime.py:122: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b385806ab0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_acceptance_runtime.py::test_exact_identity_coverage_uses_native_correction_retry[duplicate]

```text
ws = <report_agent.workspace.Workspace object at 0x74b3858ab170>
bad_names = 'duplicate'

    @pytest.mark.parametrize("bad_names", ["duplicate", "unknown", "omitted"])
    async def test_exact_identity_coverage_uses_native_correction_retry(ws, bad_names):
        seen = []
        def grade(messages):
            seen.append(messages)
            ids = [c["id"] for c in active_criteria(ws)["criteria"]]
            if len(seen) == 1:
                names = [ids[0], ids[0]] if bad_names == "duplicate" else [ids[0], "invented"] if bad_names == "unknown" else [ids[0]]
                return verdict(ws, ["satisfied"] * len(names), names)
            assert "without replacements, omissions or duplicates" in str(messages)
            return verdict(ws, ["satisfied", "satisfied"])
        driver = Driver(coordinator=[save_standards(True), save_draft(ws), select, AIMessage(content="Saved.")], rubric_grader=[grade])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_acceptance_runtime.py:151: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3858ab170>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_acceptance_runtime.py::test_exact_identity_coverage_uses_native_correction_retry[unknown]

```text
ws = <report_agent.workspace.Workspace object at 0x74b3858a99d0>
bad_names = 'unknown'

    @pytest.mark.parametrize("bad_names", ["duplicate", "unknown", "omitted"])
    async def test_exact_identity_coverage_uses_native_correction_retry(ws, bad_names):
        seen = []
        def grade(messages):
            seen.append(messages)
            ids = [c["id"] for c in active_criteria(ws)["criteria"]]
            if len(seen) == 1:
                names = [ids[0], ids[0]] if bad_names == "duplicate" else [ids[0], "invented"] if bad_names == "unknown" else [ids[0]]
                return verdict(ws, ["satisfied"] * len(names), names)
            assert "without replacements, omissions or duplicates" in str(messages)
            return verdict(ws, ["satisfied", "satisfied"])
        driver = Driver(coordinator=[save_standards(True), save_draft(ws), select, AIMessage(content="Saved.")], rubric_grader=[grade])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_acceptance_runtime.py:151: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3858a99d0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_acceptance_runtime.py::test_exact_identity_coverage_uses_native_correction_retry[omitted]

```text
ws = <report_agent.workspace.Workspace object at 0x74b385807140>
bad_names = 'omitted'

    @pytest.mark.parametrize("bad_names", ["duplicate", "unknown", "omitted"])
    async def test_exact_identity_coverage_uses_native_correction_retry(ws, bad_names):
        seen = []
        def grade(messages):
            seen.append(messages)
            ids = [c["id"] for c in active_criteria(ws)["criteria"]]
            if len(seen) == 1:
                names = [ids[0], ids[0]] if bad_names == "duplicate" else [ids[0], "invented"] if bad_names == "unknown" else [ids[0]]
                return verdict(ws, ["satisfied"] * len(names), names)
            assert "without replacements, omissions or duplicates" in str(messages)
            return verdict(ws, ["satisfied", "satisfied"])
        driver = Driver(coordinator=[save_standards(True), save_draft(ws), select, AIMessage(content="Saved.")], rubric_grader=[grade])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_acceptance_runtime.py:151: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b385807140>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_acceptance_runtime.py::test_repeated_incomplete_coverage_is_unverified_not_an_author_defect

```text
ws = <report_agent.workspace.Workspace object at 0x74b3859ce630>

    async def test_repeated_incomplete_coverage_is_unverified_not_an_author_defect(ws):
        seen = []
        def grade(messages):
            seen.append(messages)
            return verdict(ws, ["satisfied"], ["invented_id"])
        driver = Driver(coordinator=[save_standards(True), save_draft(ws), select, AIMessage(content="Saved.")], rubric_grader=[grade])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_acceptance_runtime.py:162: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3859ce630>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_acceptance_runtime.py::test_changed_standards_start_new_native_run_and_do_not_relabel_old_draft

```text
ws = <report_agent.workspace.Workspace object at 0x74b3858aa300>

    async def test_changed_standards_start_new_native_run_and_do_not_relabel_old_draft(ws):
        observed = []
        def grade(messages):
            observed.append(active_criteria(ws)["id"])
            return verdict(ws, ["not_satisfied"] if len(observed) == 1 else ["satisfied"])
        def clarify(messages):
            old = active_criteria(ws)
            return invoke("save_acceptance_criteria", title="Clarified acceptance", criteria=old["criteria"],
                          source_ids=["s"], input_ids=[], replaces_id=old["id"],
                          reason="Clarify citation evidence within the unchanged commission.")
        def revised(messages):
            assert project_state(ws)["delivery"]["status"] == "needs_attention"
            draft = next(r for r in ws.results() if r["kind"] == "draft")
            return save_draft(ws, replaces=draft["id"])(messages)
        driver = Driver(coordinator=[save_standards(), save_draft(ws, "Anytime access."), select,
                                     AIMessage(content="Saved."), clarify, revised, select, AIMessage(content="Corrected.")],
                        rubric_grader=[grade])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_acceptance_runtime.py:188: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3858aa300>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_acceptance_runtime.py::test_recovery_after_criteria_commit_keeps_one_version

```text
ws = <report_agent.workspace.Workspace object at 0x74b3858a9370>

    async def test_recovery_after_criteria_commit_keeps_one_version(ws):
        driver = Driver(coordinator=[save_standards(), save_draft(ws), select, AIMessage(content="Saved.")],
                        rubric_grader=[lambda m: verdict(ws, ["satisfied"])])
        driver.fail_once = ("coordinator", 1)
>       first = await deep_runtime.run_report(ws, driver)
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_acceptance_runtime.py:203: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3858a9370>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_acceptance_runtime.py::test_missing_preconditions_expose_recoverable_limitation_without_grader

```text
ws = <report_agent.workspace.Workspace object at 0x74b3858aa1b0>

    async def test_missing_preconditions_expose_recoverable_limitation_without_grader(ws):
>       first = await deep_runtime.run_report(ws, Driver(coordinator=[AIMessage(content="Finished.")]))
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_acceptance_runtime.py:213: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3858aa1b0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_acceptance_runtime.py::test_mixed_feedback_fixes_defect_and_preserves_unresolved_assessment

```text
ws = <report_agent.workspace.Workspace object at 0x74b3858ee300>

    async def test_mixed_feedback_fixes_defect_and_preserves_unresolved_assessment(ws):
        calls = []
        def grade(messages):
            calls.append(messages)
            return verdict(ws, ["not_satisfied", "undetermined"] if len(calls) == 1 else ["satisfied", "undetermined"])
        def revise(messages):
            feedback = next(m.content for m in reversed(messages) if m.name == "rubric_grader")
            unknown_id = active_criteria(ws)["criteria"][1]["id"]
            assert unknown_id not in feedback.split("Public acceptance observations")[0]
            assert "unresolved verification" in feedback
            draft = next(r for r in ws.results() if r["kind"] == "draft")
            return save_draft(ws, replaces=draft["id"])(messages)
        driver = Driver(coordinator=[save_standards(True), save_draft(ws, "Anytime access."), select,
                                     AIMessage(content="Saved."), revise, select, AIMessage(content="Corrected.")],
                        rubric_grader=[grade])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_acceptance_runtime.py:242: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3858ee300>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_catalog.py::test_completed_but_outdated_task_cannot_be_reported_as_reused

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_completed_but_outdated_ta0')

    async def test_completed_but_outdated_task_cannot_be_reported_as_reused(tmp_path):
        from report_agent.report_runtime import execute_task
        from test_report_trunk import baseline
        ws = workspace(tmp_path)
        draft = baseline(ws)
        Catalog(ws.store).import_file('access.txt', b'Synthetic updated source', 'access')
        def no_model(*args):
            raise AssertionError('An outdated committed task must request revision, not call a model.')
>       result = await execute_task(ws, draft['task_id'], no_model)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_catalog.py:102: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3846f65a0>
task_id = 'b4794e2b-2dd2-453d-ac3d-cf4dbb6f52d0'
model_factory = <function test_completed_but_outdated_task_cannot_be_reported_as_reused.<locals>.no_model at 0x74b384154ea0>

    async def execute_task(workspace: Workspace, task_id, model_factory):
>       raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: archived ADK task execution")
E       report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: archived ADK task execution

src/report_agent/report_runtime.py:221: ActionRejected
```

## failed: tests/test_claim_evidence_contract.py::test_contract_change_rejected_before_old_approval_early_return

```text
workspace = <report_agent.workspace.Workspace object at 0x74b3847c8440>
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b3847c8dd0>

    async def test_contract_change_rejected_before_old_approval_early_return(workspace, monkeypatch):
        from report_agent import deep_runtime
        fresh_import(workspace.store)
        configure_context_experiment(workspace.store, CANDIDATE)
        workspace.store.set("checkpoint_resume", False)
        monkeypatch.setattr(deep_runtime, "project_state", lambda ws: {"status": "reviewed_draft"})
        monkeypatch.setattr(review_contract, "CONTRACT_VERSION", "future-change")
        with pytest.raises(RuntimeError, match="REVIEW_CONTRACT_SWITCH_REQUIRES_FRESH_FORK"):
>           await deep_runtime.run_report(workspace, lambda role: pytest.fail("No model should be constructed"))

tests/test_claim_evidence_contract.py:153: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3847c8440>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_clean_trial014.py::test_clean_import_preserves_only_originals_and_frozen_blocks

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_clean_import_preserves_on0')

    def test_clean_import_preserves_only_originals_and_frozen_blocks(tmp_path):
        old = baseline(tmp_path / "baseline")
        destination = tmp_path / "clean"
        receipt = prepare(old.root, destination)
        fresh = Store(destination)
        with fresh.connect() as db:
>           assert {k for (k,) in db.execute("SELECT key FROM state")} == {
                "manifest", "status", "report_status", "clean_import"}
E           AssertionError: assert {'acceptance_...us', 'status'} == {'clean_impor...us', 'status'}
E             
E             Extra items in the left set:
E             'acceptance_default'
E             Use -v to get more diff

tests/test_clean_trial014.py:74: AssertionError
```

## failed: tests/test_clean_trial014.py::test_native_effective_tools_cannot_read_host_development_file[coordinator]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_native_effective_tools_ca0')
role = 'coordinator'

    @pytest.mark.parametrize("role", ["coordinator", "writer"])
    def test_native_effective_tools_cannot_read_host_development_file(tmp_path, role):
        old = baseline(tmp_path / "baseline")
        prepare(old.root, tmp_path / "clean")
        workspace = Workspace(Store(tmp_path / "clean"))
        host_file = tmp_path / "developer-only.md"
        host_file.write_text("HOST_DEVELOPMENT_SECRET", encoding="utf-8")
        script = [invoke("read_file", file_path=str(host_file)),
                  invoke("write_file", file_path="/scratch.txt", content="VIRTUAL_ONLY"),
                  invoke("read_file", file_path="/scratch.txt"),
                  invoke("ask_human", category="source_missing", description="Offline boundary test.")]
        scripts = {role: script}
        if role != "coordinator":
            scripts["coordinator"] = [invoke("task", subagent_type=role, description="Check synthetic file isolation.")]
        driver = Driver(**scripts)
    
        async def exercise():
            async with deep_runtime.project_agent(workspace, driver, rules=load_rules()) as agent:
                result = await agent.ainvoke(
                    {"messages": [("user", encode(deep_runtime.project_view(workspace)))], "rubric": load_rules()},
                    {"configurable": {"thread_id": "clean-isolation"}})
                assert result.get("__interrupt__")
    
>       asyncio.run(exercise())

tests/test_clean_trial014.py:115: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/runners.py:195: in run
    return runner.run(main)
           ^^^^^^^^^^^^^^^^
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/runners.py:118: in run
    return self._loop.run_until_complete(task)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/base_events.py:691: in run_until_complete
    return future.result()
           ^^^^^^^^^^^^^^^
tests/test_clean_trial014.py:109: in exercise
    async with deep_runtime.project_agent(workspace, driver, rules=load_rules()) as agent:
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/contextlib.py:210: in __aenter__
    return await anext(self.gen)
           ^^^^^^^^^^^^^^^^^^^^^
src/report_agent/deep_runtime.py:842: in project_agent
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b386b3ad80>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_clean_trial014.py::test_native_effective_tools_cannot_read_host_development_file[writer]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_native_effective_tools_ca1')
role = 'writer'

    @pytest.mark.parametrize("role", ["coordinator", "writer"])
    def test_native_effective_tools_cannot_read_host_development_file(tmp_path, role):
        old = baseline(tmp_path / "baseline")
        prepare(old.root, tmp_path / "clean")
        workspace = Workspace(Store(tmp_path / "clean"))
        host_file = tmp_path / "developer-only.md"
        host_file.write_text("HOST_DEVELOPMENT_SECRET", encoding="utf-8")
        script = [invoke("read_file", file_path=str(host_file)),
                  invoke("write_file", file_path="/scratch.txt", content="VIRTUAL_ONLY"),
                  invoke("read_file", file_path="/scratch.txt"),
                  invoke("ask_human", category="source_missing", description="Offline boundary test.")]
        scripts = {role: script}
        if role != "coordinator":
            scripts["coordinator"] = [invoke("task", subagent_type=role, description="Check synthetic file isolation.")]
        driver = Driver(**scripts)
    
        async def exercise():
            async with deep_runtime.project_agent(workspace, driver, rules=load_rules()) as agent:
                result = await agent.ainvoke(
                    {"messages": [("user", encode(deep_runtime.project_view(workspace)))], "rubric": load_rules()},
                    {"configurable": {"thread_id": "clean-isolation"}})
                assert result.get("__interrupt__")
    
>       asyncio.run(exercise())

tests/test_clean_trial014.py:115: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/runners.py:195: in run
    return runner.run(main)
           ^^^^^^^^^^^^^^^^
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/runners.py:118: in run
    return self._loop.run_until_complete(task)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/base_events.py:691: in run_until_complete
    return future.result()
           ^^^^^^^^^^^^^^^
tests/test_clean_trial014.py:109: in exercise
    async with deep_runtime.project_agent(workspace, driver, rules=load_rules()) as agent:
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/contextlib.py:210: in __aenter__
    return await anext(self.gen)
           ^^^^^^^^^^^^^^^^^^^^^
src/report_agent/deep_runtime.py:842: in project_agent
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b38829e4b0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## error: tests/test_completed_feedback_recovery.py::test_completed_copy_receives_feedback_and_normal_new_run_revises_with_fresh_review

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_completed_copy_receives_f0')

    @pytest.fixture
    async def completed(tmp_path):
        store = Store(tmp_path / "baseline")
        source = store.root / "sources/access.txt"
        source.parent.mkdir()
        source.write_bytes(b"Daytime access only.")
        store.initialize({"goal": "Compile a faithful source access summary.", "sources": [{
            "id": "s", "title": "Access notice", "content": "Daytime access only.", "coverage": "complete",
            "copied_path": "sources/access.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
        store.set("knowledge_enabled", False)
        Catalog(store)
        workspace = Workspace(store)
        driver = Driver(coordinator=[save_standards(), save_draft(workspace, "Anytime access [s]."),
                                     select, AIMessage(content="Saved synthetic draft.")],
                        rubric_grader=[lambda messages: verdict(workspace, ["satisfied"])])
>       result = await deep_runtime.run_report(workspace, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_completed_feedback_recovery.py:64: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37ed50470>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## error: tests/test_completed_feedback_recovery.py::test_refuses_unsafe_preparation_without_changing_baseline[hash-DRAFT_BODY_HASH_MISMATCH]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_refuses_unsafe_preparatio0')

    @pytest.fixture
    async def completed(tmp_path):
        store = Store(tmp_path / "baseline")
        source = store.root / "sources/access.txt"
        source.parent.mkdir()
        source.write_bytes(b"Daytime access only.")
        store.initialize({"goal": "Compile a faithful source access summary.", "sources": [{
            "id": "s", "title": "Access notice", "content": "Daytime access only.", "coverage": "complete",
            "copied_path": "sources/access.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
        store.set("knowledge_enabled", False)
        Catalog(store)
        workspace = Workspace(store)
        driver = Driver(coordinator=[save_standards(), save_draft(workspace, "Anytime access [s]."),
                                     select, AIMessage(content="Saved synthetic draft.")],
                        rubric_grader=[lambda messages: verdict(workspace, ["satisfied"])])
>       result = await deep_runtime.run_report(workspace, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_completed_feedback_recovery.py:64: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b384addbe0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## error: tests/test_completed_feedback_recovery.py::test_refuses_unsafe_preparation_without_changing_baseline[target-EXACT_SELECTED_DRAFT_REQUIRED]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_refuses_unsafe_preparatio1')

    @pytest.fixture
    async def completed(tmp_path):
        store = Store(tmp_path / "baseline")
        source = store.root / "sources/access.txt"
        source.parent.mkdir()
        source.write_bytes(b"Daytime access only.")
        store.initialize({"goal": "Compile a faithful source access summary.", "sources": [{
            "id": "s", "title": "Access notice", "content": "Daytime access only.", "coverage": "complete",
            "copied_path": "sources/access.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
        store.set("knowledge_enabled", False)
        Catalog(store)
        workspace = Workspace(store)
        driver = Driver(coordinator=[save_standards(), save_draft(workspace, "Anytime access [s]."),
                                     select, AIMessage(content="Saved synthetic draft.")],
                        rubric_grader=[lambda messages: verdict(workspace, ["satisfied"])])
>       result = await deep_runtime.run_report(workspace, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_completed_feedback_recovery.py:64: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b384adc410>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## error: tests/test_completed_feedback_recovery.py::test_refuses_unsafe_preparation_without_changing_baseline[source-SOURCE_HASH_MISMATCH]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_refuses_unsafe_preparatio2')

    @pytest.fixture
    async def completed(tmp_path):
        store = Store(tmp_path / "baseline")
        source = store.root / "sources/access.txt"
        source.parent.mkdir()
        source.write_bytes(b"Daytime access only.")
        store.initialize({"goal": "Compile a faithful source access summary.", "sources": [{
            "id": "s", "title": "Access notice", "content": "Daytime access only.", "coverage": "complete",
            "copied_path": "sources/access.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
        store.set("knowledge_enabled", False)
        Catalog(store)
        workspace = Workspace(store)
        driver = Driver(coordinator=[save_standards(), save_draft(workspace, "Anytime access [s]."),
                                     select, AIMessage(content="Saved synthetic draft.")],
                        rubric_grader=[lambda messages: verdict(workspace, ["satisfied"])])
>       result = await deep_runtime.run_report(workspace, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_completed_feedback_recovery.py:64: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37f55cf50>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## error: tests/test_completed_feedback_recovery.py::test_refuses_unsafe_preparation_without_changing_baseline[foreign_source_path-SOURCE_PATH_NOT_PROJECT_BOUND]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_refuses_unsafe_preparatio3')

    @pytest.fixture
    async def completed(tmp_path):
        store = Store(tmp_path / "baseline")
        source = store.root / "sources/access.txt"
        source.parent.mkdir()
        source.write_bytes(b"Daytime access only.")
        store.initialize({"goal": "Compile a faithful source access summary.", "sources": [{
            "id": "s", "title": "Access notice", "content": "Daytime access only.", "coverage": "complete",
            "copied_path": "sources/access.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
        store.set("knowledge_enabled", False)
        Catalog(store)
        workspace = Workspace(store)
        driver = Driver(coordinator=[save_standards(), save_draft(workspace, "Anytime access [s]."),
                                     select, AIMessage(content="Saved synthetic draft.")],
                        rubric_grader=[lambda messages: verdict(workspace, ["satisfied"])])
>       result = await deep_runtime.run_report(workspace, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_completed_feedback_recovery.py:64: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37f55e870>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## error: tests/test_completed_feedback_recovery.py::test_refuses_unsafe_preparation_without_changing_baseline[graph-REQUIREMENT_ACCEPTANCE_WITHOUT_GRAPH_REQUIRED]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_refuses_unsafe_preparatio4')

    @pytest.fixture
    async def completed(tmp_path):
        store = Store(tmp_path / "baseline")
        source = store.root / "sources/access.txt"
        source.parent.mkdir()
        source.write_bytes(b"Daytime access only.")
        store.initialize({"goal": "Compile a faithful source access summary.", "sources": [{
            "id": "s", "title": "Access notice", "content": "Daytime access only.", "coverage": "complete",
            "copied_path": "sources/access.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
        store.set("knowledge_enabled", False)
        Catalog(store)
        workspace = Workspace(store)
        driver = Driver(coordinator=[save_standards(), save_draft(workspace, "Anytime access [s]."),
                                     select, AIMessage(content="Saved synthetic draft.")],
                        rubric_grader=[lambda messages: verdict(workspace, ["satisfied"])])
>       result = await deep_runtime.run_report(workspace, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_completed_feedback_recovery.py:64: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37f55f650>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## error: tests/test_completed_feedback_recovery.py::test_refuses_unsafe_preparation_without_changing_baseline[resume-COMPLETED_SUCCESSFUL_BASELINE_REQUIRED]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_refuses_unsafe_preparatio5')

    @pytest.fixture
    async def completed(tmp_path):
        store = Store(tmp_path / "baseline")
        source = store.root / "sources/access.txt"
        source.parent.mkdir()
        source.write_bytes(b"Daytime access only.")
        store.initialize({"goal": "Compile a faithful source access summary.", "sources": [{
            "id": "s", "title": "Access notice", "content": "Daytime access only.", "coverage": "complete",
            "copied_path": "sources/access.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
        store.set("knowledge_enabled", False)
        Catalog(store)
        workspace = Workspace(store)
        driver = Driver(coordinator=[save_standards(), save_draft(workspace, "Anytime access [s]."),
                                     select, AIMessage(content="Saved synthetic draft.")],
                        rubric_grader=[lambda messages: verdict(workspace, ["satisfied"])])
>       result = await deep_runtime.run_report(workspace, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_completed_feedback_recovery.py:64: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37f0b40b0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## error: tests/test_completed_feedback_recovery.py::test_refuses_unsafe_preparation_without_changing_baseline[interrupt-COMPLETED_SUCCESSFUL_BASELINE_REQUIRED]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_refuses_unsafe_preparatio6')

    @pytest.fixture
    async def completed(tmp_path):
        store = Store(tmp_path / "baseline")
        source = store.root / "sources/access.txt"
        source.parent.mkdir()
        source.write_bytes(b"Daytime access only.")
        store.initialize({"goal": "Compile a faithful source access summary.", "sources": [{
            "id": "s", "title": "Access notice", "content": "Daytime access only.", "coverage": "complete",
            "copied_path": "sources/access.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
        store.set("knowledge_enabled", False)
        Catalog(store)
        workspace = Workspace(store)
        driver = Driver(coordinator=[save_standards(), save_draft(workspace, "Anytime access [s]."),
                                     select, AIMessage(content="Saved synthetic draft.")],
                        rubric_grader=[lambda messages: verdict(workspace, ["satisfied"])])
>       result = await deep_runtime.run_report(workspace, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_completed_feedback_recovery.py:64: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37f0b4c50>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## error: tests/test_completed_feedback_recovery.py::test_refuses_unsafe_preparation_without_changing_baseline[error-COMPLETED_SUCCESSFUL_BASELINE_REQUIRED]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_refuses_unsafe_preparatio7')

    @pytest.fixture
    async def completed(tmp_path):
        store = Store(tmp_path / "baseline")
        source = store.root / "sources/access.txt"
        source.parent.mkdir()
        source.write_bytes(b"Daytime access only.")
        store.initialize({"goal": "Compile a faithful source access summary.", "sources": [{
            "id": "s", "title": "Access notice", "content": "Daytime access only.", "coverage": "complete",
            "copied_path": "sources/access.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
        store.set("knowledge_enabled", False)
        Catalog(store)
        workspace = Workspace(store)
        driver = Driver(coordinator=[save_standards(), save_draft(workspace, "Anytime access [s]."),
                                     select, AIMessage(content="Saved synthetic draft.")],
                        rubric_grader=[lambda messages: verdict(workspace, ["satisfied"])])
>       result = await deep_runtime.run_report(workspace, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_completed_feedback_recovery.py:64: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37f55f740>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## error: tests/test_completed_feedback_recovery.py::test_refuses_unsafe_preparation_without_changing_baseline[standard-EXACT_HISTORICAL_SATISFIED_REVIEW_REQUIRED]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_refuses_unsafe_preparatio8')

    @pytest.fixture
    async def completed(tmp_path):
        store = Store(tmp_path / "baseline")
        source = store.root / "sources/access.txt"
        source.parent.mkdir()
        source.write_bytes(b"Daytime access only.")
        store.initialize({"goal": "Compile a faithful source access summary.", "sources": [{
            "id": "s", "title": "Access notice", "content": "Daytime access only.", "coverage": "complete",
            "copied_path": "sources/access.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
        store.set("knowledge_enabled", False)
        Catalog(store)
        workspace = Workspace(store)
        driver = Driver(coordinator=[save_standards(), save_draft(workspace, "Anytime access [s]."),
                                     select, AIMessage(content="Saved synthetic draft.")],
                        rubric_grader=[lambda messages: verdict(workspace, ["satisfied"])])
>       result = await deep_runtime.run_report(workspace, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_completed_feedback_recovery.py:64: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37f55f9b0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## error: tests/test_completed_feedback_recovery.py::test_refuses_unsafe_preparation_without_changing_baseline[preview-PREVIEW_PATH_NOT_BASELINE_BOUND]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_refuses_unsafe_preparatio9')

    @pytest.fixture
    async def completed(tmp_path):
        store = Store(tmp_path / "baseline")
        source = store.root / "sources/access.txt"
        source.parent.mkdir()
        source.write_bytes(b"Daytime access only.")
        store.initialize({"goal": "Compile a faithful source access summary.", "sources": [{
            "id": "s", "title": "Access notice", "content": "Daytime access only.", "coverage": "complete",
            "copied_path": "sources/access.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
        store.set("knowledge_enabled", False)
        Catalog(store)
        workspace = Workspace(store)
        driver = Driver(coordinator=[save_standards(), save_draft(workspace, "Anytime access [s]."),
                                     select, AIMessage(content="Saved synthetic draft.")],
                        rubric_grader=[lambda messages: verdict(workspace, ["satisfied"])])
>       result = await deep_runtime.run_report(workspace, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_completed_feedback_recovery.py:64: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b384add670>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## error: tests/test_completed_feedback_recovery.py::test_native_pending_checkpoint_is_refused_even_when_public_flags_say_complete

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_native_pending_checkpoint0')

    @pytest.fixture
    async def completed(tmp_path):
        store = Store(tmp_path / "baseline")
        source = store.root / "sources/access.txt"
        source.parent.mkdir()
        source.write_bytes(b"Daytime access only.")
        store.initialize({"goal": "Compile a faithful source access summary.", "sources": [{
            "id": "s", "title": "Access notice", "content": "Daytime access only.", "coverage": "complete",
            "copied_path": "sources/access.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
        store.set("knowledge_enabled", False)
        Catalog(store)
        workspace = Workspace(store)
        driver = Driver(coordinator=[save_standards(), save_draft(workspace, "Anytime access [s]."),
                                     select, AIMessage(content="Saved synthetic draft.")],
                        rubric_grader=[lambda messages: verdict(workspace, ["satisfied"])])
>       result = await deep_runtime.run_report(workspace, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_completed_feedback_recovery.py:64: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37f0b66f0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## error: tests/test_completed_feedback_recovery.py::test_existing_nested_live_and_symlink_destinations_are_refused

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_existing_nested_live_and_0')

    @pytest.fixture
    async def completed(tmp_path):
        store = Store(tmp_path / "baseline")
        source = store.root / "sources/access.txt"
        source.parent.mkdir()
        source.write_bytes(b"Daytime access only.")
        store.initialize({"goal": "Compile a faithful source access summary.", "sources": [{
            "id": "s", "title": "Access notice", "content": "Daytime access only.", "coverage": "complete",
            "copied_path": "sources/access.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
        store.set("knowledge_enabled", False)
        Catalog(store)
        workspace = Workspace(store)
        driver = Driver(coordinator=[save_standards(), save_draft(workspace, "Anytime access [s]."),
                                     select, AIMessage(content="Saved synthetic draft.")],
                        rubric_grader=[lambda messages: verdict(workspace, ["satisfied"])])
>       result = await deep_runtime.run_report(workspace, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_completed_feedback_recovery.py:64: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37f0b68a0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_deep_runtime.py::test_native_working_notes_and_todos_survive_reopen

```text
ws = <report_agent.workspace.Workspace object at 0x74b3854c4470>

    async def test_native_working_notes_and_todos_survive_reopen(ws):
        """Protocol evidence only: the scripted model does not prove autonomous progress."""
        def record_result(messages):
            total = observation(messages, "calculate")["total"]
            return invoke("write_file", file_path="/working-costs.md",
                          content=f"Adopted inputs: 10*0.6 + 20*0.4. Total: {total}. Remaining: draft.")
    
        todos = [{"content": "Batch A total verified: 14; inputs 10,20; weights 0.6,0.4",
                  "status": "completed"},
                 {"content": "Save comparison draft", "status": "pending"}]
        driver = Driver(coordinator=[invoke("calculate", terms=[["10", "0.6"], ["20", "0.4"]]),
                                    record_result, invoke("write_todos", todos=todos),
                                    AIMessage(content="Working state recorded")])
>       await run(ws, driver)

tests/test_deep_runtime.py:250: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
tests/test_deep_runtime.py:189: in run
    return await asyncio.wait_for(deep_runtime.run_report(ws, driver), timeout=30)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/tasks.py:520: in wait_for
    return await fut
           ^^^^^^^^^
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3854c4470>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_deep_runtime.py::test_repeat_feedback_reaches_agent_after_native_failure_recovery

```text
ws = <report_agent.workspace.Workspace object at 0x74b3856b14c0>
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b3856b2f30>

    async def test_repeat_feedback_reaches_agent_after_native_failure_recovery(ws, monkeypatch):
        original = deep_runtime.BusinessBoundary.awrap_tool_call
    
        async def old_failure(self, request, handler):
            if request.tool_call["id"] == "calc-2":
                raise RuntimeError("REPEATED_ACTION_WITHOUT_PROGRESS")
            return await original(self, request, handler)
    
        def react(messages):
            system = "\n".join(b["text"] for m in messages if m.type == "system"
                               for b in m.content_blocks if b["type"] == "text")
            assert "last three successful calls to calculate" in system
            assert observation(messages, "calculate")["total"] == "1"
            return draft_call()
    
        actions = [AIMessage(content="", tool_calls=[call("calculate", {"terms": [["1"]]}, f"calc-{i}")])
                   for i in range(3)]
        driver = Driver(coordinator=[*actions, react, final_receipt])
        monkeypatch.setattr(deep_runtime.BusinessBoundary, "awrap_tool_call", old_failure)
>       assert (await run(ws, driver))["status"] == "failed"
                ^^^^^^^^^^^^^^^^^^^^^

tests/test_deep_runtime.py:311: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
tests/test_deep_runtime.py:189: in run
    return await asyncio.wait_for(deep_runtime.run_report(ws, driver), timeout=30)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/tasks.py:520: in wait_for
    return await fut
           ^^^^^^^^^
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3856b14c0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_deep_runtime.py::test_repeated_submit_keeps_receipt_and_allows_progress

```text
ws = <report_agent.workspace.Workspace object at 0x74b3846aad20>

    async def test_repeated_submit_keeps_receipt_and_allows_progress(ws):
        def observe_receipt(messages):
            receipt = observation(messages, "submit_result")
            assert receipt["id"] == ws.results()[0]["id"]
            return AIMessage(content="Existing draft receipt recovered")
    
        driver = Driver(coordinator=[draft_call(), draft_call(), draft_call(), observe_receipt])
>       assert (await run(ws, driver))["status"] == "needs_attention"
                ^^^^^^^^^^^^^^^^^^^^^

tests/test_deep_runtime.py:330: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
tests/test_deep_runtime.py:189: in run
    return await asyncio.wait_for(deep_runtime.run_report(ws, driver), timeout=30)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/tasks.py:520: in wait_for
    return await fut
           ^^^^^^^^^
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3846aad20>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_deep_runtime.py::test_root_draft_native_reviewer_delivery_without_mandatory_chain

```text
ws = <report_agent.workspace.Workspace object at 0x74b3846a8ec0>
failure_stacks = []

    async def test_root_draft_native_reviewer_delivery_without_mandatory_chain(ws, failure_stacks):
        driver = trunk_driver()
>       status = await run(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^

tests/test_deep_runtime.py:337: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
tests/test_deep_runtime.py:189: in run
    return await asyncio.wait_for(deep_runtime.run_report(ws, driver), timeout=30)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/tasks.py:520: in wait_for
    return await fut
           ^^^^^^^^^
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3846a8ec0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_deep_runtime.py::test_optional_calculator_and_actual_export_observations

```text
ws = <report_agent.workspace.Workspace object at 0x74b3856b14c0>
failure_stacks = []

    async def test_optional_calculator_and_actual_export_observations(ws, failure_stacks):
        def calculated(messages):
            value = observation(messages, "calculate")
            assert value["total"] == "1.50" and not value["rounded"]
            return draft_call()
    
        def preview(messages):
            return invoke("preview_report", draft_id=observation(messages, "submit_result")["id"])
    
        def inspected(messages):
            value = observation(messages, "preview_report")
            assert value["preview"]["docx"]["sha256"] == value["content"]["docx_sha256"]
            assert value["preview"]["render"]["visual_verification"] == "not_performed"
            assert "east path" in value["content"]["text"]
            return delegate_review(messages)
    
        driver = Driver(coordinator=[invoke("calculate", terms=[["50", "0.03"]]), calculated,
                                      preview, inspected, deliver, AIMessage(content="Delivered")],
                        reviewer=[read_delegated_draft, submit_review, final_receipt])
>       status = await run(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^

tests/test_deep_runtime.py:371: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
tests/test_deep_runtime.py:189: in run
    return await asyncio.wait_for(deep_runtime.run_report(ws, driver), timeout=30)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/tasks.py:520: in wait_for
    return await fut
           ^^^^^^^^^
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3856b14c0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_deep_runtime.py::test_native_reviewer_can_use_exported_text_without_duplicate_read

```text
ws = <report_agent.workspace.Workspace object at 0x74b3842b7920>
failure_stacks = []

    async def test_native_reviewer_can_use_exported_text_without_duplicate_read(ws, failure_stacks):
        def preview_target(messages):
            request = next(m for m in reversed(messages) if isinstance(m, HumanMessage))
            return invoke("preview_report", draft_id=json.loads(request.content)["draft_id"])
    
        def review_preview(messages):
            content = observation(messages, "preview_report")["content"]
            assert "east path" in content["text"]
            return invoke("submit_result", kind="review", title="Export review", body="Checked saved export text.",
                          source_ids=["source"], target_id=content["draft_id"], outcome="accepted")
    
        driver = trunk_driver()
        driver.scripts["reviewer"] = [preview_target, review_preview, final_receipt]
>       status = await run(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^

tests/test_deep_runtime.py:392: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
tests/test_deep_runtime.py:189: in run
    return await asyncio.wait_for(deep_runtime.run_report(ws, driver), timeout=30)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/tasks.py:520: in wait_for
    return await fut
           ^^^^^^^^^
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3842b7920>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_deep_runtime.py::test_native_interrupt_rebuild_and_resume_without_recommitting[coordinator]

```text
ws = <report_agent.workspace.Workspace object at 0x74b3856b0ce0>
failure_stacks = [], role = 'coordinator'

    @pytest.mark.parametrize("role", ["coordinator", "writer"])
    async def test_native_interrupt_rebuild_and_resume_without_recommitting(ws, failure_stacks, role):
        ask = invoke("ask_human", category="source_conflict", description="Confirm daytime scope",
                     source_ids=["source"])
        driver = Driver(coordinator=[draft_call(), ask, AIMessage(content="Human answer recorded")])
        if role == "writer":
            driver.scripts["coordinator"] = [
                invoke("task", subagent_type="writer", description="Save a draft, then ask about scope"),
                AIMessage(content="Human answer recorded")]
            driver.scripts["writer"] = [draft_call(), ask, AIMessage(content="Human answer recorded")]
>       first = await run(ws, driver)
                ^^^^^^^^^^^^^^^^^^^^^

tests/test_deep_runtime.py:409: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
tests/test_deep_runtime.py:189: in run
    return await asyncio.wait_for(deep_runtime.run_report(ws, driver), timeout=30)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/tasks.py:520: in wait_for
    return await fut
           ^^^^^^^^^
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3856b0ce0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_deep_runtime.py::test_native_interrupt_rebuild_and_resume_without_recommitting[writer]

```text
ws = <report_agent.workspace.Workspace object at 0x74b37ea7f4d0>
failure_stacks = [], role = 'writer'

    @pytest.mark.parametrize("role", ["coordinator", "writer"])
    async def test_native_interrupt_rebuild_and_resume_without_recommitting(ws, failure_stacks, role):
        ask = invoke("ask_human", category="source_conflict", description="Confirm daytime scope",
                     source_ids=["source"])
        driver = Driver(coordinator=[draft_call(), ask, AIMessage(content="Human answer recorded")])
        if role == "writer":
            driver.scripts["coordinator"] = [
                invoke("task", subagent_type="writer", description="Save a draft, then ask about scope"),
                AIMessage(content="Human answer recorded")]
            driver.scripts["writer"] = [draft_call(), ask, AIMessage(content="Human answer recorded")]
>       first = await run(ws, driver)
                ^^^^^^^^^^^^^^^^^^^^^

tests/test_deep_runtime.py:409: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
tests/test_deep_runtime.py:189: in run
    return await asyncio.wait_for(deep_runtime.run_report(ws, driver), timeout=30)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/tasks.py:520: in wait_for
    return await fut
           ^^^^^^^^^
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37ea7f4d0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_deep_runtime.py::test_child_permissions_are_enforced_in_native_tool_calls[writer-materials]

```text
ws = <report_agent.workspace.Workspace object at 0x74b37ea7c080>
failure_stacks = [], role = 'writer', foreign_kind = 'materials'

    @pytest.mark.parametrize("role,foreign_kind", [("writer", "materials"), ("reviewer", "draft")])
    async def test_child_permissions_are_enforced_in_native_tool_calls(ws, failure_stacks, role, foreign_kind):
        forbidden = [call("knowledge_put", {"title": "Unauthorized", "body": "Must not persist",
                                            "source_ids": ["source"]}),
                     call("submit_result", {"kind": foreign_kind, "title": "Wrong owner", "body": "Blocked",
                                             "source_ids": ["source"], "input_ids": []}),
                     call("task", {"subagent_type": "knowledge", "description": "Nested delegation"}),
                     call("execute", {"command": "echo forbidden"})]
        driver = Driver(coordinator=[invoke("task", subagent_type=role, description="Boundary probe"),
                                     AIMessage(content="Checked")],
                        **{role: [AIMessage(content="", tool_calls=forbidden), AIMessage(content="Checked")]})
        knowledge = ForbiddenKnowledge()
>       status = await asyncio.wait_for(deep_runtime.run_report(ws, driver, knowledge=knowledge), 30)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_deep_runtime.py:463: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/tasks.py:520: in wait_for
    return await fut
           ^^^^^^^^^
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37ea7c080>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_deep_runtime.py::test_child_permissions_are_enforced_in_native_tool_calls[reviewer-draft]

```text
ws = <report_agent.workspace.Workspace object at 0x74b3842b6150>
failure_stacks = [], role = 'reviewer', foreign_kind = 'draft'

    @pytest.mark.parametrize("role,foreign_kind", [("writer", "materials"), ("reviewer", "draft")])
    async def test_child_permissions_are_enforced_in_native_tool_calls(ws, failure_stacks, role, foreign_kind):
        forbidden = [call("knowledge_put", {"title": "Unauthorized", "body": "Must not persist",
                                            "source_ids": ["source"]}),
                     call("submit_result", {"kind": foreign_kind, "title": "Wrong owner", "body": "Blocked",
                                             "source_ids": ["source"], "input_ids": []}),
                     call("task", {"subagent_type": "knowledge", "description": "Nested delegation"}),
                     call("execute", {"command": "echo forbidden"})]
        driver = Driver(coordinator=[invoke("task", subagent_type=role, description="Boundary probe"),
                                     AIMessage(content="Checked")],
                        **{role: [AIMessage(content="", tool_calls=forbidden), AIMessage(content="Checked")]})
        knowledge = ForbiddenKnowledge()
>       status = await asyncio.wait_for(deep_runtime.run_report(ws, driver, knowledge=knowledge), 30)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_deep_runtime.py:463: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/tasks.py:520: in wait_for
    return await fut
           ^^^^^^^^^
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3842b6150>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_deep_runtime.py::test_general_purpose_subagent_unavailable

```text
ws = <report_agent.workspace.Workspace object at 0x74b37ea7c7a0>
failure_stacks = []

    async def test_general_purpose_subagent_unavailable(ws, failure_stacks):
        driver = Driver(coordinator=[invoke("task", subagent_type="general-purpose", description="Do anything"),
                                     AIMessage(content="Rejected")])
>       status = await run(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^

tests/test_deep_runtime.py:488: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
tests/test_deep_runtime.py:189: in run
    return await asyncio.wait_for(deep_runtime.run_report(ws, driver), timeout=30)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/tasks.py:520: in wait_for
    return await fut
           ^^^^^^^^^
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37ea7c7a0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_deep_runtime.py::test_multiple_native_tasks_are_serialized_by_middleware

```text
ws = <report_agent.workspace.Workspace object at 0x74b3854bbf50>

    async def test_multiple_native_tasks_are_serialized_by_middleware(ws):
        driver = Driver(coordinator=[AIMessage(content="", tool_calls=[
            call("task", {"subagent_type": "writer", "description": "Independent probe A"}, "task-a"),
            call("task", {"subagent_type": "reviewer", "description": "Independent probe B"}, "task-b")]),
            AIMessage(content="Both finished")],
            writer=[AIMessage(content="Writer finished")], reviewer=[AIMessage(content="Reviewer finished")])
        driver.delay_children = True
        # Deliberately permit graph concurrency: the application's middleware must serialize.
>       async with deep_runtime.project_agent(ws, driver) as agent:
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_deep_runtime.py:505: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/contextlib.py:210: in __aenter__
    return await anext(self.gen)
           ^^^^^^^^^^^^^^^^^^^^^
src/report_agent/deep_runtime.py:842: in project_agent
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3854bbf50>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_deep_runtime.py::test_transient_model_failure_resumes_checkpoint_without_repeating_submit[coordinator-2]

```text
ws = <report_agent.workspace.Workspace object at 0x74b3854bb590>
failure_stacks = [], failed_role = 'coordinator', failed_step = 2

    @pytest.mark.parametrize("failed_role,failed_step", [("coordinator", 2), ("reviewer", 1)])
    async def test_transient_model_failure_resumes_checkpoint_without_repeating_submit(
            ws, failure_stacks, failed_role, failed_step):
        driver = trunk_driver()
        driver.fail_once = (failed_role, failed_step)
>       failed = await run(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^

tests/test_deep_runtime.py:521: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
tests/test_deep_runtime.py:189: in run
    return await asyncio.wait_for(deep_runtime.run_report(ws, driver), timeout=30)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/tasks.py:520: in wait_for
    return await fut
           ^^^^^^^^^
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3854bb590>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_deep_runtime.py::test_transient_model_failure_resumes_checkpoint_without_repeating_submit[reviewer-1]

```text
ws = <report_agent.workspace.Workspace object at 0x74b3842b7080>
failure_stacks = [], failed_role = 'reviewer', failed_step = 1

    @pytest.mark.parametrize("failed_role,failed_step", [("coordinator", 2), ("reviewer", 1)])
    async def test_transient_model_failure_resumes_checkpoint_without_repeating_submit(
            ws, failure_stacks, failed_role, failed_step):
        driver = trunk_driver()
        driver.fail_once = (failed_role, failed_step)
>       failed = await run(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^

tests/test_deep_runtime.py:521: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
tests/test_deep_runtime.py:189: in run
    return await asyncio.wait_for(deep_runtime.run_report(ws, driver), timeout=30)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/tasks.py:520: in wait_for
    return await fut
           ^^^^^^^^^
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3842b7080>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_deep_runtime.py::test_unknown_submit_outcome_replays_receipt_without_duplicate_commit

```text
ws = <report_agent.workspace.Workspace object at 0x74b3854b8ef0>
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b3842b5df0>
failure_stacks = []

    async def test_unknown_submit_outcome_replays_receipt_without_duplicate_commit(ws, monkeypatch, failure_stacks):
        original = ws.submit
        injected = False
    
        def commit_then_lose_response(*args, **kwargs):
            nonlocal injected
            receipt = original(*args, **kwargs)
            if not injected:
                injected = True
                raise httpx.ReadTimeout("offline response lost after durable commit")
            return receipt
    
        monkeypatch.setattr(ws, "submit", commit_then_lose_response)
        driver = Driver(coordinator=[draft_call(), final_receipt])
>       failed = await run(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^

tests/test_deep_runtime.py:557: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
tests/test_deep_runtime.py:189: in run
    return await asyncio.wait_for(deep_runtime.run_report(ws, driver), timeout=30)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/tasks.py:520: in wait_for
    return await fut
           ^^^^^^^^^
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3854b8ef0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_deep_runtime.py::test_checkpoint_with_old_draft_summary_field_resumes_as_draft_only

```text
ws = <report_agent.workspace.Workspace object at 0x74b3854b8f80>
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b3854baf60>

    async def test_checkpoint_with_old_draft_summary_field_resumes_as_draft_only(ws, monkeypatch):
        original = deep_runtime.BusinessBoundary.awrap_tool_call
    
        async def stop_before_tool(self, request, handler):
            if request.tool_call["name"] == "submit_result":
                raise RuntimeError("TEST_STOP_BEFORE_OLD_TOOL_CALL")
            return await original(self, request, handler)
    
        legacy = invoke("submit_result", kind="draft", title="Saved old request", body="Supplied daytime access",
                        source_ids=["source"], input_ids=[], outcome="A prose description, not an approval", target_id="")
        driver = Driver(coordinator=[legacy, final_receipt])
        monkeypatch.setattr(deep_runtime.BusinessBoundary, "awrap_tool_call", stop_before_tool)
>       assert (await run(ws, driver))["status"] == "failed"
                ^^^^^^^^^^^^^^^^^^^^^

tests/test_deep_runtime.py:589: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
tests/test_deep_runtime.py:189: in run
    return await asyncio.wait_for(deep_runtime.run_report(ws, driver), timeout=30)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/tasks.py:520: in wait_for
    return await fut
           ^^^^^^^^^
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3854b8f80>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_deep_runtime.py::test_reviewer_read_survives_child_interrupt_and_graph_rebuild

```text
ws = <report_agent.workspace.Workspace object at 0x74b37f7d7200>
failure_stacks = []

    async def test_reviewer_read_survives_child_interrupt_and_graph_rebuild(ws, failure_stacks):
        driver = trunk_driver()
        driver.scripts["reviewer"].insert(1, invoke(
            "ask_human", category="source_conflict", description="Confirm scope before review",
            source_ids=["source"]))
>       paused = await run(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^

tests/test_deep_runtime.py:610: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
tests/test_deep_runtime.py:189: in run
    return await asyncio.wait_for(deep_runtime.run_report(ws, driver), timeout=30)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/tasks.py:520: in wait_for
    return await fut
           ^^^^^^^^^
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37f7d7200>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_deep_runtime.py::test_separate_reviewer_delegations_cannot_share_read_observations[False]

```text
ws = <report_agent.workspace.Workspace object at 0x74b3854baa80>
failure_stacks = [], same_turn = False

    @pytest.mark.parametrize("same_turn", [False, True])
    async def test_separate_reviewer_delegations_cannot_share_read_observations(ws, failure_stacks, same_turn):
        def reviewer_request(messages):
            request = next(m for m in reversed(messages) if isinstance(m, HumanMessage))
            data = json.loads(request.content)
            if data.get("mode") == "submit_without_read":
                return invoke("submit_result", kind="review", title="Unread review", body="Must be rejected",
                              source_ids=[], input_ids=[data["draft_id"]], target_id=data["draft_id"],
                              outcome="accepted")
            return invoke("read_result", result_id=data["draft_id"])
    
        def second_review(messages):
            draft = observation(messages, "submit_result")
            return invoke("task", subagent_type="reviewer", description=json.dumps(
                {"draft_id": draft["id"], "mode": "submit_without_read"}))
    
        driver = Driver(coordinator=[draft_call(), delegate_review, second_review, AIMessage(content="Checked")],
                        reviewer=[reviewer_request, AIMessage(content="Probe finished")])
        if same_turn:
            def both_reviews(messages):
                first = delegate_review(messages).tool_calls[0]
                second = second_review(messages).tool_calls[0]
                return AIMessage(content="", tool_calls=[{**first, "id": "read-context"},
                                                         {**second, "id": "unread-context"}])
    
            driver.scripts["coordinator"] = [draft_call(), both_reviews, AIMessage(content="Checked")]
>       status = await run(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^

tests/test_deep_runtime.py:657: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
tests/test_deep_runtime.py:189: in run
    return await asyncio.wait_for(deep_runtime.run_report(ws, driver), timeout=30)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/tasks.py:520: in wait_for
    return await fut
           ^^^^^^^^^
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3854baa80>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_deep_runtime.py::test_separate_reviewer_delegations_cannot_share_read_observations[True]

```text
ws = <report_agent.workspace.Workspace object at 0x74b3842b44a0>
failure_stacks = [], same_turn = True

    @pytest.mark.parametrize("same_turn", [False, True])
    async def test_separate_reviewer_delegations_cannot_share_read_observations(ws, failure_stacks, same_turn):
        def reviewer_request(messages):
            request = next(m for m in reversed(messages) if isinstance(m, HumanMessage))
            data = json.loads(request.content)
            if data.get("mode") == "submit_without_read":
                return invoke("submit_result", kind="review", title="Unread review", body="Must be rejected",
                              source_ids=[], input_ids=[data["draft_id"]], target_id=data["draft_id"],
                              outcome="accepted")
            return invoke("read_result", result_id=data["draft_id"])
    
        def second_review(messages):
            draft = observation(messages, "submit_result")
            return invoke("task", subagent_type="reviewer", description=json.dumps(
                {"draft_id": draft["id"], "mode": "submit_without_read"}))
    
        driver = Driver(coordinator=[draft_call(), delegate_review, second_review, AIMessage(content="Checked")],
                        reviewer=[reviewer_request, AIMessage(content="Probe finished")])
        if same_turn:
            def both_reviews(messages):
                first = delegate_review(messages).tool_calls[0]
                second = second_review(messages).tool_calls[0]
                return AIMessage(content="", tool_calls=[{**first, "id": "read-context"},
                                                         {**second, "id": "unread-context"}])
    
            driver.scripts["coordinator"] = [draft_call(), both_reviews, AIMessage(content="Checked")]
>       status = await run(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^

tests/test_deep_runtime.py:657: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
tests/test_deep_runtime.py:189: in run
    return await asyncio.wait_for(deep_runtime.run_report(ws, driver), timeout=30)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/tasks.py:520: in wait_for
    return await fut
           ^^^^^^^^^
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3842b44a0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_deepseek_strict.py::test_all_native_and_business_tools_compile

```text
ws = <report_agent.workspace.Workspace object at 0x74b3842b6d80>

    async def test_all_native_and_business_tools_compile(ws):
        seed(ws)
        d = Driver(coordinator=[invoke('task', subagent_type='writer', description='Inspect only; return observations.'),
                                AIMessage(content='Unresolved; no delivery selected.')],
                   writer=[AIMessage(content='No content changes.')])
>       result = await run_report(ws, d)
                 ^^^^^^^^^^^^^^^^^^^^^^^

tests/test_deepseek_strict.py:45: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3842b6d80>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_deepseek_strict.py::test_actual_union_failure_reports_missing_wire_field

```text
ws = <report_agent.workspace.Workspace object at 0x74b37f7f9a90>

    def test_actual_union_failure_reports_missing_wire_field(ws):
        f = next(function(t) for t in business_tools(ws, 'coordinator', None, None) if t.__name__ == 'commit_objects')
        from test_content_tool_inputs import node
>       codec = StrictCodec(f)
                ^^^^^^^^^^^^^^

tests/test_deepseek_strict.py:107: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deepseek_strict.py:198: in __init__
    self.node = compile_node(function['parameters'])
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
src/report_agent/deepseek_strict.py:139: in compile_node
    children = {k: compile_node(s) for k, s in properties.items()}
                   ^^^^^^^^^^^^^^^
src/report_agent/deepseek_strict.py:169: in compile_node
    child = compile_node(source.get('items', {}))
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
src/report_agent/deepseek_strict.py:107: in compile_node
    nodes = [compile_node(s) for s in choices]
             ^^^^^^^^^^^^^^^
src/report_agent/deepseek_strict.py:139: in compile_node
    children = {k: compile_node(s) for k, s in properties.items()}
                   ^^^^^^^^^^^^^^^
src/report_agent/deepseek_strict.py:107: in compile_node
    nodes = [compile_node(s) for s in choices]
             ^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

source = {'additionalProperties': False, 'allOf': [{'if': {'properties': {'kind': {'enum': [...]}}, 'required': ['kind']}, 'the...'structure'], 'title': 'Claim Kind', 'type': 'string'}}, 'required': ['kind', 'body', 'qualifiers', 'claim_kind'], ...}

    def compile_node(source):
        source = deepcopy(source)
        supported = {'type', 'properties', 'required', 'additionalProperties', 'items', 'anyOf', 'oneOf',
                     'description', 'enum', 'const', 'pattern', 'format', 'minimum', 'maximum',
                     'exclusiveMinimum', 'exclusiveMaximum', 'multipleOf', 'title', 'default',
                     'minLength', 'maxLength', 'minItems', 'maxItems', 'discriminator'}
        if set(source) - supported:
>           raise WireError('Unsupported source schema keywords: ' + ','.join(sorted(set(source) - supported)))
E           report_agent.deepseek_strict.WireError: Unsupported source schema keywords: allOf

src/report_agent/deepseek_strict.py:103: WireError
```

## failed: tests/test_evidence_tools016.py::test_native_search_unknown_argument_feedback_then_correction[coordinator]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_native_search_unknown_arg0')
role = 'coordinator'

    @pytest.mark.parametrize("role", ["coordinator", "rubric_grader"])
    async def test_native_search_unknown_argument_feedback_then_correction(tmp_path, role):
        ws = workspace(tmp_path)
        ws.store.set("acceptance_mode", "legacy")  # Historical source-tool/rubric fixture.
        ws.initialize()
    
        def correct(messages):
            error = observation(messages, "search_sources")
            assert not error["accepted"]
            assert "SEARCH_ARGUMENTS_MUST_BE" in str(error)
            assert [m for m in messages if isinstance(m, ToolMessage)][-1].status == "error"
            return invoke("search_sources", query="Frozen", source_id="original")
    
        def checked(messages):
            result = observation(messages, "search_sources")
            assert result["scope"]["searched_source_ids"] == ["original"]
            assert result["total"] == 1
            return verdict("satisfied") if role == "rubric_grader" else save()
    
        def save():
            return invoke("submit_result", title="Report", body="Frozen OCR [original].",
                          source_ids=["original"], input_ids=[], replaces_id="")
    
        steps = [invoke("search_sources", query="Frozen", source="original"), correct, checked]
        driver = Driver(coordinator=steps + [select, AIMessage(content="Ready")] if role == "coordinator"
                        else [save(), select, AIMessage(content="Ready")],
                        rubric_grader=steps if role == "rubric_grader" else [verdict("satisfied")])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_evidence_tools016.py:82: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b38572f800>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_evidence_tools016.py::test_native_search_unknown_argument_feedback_then_correction[rubric_grader]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_native_search_unknown_arg1')
role = 'rubric_grader'

    @pytest.mark.parametrize("role", ["coordinator", "rubric_grader"])
    async def test_native_search_unknown_argument_feedback_then_correction(tmp_path, role):
        ws = workspace(tmp_path)
        ws.store.set("acceptance_mode", "legacy")  # Historical source-tool/rubric fixture.
        ws.initialize()
    
        def correct(messages):
            error = observation(messages, "search_sources")
            assert not error["accepted"]
            assert "SEARCH_ARGUMENTS_MUST_BE" in str(error)
            assert [m for m in messages if isinstance(m, ToolMessage)][-1].status == "error"
            return invoke("search_sources", query="Frozen", source_id="original")
    
        def checked(messages):
            result = observation(messages, "search_sources")
            assert result["scope"]["searched_source_ids"] == ["original"]
            assert result["total"] == 1
            return verdict("satisfied") if role == "rubric_grader" else save()
    
        def save():
            return invoke("submit_result", title="Report", body="Frozen OCR [original].",
                          source_ids=["original"], input_ids=[], replaces_id="")
    
        steps = [invoke("search_sources", query="Frozen", source="original"), correct, checked]
        driver = Driver(coordinator=steps + [select, AIMessage(content="Ready")] if role == "coordinator"
                        else [save(), select, AIMessage(content="Ready")],
                        rubric_grader=steps if role == "rubric_grader" else [verdict("satisfied")])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_evidence_tools016.py:82: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3854ba930>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_evidence_tools016.py::test_native_grader_awaits_vision_and_cannot_write_upstream

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_native_grader_awaits_visi0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b38572f890>

    async def test_native_grader_awaits_vision_and_cannot_write_upstream(tmp_path, monkeypatch):
        ws, model = workspace(tmp_path), VisionModel()
        ws.store.set("acceptance_mode", "legacy")  # Historical source-tool/rubric fixture.
        ws.initialize()
        catalog = Catalog(ws.store)
        manifest, blocks = ws.store.manifest, catalog.read("original")
        original = ws.store.root / "sources" / "original.pdf"
        before = hashlib.sha256(original.read_bytes()).hexdigest()
        monkeypatch.setattr(vision, "configured_vision_client", lambda: model)
    
        def grade(messages):
            result = observation(messages, "analyze_source_image")
            assert result["status"] == "observed" and result["source"]["source_id"] == "original"
            return verdict("satisfied")
    
        driver = Driver(coordinator=[invoke("submit_result", title="Report", body="Frozen OCR [original].",
                            source_ids=["original"], input_ids=[], replaces_id=""), select, AIMessage(content="Ready")],
                        rubric_grader=[invoke("analyze_source_image", source_id="original", question="Read text", page=1), grade])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_evidence_tools016.py:105: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3841f8800>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_fact_runtime.py::test_read_result_and_export_expose_unknown_currentness

```text
ws = <report_agent.workspace.Workspace object at 0x74b37e9c8ef0>
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b37e9cb440>

    def test_read_result_and_export_expose_unknown_currentness(ws, monkeypatch):
        graph = Graph()
        result = bound(ws, graph, "submit_result")(**args())
        ws.store.set("knowledge_project_id", "project")
        monkeypatch.setattr("report_agent.knowledge.Knowledge", lambda *a, **kw: graph)
        graph.fail = True
        read = bound(ws, graph, "read_result")(result["id"])
        assert not read["current"]
        assert read["knowledge"]["status"] == "unknown"
        text = "\n".join(p.text for p in Document(BytesIO(export_docx(ws, result["id"]))).paragraphs)
>       assert "current validity is unknown" in text
E       AssertionError: assert 'current validity is unknown' in 'Report\nScope: Compile supplied facts\nEvidence-based content\nSource index\n[source] Source'

tests/test_fact_runtime.py:80: AssertionError
```

## failed: tests/test_failure_diagnostics.py::test_build_agent_direct_native_call_inherits_diagnostic_callback

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_build_agent_direct_native0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b37e9e6f90>

    async def test_build_agent_direct_native_call_inherits_diagnostic_callback(tmp_path, monkeypatch):
        from report_agent.deep_runtime import build_agent
        from report_agent.workspace import Workspace
        from langchain_core.messages import AIMessage
        from test_deep_runtime import Driver
        import pytest
        monkeypatch.setenv('LANGSMITH_TRACING', 'false')
        store = Store(tmp_path)
        store.initialize({'goal': 'Synthetic diagnostic test', 'sources': [
            {'id': 's', 'content': 'Synthetic', 'coverage': 'complete'}]})
        store.set('knowledge_enabled', False)
        driver = Driver(coordinator=[AIMessage(content='Unreached')])
        driver.fail_once = ('coordinator', 0)
>       agent = build_agent(Workspace(store), driver, None, rules='')
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_failure_diagnostics.py:67: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:767: in build_agent
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37e9e4d40>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_generation_records.py::test_receipt_notes_have_bounded_presence_and_exact_owned_recovery

```text
ws = <report_agent.workspace.Workspace object at 0x74b37e84f9e0>

    async def test_receipt_notes_have_bounded_presence_and_exact_owned_recovery(ws):
        _,_,refs,_,_=seed(ws);activate(ws)
        answer=envelope('Long parser diagnostic. '*900)
        model=Model(json.dumps(answer))
        with delegated_task(ws,'coordinator',call()) as (_,actor):
            result=await produce(ws,actor,model,'produce','Use evidence','ContentNode',[refs['claim']])
            raw=json.dumps(result)
            shown=TaskContext(ws,'writer').bound_result(ToolMessage(content=raw,name='process_report_content',tool_call_id='work'))
            packet=json.loads(shown.content)
>           meta=packet['metadata']['generation_record']
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E           KeyError: 'generation_record'

tests/test_generation_records.py:87: KeyError
```

## failed: tests/test_generation_records.py::test_native_graph_adopts_enveloped_batch_and_exports_actual_word_and_excel

```text
ws = <report_agent.workspace.Workspace object at 0x74b37f646d80>
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b37ec5e690>

    async def test_native_graph_adopts_enveloped_batch_and_exports_actual_word_and_excel(ws,monkeypatch):
        import test_text_work as existing
        from report_agent.content_store import ContentStore
        from report_agent.content_workbook import read_workbook
        original_driver=existing.Driver
        process_note='Unique diagnostic for the native envelope test.'
        def driver_with_receipt_notes(*args,**kwargs):
            outputs=kwargs['text_tool']
            kwargs['text_tool']=[m.model_copy(update={'content':json.dumps({
                'payloads':json.loads(m.content),
                'generation_notes':[{'output_index':i,'text':process_note} for i in range(3)]})}) for m in outputs]
            return original_driver(*args,**kwargs)
        monkeypatch.setattr(existing,'Driver',driver_with_receipt_notes)
>       await existing.test_native_scoped_trunk_adopts_batch_and_exports_same_snapshot_word_and_xlsx(ws)
              ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       TypeError: test_native_scoped_trunk_adopts_batch_and_exports_same_snapshot_word_and_xlsx() missing 1 required positional argument: 'reference_delivery'

tests/test_generation_records.py:146: TypeError
```

## failed: tests/test_hierarchical_review_fixes.py::test_late_defect_invalidates_status_and_native_rerun

```text
ws = <report_agent.workspace.Workspace object at 0x74b37e486ab0>

    async def test_late_defect_invalidates_status_and_native_rerun(ws):
>       cs, actor, refs, snapshot, _, export, checks = await passed_delivery(ws)
                                                       ^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_hierarchical_review_fixes.py:39: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
tests/test_hierarchical_review_fixes.py:33: in passed_delivery
    result = await deep_runtime.run_report(ws, driver)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37e486ab0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_hierarchical_review_fixes.py::test_new_selection_cannot_inherit_old_pass

```text
ws = <report_agent.workspace.Workspace object at 0x74b37ea58bf0>

    async def test_new_selection_cannot_inherit_old_pass(ws):
>       cs, actor, refs, old, all_refs, _, _ = await passed_delivery(ws)
                                               ^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_hierarchical_review_fixes.py:62: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
tests/test_hierarchical_review_fixes.py:33: in passed_delivery
    result = await deep_runtime.run_report(ws, driver)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37ea58bf0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_hierarchical_review_fixes.py::test_corrected_final_record_cannot_supply_positive_coverage

```text
ws = <report_agent.workspace.Workspace object at 0x74b37f6f4740>

    async def test_corrected_final_record_cannot_supply_positive_coverage(ws):
>       cs, _, refs, snapshot, _, _, checks = await passed_delivery(ws)
                                              ^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_hierarchical_review_fixes.py:75: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
tests/test_hierarchical_review_fixes.py:33: in passed_delivery
    result = await deep_runtime.run_report(ws, driver)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37f6f4740>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_hierarchical_review_fixes.py::test_content_pass_with_unperformed_delivery_is_not_final_pass

```text
ws = <report_agent.workspace.Workspace object at 0x74b37e7c7d70>

    async def test_content_pass_with_unperformed_delivery_is_not_final_pass(ws):
        cs, actor, refs, snapshot, _ = seed(ws)
        export = export_snapshot(cs, actor, "export", snapshot)["result"]["export_ref"]
        driver = Driver(coordinator=[select(snapshot, export), AIMessage(content="Selected."), AIMessage(content="Unperformed page review retained.")],
            rubric_grader=[invoke("read_context", target_ref=snapshot), grade(snapshot, refs, "satisfied")])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_hierarchical_review_fixes.py:125: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37e7c7d70>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_hierarchical_review_fixes.py::test_native_delegation_separates_writers_and_resumes_original_owner

```text
ws = <report_agent.workspace.Workspace object at 0x74b37e484ce0>

    async def test_native_delegation_separates_writers_and_resumes_original_owner(ws):
        cs, _, refs, _, _ = seed(ws)
        created = {}
        payload = cs.read(refs["claim"])["payload"]
        def save_a(messages):
            return invoke("commit_objects", operation_id="a-create", objects=[{"client_key": "a", "type": "ContentNode", "payload": payload}])
        def done_a(messages):
            created["a"] = observation(messages, "commit_objects")["result"]["refs"]["a"]
            return AIMessage(content="A committed.")
        def edit_a(operation):
            return invoke("commit_objects", operation_id=operation, objects=[{"client_key": "a", "type": "ContentNode",
                "previous_ref": created["a"], "payload": {**payload, "body": {"text": "Owned revision"}}}])
        def reject_b(messages):
            assert observation(messages, "commit_objects")["code"] == "FORBIDDEN"
            return AIMessage(content="B cannot overwrite A.")
        def resume(messages):
            return AIMessage(content="", tool_calls=[call("task", {"subagent_type": "writer", "description": "Continue A",
                "resume_content_task_id": cs.read(created["a"])["task_id"]}, "resume-a")])
        def revised(messages):
            created["revision"] = observation(messages, "commit_objects")["result"]["refs"]["a"]
            return AIMessage(content="Original producer revised A.")
        driver = Driver(coordinator=[AIMessage(content="", tool_calls=[call("task", {"subagent_type": "writer", "description": "Write A"}, "task-a")]),
            AIMessage(content="", tool_calls=[call("task", {"subagent_type": "writer", "description": "Write B"}, "task-b")]), resume, AIMessage(content="Finished ownership test.")])
        steps = [save_a, done_a, lambda m: edit_a("b-attempt"), reject_b, lambda m: edit_a("a-resumed"), revised]
        original, count = driver.respond, {"n": 0}
        async def respond(role, messages):
            if role != "writer":
                return await original(role, messages)
            action = steps[count["n"]]
            count["n"] += 1
            return ChatResult(generations=[ChatGeneration(message=action(messages))])
        driver.respond = respond
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_hierarchical_review_fixes.py:201: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37e484ce0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_hierarchical_runtime.py::test_native_final_pass_and_effective_permissions

```text
ws = <report_agent.workspace.Workspace object at 0x74b37ee84d10>

    async def test_native_final_pass_and_effective_permissions(ws):
        cs, actor, refs, snapshot, _ = seed(ws)
        export = export_snapshot(cs, actor, "export", snapshot)["result"]["export_ref"]
        driver = Driver(coordinator=[select(snapshot, export), AIMessage(content="Selected for review.")],
            rubric_grader=[invoke("read_context", target_ref=snapshot), grade(snapshot, refs, "satisfied", delivery_evidence(cs, snapshot, export))])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_hierarchical_runtime.py:44: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37ee84d10>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_hierarchical_runtime.py::test_unexecuted_null_does_not_trigger_author_repair

```text
ws = <report_agent.workspace.Workspace object at 0x74b37ee87b90>

    async def test_unexecuted_null_does_not_trigger_author_repair(ws):
        cs, actor, refs, snapshot, _ = seed(ws)
        export = export_snapshot(cs, actor, "export", snapshot)["result"]["export_ref"]
        answer = AIMessage(content="", tool_calls=[call("HierarchicalResponse", {
            "explanation": "Reading was blocked; no semantic conclusion.",
            "review": {**submission(snapshot, refs, review_item(snapshot, refs["k"], verdict=None)), "delivery_checks": unchecked_delivery()}})])
        driver = Driver(coordinator=[select(snapshot, export), AIMessage(content="Selected."), AIMessage(content="Unexecuted review retained; no approval.")], rubric_grader=[answer])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_hierarchical_runtime.py:63: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37ee87b90>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_hierarchical_runtime.py::test_feedback_revision_recheck_runs_through_native_graph

```text
ws = <report_agent.workspace.Workspace object at 0x74b37f6f7200>

    async def test_feedback_revision_recheck_runs_through_native_graph(ws):
        cs, actor, refs, snapshot, all_refs = seed(ws)
        export = export_snapshot(cs, actor, "export", snapshot)["result"]["export_ref"]
        revised = {}
        def commit(messages):
            assert "not_satisfied" in str(messages)
            assert observation(messages, "read_feedback")["result"]["total"] == 1
            return invoke("commit_objects", operation_id="fix", objects=[
                {"client_key": "claim", "type": "ContentNode", "previous_ref": refs["claim"], "payload": {
                    **cs.read(refs["claim"])["payload"], "body": {"text": "Under class B, permitted range is 75 to 100; final selection unresolved."}}},
                {"client_key": "edge", "type": "Relation", "previous_ref": refs["edge"], "payload": {
                    **cs.read(refs["edge"])["payload"], "object_ref": {"client_key": "claim"}}},
                {"client_key": "support", "type": "Relation", "previous_ref": refs["support"], "payload": {
                    **cs.read(refs["support"])["payload"], "subject_ref": {"client_key": "claim"}}}])
        def freeze(messages):
            changed = observation(messages, "commit_objects")["result"]["refs"]
            new_refs = [r for r in all_refs if r not in [refs[k] for k in changed]] + list(changed.values())
            revised["refs"] = {**refs, **changed}
            return invoke("freeze_snapshot", operation_id="fixed-snapshot", root_ref=refs["root"], refs=new_refs)
        def export_new(messages):
            revised["snapshot"] = observation(messages, "freeze_snapshot")["result"]["snapshot_ref"]
            return invoke("export_content_snapshot", operation_id="fixed-export", snapshot_ref=revised["snapshot"])
        def select_new(messages):
            revised["export"] = observation(messages, "export_content_snapshot")["result"]["export_ref"]
            return select(revised["snapshot"], revised["export"])
        def read_new(messages):
            return invoke("read_context", target_ref=revised["snapshot"])
        def grade_new(messages):
            return grade(revised["snapshot"], revised["refs"], "undetermined", delivery_evidence(cs, revised["snapshot"], revised["export"]))(messages)
        driver = Driver(coordinator=[select(snapshot, export), AIMessage(content="Selected."), invoke("read_feedback"),
            commit, freeze, export_new, select_new, AIMessage(content="Revision selected."), AIMessage(content="Conditional revision; unresolved final choice retained.")],
            rubric_grader=[invoke("read_context", target_ref=snapshot), grade(snapshot, refs, "not_satisfied"), read_new, grade_new])
        # Each native grader attempt has a fresh message context; Driver counts globally by
        # role only through our separate closure so attempts get their respective script.
        original = driver.respond
        attempts = {"n": 0}
        async def respond(role, messages):
            if role == "rubric_grader":
                step = attempts["n"]
                attempts["n"] += 1
                from langchain_core.outputs import ChatGeneration, ChatResult
                driver.calls.append((role, step, list(messages)))
                item = driver.scripts[role][step]
                return ChatResult(generations=[ChatGeneration(message=item(messages) if callable(item) else item)])
            return await original(role, messages)
        driver.respond = respond
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_hierarchical_runtime.py:135: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37f6f7200>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_hierarchical_runtime.py::test_local_review_returns_feedback_without_finishing_or_revising

```text
ws = <report_agent.workspace.Workspace object at 0x74b37e7c7020>

    async def test_local_review_returns_feedback_without_finishing_or_revising(ws):
        cs, actor, refs, snapshot, _ = seed(ws)
        export = export_snapshot(cs, actor, "export", snapshot)["result"]["export_ref"]
        def local_review(messages):
            receipt = observation(messages, "read_context")["receipt_id"]
            return invoke("submit_review", operation_id="local-defect", review=submission(snapshot, refs,
                review_item(snapshot, refs["k"], receipt)))
        driver = Driver(coordinator=[invoke("task", subagent_type="reviewer", description="Assess the saved content version and return findings."),
            invoke("select_content_delivery", operation_id="stop-with-known-defect", snapshot_ref=snapshot, export_ref=export, ending_reason="preserve_unresolved"),
            AIMessage(content="Preserve unresolved findings."), AIMessage(content="Known defect remains; no approval.")],
            reviewer=[invoke("read_context", target_ref=snapshot), local_review, AIMessage(content="Saved local finding.")],
            rubric_grader=[invoke("read_context", target_ref=snapshot), grade(snapshot, refs, "satisfied", delivery_evidence(cs, snapshot, export))])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_hierarchical_runtime.py:157: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37e7c7020>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## skipped: tests/test_knowledge.py::test_real_graph_versions_receipts_and_provenance

```text
('/mnt/c/Users/dongy/Documents/ChatGPT/report-agent-system/tests/test_knowledge.py', 95, 'Skipped: Set REPORT_GRAPH_TEST_URI to the dedicated prototype graph')
```

## skipped: tests/test_knowledge.py::test_real_graph_read_many_versions_order_and_single_session

```text
('/mnt/c/Users/dongy/Documents/ChatGPT/report-agent-system/tests/test_knowledge.py', 119, 'Skipped: Set REPORT_GRAPH_TEST_URI to the dedicated prototype graph')
```

## skipped: tests/test_knowledge.py::test_real_graph_read_many_rejects_partial_missing_and_foreign

```text
('/mnt/c/Users/dongy/Documents/ChatGPT/report-agent-system/tests/test_knowledge.py', 138, 'Skipped: Set REPORT_GRAPH_TEST_URI to the dedicated prototype graph')
```

## skipped: tests/test_knowledge.py::test_real_graph_cross_project_and_producer_boundaries

```text
('/mnt/c/Users/dongy/Documents/ChatGPT/report-agent-system/tests/test_knowledge.py', 149, 'Skipped: Set REPORT_GRAPH_TEST_URI to the dedicated prototype graph')
```

## skipped: tests/test_knowledge.py::test_real_graph_links_traversal_and_text_paging

```text
('/mnt/c/Users/dongy/Documents/ChatGPT/report-agent-system/tests/test_knowledge.py', 169, 'Skipped: Set REPORT_GRAPH_TEST_URI to the dedicated prototype graph')
```

## skipped: tests/test_knowledge.py::test_real_graph_atomic_rollback

```text
('/mnt/c/Users/dongy/Documents/ChatGPT/report-agent-system/tests/test_knowledge.py', 186, 'Skipped: Set REPORT_GRAPH_TEST_URI to the dedicated prototype graph')
```

## skipped: tests/test_knowledge.py::test_real_graph_recovery_does_not_repeat_embedding

```text
('/mnt/c/Users/dongy/Documents/ChatGPT/report-agent-system/tests/test_knowledge.py', 197, 'Skipped: Set REPORT_GRAPH_TEST_URI to the dedicated prototype graph')
```

## skipped: tests/test_knowledge.py::test_real_graph_concurrent_duplicate_write

```text
('/mnt/c/Users/dongy/Documents/ChatGPT/report-agent-system/tests/test_knowledge.py', 209, 'Skipped: Set REPORT_GRAPH_TEST_URI to the dedicated prototype graph')
```

## skipped: tests/test_knowledge.py::test_real_local_multilingual_vector_and_hybrid

```text
('/mnt/c/Users/dongy/Documents/ChatGPT/report-agent-system/tests/test_knowledge.py', 219, 'Skipped: Set REPORT_GRAPH_TEST_URI to the dedicated prototype graph')
```

## failed: tests/test_library_trunk.py::test_import_library_revision_review_export_protocol

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_import_library_revision_r0')

    async def test_import_library_revision_review_export_protocol(tmp_path):
>       await exercise_library(tmp_path)

tests/test_library_trunk.py:140: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
tests/test_library_trunk.py:109: in exercise_library
    first = await run_report(ws, LibraryFactory(ws))
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b38435ef90>
model_factory = <test_library_trunk.LibraryFactory object at 0x74b37ea7d3d0>
timeout_seconds = 1800

    async def run_report(workspace: Workspace, model_factory=None, *, timeout_seconds=1800):
>       raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: archived ADK report loop; saved data remains readable")
E       report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: archived ADK report loop; saved data remains readable

src/report_agent/report_runtime.py:297: ActionRejected
```

## failed: tests/test_library_trunk.py::test_rejected_tool_request_returns_observation_and_worker_can_continue

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_rejected_tool_request_ret0')

    async def test_rejected_tool_request_returns_observation_and_worker_can_continue(tmp_path):
        from report_agent.report_runtime import execute_task
        store = Store(tmp_path)
        store.initialize({'goal': 'Synthetic tool feedback check', 'sources': [
            {'id': 'brief', 'title': 'Brief', 'content': 'Access summary.', 'coverage': 'complete'}]})
        ws = Workspace(store)
        Catalog(store).import_file('hours.txt', b'Access hours: synthetic daytime.')
        task = ws.request_task('materials', 'Extract supplied hours', [])
        def factory(kind, task_id):
            return LibraryModel(ws=ws, task_id=task_id, script=['bad_search', 'search', 'read', 'submit', 'final'])
>       result = await execute_task(ws, task['id'], factory)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_library_trunk.py:153: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37e9fa090>
task_id = 'e9f0ee6d-a8eb-4af5-9929-a760823b2e69'
model_factory = <function test_rejected_tool_request_returns_observation_and_worker_can_continue.<locals>.factory at 0x74b37f477f60>

    async def execute_task(workspace: Workspace, task_id, model_factory):
>       raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: archived ADK task execution")
E       report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: archived ADK task execution

src/report_agent/report_runtime.py:221: ActionRejected
```

## failed: tests/test_object_index.py::test_large_status_and_historical_projection_keep_navigation_without_changing_original

```text
ws = <report_agent.workspace.Workspace object at 0x74b37f644aa0>

    async def test_large_status_and_historical_projection_keep_navigation_without_changing_original(ws):
        populate(ws)
        activate(ws)
        status = {t.__name__: t for t in content_tools(ws, 'coordinator')}['content_status']()
        middleware = TaskContext(ws, 'coordinator')
        message = middleware.bound_result(ToolMessage(content=encode(status), name='content_status',
            tool_call_id='status-call', id='status-message'))
        packet = json.loads(message.content)
>       assert packet['metadata']['object_metadata_tool'] == 'read_object_index'
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       KeyError: 'object_metadata_tool'

tests/test_object_index.py:132: KeyError
```

## failed: tests/test_official_deepseek.py::test_native_structured_grader_uses_supported_auto_then_persists_review[False]

```text
ws = <report_agent.workspace.Workspace object at 0x74b37f468dd0>
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b37f469700>
strict = False

    @pytest.mark.parametrize('strict', [False, True])
    async def test_native_structured_grader_uses_supported_auto_then_persists_review(ws, monkeypatch, strict):
        from report_agent import deep_runtime
        from report_agent.content_export import export_snapshot
        from report_agent.hierarchical_tools import actor_for
        from test_review_coverage import covered_seed, review_data
        from hierarchical_fixtures import delivery_evidence
        from openai import AsyncOpenAI
        cs, actor, refs, snapshot, _ = covered_seed(ws)
        configured(ws.store.root, monkeypatch)
        monkeypatch.setenv('REPORT_DEEPSEEK_STRICT', '1' if strict else '0')
        export = export_snapshot(cs, actor, "export", snapshot)["result"]["export_ref"]
        ws.store.set("content_delivery", {"snapshot_ref": snapshot, "export_ref": export, "ending_reason": "preserve_unresolved"})
        data = review_data(cs, refs, snapshot)
        data["delivery_checks"] = delivery_evidence(cs, snapshot, export)
        wires = []
        async def handle(request):
            payload = json.loads(request.content)
            wires.append(payload)
            names = {t["function"]["name"] for t in payload.get("tools", [])}
            is_grader = "HierarchicalResponse" in names
            if is_grader:
                assert payload["tool_choice"] == "auto"
                arguments = {"explanation": "Protocol fixture", "review": data}
                if strict:
                    from report_agent.deepseek_strict import StrictCodec
                    from report_agent.hierarchical_review import HierarchicalResponse
                    from langchain_core.utils.function_calling import convert_to_openai_tool
                    arguments = StrictCodec(convert_to_openai_tool(HierarchicalResponse)['function']).encode(arguments)
                    assert request.url.path == '/beta/chat/completions'
                    assert all(t['function']['strict'] is True for t in payload['tools'])
                message = {"role": "assistant", "content": None, "tool_calls": [{"id": "grade", "type": "function", "function": {
                    "name": "HierarchicalResponse", "arguments": json.dumps(arguments)}}]}
            else:
                message = {"role": "assistant", "content": "Saved delivery selected."}
            return httpx.Response(200, json={"id": "native-wire-test", "object": "chat.completion", "created": 1,
                "model": "deepseek-flash", "choices": [{"index": 0, "finish_reason": "tool_calls" if is_grader else "stop", "message": message}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            sdk = AsyncOpenAI(api_key="test-key", base_url="https://api.deepseek.com/beta" if strict else "https://api.deepseek.com", http_client=client, max_retries=0)
            def factory(role):
                model = configured_model(ws.store, role)
                model.async_client = sdk.chat.completions
                return model
>           result = await deep_runtime.run_report(ws, factory)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_official_deepseek.py:111: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37f468dd0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_official_deepseek.py::test_native_structured_grader_uses_supported_auto_then_persists_review[True]

```text
ws = <report_agent.workspace.Workspace object at 0x74b37e3f6db0>
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b37e3f6ed0>
strict = True

    @pytest.mark.parametrize('strict', [False, True])
    async def test_native_structured_grader_uses_supported_auto_then_persists_review(ws, monkeypatch, strict):
        from report_agent import deep_runtime
        from report_agent.content_export import export_snapshot
        from report_agent.hierarchical_tools import actor_for
        from test_review_coverage import covered_seed, review_data
        from hierarchical_fixtures import delivery_evidence
        from openai import AsyncOpenAI
        cs, actor, refs, snapshot, _ = covered_seed(ws)
        configured(ws.store.root, monkeypatch)
        monkeypatch.setenv('REPORT_DEEPSEEK_STRICT', '1' if strict else '0')
        export = export_snapshot(cs, actor, "export", snapshot)["result"]["export_ref"]
        ws.store.set("content_delivery", {"snapshot_ref": snapshot, "export_ref": export, "ending_reason": "preserve_unresolved"})
        data = review_data(cs, refs, snapshot)
        data["delivery_checks"] = delivery_evidence(cs, snapshot, export)
        wires = []
        async def handle(request):
            payload = json.loads(request.content)
            wires.append(payload)
            names = {t["function"]["name"] for t in payload.get("tools", [])}
            is_grader = "HierarchicalResponse" in names
            if is_grader:
                assert payload["tool_choice"] == "auto"
                arguments = {"explanation": "Protocol fixture", "review": data}
                if strict:
                    from report_agent.deepseek_strict import StrictCodec
                    from report_agent.hierarchical_review import HierarchicalResponse
                    from langchain_core.utils.function_calling import convert_to_openai_tool
                    arguments = StrictCodec(convert_to_openai_tool(HierarchicalResponse)['function']).encode(arguments)
                    assert request.url.path == '/beta/chat/completions'
                    assert all(t['function']['strict'] is True for t in payload['tools'])
                message = {"role": "assistant", "content": None, "tool_calls": [{"id": "grade", "type": "function", "function": {
                    "name": "HierarchicalResponse", "arguments": json.dumps(arguments)}}]}
            else:
                message = {"role": "assistant", "content": "Saved delivery selected."}
            return httpx.Response(200, json={"id": "native-wire-test", "object": "chat.completion", "created": 1,
                "model": "deepseek-flash", "choices": [{"index": 0, "finish_reason": "tool_calls" if is_grader else "stop", "message": message}],
                "usage": {"prompt_tokens": 2, "completion_tokens": 1, "total_tokens": 3}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            sdk = AsyncOpenAI(api_key="test-key", base_url="https://api.deepseek.com/beta" if strict else "https://api.deepseek.com", http_client=client, max_retries=0)
            def factory(role):
                model = configured_model(ws.store, role)
                model.async_client = sdk.chat.completions
                return model
>           result = await deep_runtime.run_report(ws, factory)
                     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_official_deepseek.py:111: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37e3f6db0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_prototype.py::test_adk_can_reuse_without_analysis

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_adk_can_reuse_without_ana0')

    async def test_adk_can_reuse_without_analysis(tmp_path):
        store = project(tmp_path, reuse=True)
        decision = ScriptedModel(script=["select", "final"])
        unused_text = ScriptedModel(script=[])
>       status = await run_task(store, decision, unused_text)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_prototype.py:151: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

store = <report_agent.store.Store object at 0x74b37f0b4fe0>
decision_model = ScriptedModel(model='scripted-protocol-double', script=['select', 'final'], requests=[], position=0, waiting=None)
text_model = ScriptedModel(model='scripted-protocol-double', script=[], requests=[], position=0, waiting=None)
timeout_seconds = 1800

    async def run_task(store: Store, decision_model=None, text_model=None, *, timeout_seconds: float = 1800) -> dict:
>       raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: the ADK materials prototype is archived; use the native report runtime. Saved data remains readable.")
E       report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: the ADK materials prototype is archived; use the native report runtime. Saved data remains readable.

src/report_agent/runtime.py:24: ActionRejected
```

## failed: tests/test_prototype.py::test_adk_tool_loop_and_recovery_of_committed_work

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_adk_tool_loop_and_recover0')

    async def test_adk_tool_loop_and_recovery_of_committed_work(tmp_path):
        store = project(tmp_path)
>       interrupted = await run_task(store, ScriptedModel(script=["read", "save", "fail"]), ScriptedModel())
                      ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_prototype.py:160: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

store = <report_agent.store.Store object at 0x74b37f0b4620>
decision_model = ScriptedModel(model='scripted-protocol-double', script=['read', 'save', 'fail'], requests=[], position=0, waiting=None)
text_model = ScriptedModel(model='scripted-protocol-double', script=[], requests=[], position=0, waiting=None)
timeout_seconds = 1800

    async def run_task(store: Store, decision_model=None, text_model=None, *, timeout_seconds: float = 1800) -> dict:
>       raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: the ADK materials prototype is archived; use the native report runtime. Saved data remains readable.")
E       report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: the ADK materials prototype is archived; use the native report runtime. Saved data remains readable.

src/report_agent/runtime.py:24: ActionRejected
```

## failed: tests/test_prototype.py::test_final_text_alone_does_not_complete_task

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_final_text_alone_does_not0')

    async def test_final_text_alone_does_not_complete_task(tmp_path):
        store = project(tmp_path)
>       status = await run_task(store, ScriptedModel(script=["final"]), ScriptedModel())
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_prototype.py:174: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

store = <report_agent.store.Store object at 0x74b3848b6060>
decision_model = ScriptedModel(model='scripted-protocol-double', script=['final'], requests=[], position=0, waiting=None)
text_model = ScriptedModel(model='scripted-protocol-double', script=[], requests=[], position=0, waiting=None)
timeout_seconds = 1800

    async def run_task(store: Store, decision_model=None, text_model=None, *, timeout_seconds: float = 1800) -> dict:
>       raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: the ADK materials prototype is archived; use the native report runtime. Saved data remains readable.")
E       report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: the ADK materials prototype is archived; use the native report runtime. Saved data remains readable.

src/report_agent/runtime.py:24: ActionRejected
```

## failed: tests/test_prototype.py::test_selected_result_survives_tail_failure_without_replay

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_selected_result_survives_0')

    async def test_selected_result_survives_tail_failure_without_replay(tmp_path):
        store = project(tmp_path, reuse=True)
        decision = ScriptedModel(script=["select", "fail"])
>       await run_task(store, decision, ScriptedModel())

tests/test_prototype.py:181: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

store = <report_agent.store.Store object at 0x74b37e630b00>
decision_model = ScriptedModel(model='scripted-protocol-double', script=['select', 'fail'], requests=[], position=0, waiting=None)
text_model = ScriptedModel(model='scripted-protocol-double', script=[], requests=[], position=0, waiting=None)
timeout_seconds = 1800

    async def run_task(store: Store, decision_model=None, text_model=None, *, timeout_seconds: float = 1800) -> dict:
>       raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: the ADK materials prototype is archived; use the native report runtime. Saved data remains readable.")
E       report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: the ADK materials prototype is archived; use the native report runtime. Saved data remains readable.

src/report_agent/runtime.py:24: ActionRejected
```

## failed: tests/test_prototype.py::test_selected_result_survives_actual_task_cancellation

```text
fut = <coroutine object Event.wait at 0x74b37ec76c00>, timeout = 5

    async def wait_for(fut, timeout):
        """Wait for the single Future or coroutine to complete, with timeout.
    
        Coroutine will be wrapped in Task.
    
        Returns result of the Future or coroutine.  When a timeout occurs,
        it cancels the task and raises TimeoutError.  To avoid the task
        cancellation, wrap it in shield().
    
        If the wait is cancelled, the task is also cancelled.
    
        If the task suppresses the cancellation and returns a value instead,
        that value is returned.
    
        This function is a coroutine.
        """
        # The special case for timeout <= 0 is for the following case:
        #
        # async def test_waitfor():
        #     func_started = False
        #
        #     async def func():
        #         nonlocal func_started
        #         func_started = True
        #
        #     try:
        #         await asyncio.wait_for(func(), 0)
        #     except asyncio.TimeoutError:
        #         assert not func_started
        #     else:
        #         assert False
        #
        # asyncio.run(test_waitfor())
    
    
        if timeout is not None and timeout <= 0:
            fut = ensure_future(fut)
    
            if fut.done():
                return fut.result()
    
            await _cancel_and_wait(fut)
            try:
                return fut.result()
            except exceptions.CancelledError as exc:
                raise TimeoutError from exc
    
        async with timeouts.timeout(timeout):
>           return await fut
                   ^^^^^^^^^

/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/tasks.py:520: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

self = <asyncio.locks.Event object at 0x74b37f644fe0 [unset]>

    async def wait(self):
        """Block until the internal flag is true.
    
        If the internal flag is true on entry, return True
        immediately.  Otherwise, block until another coroutine calls
        set() to set the flag to true, then return True.
        """
        if self._value:
            return True
    
        fut = self._get_loop().create_future()
        self._waiters.append(fut)
        try:
>           await fut
E           asyncio.exceptions.CancelledError

/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/locks.py:212: CancelledError

The above exception was the direct cause of the following exception:

tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_selected_result_survives_1')

    async def test_selected_result_survives_actual_task_cancellation(tmp_path):
        store = project(tmp_path, reuse=True)
        waiting = asyncio.Event()
        task = asyncio.create_task(run_task(store, ScriptedModel(script=["select", "wait"], waiting=waiting), ScriptedModel()))
>       await asyncio.wait_for(waiting.wait(), timeout=5)

tests/test_prototype.py:194: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/tasks.py:519: in wait_for
    async with timeouts.timeout(timeout):
               ^^^^^^^^^^^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

self = <Timeout [expired]>
exc_type = <class 'asyncio.exceptions.CancelledError'>
exc_val = CancelledError(), exc_tb = <traceback object at 0x74b384637c80>

    async def __aexit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> Optional[bool]:
        assert self._state in (_State.ENTERED, _State.EXPIRING)
    
        if self._timeout_handler is not None:
            self._timeout_handler.cancel()
            self._timeout_handler = None
    
        if self._state is _State.EXPIRING:
            self._state = _State.EXPIRED
    
            if self._task.uncancel() <= self._cancelling and exc_type is exceptions.CancelledError:
                # Since there are no new cancel requests, we're
                # handling this.
>               raise TimeoutError from exc_val
E               TimeoutError

/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/asyncio/timeouts.py:115: TimeoutError
```

## failed: tests/test_prototype.py::test_startup_error_is_visible

```text
name = 'report_agent.runtime.InMemorySessionService', package = None

    def import_module(name, package=None):
        """Import a module.
    
        The 'package' argument is required when performing a relative import. It
        specifies the package to use as the anchor point from which to resolve the
        relative import to an absolute import.
    
        """
        level = 0
        if name.startswith('.'):
            if not package:
                raise TypeError("the 'package' argument is required to perform a "
                                f"relative import for {name!r}")
            for character in name:
                if character != '.':
                    break
                level += 1
>       return _bootstrap._gcd_import(name[level:], package, level)
               ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E       ModuleNotFoundError: No module named 'report_agent.runtime.InMemorySessionService'; 'report_agent.runtime' is not a package

/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/importlib/__init__.py:90: ModuleNotFoundError

The above exception was the direct cause of the following exception:

tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_startup_error_is_visible0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b384b69550>

    async def test_startup_error_is_visible(tmp_path, monkeypatch):
        async def fail_session(*args, **kwargs):
            raise RuntimeError("Synthetic session startup failure")
    
>       monkeypatch.setattr("report_agent.runtime.InMemorySessionService.create_session", fail_session)

tests/test_prototype.py:209: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/_pytest/monkeypatch.py:107: in derive_importpath
    target = resolve(module)
             ^^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

name = 'report_agent.runtime.InMemorySessionService'

    def resolve(name: str) -> object:
        # Simplified from zope.dottedname.
        parts = name.split(".")
    
        used = parts.pop(0)
        found: object = importlib.import_module(used)
        for part in parts:
            used += "." + part
            try:
                found = getattr(found, part)
            except AttributeError:
                pass
            else:
                continue
            # We use explicit un-nesting of the handling block in order
            # to avoid nested exceptions.
            try:
                importlib.import_module(used)
            except ImportError as ex:
                expected = str(ex).split()[-1]
                if expected == used:
                    raise
                else:
>                   raise ImportError(f"import error in {used}: {ex}") from ex
E                   ImportError: import error in report_agent.runtime.InMemorySessionService: No module named 'report_agent.runtime.InMemorySessionService'; 'report_agent.runtime' is not a package

/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/_pytest/monkeypatch.py:88: ImportError
```

## failed: tests/test_prototype.py::test_error_event_is_not_success

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_error_event_is_not_succes0')

    async def test_error_event_is_not_success(tmp_path):
>       result = await run_task(project(tmp_path), ScriptedModel(script=["error_event"]), ScriptedModel())
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_prototype.py:217: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

store = <report_agent.store.Store object at 0x74b37e437860>
decision_model = ScriptedModel(model='scripted-protocol-double', script=['error_event'], requests=[], position=0, waiting=None)
text_model = ScriptedModel(model='scripted-protocol-double', script=[], requests=[], position=0, waiting=None)
timeout_seconds = 1800

    async def run_task(store: Store, decision_model=None, text_model=None, *, timeout_seconds: float = 1800) -> dict:
>       raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: the ADK materials prototype is archived; use the native report runtime. Saved data remains readable.")
E       report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: the ADK materials prototype is archived; use the native report runtime. Saved data remains readable.

src/report_agent/runtime.py:24: ActionRejected
```

## failed: tests/test_prototype.py::test_cli_exit_code[failed-None-1]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_cli_exit_code_failed_None0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b37f0b6a80>
status = 'failed', error = None, expected = 1

    @pytest.mark.parametrize("status,error,expected", [
        ("failed", None, 1), ("interrupted", None, 1), ("needs_attention", None, 2),
        ("draft_ready", {"type": "RuntimeError"}, 2), ("draft_ready", None, 0),
    ])
    def test_cli_exit_code(tmp_path, monkeypatch, status, error, expected):
        from report_agent import cli
    
        project(tmp_path)
        async def stub(*args, **kwargs):
            return {"status": status, "last_error": error}
    
        from report_agent import runtime
        monkeypatch.setattr(runtime, "run_task", stub)
        monkeypatch.setattr("sys.argv", ["report-agent", "run", "--project", str(tmp_path)])
>       assert cli.main() == expected
               ^^^^^^^^^^

tests/test_prototype.py:235: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/cli.py:98: in main
    parser.error("Historical prototype execution is inactive; initialize a fresh native project and use report-run. Saved history remains readable.")
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/argparse.py:2650: in error
    self.exit(2, _('%(prog)s: error: %(message)s\n') % args)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

self = ArgumentParser(prog='report-agent', usage=None, description='Independent report-agent prototype', formatter_class=<class 'argparse.HelpFormatter'>, conflict_handler='error', add_help=True)
status = 2
message = 'report-agent: error: Historical prototype execution is inactive; initialize a fresh native project and use report-run. Saved history remains readable.\n'

    def exit(self, status=0, message=None):
        if message:
            self._print_message(message, _sys.stderr)
>       _sys.exit(status)
E       SystemExit: 2

/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/argparse.py:2637: SystemExit
```

## failed: tests/test_prototype.py::test_cli_exit_code[interrupted-None-1]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_cli_exit_code_interrupted0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b37ed5ce30>
status = 'interrupted', error = None, expected = 1

    @pytest.mark.parametrize("status,error,expected", [
        ("failed", None, 1), ("interrupted", None, 1), ("needs_attention", None, 2),
        ("draft_ready", {"type": "RuntimeError"}, 2), ("draft_ready", None, 0),
    ])
    def test_cli_exit_code(tmp_path, monkeypatch, status, error, expected):
        from report_agent import cli
    
        project(tmp_path)
        async def stub(*args, **kwargs):
            return {"status": status, "last_error": error}
    
        from report_agent import runtime
        monkeypatch.setattr(runtime, "run_task", stub)
        monkeypatch.setattr("sys.argv", ["report-agent", "run", "--project", str(tmp_path)])
>       assert cli.main() == expected
               ^^^^^^^^^^

tests/test_prototype.py:235: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/cli.py:98: in main
    parser.error("Historical prototype execution is inactive; initialize a fresh native project and use report-run. Saved history remains readable.")
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/argparse.py:2650: in error
    self.exit(2, _('%(prog)s: error: %(message)s\n') % args)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

self = ArgumentParser(prog='report-agent', usage=None, description='Independent report-agent prototype', formatter_class=<class 'argparse.HelpFormatter'>, conflict_handler='error', add_help=True)
status = 2
message = 'report-agent: error: Historical prototype execution is inactive; initialize a fresh native project and use report-run. Saved history remains readable.\n'

    def exit(self, status=0, message=None):
        if message:
            self._print_message(message, _sys.stderr)
>       _sys.exit(status)
E       SystemExit: 2

/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/argparse.py:2637: SystemExit
```

## failed: tests/test_prototype.py::test_cli_exit_code[needs_attention-None-2]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_cli_exit_code_needs_atten0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b37f0b54f0>
status = 'needs_attention', error = None, expected = 2

    @pytest.mark.parametrize("status,error,expected", [
        ("failed", None, 1), ("interrupted", None, 1), ("needs_attention", None, 2),
        ("draft_ready", {"type": "RuntimeError"}, 2), ("draft_ready", None, 0),
    ])
    def test_cli_exit_code(tmp_path, monkeypatch, status, error, expected):
        from report_agent import cli
    
        project(tmp_path)
        async def stub(*args, **kwargs):
            return {"status": status, "last_error": error}
    
        from report_agent import runtime
        monkeypatch.setattr(runtime, "run_task", stub)
        monkeypatch.setattr("sys.argv", ["report-agent", "run", "--project", str(tmp_path)])
>       assert cli.main() == expected
               ^^^^^^^^^^

tests/test_prototype.py:235: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/cli.py:98: in main
    parser.error("Historical prototype execution is inactive; initialize a fresh native project and use report-run. Saved history remains readable.")
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/argparse.py:2650: in error
    self.exit(2, _('%(prog)s: error: %(message)s\n') % args)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

self = ArgumentParser(prog='report-agent', usage=None, description='Independent report-agent prototype', formatter_class=<class 'argparse.HelpFormatter'>, conflict_handler='error', add_help=True)
status = 2
message = 'report-agent: error: Historical prototype execution is inactive; initialize a fresh native project and use report-run. Saved history remains readable.\n'

    def exit(self, status=0, message=None):
        if message:
            self._print_message(message, _sys.stderr)
>       _sys.exit(status)
E       SystemExit: 2

/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/argparse.py:2637: SystemExit
```

## failed: tests/test_prototype.py::test_cli_exit_code[draft_ready-error3-2]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_cli_exit_code_draft_ready0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b37f0b7290>
status = 'draft_ready', error = {'type': 'RuntimeError'}, expected = 2

    @pytest.mark.parametrize("status,error,expected", [
        ("failed", None, 1), ("interrupted", None, 1), ("needs_attention", None, 2),
        ("draft_ready", {"type": "RuntimeError"}, 2), ("draft_ready", None, 0),
    ])
    def test_cli_exit_code(tmp_path, monkeypatch, status, error, expected):
        from report_agent import cli
    
        project(tmp_path)
        async def stub(*args, **kwargs):
            return {"status": status, "last_error": error}
    
        from report_agent import runtime
        monkeypatch.setattr(runtime, "run_task", stub)
        monkeypatch.setattr("sys.argv", ["report-agent", "run", "--project", str(tmp_path)])
>       assert cli.main() == expected
               ^^^^^^^^^^

tests/test_prototype.py:235: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/cli.py:98: in main
    parser.error("Historical prototype execution is inactive; initialize a fresh native project and use report-run. Saved history remains readable.")
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/argparse.py:2650: in error
    self.exit(2, _('%(prog)s: error: %(message)s\n') % args)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

self = ArgumentParser(prog='report-agent', usage=None, description='Independent report-agent prototype', formatter_class=<class 'argparse.HelpFormatter'>, conflict_handler='error', add_help=True)
status = 2
message = 'report-agent: error: Historical prototype execution is inactive; initialize a fresh native project and use report-run. Saved history remains readable.\n'

    def exit(self, status=0, message=None):
        if message:
            self._print_message(message, _sys.stderr)
>       _sys.exit(status)
E       SystemExit: 2

/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/argparse.py:2637: SystemExit
```

## failed: tests/test_prototype.py::test_cli_exit_code[draft_ready-None-0]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_cli_exit_code_draft_ready1')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b37e9fa4e0>
status = 'draft_ready', error = None, expected = 0

    @pytest.mark.parametrize("status,error,expected", [
        ("failed", None, 1), ("interrupted", None, 1), ("needs_attention", None, 2),
        ("draft_ready", {"type": "RuntimeError"}, 2), ("draft_ready", None, 0),
    ])
    def test_cli_exit_code(tmp_path, monkeypatch, status, error, expected):
        from report_agent import cli
    
        project(tmp_path)
        async def stub(*args, **kwargs):
            return {"status": status, "last_error": error}
    
        from report_agent import runtime
        monkeypatch.setattr(runtime, "run_task", stub)
        monkeypatch.setattr("sys.argv", ["report-agent", "run", "--project", str(tmp_path)])
>       assert cli.main() == expected
               ^^^^^^^^^^

tests/test_prototype.py:235: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/cli.py:98: in main
    parser.error("Historical prototype execution is inactive; initialize a fresh native project and use report-run. Saved history remains readable.")
/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/argparse.py:2650: in error
    self.exit(2, _('%(prog)s: error: %(message)s\n') % args)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

self = ArgumentParser(prog='report-agent', usage=None, description='Independent report-agent prototype', formatter_class=<class 'argparse.HelpFormatter'>, conflict_handler='error', add_help=True)
status = 2
message = 'report-agent: error: Historical prototype execution is inactive; initialize a fresh native project and use report-run. Saved history remains readable.\n'

    def exit(self, status=0, message=None):
        if message:
            self._print_message(message, _sys.stderr)
>       _sys.exit(status)
E       SystemExit: 2

/home/dysun/miniforge3/envs/hunan-highway/lib/python3.12/argparse.py:2637: SystemExit
```

## failed: tests/test_prototype.py::test_explicit_feedback_reopens_without_mutating_saved_materials

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_explicit_feedback_reopens0')

    async def test_explicit_feedback_reopens_without_mutating_saved_materials(tmp_path):
        store = project(tmp_path, reuse=True)
        old = store.artifacts()[0]
        store.select_result(old["id"])
        feedback = store.add_feedback("Add a concise source-grounded timing limitation.")
        assert store.get("status") == "ready"
        assert store.get("selected_artifact") is None
        assert store.artifacts()[0] == old
        model = ScriptedModel(script=["read", "save", "select", "final"])
>       result = await run_task(store, model, ScriptedModel())
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_prototype.py:247: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

store = <report_agent.store.Store object at 0x74b37e9fb380>
decision_model = ScriptedModel(model='scripted-protocol-double', script=['read', 'save', 'select', 'final'], requests=[], position=0, waiting=None)
text_model = ScriptedModel(model='scripted-protocol-double', script=[], requests=[], position=0, waiting=None)
timeout_seconds = 1800

    async def run_task(store: Store, decision_model=None, text_model=None, *, timeout_seconds: float = 1800) -> dict:
>       raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: the ADK materials prototype is archived; use the native report runtime. Saved data remains readable.")
E       report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: the ADK materials prototype is archived; use the native report runtime. Saved data remains readable.

src/report_agent/runtime.py:24: ActionRejected
```

## failed: tests/test_prototype.py::test_configuration_failure_is_persisted

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_configuration_failure_is_0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b37eb93e90>

    async def test_configuration_failure_is_persisted(tmp_path, monkeypatch):
        monkeypatch.delenv("REPORT_MODEL", raising=False)
>       result = await run_task(project(tmp_path))
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_prototype.py:266: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

store = <report_agent.store.Store object at 0x74b37eb90470>
decision_model = None, text_model = None, timeout_seconds = 1800

    async def run_task(store: Store, decision_model=None, text_model=None, *, timeout_seconds: float = 1800) -> dict:
>       raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: the ADK materials prototype is archived; use the native report runtime. Saved data remains readable.")
E       report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: the ADK materials prototype is archived; use the native report runtime. Saved data remains readable.

src/report_agent/runtime.py:24: ActionRejected
```

## failed: tests/test_prototype.py::test_completed_result_does_not_require_provider_config

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_completed_result_does_not0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b37e9f80b0>

    async def test_completed_result_does_not_require_provider_config(tmp_path, monkeypatch):
        monkeypatch.delenv("REPORT_MODEL", raising=False)
        store = project(tmp_path, reuse=True)
        store.select_result(store.artifacts()[0]["id"])
>       result = await run_task(store)
                 ^^^^^^^^^^^^^^^^^^^^^

tests/test_prototype.py:275: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

store = <report_agent.store.Store object at 0x74b37e9fbec0>
decision_model = None, text_model = None, timeout_seconds = 1800

    async def run_task(store: Store, decision_model=None, text_model=None, *, timeout_seconds: float = 1800) -> dict:
>       raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: the ADK materials prototype is archived; use the native report runtime. Saved data remains readable.")
E       report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: the ADK materials prototype is archived; use the native report runtime. Saved data remains readable.

src/report_agent/runtime.py:24: ActionRejected
```

## failed: tests/test_report_trunk.py::test_permissions_and_project_reference_boundaries

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_permissions_and_project_r0')

    def test_permissions_and_project_reference_boundaries(tmp_path):
        ws = workspace(tmp_path / "one")
        other = workspace(tmp_path / "two")
        task = ws.request_task("draft", "Write report", [])
        with pytest.raises(PermissionError, match="OWNER"):
            ws.submit(task["id"], actor="materials", title="Overwrite", body="Wrong", source_ids=[], input_ids=[])
        with pytest.raises(ValueError, match="RESULT_NOT_IN_PROJECT"):
            ws.request_task("draft", "Foreign", [other.results()[0]["id"]])
        with pytest.raises(ValueError, match="INVALID_TASK"):
            ws.request_task("administrator", "Grant me SQL", [])
>       tools = worker_tools(ws, task["id"], None)
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_report_trunk.py:60: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37e4a4d40>
task_id = '6ddbf6a8-f2b1-4560-b03e-ab4186b0bd38', text_model = None

    def worker_tools(workspace: Workspace, task_id: str, text_model):
>       raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: archived ADK worker tools")
E       report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: archived ADK worker tools

src/report_agent/report_runtime.py:105: ActionRejected
```

## failed: tests/test_report_trunk.py::test_report_protocol_trunk_and_completed_reuse

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_report_protocol_trunk_and0')

    async def test_report_protocol_trunk_and_completed_reuse(tmp_path):
        ws = workspace(tmp_path)
        factory = ModelFactory(ws)
>       result = await run_report(ws, factory)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_report_trunk.py:167: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37e4876b0>
model_factory = <test_report_trunk.ModelFactory object at 0x74b37e4843b0>
timeout_seconds = 1800

    async def run_report(workspace: Workspace, model_factory=None, *, timeout_seconds=1800):
>       raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: archived ADK report loop; saved data remains readable")
E       report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: archived ADK report loop; saved data remains readable

src/report_agent/report_runtime.py:297: ActionRejected
```

## failed: tests/test_report_trunk.py::test_report_resumes_failed_task_without_regenerating_completed_plan

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_report_resumes_failed_tas0')

    async def test_report_resumes_failed_task_without_regenerating_completed_plan(tmp_path):
        ws = workspace(tmp_path)
        first = ModelFactory(ws, ["request_plan", "run_last", "request_draft", "run_last", "final"], fail_draft=True)
>       failed = await run_report(ws, first)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_report_trunk.py:180: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37e487110>
model_factory = <test_report_trunk.ModelFactory object at 0x74b37e487d40>
timeout_seconds = 1800

    async def run_report(workspace: Workspace, model_factory=None, *, timeout_seconds=1800):
>       raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: archived ADK report loop; saved data remains readable")
E       report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: archived ADK report loop; saved data remains readable

src/report_agent/report_runtime.py:297: ActionRejected
```

## failed: tests/test_report_trunk.py::test_configuration_failure_visible_without_paid_request

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_configuration_failure_vis0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b37e487800>

    async def test_configuration_failure_visible_without_paid_request(tmp_path, monkeypatch):
        monkeypatch.delenv("REPORT_MODEL", raising=False)
>       status = await run_report(workspace(tmp_path))
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_report_trunk.py:193: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37dad1d90>
model_factory = None, timeout_seconds = 1800

    async def run_report(workspace: Workspace, model_factory=None, *, timeout_seconds=1800):
>       raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: archived ADK report loop; saved data remains readable")
E       report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: archived ADK report loop; saved data remains readable

src/report_agent/report_runtime.py:297: ActionRejected
```

## failed: tests/test_report_trunk.py::test_exact_repetition_stops_without_a_total_call_quota

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_exact_repetition_stops_wi0')

    async def test_exact_repetition_stops_without_a_total_call_quota(tmp_path):
        ws = workspace(tmp_path)
        factory = ModelFactory(ws, ["request_plan"] * 8)
>       status = await run_report(ws, factory)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_report_trunk.py:222: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37dad14f0>
model_factory = <test_report_trunk.ModelFactory object at 0x74b37dad2840>
timeout_seconds = 1800

    async def run_report(workspace: Workspace, model_factory=None, *, timeout_seconds=1800):
>       raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: archived ADK report loop; saved data remains readable")
E       report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: archived ADK report loop; saved data remains readable

src/report_agent/report_runtime.py:297: ActionRejected
```

## failed: tests/test_report_trunk.py::test_new_review_is_effective_everywhere_and_system_failure_is_not_missing_data

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_new_review_is_effective_e0')

    def test_new_review_is_effective_everywhere_and_system_failure_is_not_missing_data(tmp_path):
        from io import BytesIO
        from docx import Document
        from report_agent.exporting import export_docx
        ws = workspace(tmp_path)
        draft = baseline(ws)
        first = save(ws, "review", [draft["id"]], outcome="accepted", target_id=draft["id"])
        ws.select_delivery(draft["id"], first["id"])
        task = ws.request_task("review", "New evidence in draft review", [draft["id"]])
        ws.record_read(task["id"], result_ids=[draft["id"]])
        second = ws.submit(task["id"], actor="reviewer", title="Correction required", body="Fix scope",
                           source_ids=[], input_ids=[], target_id=draft["id"], outcome="changes_required")
        assert ws.status()["delivery"]["review_id"] == second["id"]
        assert ws.status()["status"] == "changes_required"
        text = "\n".join(p.text for p in Document(BytesIO(export_docx(ws, draft["id"]))).paragraphs)
>       assert "Draft requiring corrections" in text and second["id"] in text
E       AssertionError: assert ('Draft requiring corrections' in 'Synthetic draft\nScope: Prepare a reusable, source-cited materials note for the pedestrian access section of the fict... index\n[access] Synthetic access arrangements\n[brief] Synthetic project brief\n[notice] Synthetic operational notice')

tests/test_report_trunk.py:272: AssertionError
```

## failed: tests/test_report_trunk.py::test_new_acceptance_updates_previous_rejection_without_new_model_call

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_new_acceptance_updates_pr0')

    async def test_new_acceptance_updates_previous_rejection_without_new_model_call(tmp_path):
        ws = workspace(tmp_path)
        draft = baseline(ws)
        first = save(ws, "review", [draft["id"]], outcome="changes_required", target_id=draft["id"])
        ws.select_delivery(draft["id"], first["id"])
        task = ws.request_task("review", "Review after response to findings", [draft["id"]])
        ws.record_read(task["id"], result_ids=[draft["id"]])
        ws.submit(task["id"], actor="reviewer", title="Reviewed", body="Concern addressed",
                  source_ids=[], input_ids=[], target_id=draft["id"], outcome="accepted")
        assert ws.status()["status"] == ws.status()["delivery"]["status"] == "reviewed_draft"
        factory = ModelFactory(ws)
>       assert (await run_report(ws, factory))["status"] == "reviewed_draft"
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_report_trunk.py:288: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37dad0170>
model_factory = <test_report_trunk.ModelFactory object at 0x74b37dad39e0>
timeout_seconds = 1800

    async def run_report(workspace: Workspace, model_factory=None, *, timeout_seconds=1800):
>       raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: archived ADK report loop; saved data remains readable")
E       report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: archived ADK report loop; saved data remains readable

src/report_agent/report_runtime.py:297: ActionRejected
```

## failed: tests/test_review_coverage.py::test_native_whole_report_pass_requires_new_object_accounting[True]

```text
ws = <report_agent.workspace.Workspace object at 0x74b37eb93da0>, account = True

    @pytest.mark.parametrize("account", [True, False])
    async def test_native_whole_report_pass_requires_new_object_accounting(ws, account):
        cs, actor, refs, snap, _ = covered_seed(ws)
        export = export_snapshot(cs, actor, "export", snap)["result"]["export_ref"]
        checks = delivery_evidence(cs, snap, export)
        def grade(messages):
            data = review_data(cs, refs, snap)
            data["items"][0]["observations"][0]["receipt_id"] = observation(messages, "read_context")["receipt_id"]
            data["delivery_checks"] = checks
            if not account:
                data["coverage_accounting"] = []
            return AIMessage(content="", tool_calls=[call("HierarchicalResponse", {"explanation": "Protocol fixture.", "review": data})])
        driver = Driver(coordinator=[select(snap, export), AIMessage(content="Selected."), AIMessage(content="Actual limitations retained.")],
                        rubric_grader=[invoke("read_context", target_ref=snap), grade])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_review_coverage.py:93: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37eb93da0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_review_coverage.py::test_native_whole_report_pass_requires_new_object_accounting[False]

```text
ws = <report_agent.workspace.Workspace object at 0x74b37ea465a0>
account = False

    @pytest.mark.parametrize("account", [True, False])
    async def test_native_whole_report_pass_requires_new_object_accounting(ws, account):
        cs, actor, refs, snap, _ = covered_seed(ws)
        export = export_snapshot(cs, actor, "export", snap)["result"]["export_ref"]
        checks = delivery_evidence(cs, snap, export)
        def grade(messages):
            data = review_data(cs, refs, snap)
            data["items"][0]["observations"][0]["receipt_id"] = observation(messages, "read_context")["receipt_id"]
            data["delivery_checks"] = checks
            if not account:
                data["coverage_accounting"] = []
            return AIMessage(content="", tool_calls=[call("HierarchicalResponse", {"explanation": "Protocol fixture.", "review": data})])
        driver = Driver(coordinator=[select(snap, export), AIMessage(content="Selected."), AIMessage(content="Actual limitations retained.")],
                        rubric_grader=[invoke("read_context", target_ref=snap), grade])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_review_coverage.py:93: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37ea465a0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_review_feedback.py::test_native_feedback_reaches_worker_and_revised_version_is_graded

```text
ws = <report_agent.workspace.Workspace object at 0x74b3849c3950>

    async def test_native_feedback_reaches_worker_and_revised_version_is_graded(ws):
        grades = []
    
        def grade(messages):
            grades.append(messages)
            return verdict("needs_revision", "Add daytime restriction and source s.") if len(grades) == 1 else verdict("satisfied")
    
        def revise(messages):
            assert "Add daytime restriction and source s." in str([m.content for m in messages])
            return save("Daytime access only [s].", ws.results()[0]["id"])
    
        driver = Driver(coordinator=[save("Access."), select, AIMessage(content="Ready."),
                                     revise, select, AIMessage(content="Revised." )],
                        rubric_grader=[grade])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_review_feedback.py:80: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3849c3950>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_review_feedback.py::test_terminal_feedback_is_seen_without_another_grading_loop[False]

```text
ws = <report_agent.workspace.Workspace object at 0x74b37d082420>, error = False

    @pytest.mark.parametrize("error", [False, True])
    async def test_terminal_feedback_is_seen_without_another_grading_loop(ws, error):
        grades, notices = [], []
    
        def grade(messages):
            grades.append(messages)
            if error:
                raise RuntimeError("private provider endpoint")
            return verdict("failed", "The available rubric cannot be evaluated.")
    
        def explain(messages):
            notice = next(m for m in messages if m.name == "rubric_terminal_feedback")
            notices.append(json.loads(notice.content))
            return AIMessage(content="Draft retained; review unavailable, not approved.")
    
        driver = Driver(coordinator=[save("Access."), select, AIMessage(content="Ready."), explain],
                        rubric_grader=[grade])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_review_feedback.py:109: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37d082420>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_review_feedback.py::test_terminal_feedback_is_seen_without_another_grading_loop[True]

```text
ws = <report_agent.workspace.Workspace object at 0x74b384a46f90>, error = True

    @pytest.mark.parametrize("error", [False, True])
    async def test_terminal_feedback_is_seen_without_another_grading_loop(ws, error):
        grades, notices = [], []
    
        def grade(messages):
            grades.append(messages)
            if error:
                raise RuntimeError("private provider endpoint")
            return verdict("failed", "The available rubric cannot be evaluated.")
    
        def explain(messages):
            notice = next(m for m in messages if m.name == "rubric_terminal_feedback")
            notices.append(json.loads(notice.content))
            return AIMessage(content="Draft retained; review unavailable, not approved.")
    
        driver = Driver(coordinator=[save("Access."), select, AIMessage(content="Ready."), explain],
                        rubric_grader=[grade])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_review_feedback.py:109: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b384a46f90>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_review_feedback.py::test_three_native_grades_one_terminal_handoff_without_budget_reset[normal]

```text
ws = <report_agent.workspace.Workspace object at 0x74b38562f440>
fail_handoff = False

    @pytest.mark.parametrize("fail_handoff", [False, True], ids=["normal", "reopen-pending-handoff"])
    async def test_three_native_grades_one_terminal_handoff_without_budget_reset(ws, fail_handoff):
        grades, notices = [], []
    
        def grade(messages):
            grades.append(messages)
            return verdict("needs_revision", "Add a verifiable source citation.")
    
        def revise(messages):
            assert "Add a verifiable source citation." in str([m.content for m in messages])
            previous = observation(messages, "submit_result")["id"]
            return save(f"Daytime access revision {len(grades)}.", previous)
    
        def explain(messages):
            terminal = [m for m in messages if m.name == "rubric_terminal_feedback"]
            assert len(terminal) == 1
            notice = json.loads(terminal[0].content)
            assert notice["status"] == "max_iterations_reached"
            assert notice["criteria"][0]["gap"] == "Add a verifiable source citation."
            notices.append(notice)
            return AIMessage(content="Draft saved; source citation remains unverified. Not approved.")
    
        scripts = {
            "coordinator": [save("Access."), select, AIMessage(content="Ready."),
                            revise, select, AIMessage(content="Revision one."),
                            revise, select, AIMessage(content="Revision two."), explain],
            "rubric_grader": [grade],
        }
        driver = Driver(**scripts)
        if fail_handoff:
            driver.fail_once = ("coordinator", 9)
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_review_feedback.py:175: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b38562f440>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_review_feedback.py::test_three_native_grades_one_terminal_handoff_without_budget_reset[reopen-pending-handoff]

```text
ws = <report_agent.workspace.Workspace object at 0x74b3846b4dd0>
fail_handoff = True

    @pytest.mark.parametrize("fail_handoff", [False, True], ids=["normal", "reopen-pending-handoff"])
    async def test_three_native_grades_one_terminal_handoff_without_budget_reset(ws, fail_handoff):
        grades, notices = [], []
    
        def grade(messages):
            grades.append(messages)
            return verdict("needs_revision", "Add a verifiable source citation.")
    
        def revise(messages):
            assert "Add a verifiable source citation." in str([m.content for m in messages])
            previous = observation(messages, "submit_result")["id"]
            return save(f"Daytime access revision {len(grades)}.", previous)
    
        def explain(messages):
            terminal = [m for m in messages if m.name == "rubric_terminal_feedback"]
            assert len(terminal) == 1
            notice = json.loads(terminal[0].content)
            assert notice["status"] == "max_iterations_reached"
            assert notice["criteria"][0]["gap"] == "Add a verifiable source citation."
            notices.append(notice)
            return AIMessage(content="Draft saved; source citation remains unverified. Not approved.")
    
        scripts = {
            "coordinator": [save("Access."), select, AIMessage(content="Ready."),
                            revise, select, AIMessage(content="Revision one."),
                            revise, select, AIMessage(content="Revision two."), explain],
            "rubric_grader": [grade],
        }
        driver = Driver(**scripts)
        if fail_handoff:
            driver.fail_once = ("coordinator", 9)
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_review_feedback.py:175: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3846b4dd0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_review_feedback.py::test_observation_callback_failure_reconciles_from_native_checkpoint

```text
ws = <report_agent.workspace.Workspace object at 0x74b3846b60c0>
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b3846b7440>

    async def test_observation_callback_failure_reconciles_from_native_checkpoint(ws, monkeypatch):
        event = ws.store.event
        failures = []
    
        def fail_observation(kind, data):
            if kind == "rubric_review_observed":
                failures.append(data)
                raise RuntimeError("SYNTHETIC_OBSERVATION_SINK_FAILURE")
            return event(kind, data)
    
        monkeypatch.setattr(ws.store, "event", fail_observation)
        driver = Driver(coordinator=[save("Daytime access only [s]."), select, AIMessage(content="Ready.")],
                        rubric_grader=[verdict("satisfied")])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_review_feedback.py:230: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3846b60c0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_review_feedback.py::test_native_grader_reads_exact_export_through_real_tool_node

```text
ws = <report_agent.workspace.Workspace object at 0x74b3846b48f0>

    async def test_native_grader_reads_exact_export_through_real_tool_node(ws):
        reads = []
    
        def grade_export(messages):
            page = observation(messages, "read_review_export")
            reads.append(page)
            assert "Daytime access only" in page["text"]
            assert page["unit"] == "text_blocks" and page["physical_page_numbers"] is None
            target = next(iter(ws.store.get("rubric_targets").values()))
            for field in ("draft_id", "preview_version", "draft_body_sha256", "docx_sha256"):
                assert page[field] == target[field]
            data = (ws.store.root / "previews" / page["preview_version"] / "report.docx").read_bytes()
            assert hashlib.sha256(data).hexdigest() == page["docx_sha256"]
            return verdict("satisfied")
    
        driver = Driver(coordinator=[save("Daytime access only [s]."), select, AIMessage(content="Ready.")],
                        rubric_grader=[invoke("read_review_export", offset=0, limit=30), grade_export])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_review_feedback.py:263: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3846b48f0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_review_feedback.py::test_legacy_child_interrupt_resumes_with_rubric_without_duplicate_result

```text
ws = <report_agent.workspace.Workspace object at 0x74b37d082d80>
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b37d082060>

    async def test_legacy_child_interrupt_resumes_with_rubric_without_duplicate_result(ws, monkeypatch):
        rules = deep_runtime.load_rules()
        monkeypatch.setattr(deep_runtime, "load_rules", lambda: "")
    
        def select_child(messages):
            return invoke("select_delivery", draft_id=ws.results()[0]["id"])
    
        scripts = {
            "coordinator": [invoke("task", subagent_type="writer", description="Save draft and confirm scope"),
                            select_child, AIMessage(content="Saved report ready for grading.")],
            "writer": [save("Daytime access only [s]."),
                       invoke("ask_human", category="source_conflict", description="Confirm daytime scope", source_ids=["s"]),
                       AIMessage(content="Draft saved; operator scope recorded.")],
            "rubric_grader": [verdict("satisfied")],
        }
        driver = Driver(**scripts)
>       first = await deep_runtime.run_report(ws, driver)
                ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_review_feedback.py:286: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37d082d80>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_review_feedback.py::test_grader_corrects_invalid_result_page_in_same_native_invocation

```text
ws = <report_agent.workspace.Workspace object at 0x74b37d083500>

    async def test_grader_corrects_invalid_result_page_in_same_native_invocation(ws):
        body = "Daytime access only [s]."
        corrected = []
    
        def invalid_read(messages):
            return AIMessage(content="", tool_calls=[call("read_result", {
                "result_id": ws.results()[0]["id"], "offset": 0, "characters": 16001,
            }, "invalid-read")])
    
        def correct_read(messages):
            reply = next(m for m in messages if isinstance(m, ToolMessage)
                         and m.tool_call_id == "invalid-read")
            assert reply.name == "read_result" and reply.status == "error"
            error = json.loads(reply.content)
            assert error["accepted"] is False
            assert error["error"]["type"] == "ActionRejected"
            assert error["error"]["message"] == "INVALID_RESULT_PAGE"
            assert body not in reply.content
            corrected.append(error)
            return AIMessage(content="", tool_calls=[call("read_result", {
                "result_id": ws.results()[0]["id"], "offset": 0, "characters": 16000,
            }, "corrected-read")])
    
        def grade_read(messages):
            replies = [m for m in messages if isinstance(m, ToolMessage) and m.name == "read_result"]
            assert [(m.tool_call_id, m.status) for m in replies] == [
                ("invalid-read", "error"), ("corrected-read", "success")]
            page = json.loads(replies[-1].content)
            assert page["id"] == ws.results()[0]["id"]
            assert page["body"] == body and page["next_offset"] is None
            return verdict("satisfied")
    
        driver = Driver(coordinator=[save(body), select, AIMessage(content="Ready.")],
                        rubric_grader=[invalid_read, correct_read, grade_read])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_review_feedback.py:361: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37d083500>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_review_feedback.py::test_grader_adapter_keeps_permission_denial_and_does_not_mask_unknown_errors[permission-denied]

```text
ws = <report_agent.workspace.Workspace object at 0x74b3846b7e00>
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b37e89da00>
unknown = False

    @pytest.mark.parametrize("unknown", [False, True], ids=["permission-denied", "unknown-tool-error"])
    async def test_grader_adapter_keeps_permission_denial_and_does_not_mask_unknown_errors(ws, monkeypatch, unknown):
        original_result = ws.result
        armed, errors_seen, terminal = [], [], []
    
        def protected_result(result_id):
            if armed:
                armed.pop()
                if unknown:
                    raise RuntimeError("synthetic private provider body https://invalid.example/key")
                raise ActionForbidden("RESULT_ACCESS_FORBIDDEN")
            return original_result(result_id)
    
        monkeypatch.setattr(ws, "result", protected_result)
    
        def attempt_read(messages):
            result_id = ws.results()[0]["id"]
            armed.append(True)
            return invoke("read_result", result_id=result_id, offset=0, characters=100)
    
        def observe_denial(messages):
            reply = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == "read_result")
            assert reply.status == "error"
            payload = json.loads(reply.content)
            assert payload["accepted"] is False
            assert payload["error"]["type"] == "ActionForbidden"
            assert payload["error"]["message"] == "RESULT_ACCESS_FORBIDDEN"
            assert "Daytime access only" not in reply.content
            errors_seen.append(payload)
            return verdict("failed", "Cannot verify the report because access was denied.")
    
        def explain(messages):
            notice = next(m for m in messages if m.name == "rubric_terminal_feedback")
            terminal.append(json.loads(notice.content))
            assert "invalid.example" not in notice.content
            assert "synthetic private" not in notice.content
            return AIMessage(content="Report retained, not approved; review unavailable.")
    
        driver = Driver(coordinator=[save("Daytime access only [s]."), select, AIMessage(content="Ready."), explain],
                        rubric_grader=[attempt_read] if unknown else [attempt_read, observe_denial])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_review_feedback.py:423: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3846b7e00>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_review_feedback.py::test_grader_adapter_keeps_permission_denial_and_does_not_mask_unknown_errors[unknown-tool-error]

```text
ws = <report_agent.workspace.Workspace object at 0x74b3846b46e0>
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b3846b48f0>
unknown = True

    @pytest.mark.parametrize("unknown", [False, True], ids=["permission-denied", "unknown-tool-error"])
    async def test_grader_adapter_keeps_permission_denial_and_does_not_mask_unknown_errors(ws, monkeypatch, unknown):
        original_result = ws.result
        armed, errors_seen, terminal = [], [], []
    
        def protected_result(result_id):
            if armed:
                armed.pop()
                if unknown:
                    raise RuntimeError("synthetic private provider body https://invalid.example/key")
                raise ActionForbidden("RESULT_ACCESS_FORBIDDEN")
            return original_result(result_id)
    
        monkeypatch.setattr(ws, "result", protected_result)
    
        def attempt_read(messages):
            result_id = ws.results()[0]["id"]
            armed.append(True)
            return invoke("read_result", result_id=result_id, offset=0, characters=100)
    
        def observe_denial(messages):
            reply = next(m for m in reversed(messages) if isinstance(m, ToolMessage) and m.name == "read_result")
            assert reply.status == "error"
            payload = json.loads(reply.content)
            assert payload["accepted"] is False
            assert payload["error"]["type"] == "ActionForbidden"
            assert payload["error"]["message"] == "RESULT_ACCESS_FORBIDDEN"
            assert "Daytime access only" not in reply.content
            errors_seen.append(payload)
            return verdict("failed", "Cannot verify the report because access was denied.")
    
        def explain(messages):
            notice = next(m for m in messages if m.name == "rubric_terminal_feedback")
            terminal.append(json.loads(notice.content))
            assert "invalid.example" not in notice.content
            assert "synthetic private" not in notice.content
            return AIMessage(content="Report retained, not approved; review unavailable.")
    
        driver = Driver(coordinator=[save("Daytime access only [s]."), select, AIMessage(content="Ready."), explain],
                        rubric_grader=[attempt_read] if unknown else [attempt_read, observe_denial])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_review_feedback.py:423: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3846b46e0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## error: tests/test_review_import017.py::test_fork_runs_grader_first_and_native_revision_without_touching_baseline

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_fork_runs_grader_first_an0')

    @pytest.fixture
    async def completed(tmp_path):
        store = Store(tmp_path / "baseline")
        store.set("acceptance_mode", "legacy")  # Reconstruct the historical Task017 import baseline.
        source = store.root / "sources/input.txt"
        source.parent.mkdir()
        source.write_bytes(b"Daytime access only.")
        store.initialize({"goal": "Compile synthetic access report.", "sources": [{
            "id": "s", "title": "Source", "content": "Daytime access only.", "coverage": "complete",
            "copied_path": "sources/input.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
        Catalog(store)
        workspace = Workspace(store)
        workspace.initialize()
        driver = Driver(coordinator=[save("Access [s]."), select, AIMessage(content="Draft ready.")],
                        rubric_grader=[invoke("read_review_export", limit=101),
                                       invoke("read_review_export", limit=30), verdict("satisfied")])
>       result = await deep_runtime.run_report(workspace, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_review_import017.py:62: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37d082750>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## error: tests/test_review_import017.py::test_refuses_unsafe_imports_without_baseline_changes[feedback-HUMAN_FEEDBACK_OR_DECISION_NOT_ALLOWED]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_refuses_unsafe_imports_wi0')

    @pytest.fixture
    async def completed(tmp_path):
        store = Store(tmp_path / "baseline")
        store.set("acceptance_mode", "legacy")  # Reconstruct the historical Task017 import baseline.
        source = store.root / "sources/input.txt"
        source.parent.mkdir()
        source.write_bytes(b"Daytime access only.")
        store.initialize({"goal": "Compile synthetic access report.", "sources": [{
            "id": "s", "title": "Source", "content": "Daytime access only.", "coverage": "complete",
            "copied_path": "sources/input.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
        Catalog(store)
        workspace = Workspace(store)
        workspace.initialize()
        driver = Driver(coordinator=[save("Access [s]."), select, AIMessage(content="Draft ready.")],
                        rubric_grader=[invoke("read_review_export", limit=101),
                                       invoke("read_review_export", limit=30), verdict("satisfied")])
>       result = await deep_runtime.run_report(workspace, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_review_import017.py:62: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37d081850>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## error: tests/test_review_import017.py::test_refuses_unsafe_imports_without_baseline_changes[decision-HUMAN_FEEDBACK_OR_DECISION_NOT_ALLOWED]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_refuses_unsafe_imports_wi1')

    @pytest.fixture
    async def completed(tmp_path):
        store = Store(tmp_path / "baseline")
        store.set("acceptance_mode", "legacy")  # Reconstruct the historical Task017 import baseline.
        source = store.root / "sources/input.txt"
        source.parent.mkdir()
        source.write_bytes(b"Daytime access only.")
        store.initialize({"goal": "Compile synthetic access report.", "sources": [{
            "id": "s", "title": "Source", "content": "Daytime access only.", "coverage": "complete",
            "copied_path": "sources/input.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
        Catalog(store)
        workspace = Workspace(store)
        workspace.initialize()
        driver = Driver(coordinator=[save("Access [s]."), select, AIMessage(content="Draft ready.")],
                        rubric_grader=[invoke("read_review_export", limit=101),
                                       invoke("read_review_export", limit=30), verdict("satisfied")])
>       result = await deep_runtime.run_report(workspace, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_review_import017.py:62: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37e84ce60>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## error: tests/test_review_import017.py::test_refuses_unsafe_imports_without_baseline_changes[graph-GRAPH_DEPENDENT_RESULTS]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_refuses_unsafe_imports_wi2')

    @pytest.fixture
    async def completed(tmp_path):
        store = Store(tmp_path / "baseline")
        store.set("acceptance_mode", "legacy")  # Reconstruct the historical Task017 import baseline.
        source = store.root / "sources/input.txt"
        source.parent.mkdir()
        source.write_bytes(b"Daytime access only.")
        store.initialize({"goal": "Compile synthetic access report.", "sources": [{
            "id": "s", "title": "Source", "content": "Daytime access only.", "coverage": "complete",
            "copied_path": "sources/input.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
        Catalog(store)
        workspace = Workspace(store)
        workspace.initialize()
        driver = Driver(coordinator=[save("Access [s]."), select, AIMessage(content="Draft ready.")],
                        rubric_grader=[invoke("read_review_export", limit=101),
                                       invoke("read_review_export", limit=30), verdict("satisfied")])
>       result = await deep_runtime.run_report(workspace, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_review_import017.py:62: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b384a45e20>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## error: tests/test_review_import017.py::test_refuses_unsafe_imports_without_baseline_changes[source-BASELINE_SOURCE_HASH_MISMATCH]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_refuses_unsafe_imports_wi3')

    @pytest.fixture
    async def completed(tmp_path):
        store = Store(tmp_path / "baseline")
        store.set("acceptance_mode", "legacy")  # Reconstruct the historical Task017 import baseline.
        source = store.root / "sources/input.txt"
        source.parent.mkdir()
        source.write_bytes(b"Daytime access only.")
        store.initialize({"goal": "Compile synthetic access report.", "sources": [{
            "id": "s", "title": "Source", "content": "Daytime access only.", "coverage": "complete",
            "copied_path": "sources/input.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
        Catalog(store)
        workspace = Workspace(store)
        workspace.initialize()
        driver = Driver(coordinator=[save("Access [s]."), select, AIMessage(content="Draft ready.")],
                        rubric_grader=[invoke("read_review_export", limit=101),
                                       invoke("read_review_export", limit=30), verdict("satisfied")])
>       result = await deep_runtime.run_report(workspace, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_review_import017.py:62: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37d080890>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## error: tests/test_review_import017.py::test_refuses_unsafe_imports_without_baseline_changes[error-BASELINE_HAS_UNRESOLVED_EXECUTION_STATE]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_refuses_unsafe_imports_wi4')

    @pytest.fixture
    async def completed(tmp_path):
        store = Store(tmp_path / "baseline")
        store.set("acceptance_mode", "legacy")  # Reconstruct the historical Task017 import baseline.
        source = store.root / "sources/input.txt"
        source.parent.mkdir()
        source.write_bytes(b"Daytime access only.")
        store.initialize({"goal": "Compile synthetic access report.", "sources": [{
            "id": "s", "title": "Source", "content": "Daytime access only.", "coverage": "complete",
            "copied_path": "sources/input.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
        Catalog(store)
        workspace = Workspace(store)
        workspace.initialize()
        driver = Driver(coordinator=[save("Access [s]."), select, AIMessage(content="Draft ready.")],
                        rubric_grader=[invoke("read_review_export", limit=101),
                                       invoke("read_review_export", limit=30), verdict("satisfied")])
>       result = await deep_runtime.run_report(workspace, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_review_import017.py:62: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b38541a450>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## error: tests/test_review_import017.py::test_refuses_unsafe_imports_without_baseline_changes[post_commit-BUSINESS_OR_ERROR_EVENT_AFTER_REVIEW_BOUNDARY]

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_refuses_unsafe_imports_wi5')

    @pytest.fixture
    async def completed(tmp_path):
        store = Store(tmp_path / "baseline")
        store.set("acceptance_mode", "legacy")  # Reconstruct the historical Task017 import baseline.
        source = store.root / "sources/input.txt"
        source.parent.mkdir()
        source.write_bytes(b"Daytime access only.")
        store.initialize({"goal": "Compile synthetic access report.", "sources": [{
            "id": "s", "title": "Source", "content": "Daytime access only.", "coverage": "complete",
            "copied_path": "sources/input.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
        Catalog(store)
        workspace = Workspace(store)
        workspace.initialize()
        driver = Driver(coordinator=[save("Access [s]."), select, AIMessage(content="Draft ready.")],
                        rubric_grader=[invoke("read_review_export", limit=101),
                                       invoke("read_review_export", limit=30), verdict("satisfied")])
>       result = await deep_runtime.run_report(workspace, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_review_import017.py:62: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b384a47c50>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## error: tests/test_review_import017.py::test_refuses_existing_destination_invalid_checkpoint_and_live_baseline

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_refuses_existing_destinat0')

    @pytest.fixture
    async def completed(tmp_path):
        store = Store(tmp_path / "baseline")
        store.set("acceptance_mode", "legacy")  # Reconstruct the historical Task017 import baseline.
        source = store.root / "sources/input.txt"
        source.parent.mkdir()
        source.write_bytes(b"Daytime access only.")
        store.initialize({"goal": "Compile synthetic access report.", "sources": [{
            "id": "s", "title": "Source", "content": "Daytime access only.", "coverage": "complete",
            "copied_path": "sources/input.txt", "sha256": hashlib.sha256(source.read_bytes()).hexdigest()}]})
        Catalog(store)
        workspace = Workspace(store)
        workspace.initialize()
        driver = Driver(coordinator=[save("Access [s]."), select, AIMessage(content="Draft ready.")],
                        rubric_grader=[invoke("read_review_export", limit=101),
                                       invoke("read_review_export", limit=30), verdict("satisfied")])
>       result = await deep_runtime.run_report(workspace, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_review_import017.py:62: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b384a47ec0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_review_status.py::test_native_grader_reads_inventory_then_submits_its_own_judgment

```text
ws = <report_agent.workspace.Workspace object at 0x74b38529a330>

    async def test_native_grader_reads_inventory_then_submits_its_own_judgment(ws):
        cs, actor, refs, snapshot, _ = seed(ws)
        export = export_snapshot(cs, actor, "export", snapshot)["result"]["export_ref"]
        def inspect_inventory(messages):
            result = observation(messages, "read_review_status")["result"]
            assert any(r["execution_state"] == "not_started" for r in result["objects"])
            return invoke("read_context", target_ref=snapshot)
        driver = Driver(coordinator=[select(snapshot, export), AIMessage(content="Selected.")],
            rubric_grader=[invoke("read_review_status", snapshot_ref=snapshot), inspect_inventory,
                           grade(snapshot, refs, "satisfied", delivery_evidence(cs, snapshot, export))])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_review_status.py:190: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b38529a330>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_reviewer_prompt017.py::test_effective_native_prompt_and_single_review_entry

```text
ws = <report_agent.workspace.Workspace object at 0x74b37ec546b0>

    async def test_effective_native_prompt_and_single_review_entry(ws):
        def inspect(messages):
            system = next(m for m in messages if isinstance(m, SystemMessage)).text
            assert reviewer_prompt() in system
            assert GRADER_SYSTEM_PROMPT in system
            assert "# Report review responsibility" in system
            # Capabilities are verified from the bound tool schemas below; the role
            # prompt need not name or prescribe any particular tool.
            return verdict("satisfied")
    
        driver = Driver(coordinator=[save("Daytime access only [s]."), select, AIMessage("Ready")],
                        rubric_grader=[inspect])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_reviewer_prompt017.py:24: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37ec546b0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_reviewer_prompt017.py::test_old_prompt_acceptance_is_historical_not_current_acceptance

```text
ws = <report_agent.workspace.Workspace object at 0x74b3852175f0>
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b385215f70>

    async def test_old_prompt_acceptance_is_historical_not_current_acceptance(ws, monkeypatch):
        driver = Driver(coordinator=[save("Daytime access only [s]."), select, AIMessage("Ready")],
                        rubric_grader=[verdict("satisfied")])
>       await deep_runtime.run_report(ws, driver)

tests/test_reviewer_prompt017.py:39: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3852175f0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_reviewer_prompt017.py::test_generic_historical_acceptance_does_not_skip_new_native_reviewer

```text
ws = <report_agent.workspace.Workspace object at 0x74b385216720>

    async def test_generic_historical_acceptance_does_not_skip_new_native_reviewer(ws):
        driver = Driver(coordinator=[save("Daytime access only [s]."), select, AIMessage("Ready")],
                        rubric_grader=[verdict("satisfied")])
>       await deep_runtime.run_report(ws, driver)

tests/test_reviewer_prompt017.py:51: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b385216720>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_reviewer_prompt017.py::test_disabled_graph_production_path_uses_saved_results_without_graph

```text
ws = <report_agent.workspace.Workspace object at 0x74b3852151c0>
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b3852155b0>

    async def test_disabled_graph_production_path_uses_saved_results_without_graph(ws, monkeypatch):
        from report_agent import knowledge
        ws.store.set("knowledge_enabled", False)
        ws.store.set("knowledge_project_id", "historical-namespace-never-open")
    
        def forbidden(*args, **kwargs):
            raise AssertionError("Graph must remain disconnected")
    
        monkeypatch.setattr(knowledge, "Knowledge", forbidden)
        driver = Driver(coordinator=[save("Daytime access only [s]."), select, AIMessage("Ready")],
                        rubric_grader=[verdict("satisfied")])
        monkeypatch.setattr(deep_runtime, "configured_model", lambda store, role: driver(role))
>       result = await deep_runtime.run_report(ws)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_reviewer_prompt017.py:76: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3852151c0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_single_reviewer.py::test_feedback_returns_control_without_automatic_grader[not_satisfied]

```text
ws = <report_agent.workspace.Workspace object at 0x74b37e9e6fc0>
verdict = 'not_satisfied'

    @pytest.mark.parametrize("verdict", ["not_satisfied", "undetermined", None])
    async def test_feedback_returns_control_without_automatic_grader(ws, verdict):
        new_path(ws)
        cs, actor, refs, snapshot, _ = seed(ws)
        export = export_snapshot(cs, actor,"export",snapshot)["result"]["export_ref"]
        def submit(messages):
            receipt = observation(messages,"read_context")["receipt_id"]
            data = submission(snapshot,refs,review_item(refs["claim"],refs["k"],receipt,verdict))
            return invoke("submit_review",operation_id="review",review=data,delivery_export_ref=export)
        driver = Driver(coordinator=[
            invoke("select_content_delivery",operation_id="select",snapshot_ref=snapshot,export_ref=export),
            invoke("task",**review_assignment(snapshot, refs)),
            invoke("record_execution_decision",operation_id="decision",decision="continue",reason="Investigate next useful correction",evidence=["saved review"],unresolved=["remaining checks"]),
            invoke("read_feedback"), AIMessage(content="Preserved incomplete delivery.")],
            reviewer=[invoke("read_context",target_ref=snapshot),submit,AIMessage(content="Saved review and limitations.")])
        result=await deep_runtime.run_report(ws,driver)
        assert result["last_error"] is None, result
        assert "rubric_grader" not in driver.created
        assert ws.store.get("content_execution_decision")["decision"] == "continue"
>       assert current_delivery(ws.store)["items"]
E       assert []

tests/test_single_reviewer.py:79: AssertionError
```

## failed: tests/test_single_reviewer.py::test_feedback_returns_control_without_automatic_grader[undetermined]

```text
ws = <report_agent.workspace.Workspace object at 0x74b37daa6e10>
verdict = 'undetermined'

    @pytest.mark.parametrize("verdict", ["not_satisfied", "undetermined", None])
    async def test_feedback_returns_control_without_automatic_grader(ws, verdict):
        new_path(ws)
        cs, actor, refs, snapshot, _ = seed(ws)
        export = export_snapshot(cs, actor,"export",snapshot)["result"]["export_ref"]
        def submit(messages):
            receipt = observation(messages,"read_context")["receipt_id"]
            data = submission(snapshot,refs,review_item(refs["claim"],refs["k"],receipt,verdict))
            return invoke("submit_review",operation_id="review",review=data,delivery_export_ref=export)
        driver = Driver(coordinator=[
            invoke("select_content_delivery",operation_id="select",snapshot_ref=snapshot,export_ref=export),
            invoke("task",**review_assignment(snapshot, refs)),
            invoke("record_execution_decision",operation_id="decision",decision="continue",reason="Investigate next useful correction",evidence=["saved review"],unresolved=["remaining checks"]),
            invoke("read_feedback"), AIMessage(content="Preserved incomplete delivery.")],
            reviewer=[invoke("read_context",target_ref=snapshot),submit,AIMessage(content="Saved review and limitations.")])
        result=await deep_runtime.run_report(ws,driver)
        assert result["last_error"] is None, result
        assert "rubric_grader" not in driver.created
        assert ws.store.get("content_execution_decision")["decision"] == "continue"
>       assert current_delivery(ws.store)["items"]
E       assert []

tests/test_single_reviewer.py:79: AssertionError
```

## failed: tests/test_single_reviewer.py::test_feedback_returns_control_without_automatic_grader[None]

```text
ws = <report_agent.workspace.Workspace object at 0x74b37e631040>, verdict = None

    @pytest.mark.parametrize("verdict", ["not_satisfied", "undetermined", None])
    async def test_feedback_returns_control_without_automatic_grader(ws, verdict):
        new_path(ws)
        cs, actor, refs, snapshot, _ = seed(ws)
        export = export_snapshot(cs, actor,"export",snapshot)["result"]["export_ref"]
        def submit(messages):
            receipt = observation(messages,"read_context")["receipt_id"]
            data = submission(snapshot,refs,review_item(refs["claim"],refs["k"],receipt,verdict))
            return invoke("submit_review",operation_id="review",review=data,delivery_export_ref=export)
        driver = Driver(coordinator=[
            invoke("select_content_delivery",operation_id="select",snapshot_ref=snapshot,export_ref=export),
            invoke("task",**review_assignment(snapshot, refs)),
            invoke("record_execution_decision",operation_id="decision",decision="continue",reason="Investigate next useful correction",evidence=["saved review"],unresolved=["remaining checks"]),
            invoke("read_feedback"), AIMessage(content="Preserved incomplete delivery.")],
            reviewer=[invoke("read_context",target_ref=snapshot),submit,AIMessage(content="Saved review and limitations.")])
        result=await deep_runtime.run_report(ws,driver)
        assert result["last_error"] is None, result
        assert "rubric_grader" not in driver.created
        assert ws.store.get("content_execution_decision")["decision"] == "continue"
>       assert current_delivery(ws.store)["items"]
E       assert []

tests/test_single_reviewer.py:79: AssertionError
```

## failed: tests/test_source_search_view.py::test_native_tool_schema_exposes_choice_and_exact_full_access

```text
ws = <report_agent.workspace.Workspace object at 0x74b3856f37d0>

    async def test_native_tool_schema_exposes_choice_and_exact_full_access(ws):
        configure_source_search(ws)
        def inspect_ref(messages):
            got = observation(messages, "search_sources")
            assert got["matches"][0]["text"] == "alpha"
            assert got["table_detail"] == "references"
            return invoke("search_sources", query="alpha", limit=1, source_id="original", table_detail="full")
        def finish(messages):
            got = observation(messages, "search_sources")
            assert got["source_table_views"][0]["tables"][0]["rows"][2] == ["2", "", "7"]
            return verdict(ws, ["satisfied"])
        driver = Driver(rubric_grader=[invoke("search_sources", query="alpha", limit=1, source_id="original"), inspect_ref, finish])
        review = grader(ws, driver)
>       result = await review._ensure_grader().ainvoke(payload(ws, review))
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_source_search_view.py:226: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/langgraph/pregel/main.py:4090: in ainvoke
    async for chunk in self.astream(
/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/langgraph/pregel/main.py:3440: in astream
    async for _ in runner.atick(
/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/langgraph/pregel/_runner.py:396: in atick
    await arun_with_retry(
/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/langgraph/pregel/_retry.py:744: in arun_with_retry
    return await task.proc.ainvoke(task.input, config)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/langgraph/_internal/_runnable.py:756: in ainvoke
    input = await asyncio.create_task(
/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/langgraph/_internal/_runnable.py:522: in ainvoke
    ret = await self.afunc(*args, **kwargs)
          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/langchain/agents/factory.py:1537: in amodel_node
    result = await awrap_model_call_handler(request, _execute_model_async)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/langchain/agents/factory.py:430: in composed
    outer_result = await outer(request, inner_handler)
                   ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/langchain/agents/middleware/todo.py:283: in awrap_model_call
    return await handler(request.override(system_message=new_system_message))
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/langchain/agents/factory.py:420: in inner_handler
    inner_result = await inner(req, handler)
                   ^^^^^^^^^^^^^^^^^^^^^^^^^
src/report_agent/deep_runtime.py:177: in awrap_model_call
    return await handler(request)
           ^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/langchain/agents/factory.py:1505: in _execute_model_async
    output = await model_.ainvoke(messages)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/langchain_core/language_models/chat_models.py:511: in ainvoke
    llm_result = await self.agenerate_prompt(
/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/langchain_core/language_models/chat_models.py:1888: in agenerate_prompt
    return await self.agenerate(
/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/langchain_core/language_models/chat_models.py:1846: in agenerate
    raise exceptions[0]
/home/dysun/.venvs/report-agent-system/lib/python3.12/site-packages/langchain_core/language_models/chat_models.py:2179: in _agenerate_with_cache
    result = await self._agenerate(
tests/test_deep_runtime.py:49: in _agenerate
    return await self.driver.respond(self.role, messages)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
tests/test_deep_runtime.py:85: in respond
    response = item(messages) if callable(item) else item
               ^^^^^^^^^^^^^^
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

messages = [SystemMessage(content=[{'type': 'text', 'text': "# Acceptance responsibility\n\nYou are responsible for planning, exe..."}}', name='search_sources', id='cbfa35a6-21ef-4d27-8c11-a94069e99c6b', tool_call_id='search_sources', status='error')]

    def inspect_ref(messages):
        got = observation(messages, "search_sources")
>       assert got["matches"][0]["text"] == "alpha"
               ^^^^^^^^^^^^^^
E       KeyError: 'matches'
E       During task with name 'model' and id '752c0334-8c1c-f780-aabb-85a4a9fbcfc4'

tests/test_source_search_view.py:217: KeyError
```

## failed: tests/test_text_work_candidate_inputs.py::test_candidate_counts_toward_bound_and_old_receipt_stays_usable

```text
ws = <report_agent.workspace.Workspace object at 0x74b37e89d4c0>
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b37e89dd90>

    async def test_candidate_counts_toward_bound_and_old_receipt_stays_usable(ws,monkeypatch):
        _,_,refs,_,_=seed(ws)
        with delegated_task(ws,'coordinator',writer_call()) as (_,actor):
            first=await draft(ws,refs,actor)
            monkeypatch.setattr(text_work,'MAX_EVIDENCE_CHARACTERS',20)
            attempt=Model(json.dumps(content()))
>           with pytest.raises(ActionRejected,match='SELECT_SMALLER_LOCATED_EVIDENCE'):
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E           Failed: DID NOT RAISE ActionRejected

tests/test_text_work_candidate_inputs.py:148: Failed
```

## failed: tests/test_tool_feedback.py::test_analysis_failure_does_not_record_successful_source_observation

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_analysis_failure_does_not0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b38529b530>

    async def test_analysis_failure_does_not_record_successful_source_observation(tmp_path, monkeypatch):
        from types import SimpleNamespace
        from report_agent.models import TextAnalysis
        ws = workspace(tmp_path)
        task = ws.request_task('materials', 'Optional analysis', [])
>       tools = {t.__name__: t for t in worker_tools(ws, task['id'], SimpleNamespace(model='offline-only'))}
                                        ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_tool_feedback.py:32: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3856f1a00>
task_id = 'a5135cfa-4950-4ab5-ac9a-2c62245d5e67'
text_model = namespace(model='offline-only')

    def worker_tools(workspace: Workspace, task_id: str, text_model):
>       raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: archived ADK worker tools")
E       report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: archived ADK worker tools

src/report_agent/report_runtime.py:105: ActionRejected
```

## failed: tests/test_tool_transport.py::test_native_review_transport_preserves_actor_receipt_and_idempotency

```text
ws = <report_agent.workspace.Workspace object at 0x74b38562ee70>

    async def test_native_review_transport_preserves_actor_receipt_and_idempotency(ws):
        cs, _, refs, snapshot, _ = seed(ws)
        captured = {}
        def save(messages):
            receipt = observation(messages, 'read_context')['receipt_id']
            data = submission(snapshot, refs, review_item(snapshot, refs['k'], receipt))
            captured['review'] = data
            return invoke('submit_review', operation_id='same-review', review=json.dumps(data))
        def repeat(messages):
            captured['saved'] = observation(messages, 'submit_review')
            return invoke('submit_review', operation_id='same-review', review=captured['review'])
        def verify(messages):
            assert observation(messages, 'submit_review') == captured['saved']
            return AIMessage(content='Saved scoped test review.')
        driver = Driver(coordinator=[invoke('task', subagent_type='reviewer', description='Inspect synthetic claim.'),
                                     AIMessage(content='Done.')],
            reviewer=[invoke('read_context', target_ref=json.dumps(refs['claim'])), save, repeat, verify])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_tool_transport.py:66: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b38562ee70>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_tool_transport.py::test_decoded_review_still_requires_schema_and_observation[missing]

```text
ws = <report_agent.workspace.Workspace object at 0x74b385272a80>
fault = 'missing'

    @pytest.mark.parametrize('fault', ['missing', 'unknown', 'wrong_version_type', 'missing_version', 'fake_receipt', 'foreign_receipt'])
    async def test_decoded_review_still_requires_schema_and_observation(ws, fault):
        cs, actor, refs, snapshot, _ = seed(ws)
        data = submission(snapshot, refs, review_item(snapshot, refs['k'], 'invented-receipt'))
        if fault == 'missing':
            del data['items']
        elif fault == 'unknown':
            data['owner_id'] = 'content:coordinator'
        elif fault == 'wrong_version_type':
            data['snapshot_ref'] = {**snapshot, 'version': '1'}
        elif fault == 'missing_version':
            data['snapshot_ref'] = {**snapshot, 'version': 999}
        elif fault == 'foreign_receipt':
            data['items'][0]['observations'][0]['receipt_id'] = cs.read_context(actor, refs['claim'])['receipt_id']
        def rejected(messages):
            msg = next(m for m in reversed(messages) if isinstance(m, ToolMessage))
            assert msg.status == 'error' or json.loads(msg.content).get('ok') is False
            return AIMessage(content='Rejected; no review saved.')
        driver = Driver(coordinator=[invoke('task', subagent_type='reviewer', description='Synthetic invalid call test.'),
                                     AIMessage(content='Done.')],
            reviewer=[invoke('submit_review', operation_id='invalid-review', review=json.dumps(data)), rejected])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_tool_transport.py:98: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b385272a80>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_tool_transport.py::test_decoded_review_still_requires_schema_and_observation[unknown]

```text
ws = <report_agent.workspace.Workspace object at 0x74b38562e990>
fault = 'unknown'

    @pytest.mark.parametrize('fault', ['missing', 'unknown', 'wrong_version_type', 'missing_version', 'fake_receipt', 'foreign_receipt'])
    async def test_decoded_review_still_requires_schema_and_observation(ws, fault):
        cs, actor, refs, snapshot, _ = seed(ws)
        data = submission(snapshot, refs, review_item(snapshot, refs['k'], 'invented-receipt'))
        if fault == 'missing':
            del data['items']
        elif fault == 'unknown':
            data['owner_id'] = 'content:coordinator'
        elif fault == 'wrong_version_type':
            data['snapshot_ref'] = {**snapshot, 'version': '1'}
        elif fault == 'missing_version':
            data['snapshot_ref'] = {**snapshot, 'version': 999}
        elif fault == 'foreign_receipt':
            data['items'][0]['observations'][0]['receipt_id'] = cs.read_context(actor, refs['claim'])['receipt_id']
        def rejected(messages):
            msg = next(m for m in reversed(messages) if isinstance(m, ToolMessage))
            assert msg.status == 'error' or json.loads(msg.content).get('ok') is False
            return AIMessage(content='Rejected; no review saved.')
        driver = Driver(coordinator=[invoke('task', subagent_type='reviewer', description='Synthetic invalid call test.'),
                                     AIMessage(content='Done.')],
            reviewer=[invoke('submit_review', operation_id='invalid-review', review=json.dumps(data)), rejected])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_tool_transport.py:98: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b38562e990>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_tool_transport.py::test_decoded_review_still_requires_schema_and_observation[wrong_version_type]

```text
ws = <report_agent.workspace.Workspace object at 0x74b3852beb10>
fault = 'wrong_version_type'

    @pytest.mark.parametrize('fault', ['missing', 'unknown', 'wrong_version_type', 'missing_version', 'fake_receipt', 'foreign_receipt'])
    async def test_decoded_review_still_requires_schema_and_observation(ws, fault):
        cs, actor, refs, snapshot, _ = seed(ws)
        data = submission(snapshot, refs, review_item(snapshot, refs['k'], 'invented-receipt'))
        if fault == 'missing':
            del data['items']
        elif fault == 'unknown':
            data['owner_id'] = 'content:coordinator'
        elif fault == 'wrong_version_type':
            data['snapshot_ref'] = {**snapshot, 'version': '1'}
        elif fault == 'missing_version':
            data['snapshot_ref'] = {**snapshot, 'version': 999}
        elif fault == 'foreign_receipt':
            data['items'][0]['observations'][0]['receipt_id'] = cs.read_context(actor, refs['claim'])['receipt_id']
        def rejected(messages):
            msg = next(m for m in reversed(messages) if isinstance(m, ToolMessage))
            assert msg.status == 'error' or json.loads(msg.content).get('ok') is False
            return AIMessage(content='Rejected; no review saved.')
        driver = Driver(coordinator=[invoke('task', subagent_type='reviewer', description='Synthetic invalid call test.'),
                                     AIMessage(content='Done.')],
            reviewer=[invoke('submit_review', operation_id='invalid-review', review=json.dumps(data)), rejected])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_tool_transport.py:98: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3852beb10>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_tool_transport.py::test_decoded_review_still_requires_schema_and_observation[missing_version]

```text
ws = <report_agent.workspace.Workspace object at 0x74b3852bf560>
fault = 'missing_version'

    @pytest.mark.parametrize('fault', ['missing', 'unknown', 'wrong_version_type', 'missing_version', 'fake_receipt', 'foreign_receipt'])
    async def test_decoded_review_still_requires_schema_and_observation(ws, fault):
        cs, actor, refs, snapshot, _ = seed(ws)
        data = submission(snapshot, refs, review_item(snapshot, refs['k'], 'invented-receipt'))
        if fault == 'missing':
            del data['items']
        elif fault == 'unknown':
            data['owner_id'] = 'content:coordinator'
        elif fault == 'wrong_version_type':
            data['snapshot_ref'] = {**snapshot, 'version': '1'}
        elif fault == 'missing_version':
            data['snapshot_ref'] = {**snapshot, 'version': 999}
        elif fault == 'foreign_receipt':
            data['items'][0]['observations'][0]['receipt_id'] = cs.read_context(actor, refs['claim'])['receipt_id']
        def rejected(messages):
            msg = next(m for m in reversed(messages) if isinstance(m, ToolMessage))
            assert msg.status == 'error' or json.loads(msg.content).get('ok') is False
            return AIMessage(content='Rejected; no review saved.')
        driver = Driver(coordinator=[invoke('task', subagent_type='reviewer', description='Synthetic invalid call test.'),
                                     AIMessage(content='Done.')],
            reviewer=[invoke('submit_review', operation_id='invalid-review', review=json.dumps(data)), rejected])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_tool_transport.py:98: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3852bf560>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_tool_transport.py::test_decoded_review_still_requires_schema_and_observation[fake_receipt]

```text
ws = <report_agent.workspace.Workspace object at 0x74b3852bcfb0>
fault = 'fake_receipt'

    @pytest.mark.parametrize('fault', ['missing', 'unknown', 'wrong_version_type', 'missing_version', 'fake_receipt', 'foreign_receipt'])
    async def test_decoded_review_still_requires_schema_and_observation(ws, fault):
        cs, actor, refs, snapshot, _ = seed(ws)
        data = submission(snapshot, refs, review_item(snapshot, refs['k'], 'invented-receipt'))
        if fault == 'missing':
            del data['items']
        elif fault == 'unknown':
            data['owner_id'] = 'content:coordinator'
        elif fault == 'wrong_version_type':
            data['snapshot_ref'] = {**snapshot, 'version': '1'}
        elif fault == 'missing_version':
            data['snapshot_ref'] = {**snapshot, 'version': 999}
        elif fault == 'foreign_receipt':
            data['items'][0]['observations'][0]['receipt_id'] = cs.read_context(actor, refs['claim'])['receipt_id']
        def rejected(messages):
            msg = next(m for m in reversed(messages) if isinstance(m, ToolMessage))
            assert msg.status == 'error' or json.loads(msg.content).get('ok') is False
            return AIMessage(content='Rejected; no review saved.')
        driver = Driver(coordinator=[invoke('task', subagent_type='reviewer', description='Synthetic invalid call test.'),
                                     AIMessage(content='Done.')],
            reviewer=[invoke('submit_review', operation_id='invalid-review', review=json.dumps(data)), rejected])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_tool_transport.py:98: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b3852bcfb0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_tool_transport.py::test_decoded_review_still_requires_schema_and_observation[foreign_receipt]

```text
ws = <report_agent.workspace.Workspace object at 0x74b37f398fe0>
fault = 'foreign_receipt'

    @pytest.mark.parametrize('fault', ['missing', 'unknown', 'wrong_version_type', 'missing_version', 'fake_receipt', 'foreign_receipt'])
    async def test_decoded_review_still_requires_schema_and_observation(ws, fault):
        cs, actor, refs, snapshot, _ = seed(ws)
        data = submission(snapshot, refs, review_item(snapshot, refs['k'], 'invented-receipt'))
        if fault == 'missing':
            del data['items']
        elif fault == 'unknown':
            data['owner_id'] = 'content:coordinator'
        elif fault == 'wrong_version_type':
            data['snapshot_ref'] = {**snapshot, 'version': '1'}
        elif fault == 'missing_version':
            data['snapshot_ref'] = {**snapshot, 'version': 999}
        elif fault == 'foreign_receipt':
            data['items'][0]['observations'][0]['receipt_id'] = cs.read_context(actor, refs['claim'])['receipt_id']
        def rejected(messages):
            msg = next(m for m in reversed(messages) if isinstance(m, ToolMessage))
            assert msg.status == 'error' or json.loads(msg.content).get('ok') is False
            return AIMessage(content='Rejected; no review saved.')
        driver = Driver(coordinator=[invoke('task', subagent_type='reviewer', description='Synthetic invalid call test.'),
                                     AIMessage(content='Done.')],
            reviewer=[invoke('submit_review', operation_id='invalid-review', review=json.dumps(data)), rejected])
>       result = await deep_runtime.run_report(ws, driver)
                 ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

tests/test_tool_transport.py:98: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 
src/report_agent/deep_runtime.py:849: in run_report
    require_native_runtime(workspace)
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ 

workspace = <report_agent.workspace.Workspace object at 0x74b37f398fe0>

    def require_native_runtime(workspace):
        """Reject retired execution before locks, status changes or checkpoint setup."""
        from .hierarchical_tools import enabled
        if workspace.store.get("decision_observation"):
            raise ActionRejected("DECISION_OBSERVATION_TERMINAL_USE_NEW_ISOLATED_CASE")
        if not enabled(workspace) or workspace.store.manifest.get("review_entrypoint") == "native-rubric-v1":
>           raise ActionRejected("HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable")
E           report_agent.errors.ActionRejected: HISTORICAL_AGENT_EXECUTION_INACTIVE: use a fresh native hierarchical project with independent text tools; saved historical data remains readable

src/report_agent/deep_runtime.py:763: ActionRejected
```

## failed: tests/test_vision.py::test_vision_model_uses_authorized_account_without_changing_agent_model

```text
tmp_path = PosixPath('/tmp/report-round0-df5nuc3x/pytest/test_vision_model_uses_authori0')
monkeypatch = <_pytest.monkeypatch.MonkeyPatch object at 0x74b37cfaf500>

    @pytest.mark.asyncio
    async def test_vision_model_uses_authorized_account_without_changing_agent_model(tmp_path, monkeypatch):
        monkeypatch.setenv('REPORT_BASE_URL', 'https://unit.invalid/v1')
        monkeypatch.setenv('REPORT_API_KEY', 'synthetic-secret')
        monkeypatch.setenv('REPORT_MODEL', 'glm-5.3')
        vision = configured_vision_client()
        agent = configured_model(workspace(tmp_path).store, 'writer')
        assert agent.model_name == 'glm-5.3'
        assert str(vision.base_url).rstrip('/') == agent.openai_api_base
>       assert vision.max_retries == 0
E       assert 5 == 0
E        +  where 5 = <openai.AsyncOpenAI object at 0x74b37d0cbb90>.max_retries

tests/test_vision.py:139: AssertionError
```
