"""Expose existing content contracts to models, retaining batch-local references.

These are tool input shapes. ContentStore remains the authority for resolved
references, semantic structural validators, permissions and atomic writes.
"""
from copy import deepcopy
from typing import Annotated, Literal

from pydantic import Field, create_model

from .content_models import Contract, Ref, Criterion, ContentNode, Evidence, Relation, SourceRef


class ClientRef(Contract):
    client_key: str = Field(min_length=1, description="Key of a new object in this same atomic batch.")


BatchRef = Ref | ClientRef


class RequirementRef(Ref):
    type: Literal['Requirement']


def input_shape(model, overrides=None, descriptions=None):
    """Reuse field definitions, leaving post-resolution validators in the store."""
    overrides, descriptions = overrides or {}, descriptions or {}
    fields = {}
    for name, original in model.model_fields.items():
        field = deepcopy(original)
        if name in descriptions:
            field.description = descriptions[name]
        fields[name] = (overrides.get(name, original.annotation), field)
    return create_model('Commit' + model.__name__ + 'Payload', __base__=Contract, __config__=dict(model.model_config), **fields)


CriterionInput = input_shape(Criterion, {'requirement_refs': list[RequirementRef]}, descriptions={
    'requirement_refs': 'Exact Requirement refs returned by import_source_versions; source IDs or SourceArtifact refs are not Requirement refs.'})
NodeInput = input_shape(ContentNode)
EvidenceInput = input_shape(Evidence, {
    'source_refs': list[SourceRef], 'input_refs': list[BatchRef], 'extraction_ref': BatchRef | None})
RelationInput = input_shape(Relation, {
    'subject_ref': BatchRef, 'object_ref': BatchRef, 'basis_refs': list[BatchRef]})
RelationInputV2 = input_shape(Relation, {
    'subject_ref': BatchRef, 'object_ref': BatchRef, 'basis_refs': list[BatchRef]}, descriptions={
    'predicate': 'contains requires ContentNode endpoints and position. supported_by and contradicted_by require a ContentNode subject_ref and an Evidence object_ref, not SourceArtifact. Same-batch client_key refs are resolved before endpoint validation.'})


def object_shape(kind, payload):
    return create_model('Commit' + kind, __base__=Contract,
        client_key=(str, Field(min_length=1)),
        type=(Literal[kind], ...),
        payload=(payload, ...),
        previous_ref=(Ref | None, Field(default=None,
            description='Exact current owned version for a revision; omit for a new object.')))


CriterionObject = object_shape('Criterion', CriterionInput)
NodeObject = object_shape('ContentNode', NodeInput)
EvidenceObject = object_shape('Evidence', EvidenceInput)
RelationObject = object_shape('Relation', RelationInput)
CommitObject = Annotated[CriterionObject | NodeObject | EvidenceObject | RelationObject,
                         Field(discriminator='type')]
