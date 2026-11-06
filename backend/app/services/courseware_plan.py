"""Source-grounded, offline lesson plans for Biboo's children's slide theme.

This is a deliberately bounded teaching template, not an AI-content claim.
Unknown vocabulary stays unknown: no inferred translation or invented picture.
The original material is retained for teacher notes, separate from slide copy.
"""

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class Vocabulary:
    word: str
    label_zh: str
    asset: str
    model_sentence: str
    gesture: str
    clue: str


@dataclass(frozen=True)
class Mystery:
    question: str
    options: tuple[str, ...]
    correct: int
    answer: str
    teacher_note: str


@dataclass(frozen=True)
class Activity:
    kind: str
    title: str
    instruction: str
    teacher_note: str
    minutes: int


@dataclass(frozen=True)
class CoursewarePlan:
    title: str
    theme: str
    age_band: str
    vocabulary: tuple[Vocabulary, ...]
    patterns: tuple[str, ...]
    mystery: Mystery | None
    activities: tuple[Activity, ...]
    source_notes: str
    teacher_notes: str


# These small teaching examples describe the bundled pictures. They do not
# assert that the uploaded document contains facts beyond its actual words.
_BODY = {
    "arms": ("手臂", "octopus", "It's got arms.", "双臂慢慢伸开，再轻轻弯曲。"),
    "claws": ("钳子", "crab", "It's got claws.", "拇指和食指轻轻开合，做一对小钳子。"),
    "tentacles": ("触手", "jellyfish", "It's got tentacles.", "张开手指，轻轻摆动，像触手一样。"),
    "shell": ("壳", "turtle", "It's got a shell.", "双手在背后围出一个圆圆的壳。"),
    "tail": ("尾巴", "turtle", "It's got a tail.", "用手在身后比一比尾巴。"),
    "fin": ("鳍", "owl", "It's got a fin.", "用手掌比一比鳍。"),
    "blowhole": ("呼吸孔", "owl", "It's got a blowhole.", "用手在头顶比一个小圆圈。"),
}
_ANIMALS = {
    "octopus": ("章鱼", "octopus", "It's an octopus.", "双臂伸开，手指轻轻摆动。"),
    "crab": ("螃蟹", "crab", "It's a crab.", "手指做小钳子，在座位旁轻轻侧移一步。"),
    "jellyfish": ("水母", "jellyfish", "It's a jellyfish.", "轻轻张开双手，再慢慢合拢。"),
    "turtle": ("龟", "turtle", "It's a turtle.", "慢慢伸出手，做游动的动作。"),
    "dolphin": ("海豚", "owl", "It's a dolphin.", "用一只手在空中画一条弧线。"),
    "whale": ("鲸", "owl", "It's a whale.", "张开双臂，表示大大的身体。"),
    "shark": ("鲨鱼", "owl", "It's a shark.", "一只手掌在头顶比出背鳍。"),
    "seahorse": ("海马", "owl", "It's a seahorse.", "用手指画一个卷卷的尾巴。"),
    "penguin": ("企鹅", "owl", "It's a penguin.", "双臂贴近身体，轻轻摆动。"),
    "fish": ("鱼", "owl", "It's a fish.", "双手合拢，轻轻左右摆动。"),
    "cat": ("猫", "owl", "It's a cat.", "双手在脸旁比出胡须。"),
    "dog": ("狗", "owl", "It's a dog.", "双手在头旁比出耳朵。"),
    "bird": ("鸟", "owl", "It's a bird.", "双臂轻轻摆动。"),
    "rabbit": ("兔子", "owl", "It's a rabbit.", "两根手指在头顶比出长耳朵。"),
}
_COMMON = {
    "apple": "苹果", "banana": "香蕉", "orange": "橙子", "pear": "梨", "grape": "葡萄",
    "bread": "面包", "milk": "牛奶", "water": "水", "rice": "米饭", "egg": "鸡蛋",
    "mother": "妈妈", "father": "爸爸", "sister": "姐妹", "brother": "兄弟", "family": "家人",
    "red": "红色", "blue": "蓝色", "yellow": "黄色", "green": "绿色", "pink": "粉色",
    "book": "书", "pencil": "铅笔", "bag": "包", "chair": "椅子", "table": "桌子",
    "sun": "太阳", "moon": "月亮", "star": "星星", "tree": "树", "flower": "花",
    "happy": "开心的", "sad": "难过的", "big": "大的", "small": "小的",
    "swim": "游泳", "jump": "跳", "run": "跑", "walk": "走", "hide": "躲藏",
}
_VOCAB_HEADING = re.compile(
    r"^(?:本课词汇|重点词汇|词汇|单词|vocabulary|key\s*words?|words?)\s*(?:[:：]\s*(.*))?$", re.I,
)
_PATTERN_HEADING = re.compile(
    r"^(?:重点句型|句型|例句|sentences?|sentence\s*patterns?|patterns?|examples?)\s*(?:[:：]\s*(.*))?$", re.I,
)
_OTHER_HEADING = re.compile(
    r"^(?:学习目标|教学目标|课堂活动|课末回顾|发音重点|发音|课堂练习|homework|activities?|"
    r"learning\s+(?:outcomes|objectives)|phonics|sound\s+focus)(?:\s*[:：].*)?$", re.I,
)
_WORD = re.compile(r"[a-zA-Z]+(?:['’\-][a-zA-Z]+)*")
MAX_FOCUS_WORD_CHARS = 24
_SOURCE_NOISE = re.compile(
    r"https?://|www\.|©|copyright|teachingenglish|british\s+council|all\s+rights\s+reserved", re.I,
)
_DATE = re.compile(r"^(?:(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+)?\d{4}$", re.I)
_INSTRUCTION = re.compile(
    r"^(?:listen to|put your hand|show your group|tell your group|ask (?:the |your )?|"
    r"teacher(?:s)?\b|teaching\b|lesson\s*plan|slide\s*\d|thanks for|draw a picture|"
    r"what(?:'s|’s| is) (?:the same|its name)|what does it (?:look|eat)|what can it do|"
    r"材料讲解|课堂活动|老师补充活动|本课跟读)", re.I,
)
_STOP = set((
    "a an and are as at be been being but by can could did do does eat eats eating for from got has have "
    "he her here hers him his how i if in into is it its like may me mine more most my of on or our ours "
    "out say says she so some than that the their theirs them then there these they this those to too us "
    "was we were what when where which who why will with would you your yours "
    "age aged ages band body children child classroom class classes course creature creatures discover "
    "different english example examples focus group groups idea ideas know learn learning lesson lessons "
    "let let's listen little look material name new next now other page pages part parts picture pictures "
    "please present presentation primary pupil pupils read reading repeat resource resources school see "
    "sentence sentences show speak speaking student students study target task tasks teach teacher teachers "
    "teaching tell theme today topic understand vocabulary warm warmer welcome word words worksheet worksheets "
    "write writing year years homework human humans"
).split())
_OCEAN = re.compile(r"\b(?:sea|ocean|octopus|jellyfish|seahorse|dolphin|whale|shark)\b|海洋|海底", re.I)
_BASIC_PATTERN = re.compile(
    r"^(?:It(?:'s|’s| is| has| hasn't| hasn’t| can| can't| can’t| eats| doesn't| doesn’t)|"
    r"I (?:can|can't|like|have|see|am)|This is|These are|There (?:is|are)|My \w+ is)\b", re.I,
)


def _clean_lines(source: str) -> list[str]:
    result = []
    for line in source.splitlines():
        line = re.sub(r"^\s*(?:#{1,6}\s*|[-*•]\s*|\d+[.、)]\s*)", "", line).strip()
        if not line or _SOURCE_NOISE.search(line) or _DATE.fullmatch(line):
            continue
        result.append(" ".join(line.split()))
    return result


def _fields(lines: list[str]) -> tuple[list[str], list[str]]:
    words, patterns = [], []
    current = None
    for line in lines:
        match = _VOCAB_HEADING.fullmatch(line)
        if match:
            current = "vocabulary"
            if match.group(1):
                words.extend(_WORD.findall(match.group(1)))
                current = None
            continue
        match = _PATTERN_HEADING.fullmatch(line)
        if match:
            current = "patterns"
            if match.group(1):
                patterns.extend(re.split(r"[；;]", match.group(1)))
                current = None
            continue
        if _OTHER_HEADING.fullmatch(line):
            current = None
        elif current == "vocabulary":
            # A vocabulary list contains short entries, not a paragraph of
            # instructions following an unmarked section break.
            if len(_WORD.findall(line)) <= 8 and not _INSTRUCTION.search(line) and not _BASIC_PATTERN.search(line):
                words.extend(_WORD.findall(line))
            else:
                current = None
        elif current == "patterns":
            if len(line) <= 100 and not _INSTRUCTION.search(line):
                patterns.append(line)
            else:
                current = None
    return words, patterns


def _unique(values, limit: int) -> tuple[str, ...]:
    result = {}
    for value in values:
        clean = value.strip().strip(".,;: ").replace("’", "'")
        if clean and clean.casefold() not in result:
            result[clean.casefold()] = clean
        if len(result) == limit:
            break
    return tuple(result.values())


def _contains(source: str, word: str) -> bool:
    # Match whole lexical items: e.g. do not turn "jell-octo-crab" into "crab".
    return re.search(r"(?<![a-zA-Z'\-])" + re.escape(word) + r"(?![a-zA-Z'\-])", source, re.I) is not None


def _vocabulary_words(lines: list[str], explicit: list[str], theme: str) -> tuple[str, ...]:
    if explicit:
        return _unique((
            word.casefold() for word in explicit
            if len(word) <= MAX_FOCUS_WORD_CHARS and word.casefold() not in {"a", "an", "the"}
        ), 4)
    prose = "\n".join(line for line in lines if not _INSTRUCTION.search(line))
    ordered_known = list(_BODY) + list(_ANIMALS) if theme == "ocean" else list(_ANIMALS) + list(_COMMON) + list(_BODY)
    known = [word for word in ordered_known if _contains(prose, word)]
    if known:
        return _unique(known, 4)
    candidates = [
        word.casefold() for line in lines if not _INSTRUCTION.search(line)
        for word in _WORD.findall(line)
        if 2 < len(word) <= MAX_FOCUS_WORD_CHARS
        and word.casefold() not in _STOP and not word.casefold().endswith("'s")
    ]
    return _unique(candidates, 4)


def _word(word: str, theme: str) -> Vocabulary:
    if word in _BODY:
        label, asset, sentence, gesture = _BODY[word]
        if theme != "ocean":
            asset = "owl"
        return Vocabulary(word, label, asset, sentence, gesture, f"{label}，用英语怎么说？")
    if word in _ANIMALS:
        label, asset, sentence, gesture = _ANIMALS[word]
        return Vocabulary(word, label, asset, sentence, gesture, f"{label}，用英语怎么说？")
    label = _COMMON.get(word, "")
    clue = f"{label}，用英语怎么说？" if label else f"哪个单词以 {word[0].upper()} 开头？"
    return Vocabulary(word, label, "owl", f"I can say {word}.", "给这个词设计一个小动作，再让同伴猜。", clue)


def _patterns(lines: list[str], explicit: list[str], vocabulary: tuple[Vocabulary, ...]) -> tuple[str, ...]:
    candidates = explicit or [line for line in lines if _BASIC_PATTERN.search(line)]
    clean = []
    for candidate in candidates:
        candidate = re.sub(r"…|\.{3,}|_{2,}", "___", candidate.replace("’", "'")).strip()
        if 0 < len(candidate) <= 70 and len(_WORD.findall(candidate)) <= 12:
            clean.append(candidate)
    if not explicit and any(item.word in _BODY for item in vocabulary):
        # For the sea-body-parts source, "It's got ___" is more useful than
        # an incidental colour example. Both remain traceable to the source.
        clean.sort(key=lambda line: (not line.casefold().startswith("it's got"), "___" not in line))
    if clean:
        return _unique(clean, 3)
    if vocabulary:
        return (vocabulary[0].model_sentence,)
    return ()


def _mystery(vocabulary: tuple[Vocabulary, ...]) -> Mystery | None:
    if len(vocabulary) < 2:
        return None
    options = tuple(item.word for item in vocabulary[:3])
    # Choose a supported translation or an unambiguous initial-letter prompt.
    for correct in list(range(1, len(options))) + [0]:
        item = vocabulary[correct]
        if item.label_zh or sum(word[0].casefold() == item.word[0].casefold() for word in options) == 1:
            return Mystery(
                question=item.clue, options=options, correct=correct, answer=item.word,
                teacher_note="先读题，留出 5 秒独立思考。孩子用手势或口头选答案后，再点击选项；选错时允许重试。",
            )
    # Same-initial unknown words: point to an explicitly spelled target instead
    # of fabricating a translation or relying on an ambiguous picture.
    target = vocabulary[0].word
    return Mystery(
        question="找一找：" + " · ".join(target.upper()), options=options, correct=0, answer=target,
        teacher_note="教师逐个读出字母，孩子把字母连成一个词后再选择。未知词义请先核对原材料。",
    )


def _activities(theme: str, vocabulary: tuple[Vocabulary, ...]) -> tuple[Activity, ...]:
    target = "海洋生物" if theme == "ocean" else "今天的主题"
    return (
        Activity("warmup", "你发现了什么？", "看一看，指一指，说出你认识的词。", "先让孩子安静看图 10 秒，再请两位孩子各分享一个发现；允许先用中文表达，再给出英文示范。", 2),
        Activity("vocabulary", "一起发现新词", "听一次，跟一次，再做一个小动作。", "每次只呈现一个词。先看图或实物，再听老师示范，最后才读文字。6–7 岁重点跟说，8–10 岁补充一句描述。", max(3, len(vocabulary))),
        Activity("mystery", "猜猜我是谁", "先想一想，再选答案。", "给所有孩子思考时间。先同时用手指选项，再请一位孩子说理由，避免只由反应最快的孩子作答。", 2),
        Activity("movement", "动作猜词", "一人做动作，一人说单词。", "两人一组，A 用本课词做小动作，B 猜词，然后交换。可坐着用手势完成，不要求跑跳。", 3),
        Activity("sentence", "我也会说一句", "先听示范，再换一个词试试看。", "老师完整示范一句。6–7 岁可指图并补一个词；8–10 岁说完整句。同伴轮流开口，不要求齐声回答代替个人表达。", 3),
        Activity("create", "我的新发现", f"画出你的{target}，用今天的词介绍它。" if theme == "ocean" else "选两个本课单词，画一幅小画，再介绍它。", "先独立画 2 分钟，再两人互相介绍。只检查能否使用本课词和句型表达想法，不评价画得像不像。", 5),
        Activity("exit", "离开前的小挑战", "不看提示，说出一个词，再说一句话。", "隐藏词卡，给每个孩子一次提取机会。需要帮助的孩子可以指图或跟说；记录下节课需要复习的词。", 2),
    )


def plan_courseware(title: str, source: str, *, age_band: str = "6–10 岁") -> CoursewarePlan:
    """Make a small editable teaching sequence using only source vocabulary.

    Vocabulary selection is intentionally capped at four focus words. Raw
    material remains in ``source_notes`` so a teacher can check omitted content.
    """
    lines = _clean_lines(source)
    explicit, explicit_patterns = _fields(lines)
    semantic_source = "\n".join(lines)
    theme = "ocean" if _OCEAN.search(semantic_source) else "general"
    words = _vocabulary_words(lines, explicit, theme)
    vocabulary = tuple(_word(word, theme) for word in words)
    patterns = _patterns(lines, explicit_patterns, vocabulary)
    teacher_notes = (
        f"适用年龄：{age_band}。本课按热身、词汇、猜词、动作、句型、创作、回顾安排。"
        "放映时先让孩子回答，再点击选项或揭晓答案。文字和句型可在上课前编辑。"
        "6–7 岁允许指图、单词和手势回答；8–10 岁鼓励完整句和同伴追问。"
        "每个孩子都要有开口机会，不设置速度排名。"
    )
    if not vocabulary:
        teacher_notes += "未找到可靠的英文目标词，请先在原材料中补充 Vocabulary / 词汇一栏再生成。"
    return CoursewarePlan(
        title=" ".join(title.split())[:100] or "今天的新发现", theme=theme, age_band=age_band,
        vocabulary=vocabulary, patterns=patterns, mystery=_mystery(vocabulary),
        activities=_activities(theme, vocabulary), source_notes=source, teacher_notes=teacher_notes,
    )
