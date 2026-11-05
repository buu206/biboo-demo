from typing import Literal

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from app.core.auth import CurrentTeacher, Database
from app.core.errors import AppError, ErrorResponse, not_found
from app.services import review
from app.services.recordings import MAX_UPLOAD_BYTES, normalize_wav

router = APIRouter(
    prefix="/api/v1/review",
    responses={code: {"model": ErrorResponse} for code in (401, 404, 409, 413, 415, 422)},
)
NO_CACHE = {"Cache-Control": "private, no-store"}


class ReviewInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    verdict: Literal["good", "practice"]
    note: str = Field(default="", max_length=600)
    focus: str = Field(default="", max_length=60)


@router.get("/classes/{class_id}/dashboard")
def classroom_dashboard(class_id: int, request: Request, db: Database, teacher: CurrentTeacher,
                        lesson_id: int | None = None):
    return review.dashboard(db, request.app.state.settings.data_dir, teacher.id, class_id, lesson_id)


@router.put("/attempts/{attempt_id}")
def review_attempt(attempt_id: int, data: ReviewInput, request: Request, db: Database, teacher: CurrentTeacher):
    return review.save_review(db, request.app.state.settings.data_dir, teacher.id, attempt_id,
                              data.verdict, data.note, data.focus)


@router.get("/attempts/{attempt_id}/audio", response_class=FileResponse)
def attempt_audio(attempt_id: int, request: Request, db: Database, teacher: CurrentTeacher):
    attempt, _, _ = review.owned_attempt(db, teacher.id, attempt_id)
    path = review.recording_path(request.app.state.settings.data_dir, attempt)
    if path is None:
        raise not_found()
    return FileResponse(path, media_type="audio/wav", headers=NO_CACHE)


@router.put("/attempts/{attempt_id}/feedback-audio")
async def upload_feedback_audio(attempt_id: int, request: Request, db: Database, teacher: CurrentTeacher):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() not in ("audio/wav", "audio/x-wav"):
        raise AppError(415, "UNSUPPORTED_AUDIO", "请提交 WAV 录音。")
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_UPLOAD_BYTES:
            raise AppError(413, "AUDIO_TOO_LARGE", "录音不能超过 2 MB。")
        raw.extend(chunk)
    audio, _, _ = await run_in_threadpool(normalize_wav, bytes(raw))
    return await run_in_threadpool(
        review.save_voice, db, request.app.state.settings.data_dir, teacher.id, attempt_id, audio,
    )


@router.get("/attempts/{attempt_id}/feedback-audio", response_class=Response)
def feedback_audio(attempt_id: int, db: Database, teacher: CurrentTeacher):
    _, _, record = review.owned_attempt(db, teacher.id, attempt_id)
    details = review.review_details(record)
    if not details or not details["audio_url"] or not record.voice_audio:
        raise not_found()
    return Response(record.voice_audio, media_type="audio/wav", headers=NO_CACHE)
