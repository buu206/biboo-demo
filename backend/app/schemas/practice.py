from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class Drill(BaseModel):
    text: str


class TeacherFeedback(BaseModel):
    verdict: Literal["good", "practice"]
    note: str
    focus: str
    reviewed_at: datetime
    audio_url: str | None


class AttemptView(BaseModel):
    id: int
    decision: Literal["good", "practice", "teacher_review"]
    feedback: str
    reference: str
    round: int
    drill: Drill | None
    teacher_feedback: TeacherFeedback | None = None
