"""Stable domain error codes."""


class DomainError(ValueError):
    def __init__(self, reason_code: str) -> None:
        self.reason_code = reason_code
        super().__init__(reason_code)


class TransitionError(DomainError):
    pass
