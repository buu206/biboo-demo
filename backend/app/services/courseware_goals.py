"""Suggest editable teaching goals from source text without a network call."""

import re

from pydantic import BaseModel

from app.services.ai import WORDS


class MaterialGoals(BaseModel):
    topic: str
    vocabulary: list[str]
    patterns: list[str]
    sound_focus: list[str]


HEADINGS = {
    "vocabulary": r"本课词汇|重点词汇|词汇|单词|vocabulary|key words?|words?",
    "patterns": r"重点句型|句型|例句|sentences?|sentence patterns?|examples?",
    "sound_focus": r"发音重点|发音|音标|自然拼读|sound focus|phonics|pronunciation",
}
FIELD_HEADINGS = {
    name: re.compile(rf"^(?:{heading})(?:\s*[:：]\s*(.*))?$", re.I)
    for name, heading in HEADINGS.items()
}
OTHER_HEADING = re.compile(r"^(?:课堂活动|学习目标|教学目标|课堂练习|课堂回顾|homework|activity)(?:\s*[:：].*)?$", re.I)
LIST_MARKER = re.compile(r"^\s*(?:#{1,6}\s*|[-*•]\s*|\d+[.、)]\s*)")
ENGLISH_SENTENCE = re.compile(r"[A-Za-z][A-Za-z0-9 ,\-'’_]*(?:[.?!]|$)")
FUNCTION_WORDS = set(
    "a an and are as at be can for from has have he her his i in is it my of on or she that the "
    "their them there they this to was we were what when where which who will with you your".split()
)


def _unique(values, count, length):
    result = {}
    for value in values:
        if 0 < len(value) <= length:
            result.setdefault(value.casefold(), value)
    return list(result.values())[:count]


def suggest_goals(title: str, source: str) -> MaterialGoals:
    lines = [LIST_MARKER.sub("", line.strip()) for line in source.splitlines() if line.strip()]
    fields = {name: [] for name in FIELD_HEADINGS}
    prose = []
    current_field = None
    for line in lines:
        for name, heading in FIELD_HEADINGS.items():
            match = heading.fullmatch(line)
            if match:
                inline = match.group(1)
                current_field = name if not inline else None
                if inline:
                    fields[name].append(inline)
                break
        else:
            if OTHER_HEADING.fullmatch(line):
                current_field = None
            elif current_field:
                fields[current_field].append(line)
            else:
                prose.append(line)

    explicit_vocabulary = [word for value in fields["vocabulary"] for word in WORDS.findall(value)]
    candidates = [
        word.casefold() for word in WORDS.findall(" ".join(prose))
        if len(word) >= 3 and word[0].isalpha() and word.casefold() not in FUNCTION_WORDS
    ]
    explicit_patterns = [
        value.strip() for line in fields["patterns"] for value in re.split(r"[；;]", line)
        if WORDS.search(value)
    ]
    sentences = [
        match.group().strip() for line in prose for match in ENGLISH_SENTENCE.finditer(line)
        if len(WORDS.findall(match.group())) >= 3 and match.group().endswith((".", "?", "!"))
    ]
    sound = [value.strip() for line in fields["sound_focus"] for value in re.split(r"[,，、;；]", line)]
    return MaterialGoals(
        topic=title,
        vocabulary=_unique(explicit_vocabulary or candidates, 12 if explicit_vocabulary else 6, 60),
        patterns=_unique(explicit_patterns or sentences, 5, 140),
        sound_focus=_unique(sound, 5, 60),
    )
