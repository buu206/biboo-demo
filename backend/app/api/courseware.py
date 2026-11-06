from pathlib import PurePosixPath
from typing import Annotated, Literal
from urllib.parse import quote

from fastapi import APIRouter, Query, Request, Response
from starlette.concurrency import run_in_threadpool

from app.core.auth import CurrentTeacher, Database
from app.core.errors import AppError, ErrorResponse, invalid_state
from app.services.courseware_goals import MaterialGoals, suggest_goals
from app.services.courseware_pptx import build_courseware
from app.services.courseware_source import MAX_COURSEWARE_BYTES, extract_courseware
from app.services.lessons import get_lesson

PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
Filename = Annotated[str, Query(min_length=1, max_length=255)]
Title = Annotated[str, Query(max_length=100)]
CoursewareStyle = Literal["standard", "children"]
UPLOAD_BODY = {"requestBody": {"required": True, "content": {
    "application/octet-stream": {"schema": {"type": "string", "format": "binary"}},
}}}
router = APIRouter(
    prefix="/api/v1/courseware",
    responses={code: {"model": ErrorResponse} for code in (401, 413, 415, 422, 503)},
)


async def material(request: Request, filename: str, title: str) -> tuple[str, str]:
    upload = bytearray()
    async for chunk in request.stream():
        if len(upload) + len(chunk) > MAX_COURSEWARE_BYTES:
            raise AppError(413, "MATERIAL_TOO_LARGE", "请上传 10 MB 以内的教学材料。")
        upload.extend(chunk)

    original_name = PurePosixPath(filename.replace("\\", "/")).name
    proposed_title = title.strip() or PurePosixPath(original_name).stem.strip()
    clean_title = "".join(character for character in proposed_title if character.isprintable())[:60]
    clean_title = clean_title.strip() or "课堂课件"
    source = await run_in_threadpool(extract_courseware, original_name, bytes(upload))
    return clean_title, source


def pptx_response(
    clean_title: str, pptx: bytes, slide_count: int, style: CoursewareStyle = "standard",
) -> Response:
    download_stem = "".join(
        "_" if character in '/\\:*?"<>|' else character for character in clean_title
    ).strip(" .") or "课堂课件"
    suffix = "-儿童互动" if style == "children" else ""
    encoded_name = quote(f"{download_stem}{suffix}.pptx", safe="")
    return Response(
        pptx,
        media_type=PPTX_MIME,
        headers={
            "Content-Disposition": f"attachment; filename=\"Biboo-lesson.pptx\"; filename*=UTF-8''{encoded_name}",
            "X-Slide-Count": str(slide_count),
            "X-Courseware-Style": style,
        },
    )


def render_courseware(
    title: str, source: str, style: CoursewareStyle, *, lesson: bool = False,
) -> tuple[bytes, int]:
    if style == "children":
        from app.services.courseware_children_pptx import build_children_courseware

        return build_children_courseware(title, source, lesson=lesson)
    return build_courseware(title, source, lesson=lesson)


@router.post("/goals", openapi_extra=UPLOAD_BODY)
async def import_goals(
    request: Request, teacher: CurrentTeacher, filename: Filename, title: Title = "",
) -> MaterialGoals:
    clean_title, source = await material(request, filename, title)
    return suggest_goals(clean_title, source)


@router.post("/pptx", response_class=Response, openapi_extra=UPLOAD_BODY)
async def make_pptx(
    request: Request, teacher: CurrentTeacher, filename: Filename, title: Title = "",
    style: CoursewareStyle = "standard",
) -> Response:
    clean_title, source = await material(request, filename, title)
    pptx, count = await run_in_threadpool(render_courseware, clean_title, source, style)
    return pptx_response(clean_title, pptx, count, style)


@router.get("/pptx/{lesson_id}", response_class=Response)
def lesson_pptx(
    lesson_id: int, db: Database, teacher: CurrentTeacher, style: CoursewareStyle = "standard",
) -> Response:
    lesson = get_lesson(db, teacher.id, lesson_id)
    if not lesson.outline:
        raise invalid_state("请先生成课堂活动，再下载本课 PPT。")
    lines = ["教学目标", f"- 朗读本课词汇：{'、'.join(lesson.vocabulary)}"]
    if lesson.patterns:
        lines.append(f"- 练习本课句型：{' / '.join(lesson.patterns)}")
    if lesson.sound_focus:
        lines.append(f"- 留意发音：{'、'.join(lesson.sound_focus)}")
    lines.extend(["", f"课堂活动 · {lesson.age_band} · {lesson.duration_minutes} 分钟"])
    for section in lesson.outline["sections"]:
        lines.extend([f"{section['title']} · {section['minutes']} 分钟", section["activity"]])
    lines.append("本课跟读")
    lines.extend(item.text for item in lesson.items)
    if style == "children":
        lines = [
            "Vocabulary", *lesson.vocabulary,
            "Sentence patterns", *lesson.patterns,
            "课堂活动", *lines,
        ]
    pptx, count = render_courseware(lesson.topic, "\n".join(lines), style, lesson=True)
    return pptx_response(lesson.topic, pptx, count, style)
