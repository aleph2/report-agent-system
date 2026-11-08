"""Task-side ownership of the assessment produced for one approved plan and slope."""
from uuid import NAMESPACE_URL, uuid5

from . import legacy_state as legacy
from .assertions.launch import Commission
from .assessment_projection import selected_assessment
from .errors import ActionForbidden, ActionRejected
from .store import digest


def bind_producer(cs, db, plan_ref, object_id, actor, *, bulk=False, draft_only=False):
    """Check and claim inside the Writer's existing serialized content transaction."""
    key = digest([plan_ref, object_id])
    db.execute("""CREATE TABLE IF NOT EXISTS assessment_producers(
        plan_object TEXT PRIMARY KEY, actor TEXT NOT NULL, native INTEGER NOT NULL)""")
    row = db.execute("SELECT actor,native FROM assessment_producers WHERE plan_object=?", (key,)).fetchone()
    if row and row[0] != actor.id:
        raise ActionForbidden("FORBIDDEN: assessment producer ownership")
    if row and row[1]:
        if bulk:
            raise ActionRejected("ASSESSMENT_NATIVE_INPUTS_REQUIRED")
        return
    if not row:
        historic = legacy.get_g6_assessment_producer(db, key) or selected_assessment(db, plan_ref, object_id)
        if historic and cs._read(db, historic)["owner_id"] != actor.id:
            raise ActionForbidden("FORBIDDEN: assessment producer ownership")
    # An M2 judgment may have committed before its task-side receipt or runtime binding.
    if (cs.store.root / "assertions.sqlite3").is_file():
        owner = Commission(cs.store.root).producer(digest(plan_ref), object_id)
        if owner and owner != str(uuid5(NAMESPACE_URL, actor.id)):
            raise ActionForbidden("FORBIDDEN: assessment producer ownership")
        if owner and bulk:
            raise ActionRejected("ASSESSMENT_NATIVE_INPUTS_REQUIRED")
    if bulk and draft_only:
        return
    if not row:
        db.execute("INSERT INTO assessment_producers VALUES(?,?,?)", (key, actor.id, not bulk))
    elif not bulk:
        db.execute("UPDATE assessment_producers SET native=1 WHERE plan_object=?", (key,))
