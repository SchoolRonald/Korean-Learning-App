import logging
import os
import threading
import time

import httpx

URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.14.0"  # pinned: jev-latest can change answers between releases
THRESHOLD = 0.7
TIMEOUT = 10.0

log = logging.getLogger("gongbu.llm")
usage = {"calls": 0, "input_tokens": 0}
_lock = threading.Lock()

MEANING = ("The learner's Korean answer means the same as the English sentence. "
           "The accepted translations are examples of right answers; other wordings with the same meaning also count.")
CORRECT = ("The learner's Korean answer is grammatical, natural Korean that a native speaker would write, "
           "with every word spelled exactly right: no typos, no missing or extra letters, no wrong particles or endings.")
CRITERIA = {
    "meaning": {"true": "Same meaning as the English sentence, even if worded differently or using a synonym.",
                "false": "A different meaning, a missing or extra idea, or a wrong word choice that changes the meaning."},
    "correct": {"true": "Every word is spelled and conjugated correctly and the sentence is grammatical.",
                "false": "Any typo, misspelling, wrong particle, wrong ending, or ungrammatical sentence, however small."},
}


class JevError(Exception):
    """Jev could not answer; callers fall back to another grader."""


def available():
    return bool(os.environ.get("JEV_API_KEY"))


def ask(state, questions):
    """One Jev call. Returns {question name: probability that it is true}."""
    key = os.environ.get("JEV_API_KEY")
    if not key:
        raise JevError("No JEV_API_KEY set.")
    body = {"model": MODEL, "state": state,
            "questions": {name: {"type": "noul", **q} for name, q in questions.items()}}
    start = time.perf_counter()
    try:
        response = httpx.post(URL, json=body, timeout=TIMEOUT, headers={"Authorization": f"Bearer {key}"})
    except httpx.HTTPError as e:
        raise JevError(f"Could not reach Jev: {e}")
    seconds = time.perf_counter() - start
    if response.status_code != 200:
        raise JevError(f"Jev returned {response.status_code}: {response.text[:200]}")
    data = response.json()
    tokens = data.get("usage", {}).get("input_tokens", 0)
    with _lock:
        usage["calls"] += 1
        usage["input_tokens"] += tokens
        calls = usage["calls"]
    log.info("jev (%s) call %d: %.2fs in=%d", data.get("model", MODEL), calls, seconds, tokens)
    try:
        return {name: float(data["answers"][name]["noul"]) for name in questions}
    except (KeyError, TypeError, ValueError):
        raise JevError("Jev returned an answer that could not be read.")


def judge(task, shown, accepted, answer, point=None, english=None, extra=None):
    """Whether a learner's free answer is right: same meaning and spelled exactly right
    (and, in grammar practice, using the point). Returns (correct, probabilities).
    extra: more yes/no questions asked in the same call, which do not decide the verdict."""
    state = {"task": task, "shown_to_learner": shown, "accepted_answers": accepted, "learner_answer": answer}
    if english:
        state["english_meaning"] = english
    questions = {
        "meaning": {"instructions": MEANING, "criteria": CRITERIA["meaning"]},
        "correct": {"instructions": CORRECT, "criteria": CRITERIA["correct"]},
    }
    if point:
        state["grammar_point"] = point
        questions["uses_point"] = {
            "instructions": ("The learner's Korean answer contains the grammar point being practiced (see grammar_point). "
                             "Particles and endings attach to the end of a word, and the word may differ from the accepted "
                             "answers: 나는 is 나 + 는, 집에서 is 집 + 에서, 읽었어요 is 읽 + 었 + 어요."),
            "criteria": {"true": "The point's form appears in the answer, attached to any word.",
                         "false": "The point's form does not appear; the answer uses a different particle or ending instead."},
        }
    deciding = list(questions)
    probabilities = ask(state, {**questions, **(extra or {})})
    return all(probabilities[name] >= THRESHOLD for name in deciding), probabilities


def usage_summary():
    return {"calls": usage["calls"]}
