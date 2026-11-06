class AppError(Exception):
    """An expected application failure, rendered by the HTTP adapter."""

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message

    @property
    def detail(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message}


def fail(status: int, code: str, message: str) -> AppError:
    return AppError(status, code, message)
