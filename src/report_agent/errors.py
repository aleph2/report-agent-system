class ActionRejected(ValueError):
    """An explicit domain request rejection that an agent can correct."""


class ActionForbidden(PermissionError):
    """A rejected domain action; the tool never relaxes the caller's authority."""


class ModelRequestDeadlineExceeded(TimeoutError):
    """The adapter's own logical request deadline expired; outcome is unknown."""

    def __init__(self, seconds):
        super().__init__("MODEL_REQUEST_DEADLINE_EXCEEDED")
        self.deadline_seconds = seconds
