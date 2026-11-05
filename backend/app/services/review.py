"""Teacher-owned review queues and classroom progress."""

from collections import defaultdict

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.sqlite import insert

from app.core.db import now
from app.core.errors import invalid_state, not_found
from app.models import AuditLog, Classroom, HomeworkItem, Lesson, PracticeAttempt, PracticeReview
from app.services.ai import WORDS

VISIBLE_ATTEMPTS = 100
REASONS = {
    "audio_unclear": "录音不清楚",
    "uncertain_alignment": "朗读内容难以确认",
    "uncertain_pronunciation": "发音需要复核",
    "localized_phone": "个别发音需要巩固",
    "practice_limit": "已达到加练次数上限",
    "clear_reading": "朗读清楚",
}
PRONUNCIATION_REASONS = {"uncertain_pronunciation", "localized_phone", "practice_limit"}
GENERAL_ISSUE = "跟读需要巩固"


def recording_path(data_dir, attempt):
    base = data_dir.resolve()
    root = base / "recordings" / str(attempt.owner_id)
    path = (base / attempt.audio_path).resolve()
    if path.is_relative_to(root) and path.is_file():
        return path
    return None


def _attempt_query(owner_id):
    return (
        select(PracticeAttempt, Lesson, PracticeReview)
        .join(HomeworkItem, HomeworkItem.id == PracticeAttempt.item_id)
        .join(Lesson, Lesson.id == HomeworkItem.lesson_id)
        .outerjoin(
            PracticeReview,
            and_(PracticeReview.attempt_id == PracticeAttempt.id, PracticeReview.owner_id == owner_id),
        )
        .where(
            PracticeAttempt.owner_id == owner_id, HomeworkItem.owner_id == owner_id,
            Lesson.owner_id == owner_id, Lesson.status == "published",
        )
    )


def owned_attempt(db, owner_id, attempt_id):
    result = db.execute(_attempt_query(owner_id).where(PracticeAttempt.id == attempt_id)).one_or_none()
    if result is None:
        raise not_found()
    return result


def _learner_label(learner_id):
    return f"学员 {learner_id[:6]}"


def review_details(review):
    if review is None:
        return None
    has_voice = review.voice_recorded_at is not None
    return {
        "verdict": review.verdict,
        "note": review.note,
        "focus": review.focus,
        "reviewed_at": review.reviewed_at,
        "audio_url": f"/api/v1/review/attempts/{review.attempt_id}/feedback-audio" if has_voice else None,
    }


def attempt_details(data_dir, row):
    attempt, lesson, review = row
    return {
        "id": attempt.id,
        "learner_id": attempt.learner_id,
        "learner_label": _learner_label(attempt.learner_id),
        "lesson_id": lesson.id,
        "lesson_title": lesson.topic,
        "reference": attempt.reference,
        "round": attempt.round,
        "decision": attempt.decision,
        "feedback": attempt.feedback,
        "reason": REASONS.get(attempt.assessment.get("reason"), "需要老师确认"),
        "created_at": attempt.created_at,
        "audio_url": f"/api/v1/review/attempts/{attempt.id}/audio" if recording_path(data_dir, attempt) else None,
        "review": review_details(review),
    }


def save_review(db, data_dir, owner_id, attempt_id, verdict, note, focus):
    attempt, _, _ = owned_attempt(db, owner_id, attempt_id)
    if attempt.decision != "teacher_review":
        raise invalid_state("这条跟读未进入老师复核队列。")
    if verdict == "good":
        focus = ""
    record = insert(PracticeReview).values(
        attempt_id=attempt.id, owner_id=owner_id, verdict=verdict, note=note,
        focus=focus, reviewed_at=now(),
    )
    current = record.excluded
    updated = db.execute(record.on_conflict_do_update(
        index_elements=[PracticeReview.attempt_id],
        set_={"verdict": current.verdict, "note": current.note, "focus": current.focus,
              "reviewed_at": current.reviewed_at},
        where=and_(PracticeReview.owner_id == owner_id, or_(
            PracticeReview.verdict != current.verdict,
            PracticeReview.note != current.note,
            PracticeReview.focus != current.focus,
        )),
    ))
    if updated.rowcount:
        db.add(AuditLog(owner_id=owner_id, event="practice_reviewed", detail={
            "attempt_id": attempt.id, "automatic_decision": attempt.decision, "teacher_verdict": verdict,
        }))
    db.commit()
    return attempt_details(data_dir, owned_attempt(db, owner_id, attempt_id))


def save_voice(db, data_dir, owner_id, attempt_id, wav):
    _, _, review = owned_attempt(db, owner_id, attempt_id)
    if review is None:
        raise invalid_state("请先保存老师的判定，再添加语音点评。")
    review.voice_audio = wav
    review.voice_recorded_at = now()
    db.commit()
    return attempt_details(data_dir, owned_attempt(db, owner_id, attempt_id))


def _suggestion(focus, words):
    if not focus or not words:
        return None
    sound_focus = [] if focus in REASONS.values() or focus == GENERAL_ISSUE else [focus]
    return {
        "topic": f"复习 {focus}" if sound_focus else "跟读复习",
        "vocabulary": list(words)[:12],
        "patterns": [],
        "sound_focus": sound_focus,
        "reason": "根据已有跟读记录，回顾需要巩固的练习。",
    }


def _issue_focus(attempt, review):
    if review is not None and review.focus:
        return review.focus
    reason = attempt.assessment.get("reason")
    if reason in {"localized_phone", "practice_limit"}:
        provider = attempt.assessment.get("provider") or {}
        weak = {
            phone["symbol"] for word in provider.get("words", []) for phone in word.get("phones", [])
            if phone.get("accuracy", 100) <= 55 and phone.get("symbol")
        }
        if len(weak) == 1:
            return next(iter(weak))
    return REASONS.get(reason, GENERAL_ISSUE)


def dashboard(db, data_dir, owner_id, class_id, lesson_id=None):
    classroom = db.scalar(select(Classroom).where(Classroom.id == class_id, Classroom.owner_id == owner_id))
    if classroom is None:
        raise not_found()

    lesson_query = select(Lesson).where(
        Lesson.owner_id == owner_id, Lesson.class_id == class_id, Lesson.status == "published",
    )
    if lesson_id is not None:
        lesson_query = lesson_query.where(Lesson.id == lesson_id)
    lessons = list(db.scalars(lesson_query))
    if lesson_id is not None and not lessons:
        raise not_found()
    item_ids = set(db.scalars(select(HomeworkItem.id).where(
        HomeworkItem.owner_id == owner_id, HomeworkItem.lesson_id.in_([lesson.id for lesson in lessons]),
    )))

    query = _attempt_query(owner_id).where(Lesson.class_id == class_id)
    if lesson_id is not None:
        query = query.where(Lesson.id == lesson_id)
    attempts = list(db.execute(query.order_by(PracticeAttempt.id.desc())))
    queue, reviewed = [], []
    latest = {}
    for row in attempts:
        attempt, _, review = row
        latest.setdefault((attempt.learner_id, attempt.item_id), row)
        if attempt.decision == "teacher_review":
            (reviewed if review is not None else queue).append(row)

    completed_by = defaultdict(set)
    pending = set()
    issue_learners = defaultdict(set)
    practice_words = defaultdict(dict)
    for (learner_id, item_id), (attempt, _, review) in latest.items():
        decision = review.verdict if review is not None else attempt.decision
        completed = completed_by[learner_id]
        if decision == "good":
            completed.add(item_id)
            continue
        if decision == "teacher_review":
            pending.add(learner_id)
        reason = attempt.assessment.get("reason")
        focus = _issue_focus(attempt, review)
        issue_learners[focus].add(learner_id)
        if decision == "practice" or reason in PRONUNCIATION_REASONS:
            for word in WORDS.findall(attempt.reference):
                if len(word) <= 60:
                    practice_words[focus].setdefault(word.casefold(), None)

    students = []
    for learner_id, completed in sorted(completed_by.items()):
        status = "completed" if item_ids and item_ids <= completed else "in_progress"
        if learner_id in pending:
            status = "pending_review"
        students.append({
            "learner_id": learner_id, "label": _learner_label(learner_id),
            "completed_items": len(completed), "total_items": len(item_ids), "status": status,
        })

    issues = sorted(issue_learners.items(), key=lambda issue: (-len(issue[1]), issue[0]))
    suggestion = next((_suggestion(label, practice_words[label]) for label, _ in issues if practice_words[label]), None)
    incomplete = sum(student["status"] != "completed" for student in students)
    return {
        "class_id": classroom.id,
        "class_name": classroom.name,
        "lesson_id": lesson_id,
        "lesson_title": lessons[0].topic if lesson_id is not None else None,
        "counts": {
            "learners": len(students), "completed": len(students) - incomplete,
            "pending_review": len(queue), "reviewed": len(reviewed), "attempts": len(attempts),
        },
        "students": students,
        "queue": [attempt_details(data_dir, row) for row in queue[:VISIBLE_ATTEMPTS]],
        "recent_reviews": [attempt_details(data_dir, row) for row in reviewed[:VISIBLE_ATTEMPTS]],
        "common_issues": [{"label": label, "learner_count": len(learners)} for label, learners in issues[:8]],
        "suggestion": suggestion,
        "reminder": (
            "您好，请提醒孩子完成英语跟读练习。可以先听示范，再分段跟读。谢谢配合！"
            if incomplete else None
        ),
    }
