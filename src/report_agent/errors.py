from contextlib import contextmanager


class ActionRejected(ValueError):
    """An explicit domain request rejection that an agent can correct."""

    def __init__(self, *args, diagnostic=None):
        super().__init__(*args)
        self.diagnostic = diagnostic


class ActionForbidden(PermissionError):
    """A rejected domain action; the tool never relaxes the caller's authority."""


class LocalStorageBusy(ActionRejected):
    """Local transaction rolled back; external operation receipts remain authoritative."""

    def __init__(self, message='LOCAL_STORAGE_BUSY', *, diagnostic=None):
        super().__init__(message, diagnostic=diagnostic or {
            'retryable': True, 'local_transaction': 'rolled_back',
            'note': 'Retry only the same local operation identity. Inspect its receipt; external work is never automatically replayed.'})


@contextmanager
def external_outcome_pending(operation):
    """Local rollback cannot undo an already dispatched external operation."""
    try:
        yield
    except LocalStorageBusy as error:
        error.diagnostic = {**(error.diagnostic or {}), 'retryable': False,
                            'operation': operation, 'external_outcome': 'unresolved',
                            'note': 'Inspect the saved operation reservation and original response. Do not repeat external work.'}
        raise


class ModelRequestDeadlineExceeded(TimeoutError):
    """The adapter's own logical request deadline expired; outcome is unknown."""

    def __init__(self, seconds):
        super().__init__("MODEL_REQUEST_DEADLINE_EXCEEDED")
        self.deadline_seconds = seconds
