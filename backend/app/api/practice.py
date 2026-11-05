from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.core.auth import CurrentTeacher, Database
from app.core.errors import AppError, ErrorResponse, not_found
from app.models import PracticeAttempt
from app.schemas.practice import AttemptView
from app.services import demo_voice, practice
from app.services.recordings import MAX_UPLOAD_BYTES

router = APIRouter(
    prefix="/api/v1/practice",
    responses={code: {"model": ErrorResponse} for code in (401, 404, 409, 413, 415, 422, 503)},
)


@router.get("/items/{item_id}/demo-audio", response_class=FileResponse)
def read_demo_audio(
    item_id: int, request: Request, db: Database, teacher: CurrentTeacher,
    drill_attempt_id: Annotated[int | None, Query(gt=0)] = None,
) -> FileResponse:
    settings = request.app.state.settings
    if not settings.fake_models:
        raise not_found()
    item = practice.published_item(db, teacher.id, item_id)
    spoken = item.text
    if drill_attempt_id is not None:
        spoken = db.scalar(select(PracticeAttempt.drill_text).where(
            PracticeAttempt.id == drill_attempt_id, PracticeAttempt.item_id == item_id,
            PracticeAttempt.owner_id == teacher.id, PracticeAttempt.decision == "practice",
        ))
        if not spoken:
            raise not_found()
    return FileResponse(demo_voice.speak(settings.data_dir / "demo-voice", spoken), media_type="audio/wav")


@router.get("/items/{item_id}/attempts")
def history(item_id: int, learner_id: UUID, db: Database, teacher: CurrentTeacher) -> list[AttemptView]:
    return practice.list_attempts(db, teacher.id, item_id, str(learner_id))


@router.post(
    "/items/{item_id}/attempts",
    openapi_extra={"requestBody": {"required": True, "content": {
        "audio/wav": {"schema": {"type": "string", "format": "binary"}},
    }}},
)
async def submit_attempt(
    item_id: int, learner_id: UUID, request: Request, db: Database, teacher: CurrentTeacher,
    idempotency_key: Annotated[UUID, Header()], drill: bool = False,
) -> AttemptView:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type not in ("audio/wav", "audio/x-wav"):
        raise AppError(415, "UNSUPPORTED_AUDIO", "请提交 WAV 录音。")

    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_UPLOAD_BYTES:
            raise AppError(413, "AUDIO_TOO_LARGE", "录音不能超过 2 MB。")
        data.extend(chunk)

    return await run_in_threadpool(
        practice.submit, db, request.app.state.settings, teacher.id, item_id,
        str(learner_id), str(idempotency_key), drill, bytes(data), request.app.state.observer,
    )
