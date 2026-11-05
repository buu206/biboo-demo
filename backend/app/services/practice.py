import fcntl
import os
import time
from contextlib import contextmanager
from dataclasses import asdict
from hashlib import sha256
from tempfile import NamedTemporaryFile

from sqlalchemy import and_, select

from app.core.errors import AppError, invalid_state, not_found
from app.models import HomeworkItem, Lesson, PracticeAttempt, PracticeReview
from app.schemas.practice import AttemptView, Drill
from app.services import oral_provider
from app.services.ai import Call, WORDS
from app.services.lessons import record_call
from app.services.oral_provider import OralPhone, OralResult, OralWord
from app.services.practice_feedback import coach
from app.services.recordings import normalize_wav
from app.services.review import review_details

GOOD_FEEDBACK = "这次读得很清楚，继续保持！"
REVIEW_FEEDBACK = "谢谢你完成跟读，老师会再听一听。"


def evaluate(settings, pcm_wav, reference):
    if not settings.fake_models:
        return oral_provider.evaluate(settings, pcm_wav, reference)
    _, rms, _ = normalize_wav(pcm_wav)
    words = WORDS.findall(reference)
    if rms >= 5_000:
        rows = [
            OralWord(word, True, (OralPhone("θ", 45), OralPhone("k", 88)) if index == 0
                     else (OralPhone("k", 88),))
            for index, word in enumerate(words)
        ]
        return OralResult(72, 1.0, tuple(rows))
    return OralResult(92, 1.0, tuple(OralWord(word, True, (OralPhone("k", 92),)) for word in words))


def assess(result, reference):
    expected = [word.casefold() for word in WORDS.findall(reference)]
    if (
        result.accuracy is None
        or not expected
        or (len(expected) > 1 and (result.completion is None or result.completion < 0.90))
        or [token.casefold() for word in result.words for token in WORDS.findall(word.text)] != expected
        or len(result.words) != len(expected)
        or not all(word.matched and word.phones for word in result.words)
    ):
        return "teacher_review", None, "uncertain_alignment"

    phones = [
        (reference_word, phone)
        for reference_word, word in zip(WORDS.findall(reference), result.words)
        for phone in word.phones
    ]
    if result.accuracy >= 85 and all(phone.accuracy >= 65 for _, phone in phones):
        return "good", None, "clear_reading"

    low = [(word, phone.symbol) for word, phone in phones if phone.accuracy < 65]
    severe = [phone for _, phone in phones if phone.accuracy <= 55 and phone.symbol]
    if result.accuracy >= 55 and len(low) == 1 and len(severe) == 1 and len(phones) >= 2:
        return "practice", low[0], "localized_phone"
    return "teacher_review", None, "uncertain_pronunciation"


def published_item(db, owner_id, item_id):
    item = db.scalar(
        select(HomeworkItem).join(Lesson, Lesson.id == HomeworkItem.lesson_id).where(
            HomeworkItem.id == item_id, HomeworkItem.owner_id == owner_id,
            Lesson.owner_id == owner_id, Lesson.status == "published",
        )
    )
    if item is None:
        raise not_found()
    return item


def attempts_query(owner_id, item_id, learner_id):
    return select(PracticeAttempt).where(
        PracticeAttempt.owner_id == owner_id,
        PracticeAttempt.item_id == item_id,
        PracticeAttempt.learner_id == learner_id,
    )


def view(attempt, teacher_review=None):
    return AttemptView(
        id=attempt.id, decision=attempt.decision, feedback=attempt.feedback,
        reference=attempt.reference, round=attempt.round,
        drill=Drill(text=attempt.drill_text) if attempt.drill_text else None,
        teacher_feedback=review_details(teacher_review),
    )


def list_attempts(db, owner_id, item_id, learner_id):
    published_item(db, owner_id, item_id)
    query = (
        attempts_query(owner_id, item_id, learner_id).add_columns(PracticeReview)
        .outerjoin(PracticeReview, and_(
            PracticeReview.attempt_id == PracticeAttempt.id,
            PracticeReview.owner_id == owner_id,
        ))
        .order_by(PracticeAttempt.id)
    )
    return [view(attempt, review) for attempt, review in db.execute(query)]


@contextmanager
def practice_lock(settings, item_id, learner_id):
    directory = settings.data_dir / "locks"
    directory.mkdir(exist_ok=True)
    with (directory / f"practice-{item_id}-{learner_id}.lock").open("ab") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise invalid_state("正在评测这条跟读，请稍后重试。") from None
        yield


def save_attempt(db, settings, attempt, audio):
    path = settings.data_dir / attempt.audio_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, prefix=".recording-", delete=False) as file:
        try:
            file.write(audio)
            file.flush()
            os.fsync(file.fileno())
            os.replace(file.name, path)
        finally:
            if os.path.exists(file.name):
                os.unlink(file.name)
    try:
        db.add(attempt)
        db.flush()
        response = view(attempt)
        db.commit()
        return response
    except Exception:
        db.rollback()
        path.unlink(missing_ok=True)
        raise


def evaluate_with_audit(settings, audio, reference, record):
    if settings.fake_models:
        return evaluate(settings, audio, reference)
    call = Call("Tencent SOE-N")
    started = time.monotonic()
    try:
        result = evaluate(settings, audio, reference)
        call.request_id = result.request_id
        call.structure = "首测合规"
        call.result = "通过"
        return result
    except AppError as error:
        call.error = error.detail.error.code
        raise
    finally:
        call.seconds = round(time.monotonic() - started, 3)
        if call.error != "ORAL_NOT_CONFIGURED":
            record("oral_assessment", call)


def submit(db, settings, owner_id, item_id, learner_id, request_key, drill, upload, observer):
    item = published_item(db, owner_id, item_id)
    checksum = sha256(upload).hexdigest()
    with practice_lock(settings, item_id, learner_id):
        query = attempts_query(owner_id, item_id, learner_id)
        existing = db.scalar(query.where(PracticeAttempt.request_key == request_key))
        if existing is not None:
            if existing.audio_digest != checksum or (existing.round > 0) != drill:
                raise invalid_state("这次提交已对应另一份录音，请重新录制后提交。")
            return view(existing)

        history = list(db.scalars(query.order_by(PracticeAttempt.id)))
        latest = history[-1] if history else None
        if latest and latest.decision != "practice":
            raise invalid_state("这项跟读已结束。")
        if drill:
            if latest is None or not latest.drill_text or latest.round >= 2:
                raise invalid_state("当前没有可提交的加练。")
            reference, round_number = latest.drill_text, latest.round + 1
        else:
            if latest and latest.round > 0:
                raise invalid_state("这项跟读已进入加练，请按加练内容提交。")
            reference, round_number = item.text, 0

        if not 1 <= len(WORDS.findall(reference)) <= 30:
            raise AppError(422, "INVALID_REFERENCE", "跟读文本需要包含 1–30 个英文单词。")
        audio, rms, clipped = normalize_wav(upload)
        record = record_call(db.get_bind(), owner_id, observer)
        result = None
        if rms < 120 or clipped:
            decision, focus, reason = "teacher_review", None, "audio_unclear"
        else:
            result = evaluate_with_audit(settings, audio, reference, record)
            decision, focus, reason = assess(result, reference)

        if decision == "practice" and (round_number == 2 or (round_number == 0 and len(history) >= 2)):
            decision, focus, reason = "teacher_review", None, "practice_limit"

        drill_text = None
        if decision == "practice" and focus is not None:
            feedback, drill_text = coach(settings, *focus, record)
        else:
            feedback = GOOD_FEEDBACK if decision == "good" else REVIEW_FEEDBACK

        return save_attempt(db, settings, PracticeAttempt(
            owner_id=owner_id, item_id=item_id, learner_id=learner_id,
            request_key=request_key, audio_digest=checksum,
            audio_path=f"recordings/{owner_id}/{item_id}/{learner_id}/{request_key}.wav",
            reference=reference, round=round_number, decision=decision, feedback=feedback, drill_text=drill_text,
            assessment={"policy": 1, "reason": reason, "provider": asdict(result) if result else None},
        ), audio)
