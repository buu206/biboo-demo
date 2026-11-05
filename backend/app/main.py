from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from starlette.exceptions import HTTPException

from app.api.courseware import router as courseware_router
from app.api.practice import router as practice_router
from app.api.review import router as review_router
from app.api.routes import router
from app.core.config import BACKEND, Settings
from app.core.db import database, migrate
from app.core.errors import AppError


def error_response(status, code, message, headers=None):
    error = AppError(status, code, message)
    return JSONResponse(error.detail.model_dump(), status_code=status, headers=headers)


def create_app(settings=None, observer=None):
    @asynccontextmanager
    async def lifespan(app):
        app.state.settings = settings or Settings.load()
        app.state.engine = database(app.state.settings.data_dir)
        try:
            migrate(app.state.engine)
            yield
        finally:
            app.state.engine.dispose()

    app = FastAPI(title="Biboo", lifespan=lifespan)
    app.state.observer = observer
    app.include_router(router)
    app.include_router(practice_router)
    app.include_router(courseware_router)
    app.include_router(review_router)

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(BACKEND / "static" / "index.html", headers={"Cache-Control": "no-store"})

    @app.middleware("http")
    async def same_origin(request: Request, call_next):
        origin = request.headers.get("origin")
        if request.method in {"POST", "PUT"} and origin and origin != str(request.base_url).rstrip("/"):
            return error_response(403, "INVALID_ORIGIN", "请从 Biboo 页面发起操作。")
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.exception_handler(AppError)
    async def app_error(_request, error):
        return JSONResponse(error.detail.model_dump(), status_code=error.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_request, error):
        fields = "、".join(dict.fromkeys(str(issue["loc"][1]) for issue in error.errors() if len(issue["loc"]) > 1))
        message = f"请检查这些字段：{fields}。" if fields else "请检查请求内容。"
        return error_response(422, "VALIDATION_ERROR", message)

    @app.exception_handler(HTTPException)
    async def http_error(_request, error):
        messages = {404: ("NOT_FOUND", "找不到这个地址。"), 405: ("METHOD_NOT_ALLOWED", "不支持此请求方式。")}
        code, message = messages.get(error.status_code, ("HTTP_ERROR", "请求未能完成。"))
        return error_response(error.status_code, code, message, error.headers)

    @app.exception_handler(Exception)
    async def unexpected_error(_request, _error):
        return error_response(500, "INTERNAL_ERROR", "服务暂时无法完成请求。")

    return app


app = create_app()
