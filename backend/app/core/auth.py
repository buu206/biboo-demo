from datetime import timedelta
from hashlib import sha256
from secrets import token_urlsafe
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.db import now
from app.core.errors import AppError
from app.models import LoginSession, Teacher

COOKIE = "biboo_session"
MAX_AGE = 7 * 24 * 60 * 60


def digest(value: str):
    return sha256(value.encode()).hexdigest()


def create_teacher(db, name):
    code = token_urlsafe(24)
    teacher = Teacher(name=name, invite_code_hash=digest(code))
    db.add(teacher)
    db.commit()
    return teacher, code


def begin_session(db, invite_code):
    teacher = db.scalar(select(Teacher).where(Teacher.invite_code_hash == digest(invite_code)))
    if teacher is None:
        raise AppError(401, "INVALID_INVITE_CODE", "邀请码无效。")
    token = token_urlsafe(32)
    timestamp = now()
    db.execute(delete(LoginSession).where(LoginSession.expires_at <= timestamp))
    db.add(LoginSession(token_hash=digest(token), teacher_id=teacher.id,
                        expires_at=timestamp + timedelta(seconds=MAX_AGE)))
    db.commit()
    return teacher, token


def get_db(request: Request):
    with Session(request.app.state.engine) as db:
        yield db


Database = Annotated[Session, Depends(get_db)]


def current_teacher(request: Request, db: Database):
    token = request.cookies.get(COOKIE, "")
    teacher = db.scalar(
        select(Teacher).join(LoginSession, LoginSession.teacher_id == Teacher.id)
        .where(LoginSession.token_hash == digest(token), LoginSession.expires_at > now())
    )
    if teacher is None:
        raise AppError(401, "UNAUTHORIZED", "请先用老师邀请码登录。")
    return teacher


CurrentTeacher = Annotated[Teacher, Depends(current_teacher)]
