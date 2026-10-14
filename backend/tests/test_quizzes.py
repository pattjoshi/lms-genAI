"""Quiz generation checks and grading (Phase 3c). Pure functions: no LLM, no database."""

from app.models import QuizQuestion
from app.quiz.generate import (
    DraftQuestion,
    Passage,
    QuizDraft,
    check_questions,
    grade,
    main_topic,
    pick_passages,
    shuffle_options,
)

TEXT = (
    "The chain rule gives the derivative of a composed function. "
    "Backpropagation applies the chain rule layer by layer, from the output back to the input."
)


def passage(i: int, text: str = TEXT, topic: str | None = "Backpropagation") -> Passage:
    return Passage(i, 1, "dl.pdf", i, 3, "Backprop", topic, text)


def q(**over) -> DraftQuestion:
    base = {
        "question": "In which direction does backpropagation apply the chain rule?",
        "options": ["From the output back to the input", "From the input to the output", "Randomly", "Only once"],
        "correct_option": 0,
        "explanation": "The passage says it goes from the output back to the input.",
        "passage": 1,
        "quote": "applies the chain rule layer by layer, from the output back to the input",
        "difficulty": "easy",
    }
    return DraftQuestion(**(base | over))


def check(*questions, limit=10):
    return check_questions(QuizDraft(questions=list(questions)), [passage(0)], limit)


def test_good_question_is_kept_and_answer_follows_the_shuffle():
    kept, dropped = check(q())
    assert dropped == []
    k = kept[0]
    assert k.options[k.correct_index] == "From the output back to the input"
    assert sorted(k.options) == sorted(q().options)


def test_question_whose_quote_is_not_in_the_passage_is_dropped():
    kept, dropped = check(q(quote="Gradient descent minimises the loss with a learning rate"))
    assert kept == [] and "quote not in passage" in dropped[0]


def test_bad_options_are_dropped():
    assert "4" in check(q(options=["a", "b", "c"]))[1][0]
    assert "same" in check(q(options=["Yes", "yes.", "No", "Maybe"]))[1][0]
    assert "above" in check(q(options=["A thing", "B thing", "C thing", "All of the above"]))[1][0]
    assert "range" in check(q(correct_option=4))[1][0]
    assert "unknown passage" in check(q(passage=2))[1][0]


def test_letters_are_stripped_and_duplicates_dropped():
    kept, dropped = check(q(options=["A) Forward", "B) Backward", "C) Sideways", "D) Nowhere"]), q())
    assert set(kept[0].options) == {"Forward", "Backward", "Sideways", "Nowhere"}
    assert "duplicate" in dropped[0]


def test_limit():
    kept, dropped = check(q(), q(question="What does the chain rule give?"), limit=1)
    assert len(kept) == 1 and "limit" in dropped[0]


def test_shuffle_is_deterministic_and_spreads_the_answer():
    opts = ["right", "w1", "w2", "w3"]
    assert shuffle_options(opts, 0, "same seed") == shuffle_options(opts, 0, "same seed")
    positions = {shuffle_options(opts, 0, f"question {i}")[1] for i in range(40)}
    assert positions == {0, 1, 2, 3}


def test_pick_passages_spreads_over_the_file_and_skips_tiny_chunks():
    ps = [passage(i) for i in range(20)] + [passage(99, "Heading only")]
    picked = pick_passages(ps, 4)
    assert len(picked) == 4
    assert picked[0].chunk_index < 5 and picked[-1].chunk_index >= 15
    assert all(p.chunk_index != 99 for p in picked)
    assert pick_passages([passage(1, "short")], 4)[0].text == "short"  # nothing longer: keep it


def test_main_topic_needs_a_majority():
    kept, _ = check_questions(
        QuizDraft(questions=[q(), q(question="Another one?", passage=2), q(question="Third?", passage=3)]),
        [passage(0), passage(1, topic="Chain Rule"), passage(2, topic="Chain Rule")],
        10,
    )
    assert main_topic(kept) == "Chain Rule"
    assert main_topic(kept[:2]) is None  # 1 vs 1


def test_grade():
    qs = [QuizQuestion(id=1, correct_index=2), QuizQuestion(id=2, correct_index=0), QuizQuestion(id=3, correct_index=1)]
    score, results = grade(qs, {1: 2, 2: 3})  # right, wrong, skipped
    assert score == 33
    assert [r["correct"] for r in results] == [True, False, False]
    assert results[2]["chosen"] is None
