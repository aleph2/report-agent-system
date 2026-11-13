"""Current flat coordinator task contract; the program binds resource identities."""
from typing import Annotated, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator



class CoTaskMessage(BaseModel):
    """Current model-facing task message. Resource identities belong to the request dictionary."""
    model_config = ConfigDict(extra='forbid', strict=True)
    diagnostic_errors: ClassVar[dict] = {
        'WRITER_OBJECT_REQUIRES_FRESH_TASK': (['assessment_object_id', 'subagent_type', 'resume_task_scope'], 'Select one included object only for a new Writer task; omit the binding for other roles and task continuation.'),
        'TASK_OBJECTIVE_REQUIRED': (['description'], 'State the actual non-blank task objective.'),
        'TASK_CONTINUATION_CANNOT_CHANGE_ASSIGNMENT': (['resume_task_scope'], 'Continue the saved task without new assignment fields; choose a new task for a changed assignment.'),
        'REVIEW_SNAPSHOT_COMPLETE_BASIS_AND_SCOPE_REQUIRED': (['snapshot_scope', 'commission_criterion_scopes', 'review_scope'], 'Select the exact snapshot, complete commissioned standard basis and actual review extent from this request.'),
        'WHOLE_CONTENT_CANNOT_MIX_TARGETED_SELECTIONS': (['review_scope', 'target_scope', 'criterion_scopes', 'artifact_scopes'], 'Whole content uses the complete content basis. Choose targeted for an explicit subset, target or artifact question.'),
        'TARGETED_REVIEW_TARGET_REQUIRED': (['target_scope'], 'Select the exact authorized target for the targeted question.'),
        'ARTIFACT_SELECTION_REQUIRED': (['assessment_kind', 'artifact_scopes'], 'Select actual saved artifacts for an export or render question; available files do not prove correctness.'),
        'CONTENT_SELECTION_HAS_NO_ARTIFACT_JUDGMENT': (['assessment_kind', 'artifact_scopes'], 'Express the actual content versus artifact question, without combining incompatible selections.'),
        'REVIEW_SELECTION_REQUIRES_REVIEWER': (['subagent_type'], 'Review selection fields belong to Reviewer tasks; other roles use only their actual task fields.'),
        'LAYOUT_SNAPSHOT_SCOPE_REQUIRED': (['snapshot_scope'], 'Select the exact saved snapshot to grant Layout presentation access.'),
        'REVIEW_EXTENT_SELECTION_INVALID': (['content_extent', 'artifact_pages', 'assessment_kind'], 'Select the actual body extent or distinct physical pages for one rendered artifact; do not mix unrelated kinds or infer unchecked pages.'),
    }
    description: str = Field(min_length=1, description='Required actual task objective, constraints, scope and expected return. State work to perform, not a result in advance. Text does not grant access.')
    subagent_type: Literal['writer', 'reviewer', 'layout'] = Field(description='Required responsible role. Choose from the actual task goal; no role sequence is prescribed.')
    section_ids: list[str] = Field(default_factory=list, description='For a new writer assignment under an owner-confirmed commission plan, choose the saved section IDs. The host binds their exact source-linked plan rows. Omit for other roles and task continuation.')
    assessment_object_id: str | None = Field(default=None, min_length=1, description='For a new Writer assignment, bind the Writer to one included object ID from the confirmed commission plan. Assign one extracted section for that object. Omit for other roles and task continuation.')
    snapshot_scope: str | None = Field(default=None, description='Short DocumentSnapshot scope from THIS request dictionary. Required for a new Reviewer assignment or Layout grant. Do not return a UUID or resource object. Omit when continuing an existing task.')
    commission_criterion_scopes: list[str] = Field(default_factory=list, min_length=1, description='For a new Reviewer task, required non-empty distinct Criterion scopes defining the complete commissioned acceptance basis. Choose the full basis, including outcomes not checked in this task. This is not a verdict. Other roles omit this field.')
    criterion_scopes: list[str] = Field(default_factory=list, min_length=1, description='For targeted Reviewer work, optional distinct Criterion scopes selected from commission_criterion_scopes. Omit to select the complete basis. An explicit empty list or null is invalid. Every selected criterion uses this task same selected target and artifacts; use separate tasks for different mappings.')
    review_scope: Literal['whole_content', 'targeted'] | None = Field(default=None, description='Required for a new Reviewer assignment: whole_content checks the commissioned content basis in the selected snapshot; targeted checks the explicit target/artifacts. These are distinct business scopes, not completion statuses. Other roles and task continuation omit this field.')
    target_scope: str | None = Field(default=None, description='Required for targeted Reviewer work: exact DocumentSnapshot or ContentNode short scope from THIS dictionary. It must belong to snapshot_scope. Omit for whole_content; the program uses the snapshot root without inventing a narrower or broader question.')
    assessment_kind: Literal['content', 'export', 'render'] = Field(default='content', description='Reviewer targeted question: content checks report substance; export checks saved export fidelity; render checks rendered-page presentation. Default content. Select the actual question, never infer success from an artifact existing.')
    artifact_scopes: list[str] = Field(default_factory=list, description='Distinct short artifact scopes from THIS dictionary. Required and non-empty for export/render; export requires exact ExportArtifact scopes, render exact RenderArtifact scopes. Each must belong to snapshot_scope. Content uses no artifacts. This does not assert the files were read.')
    content_extent: Literal['local_body', 'subtree_bodies'] | None = Field(default=None,
        description='Optional targeted content extent for the selected ContentNode: only its own body or its actual contained subtree bodies. Omit when no such body extent is assigned. This does not broaden the chosen criterion or mean the content was verified.')
    artifact_pages: list[Annotated[int, Field(ge=1)]] = Field(default_factory=list,
        description='Optional distinct one-based physical pages of ONE selected RenderArtifact for targeted page review. Return only the actual pages requested, not PDF block indexes. Omission selects no extra page-specific extent; it does not claim all pages checked. Export structure and content questions omit this field.')
    supervision_plugin: str | None = Field(default=None, description='Optional registered Reviewer supervision plugin name; omit for no selection. It does not create access or semantic approval.')
    resume_task_scope: str | None = Field(default=None, description='Optional existing DelegatedTask scope from THIS dictionary to continue its persistent owner with unchanged role, permissions and assignment. Use an owned object owner_task_scope for its original producer, not a UUID or a new same-role task. Return description/subagent_type plus this scope; do not combine it with a new snapshot, standards, scope, artifacts or supervision selection. This restores business identity, not all earlier chat messages.')

    @model_validator(mode='after')
    def actual_business_selection(self):
        if not self.description.strip():
            raise ValueError('TASK_OBJECTIVE_REQUIRED')
        if 'section_ids' in self.model_fields_set and (self.subagent_type != 'writer' or self.resume_task_scope is not None):
            raise ValueError('COMMISSION_SECTIONS_REQUIRE_NEW_WRITER_TASK')
        if self.assessment_object_id is not None and (self.subagent_type != 'writer' or self.resume_task_scope is not None):
            raise ValueError('WRITER_OBJECT_REQUIRES_FRESH_TASK')
        new_fields = {'snapshot_scope', 'commission_criterion_scopes', 'criterion_scopes', 'review_scope',
                      'target_scope', 'assessment_kind', 'artifact_scopes', 'supervision_plugin', 'content_extent', 'artifact_pages'}
        if self.resume_task_scope is not None:
            if self.model_fields_set & new_fields:
                raise ValueError('TASK_CONTINUATION_CANNOT_CHANGE_ASSIGNMENT')
            return self
        if self.subagent_type == 'reviewer':
            if self.snapshot_scope is None or not self.commission_criterion_scopes or self.review_scope is None:
                raise ValueError('REVIEW_SNAPSHOT_COMPLETE_BASIS_AND_SCOPE_REQUIRED')
            if self.review_scope == 'whole_content':
                if self.target_scope is not None or self.artifact_scopes or self.assessment_kind != 'content' or 'criterion_scopes' in self.model_fields_set or self.content_extent is not None or self.artifact_pages:
                    raise ValueError('WHOLE_CONTENT_CANNOT_MIX_TARGETED_SELECTIONS')
            elif self.target_scope is None:
                raise ValueError('TARGETED_REVIEW_TARGET_REQUIRED')
            if self.assessment_kind != 'content' and not self.artifact_scopes:
                raise ValueError('ARTIFACT_SELECTION_REQUIRED')
            if self.assessment_kind == 'content' and self.artifact_scopes:
                raise ValueError('CONTENT_SELECTION_HAS_NO_ARTIFACT_JUDGMENT')
            if ((self.content_extent is not None and (self.review_scope != 'targeted' or self.assessment_kind != 'content'))
                    or (self.artifact_pages and (self.review_scope != 'targeted' or self.assessment_kind != 'render'
                        or len(self.artifact_scopes) != 1 or len(set(self.artifact_pages)) != len(self.artifact_pages)))):
                raise ValueError('REVIEW_EXTENT_SELECTION_INVALID')
        else:
            fields = new_fields - {'snapshot_scope'} if self.subagent_type == 'layout' else new_fields
            if self.model_fields_set & fields:
                raise ValueError('REVIEW_SELECTION_REQUIRES_REVIEWER')
            if self.subagent_type == 'layout' and self.snapshot_scope is None:
                raise ValueError('LAYOUT_SNAPSHOT_SCOPE_REQUIRED')
        return self
