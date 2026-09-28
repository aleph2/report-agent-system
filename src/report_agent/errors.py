class ActionRejected(ValueError):
    """An explicit domain request rejection that an agent can correct."""


class ActionForbidden(PermissionError):
    """A rejected domain action; the tool never relaxes the caller's authority."""
