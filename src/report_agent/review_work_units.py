"""Task-bound planning declarations; structure is neither evidence nor semantic approval."""

from pydantic import ValidationError

from .content_models import Ref
from .content_store import ContentStore
from .content_tasks import bound_actor
from .errors import ActionForbidden, ActionRejected


def material_allowed(workspace, task, ref, allowed):
    if ref.key() in allowed:
        return True
    if ref.type != 'RenderArtifact':
        return False
    contents = ContentStore(workspace.store)
    actor = bound_actor(workspace, 'reviewer', None)
    try:
        render = contents.read(ref.model_dump())
        if (render['owner_id'] != actor.id or render['created_by'] != actor.id
                or render['task_id'] != actor.task_id):
            return False
        payload = render['payload']
        exported = Ref.model_validate(payload.get('export_ref'))
        if exported.type != 'ExportArtifact' or exported.key() not in allowed:
            return False
        export = contents.read(exported.model_dump())['payload']
    except (ActionRejected, ActionForbidden, ValidationError):
        return False
    return (payload.get('snapshot_ref') == task['review_snapshot_ref']
            and export.get('snapshot_ref') == task['review_snapshot_ref']
            and bool(export.get('file_digest'))
            and payload.get('export_digest') == export['file_digest'])
