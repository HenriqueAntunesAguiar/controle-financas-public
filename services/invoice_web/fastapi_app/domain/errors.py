"""Erros publicos do nucleo, traduzidos para HTTP apenas no adaptador web."""


class ApplicationError(RuntimeError):
    code = "application_error"

    def __init__(self, public_message: str):
        super().__init__(public_message)
        self.public_message = public_message


class InvalidInputError(ApplicationError):
    code = "invalid_input"


class NotFoundError(ApplicationError):
    code = "not_found"


class ConflictError(ApplicationError):
    code = "conflict"


class ForbiddenError(ApplicationError):
    code = "forbidden"


class ProcessingError(ApplicationError):
    code = "processing_failed"


class ImportUnavailableError(ApplicationError):
    code = "import_unavailable"
