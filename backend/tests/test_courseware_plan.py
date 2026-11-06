from app.services.courseware_plan import plan_courseware


def test_body_parts_source_remains_body_parts_lesson_with_matching_visuals():
    source = """Sea explorers
www.publisher.example/teacher-resource
TeachingEnglish lessons
April 2020
Listen to your teacher.
The jell-octo-crab!
It's big / blue.
It's got ...
It can ...
tentacles
claws
a shell
arms
a tail
fish
Homework:
Draw a picture and write about it.
"""
    plan = plan_courseware("我们的海洋发现", source)
    assert plan.theme == "ocean"
    assert [item.word for item in plan.vocabulary] == ["arms", "claws", "tentacles", "shell"]
    assert [item.asset for item in plan.vocabulary] == ["octopus", "crab", "jellyfish", "turtle"]
    assert plan.patterns[0] == "It's got ___"
    assert not {"octopus", "crab", "jellyfish", "turtle"} & {item.word for item in plan.vocabulary}
    assert plan.source_notes == source


def test_explicit_focus_words_win_over_instructions_and_incidental_examples():
    source = """Vocabulary: mother, father, sister
Sentence patterns: This is my mother.
课堂活动
Teacher: show a picture of a family at the seaside with a crab.
"""
    plan = plan_courseware("My family", source)
    assert [item.word for item in plan.vocabulary] == ["mother", "father", "sister"]
    assert plan.theme == "general"
    assert plan.patterns == ("This is my mother",)
    assert plan.mystery is not None
    assert set(plan.mystery.options).issubset({"mother", "father", "sister"})
    assert "海洋" not in " ".join(item.instruction for item in plan.activities)


def test_unfamiliar_words_have_no_invented_translation_or_ambiguous_letter_quiz():
    source = "Vocabulary: glimmer, glisten, glow\nSentence patterns: I can say glimmer."
    plan = plan_courseware("Light words", source)
    assert all(item.label_zh == "" and item.asset == "owl" for item in plan.vocabulary)
    assert plan.mystery is not None
    assert "G · L · I · M · M · E · R" in plan.mystery.question
    assert plan.mystery.answer == plan.mystery.options[plan.mystery.correct]
    assert plan.mystery.answer == "glimmer"


def test_single_word_is_not_given_a_fake_multiple_choice_question():
    plan = plan_courseware("One word", "Vocabulary: apple")
    assert [item.word for item in plan.vocabulary] == ["apple"]
    assert plan.mystery is None
    assert any(item.kind == "exit" for item in plan.activities)


def test_source_without_target_english_does_not_invent_vocabulary():
    plan = plan_courseware("认识四季", "学习目标\n观察春天的变化。\n用中文分享一个发现。")
    assert plan.vocabulary == ()
    assert plan.patterns == ()
    assert plan.mystery is None
    assert "未找到可靠的英文目标词" in plan.teacher_notes


def test_metadata_and_teacher_instructions_are_not_fallback_vocabulary():
    source = """TeachingEnglish lessons
www.example.com/material
© Example Publisher 2026
April 2020
Listen to your teacher.
Teacher instructions: display the presentation to your class.
"""
    plan = plan_courseware("A lesson", source)
    assert plan.vocabulary == ()
    assert plan.source_notes == source


def test_short_source_retrieval_and_turn_taking_are_explicit_teacher_actions():
    source = "Vocabulary\n- apple\n- banana\n- pear\n- orange\n- grape\n句型：I like apples."
    plan = plan_courseware("Fruit", source, age_band="6–10 岁")
    assert [item.word for item in plan.vocabulary] == ["apple", "banana", "pear", "orange"]
    assert [item.kind for item in plan.activities] == ["warmup", "vocabulary", "mystery", "movement", "sentence", "create", "exit"]
    assert "然后交换" in next(item.teacher_note for item in plan.activities if item.kind == "movement")
    assert "隐藏词卡" in next(item.teacher_note for item in plan.activities if item.kind == "exit")
    assert "6–7 岁" in plan.teacher_notes and "8–10 岁" in plan.teacher_notes


def test_extreme_explicit_tokens_are_skipped_without_truncating_or_inventing_words():
    long_word = "z" * 1000
    source = f"Vocabulary: {long_word}, apple, banana"
    plan = plan_courseware("Fruit", source)
    assert [item.word for item in plan.vocabulary] == ["apple", "banana"]
    assert long_word in plan.source_notes
    assert plan.mystery is not None
    assert all(len(option) <= 24 for option in plan.mystery.options)


def test_only_extreme_fallback_tokens_produce_no_target_words():
    source = "z" * 1000 + "\n" + "q" * 25
    plan = plan_courseware("Unknown source", source)
    assert plan.vocabulary == ()
    assert plan.mystery is None
    assert plan.source_notes == source
