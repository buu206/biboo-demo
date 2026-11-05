from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=140)]
Note = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
Word = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)]
Status = Literal["draft", "generated", "published"]
Kind = Literal["word", "sentence", "dialogue"]


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ReadModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Login(Input):
    invite_code: Text


class TeacherView(ReadModel):
    id: int
    name: str


class ClassInput(Input):
    name: Text


class ClassView(TeacherView):
    created_at: datetime


class LessonInput(Input):
    class_id: int = Field(gt=0)
    topic: Text
    age_band: Text
    duration_minutes: int = Field(ge=5, le=180)
    vocabulary: list[Word] = Field(min_length=1, max_length=12)
    patterns: list[Text] = Field(default_factory=list, max_length=5)
    sound_focus: list[Word] = Field(default_factory=list, max_length=5)


class OutlineSection(Input):
    title: Text
    minutes: int = Field(ge=1, le=180)
    activity: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class Line(Input):
    text: Text
    translation: Note


class DialogueLine(Line):
    speaker: Literal["A", "B"]


class GeneratedContent(Input):
    outline: list[OutlineSection] = Field(min_length=1, max_length=15)
    sentences: list[Line] = Field(min_length=1, max_length=12)
    dialogue: list[DialogueLine] = Field(min_length=1, max_length=12)


class EditItem(Line):
    id: int = Field(gt=0)


class EditContent(Input):
    revision: int = Field(ge=0)
    outline: list[OutlineSection] = Field(min_length=1, max_length=15)
    items: list[EditItem] = Field(min_length=1, max_length=36)


class Publish(Input):
    confirm: Literal[True]
    revision: int = Field(ge=0)


class Outline(BaseModel):
    schema_version: Literal[1]
    sections: list[OutlineSection]


class ItemView(ReadModel):
    id: int
    kind: Kind
    position: int
    speaker: Literal["A", "B"] | None
    text: str
    translation: str
    audio_asset_id: int | None


class LessonSummary(ReadModel):
    id: int
    class_id: int
    topic: str
    status: Status
    updated_at: datetime


class LessonView(LessonSummary):
    age_band: str
    duration_minutes: int
    vocabulary: list[str]
    patterns: list[str]
    sound_focus: list[str]
    outline: Outline | None
    quality_notes: list[str]
    revision: int
    items: list[ItemView]


class Health(BaseModel):
    status: Literal["ok"] = "ok"
    mode: Literal["mock", "unconfigured", "real"]
