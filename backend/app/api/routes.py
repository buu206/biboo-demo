from fastapi import APIRouter, Request, Response
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.core.auth import COOKIE, MAX_AGE, CurrentTeacher, Database, begin_session, digest
from app.core.errors import ErrorResponse, not_found
from app.models import Asset, Classroom, Lesson, LoginSession
from app.schemas import (
    ClassInput, ClassView, EditContent, Health, LessonInput, LessonSummary,
    LessonView, Login, Publish, TeacherView,
)
from app.services import lessons

router = APIRouter(
    prefix="/api/v1",
    responses={code: {"model": ErrorResponse} for code in (400, 401, 404, 409, 422, 500, 502, 503)},
)


@router.get("/health")
def health(request: Request) -> Health:
    settings = request.app.state.settings
    if settings.fake_models:
        return Health(mode="mock")
    return Health(mode="real" if settings.credentials_ready else "unconfigured")


@router.post("/auth/login")
def login(data: Login, response: Response, db: Database, request: Request) -> TeacherView:
    teacher, token = begin_session(db, data.invite_code)
    response.set_cookie(COOKIE, token, max_age=MAX_AGE, httponly=True,
                        secure=request.app.state.settings.secure_cookie, samesite="strict")
    return teacher


@router.get("/auth/me")
def me(teacher: CurrentTeacher) -> TeacherView:
    return teacher


@router.post("/auth/logout", status_code=204)
def logout(request: Request, response: Response, db: Database, teacher: CurrentTeacher):
    session = db.get(LoginSession, digest(request.cookies[COOKIE]))
    db.delete(session)
    db.commit()
    response.delete_cookie(COOKIE, httponly=True, samesite="strict",
                           secure=request.app.state.settings.secure_cookie)


@router.post("/classes", status_code=201)
def create_class(data: ClassInput, db: Database, teacher: CurrentTeacher) -> ClassView:
    row = Classroom(owner_id=teacher.id, name=data.name)
    db.add(row)
    db.commit()
    return row


@router.get("/classes")
def list_classes(db: Database, teacher: CurrentTeacher) -> list[ClassView]:
    return list(db.scalars(select(Classroom).where(Classroom.owner_id == teacher.id).order_by(Classroom.id)))


def own_class(db, owner_id, class_id):
    row = db.scalar(select(Classroom).where(Classroom.id == class_id, Classroom.owner_id == owner_id))
    if row is None:
        raise not_found()
    return row


@router.post("/lessons", status_code=201)
def create_lesson(data: LessonInput, db: Database, teacher: CurrentTeacher) -> LessonView:
    own_class(db, teacher.id, data.class_id)
    row = Lesson(owner_id=teacher.id, **data.model_dump())
    db.add(row)
    db.commit()
    return row


@router.get("/lessons")
def list_lessons(db: Database, teacher: CurrentTeacher, class_id: int | None = None) -> list[LessonSummary]:
    query = select(Lesson).where(Lesson.owner_id == teacher.id)
    if class_id is not None:
        own_class(db, teacher.id, class_id)
        query = query.where(Lesson.class_id == class_id)
    return list(db.scalars(query.order_by(Lesson.updated_at.desc(), Lesson.id.desc())))


@router.get("/lessons/{lesson_id}")
def lesson_detail(lesson_id: int, db: Database, teacher: CurrentTeacher) -> LessonView:
    return lessons.get_lesson(db, teacher.id, lesson_id)


@router.post("/lessons/{lesson_id}/generate")
def generate(lesson_id: int, request: Request, db: Database, teacher: CurrentTeacher) -> LessonView:
    return lessons.generate(db, request.app.state.settings, teacher.id, lesson_id, request.app.state.observer)


@router.put("/lessons/{lesson_id}/content")
def edit(lesson_id: int, data: EditContent, request: Request, db: Database, teacher: CurrentTeacher) -> LessonView:
    return lessons.edit(db, request.app.state.settings, teacher.id, lesson_id, data)


@router.post("/lessons/{lesson_id}/publish")
def publish(lesson_id: int, data: Publish, request: Request, db: Database, teacher: CurrentTeacher) -> LessonView:
    return lessons.publish(db, request.app.state.settings, teacher.id, lesson_id, data.revision, request.app.state.observer)


@router.get(
    "/assets/{asset_id}", response_class=FileResponse,
    responses={200: {"content": {mime: {"schema": {"type": "string", "format": "binary"}}
                                 for mime in ("audio/mpeg", "audio/wav")}}},
)
def read_asset(asset_id: int, request: Request, db: Database, teacher: CurrentTeacher):
    asset = db.scalar(select(Asset).where(Asset.id == asset_id, Asset.owner_id == teacher.id))
    if asset is None:
        raise not_found()
    data_dir = request.app.state.settings.data_dir.resolve()
    root = data_dir / "audio" / str(teacher.id)
    path = (data_dir / asset.path).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise not_found()
    return FileResponse(path, media_type=asset.mime, headers={"Cache-Control": "private, no-store"})
