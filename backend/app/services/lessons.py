import fcntl
import os
import shutil
import time
from contextlib import contextmanager

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.errors import AppError, invalid_state, not_found
from app.models import Asset, AuditLog, HomeworkItem, Lesson
from app.schemas import LessonInput, LessonView
from app.services import ai


def get_lesson(db, owner_id, lesson_id):
    lesson = db.scalar(
        select(Lesson).where(Lesson.owner_id == owner_id, Lesson.id == lesson_id)
        .options(selectinload(Lesson.items))
    )
    if lesson is None:
        raise not_found()
    return lesson


@contextmanager
def lesson_lock(db, settings, owner_id, lesson_id):
    if db.scalar(select(Lesson.id).where(Lesson.id == lesson_id, Lesson.owner_id == owner_id)) is None:
        raise not_found()
    directory = settings.data_dir / "locks"
    directory.mkdir(exist_ok=True)
    with (directory / f"lesson-{lesson_id}.lock").open("ab") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise invalid_state("这份作业正在处理，请稍后再试。") from None
        yield


def record_call(engine, owner_id, observer):
    def record(event, call):
        with Session(engine) as db, db.begin():
            db.add(AuditLog(owner_id=owner_id, event=event, detail=call.detail()))
        if observer is not None:
            observer(event, call)
    return record


def set_quality(lesson, outline):
    lesson.outline = {"schema_version": 1, "sections": [section.model_dump() for section in outline]}
    lesson.quality_notes = ai.quality_notes(
        lesson, outline,
        [item.text for item in lesson.items if item.kind == "sentence"],
        [item for item in lesson.items if item.kind == "dialogue"],
    )
    lesson.revision += 1


def generate(db, settings, owner_id, lesson_id, observer):
    with lesson_lock(db, settings, owner_id, lesson_id):
        lesson = get_lesson(db, owner_id, lesson_id)
        if lesson.status == "published":
            raise invalid_state("已发布的作业不能重新生成。")
        target = LessonInput.model_validate(lesson, from_attributes=True)
        record = record_call(db.get_bind(), owner_id, observer)
        output = ai.generate(settings, target, record)
        rows = [("word", None, word, "") for word in target.vocabulary]
        rows += [("sentence", None, line.text, line.translation) for line in output.sentences]
        rows += [("dialogue", line.speaker, line.text, line.translation) for line in output.dialogue]
        lesson.items.clear()
        db.flush()
        lesson.items = [
            HomeworkItem(owner_id=owner_id, kind=kind, position=position, speaker=speaker,
                         text=text, translation=translation)
            for position, (kind, speaker, text, translation) in enumerate(rows)
        ]
        set_quality(lesson, output.outline)
        lesson.status = "generated"
        db.flush()
        result = LessonView.model_validate(lesson)
        db.commit()
        return result


def check_editable(lesson, revision):
    if lesson.status != "generated":
        raise invalid_state("只有已生成、待发布的作业可以执行此操作。")
    if lesson.revision != revision:
        raise invalid_state("作业内容已更新，请重新打开后再操作。")


def edit(db, settings, owner_id, lesson_id, content):
    with lesson_lock(db, settings, owner_id, lesson_id):
        lesson = get_lesson(db, owner_id, lesson_id)
        check_editable(lesson, content.revision)
        updates = {item.id: item for item in content.items}
        if len(updates) != len(content.items) or updates.keys() != {item.id for item in lesson.items}:
            raise AppError(422, "VALIDATION_ERROR", "编辑时需提交这份作业的所有练习项。")
        for item in lesson.items:
            item.text = updates[item.id].text
            item.translation = updates[item.id].translation
        set_quality(lesson, content.outline)
        db.flush()
        result = LessonView.model_validate(lesson)
        db.commit()
        return result


def publish(db, settings, owner_id, lesson_id, revision, observer):
    with lesson_lock(db, settings, owner_id, lesson_id):
        lesson = get_lesson(db, owner_id, lesson_id)
        if lesson.status == "published" and lesson.revision == revision + 1:
            return LessonView.model_validate(lesson)
        check_editable(lesson, revision)
        record = record_call(db.get_bind(), owner_id, observer)
        relative = f"audio/{owner_id}/{lesson_id}"
        directory = settings.data_dir / relative
        # An unpublished lesson can have files left by an interrupted commit.
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True)
        try:
            deadline = time.monotonic() + settings.publish_timeout_seconds
            by_text = {}
            for item in lesson.items:
                if item.text not in by_text:
                    audio, mime = ai.synthesize(settings, item.text, deadline, record)
                    extension = "wav" if mime == "audio/wav" else "mp3"
                    name = f"{item.position}.{extension}"
                    with (directory / name).open("xb") as file:
                        file.write(audio)
                        file.flush()
                        os.fsync(file.fileno())
                    by_text[item.text] = Asset(
                        owner_id=owner_id, path=f"{relative}/{name}", mime=mime, size=len(audio),
                    )
                item.audio = by_text[item.text]
            folder = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(folder)
            finally:
                os.close(folder)
            lesson.status = "published"
            lesson.revision += 1
            db.add(AuditLog(owner_id=owner_id, event="publish", detail={"lesson_id": lesson.id}))
            db.flush()
            result = LessonView.model_validate(lesson)
            db.commit()
        except Exception:
            db.rollback()
            shutil.rmtree(directory, ignore_errors=True)
            raise
        return result
