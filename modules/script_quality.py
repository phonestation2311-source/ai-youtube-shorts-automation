"""
Script Quality Checker - Hindi kids' animal stories
Validates a story before the video is made:
Hindi (Devanagari), right length, short hook, story shape, clean text, child safe.
"""

import re
from typing import Tuple

from config.settings import STORY_MAX_WORDS, STORY_MIN_WORDS
from modules.ai_engine import (
    ask_ollama,
    clean_story_text,
    count_words,
    detect_animals,
    devanagari_ratio,
    is_child_safe,
    split_sentences,
)
from utils import get_logger

log = get_logger("quality")

# Allowed range (a little wider than the target; voice speed is fine-tuned later)
MIN_WORDS = STORY_MIN_WORDS - 10
MAX_WORDS = STORY_MAX_WORDS + 15
MIN_SENTENCES = 5
IDEAL_HOOK_MAX_WORDS = 12

# Checks that MUST pass, otherwise the story is not used
REQUIRED_CHECKS = ("hindi_script", "child_safe", "word_count")


def check_word_count(script: str) -> Tuple[bool, str]:
    words = count_words(script)
    if words < MIN_WORDS:
        return False, f"Too short ({words} words, need {STORY_MIN_WORDS}-{STORY_MAX_WORDS})"
    if words > MAX_WORDS:
        return False, f"Too long ({words} words, need {STORY_MIN_WORDS}-{STORY_MAX_WORDS})"
    return True, f"Word count OK ({words})"


def check_hindi_script(script: str) -> Tuple[bool, str]:
    ratio = devanagari_ratio(script)
    if ratio < 0.85:
        return False, f"Not enough Hindi/Devanagari text ({ratio:.0%})"
    return True, f"Hindi Devanagari OK ({ratio:.0%})"


def check_hook_strength(script: str) -> Tuple[bool, str]:
    sentences = split_sentences(script)
    first = sentences[0] if sentences else script[:60]
    n = count_words(first)
    if n > IDEAL_HOOK_MAX_WORDS:
        return False, f"Opening sentence too long ({n} words, max {IDEAL_HOOK_MAX_WORDS})"
    return True, f"Opening is short ({n} words)"


def check_story_shape(script: str) -> Tuple[bool, str]:
    n = len(split_sentences(script))
    if n < MIN_SENTENCES:
        return False, f"Too few sentences for a story ({n})"
    if not detect_animals(script):
        return False, "No animal character found in the story"
    return True, f"Story has {n} sentences and animal characters"


def check_clean_text(script: str) -> Tuple[bool, str]:
    if re.search(r"[*#`\[\]{}<>]|^\s*-", script):
        return False, "Contains markdown or formatting symbols"
    if re.search(r"[A-Za-z]{3,}", script):
        return False, "Contains English words"
    return True, "Clean narration text"


def check_child_safe(script: str) -> Tuple[bool, str]:
    if not is_child_safe(script):
        return False, "Contains words that are not suitable for children"
    return True, "Child safe"


def validate_script(script: str) -> dict:
    """Run all checks. Returns score, details and approved flag."""
    checks = {
        "hindi_script": check_hindi_script(script),
        "word_count": check_word_count(script),
        "child_safe": check_child_safe(script),
        "hook_strength": check_hook_strength(script),
        "story_shape": check_story_shape(script),
        "clean_text": check_clean_text(script),
    }
    passed = sum(1 for ok, _ in checks.values() if ok)
    total = len(checks)
    score = round(passed / total * 100)
    required_ok = all(checks[name][0] for name in REQUIRED_CHECKS)

    result = {
        "score": score,
        "passed": passed,
        "total": total,
        "checks": {name: {"pass": ok, "message": msg} for name, (ok, msg) in checks.items()},
        "required_ok": required_ok,
        "approved": required_ok and score >= 65,
    }

    log.info(f"Script quality: {score}% ({passed}/{total} checks passed)")
    for name, (ok, msg) in checks.items():
        log.info(f"  {'OK ' if ok else 'BAD'} {name}: {msg}")
    return result


def ai_quality_score(script: str) -> int:
    """Ask the AI to rate the kids' story 1-10 (optional helper)."""
    prompt = f"""Rate this Hindi children's animal story from 1 to 10 for a YouTube Short for kids.
Consider: engaging opening, cute characters, clear small problem, kind/clever solution, happy ending, simple Hindi, child safety.

STORY: {script}

Return ONLY one number from 1 to 10."""
    response = ask_ollama(prompt, max_tokens=400)
    numbers = re.findall(r"\d+", response or "")
    if numbers:
        return min(max(int(numbers[0]), 1), 10)
    return 5


def improve_script(script: str, issues: list) -> str:
    """Ask the AI to fix the listed issues. Keeps the original if the rewrite is worse."""
    issues_text = "\n".join(f"- {issue}" for issue in issues)
    prompt = f"""Rewrite this Hindi children's animal story and fix these problems:
{issues_text}

STORY:
{script}

Rules:
- Simple, natural Hindi in Devanagari only (no English words).
- {STORY_MIN_WORDS}-{STORY_MAX_WORDS} words.
- First sentence under 12 words and exciting.
- Keep the same animal characters and names; small problem, kind or clever solution, happy ending, short lesson at the end.
- Completely safe and gentle for small children.
- Return ONLY the story as one paragraph. No title, no markdown, no notes."""

    improved = clean_story_text(ask_ollama(prompt, max_tokens=2500))
    if not improved:
        return script
    old_q, new_q = validate_script(script), validate_script(improved)
    if new_q["required_ok"] and new_q["score"] >= old_q["score"]:
        return improved
    log.info("Rewrite was not better, keeping the original story.")
    return script


if __name__ == "__main__":
    test_script = (
        "जंगल में आज एक अजीब आवाज़ आई! छोटा खरगोश चीकू डर गया। "
        "उसने देखा, उसका दोस्त कछुआ मोती एक गड्ढे में फँसा था। "
        "चीकू ने सोचा, मैं अकेले उसे नहीं निकाल सकता। "
        "वह दौड़कर हाथी गोलू को बुला लाया। गोलू ने अपनी लंबी सूँड बढ़ाई। "
        "मोती ने सूँड पकड़ी और धीरे से बाहर आ गया। तीनों दोस्त खुशी से नाचने लगे। "
        "सीख: मुश्किल में दोस्तों की मदद करो।"
    )
    result = validate_script(test_script)
    print(f"\nScore: {result['score']}%  approved={result['approved']}")
