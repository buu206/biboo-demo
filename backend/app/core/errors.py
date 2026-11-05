from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.detail = ErrorResponse(error=ErrorDetail(code=code, message=message))


def not_found():
    return AppError(404, "NOT_FOUND", "找不到这条记录。")


def invalid_state(message: str):
    return AppError(409, "INVALID_STATE", message)
