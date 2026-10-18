"""
AI Engine - Groq API (hosted, free tier)
Handles all AI generation for Hindi kids' animal-story Shorts:
story idea, story script, hook, SEO metadata and footage keywords.

The function is still called ask_ollama() so older modules keep working,
but it talks to Groq. Your GROQ_API_KEY is read from .env (never printed).
"""

import json
import os
import random
import re
import time
from pathlib import Path

import requests

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
except ImportError:
    pass

from config.settings import (
    ANIMALS,
    CHARACTER_NAMES,
    GROQ_API_URL,
    GROQ_MAX_RETRIES,
    GROQ_MODEL,
    STORY_MAX_WORDS,
    STORY_MIN_WORDS,
)
from utils import get_logger

log = get_logger("ai_engine")

STORY_SYSTEM_PROMPT = (
    "You write original, warm, child-friendly stories for kids aged 3-8 in simple, "
    "natural Hindi using Devanagari script. Everything must be safe, kind, positive, "
    "age-appropriate and suitable for family viewing. Never include violence, injury, "
    "death, weapons, scary content, romance, brands or real people."
)

# Words that should never appear in a kids story (Hindi + English).
UNSAFE_WORDS = [
    "खून", "हत्या", "मौत", "मर गया", "मर गई", "मर गए", "मार डाला", "मार डालूँगा",
    "बंदूक", "चाकू", "तलवार", "शराब", "सिगरेट", "नशा", "भूत", "चुड़ैल", "लाश",
    "kill", "blood", "gun", "knife", "dead", "death", "murder", "alcohol", "sexy",
]

_HINDI_SUFFIXES = ("", "ों", "ो", "ें", "े", "ी", "ियों", "ियाँ")

# Remembers the animals picked for the current idea (used for footage fallback)
_current_story = {"animals": [], "theme": "", "name": ""}


# ------------------------------------------------------------------
# Groq API
# ------------------------------------------------------------------
def ask_ollama(
    prompt: str,
    max_retries: int = GROQ_MAX_RETRIES,
    system: str = None,
    temperature: float = 0.8,
    max_tokens: int = 2048,
) -> str:
    """Send a prompt to Groq and return the reply text ("" on failure)."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        log.error("GROQ_API_KEY is missing. Add it to your .env file.")
        return ""

    payload = {
        "model": GROQ_MODEL,
        "messages": [
            {"role": "system", "content": system or STORY_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    # gpt-oss models "think" before answering. With a high effort the thinking can
    # use up all tokens and the answer comes back EMPTY (this caused the
    # "Generated script (0 words)" error). Low effort leaves room for the answer.
    if GROQ_MODEL.startswith("openai/gpt-oss"):
        payload["reasoning_effort"] = "low"

    for attempt in range(1, max_retries + 1):
        try:
            resp = requests.post(
                GROQ_API_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=90,
            )
            if resp.status_code == 200:
                data = resp.json()
                choice = data["choices"][0]
                content = (choice.get("message", {}).get("content") or "").strip()
                if content:
                    return content
                log.warning(
                    "Groq returned an empty answer (attempt %s/%s, finish_reason=%s)",
                    attempt, max_retries, choice.get("finish_reason"),
                )
                payload["max_tokens"] = min(int(payload["max_tokens"] * 1.5), 6000)
            elif resp.status_code == 400 and "reasoning" in resp.text.lower() and "reasoning_effort" in payload:
                log.warning("Model does not accept reasoning_effort; retrying without it.")
                payload.pop("reasoning_effort", None)
                continue
            elif resp.status_code == 429:
                wait = 5
                try:
                    wait = min(float(resp.headers.get("retry-after", 5)), 30)
                except ValueError:
                    pass
                log.warning("Groq rate limit hit, waiting %.0fs...", wait)
                time.sleep(wait)
                continue
            elif resp.status_code in (401, 403, 404):
                # Wrong key / no access / unknown model: retrying will not help.
                log.error("Groq error %s: %s", resp.status_code, resp.text[:300])
                return ""
            else:
                log.warning("Groq returned status %s: %s", resp.status_code, resp.text[:300])
        except requests.RequestException as e:
            log.warning("Groq request attempt %s failed: %s", attempt, e)
        except (KeyError, IndexError, ValueError) as e:
            log.warning("Could not parse Groq response: %s", e)
        time.sleep(2 * attempt)

    return ""


# Clearer alias for new code
ask_groq = ask_ollama


# ------------------------------------------------------------------
# Text helpers (also used by script_quality.py)
# ------------------------------------------------------------------
def devanagari_ratio(text: str) -> float:
    """Share of letters that are Devanagari (0.0 - 1.0)."""
    letters = [c for c in text if c.isalpha() or "ऀ" <= c <= "ॿ"]
    if not letters:
        return 0.0
    deva = sum(1 for c in letters if "ऀ" <= c <= "ॿ")
    return deva / len(letters)


def count_words(text: str) -> int:
    return len([w for w in re.split(r"\s+", text.strip()) if re.search(r"\w", w)])


def split_sentences(text: str) -> list:
    """Split Hindi/English text into sentences, keeping the end mark."""
    parts = re.findall(r"[^।!?.]+[।!?.]*", text)
    return [p.strip() for p in parts if p.strip()]


def is_child_safe(text: str) -> bool:
    lower = text.lower()
    for w in UNSAFE_WORDS:
        if re.fullmatch(r"[a-z ]+", w):
            if re.search(rf"\b{re.escape(w)}\b", lower):
                return False
        elif w in text:
            return False
    return True


def _strip_emojis(text: str) -> str:
    return re.sub(r"[\U0001F000-\U0001FAFF☀-➿️‍]", "", text)


def clean_story_text(text: str) -> str:
    """Turn an AI reply into plain narration text (no titles, markdown, notes)."""
    if not text:
        return ""
    text = re.sub(r"```.*?```", lambda m: m.group(0).strip("`"), text, flags=re.S)
    text = text.replace("```", "")
    lines = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^#+\s*", "", line)
        line = line.replace("**", "").replace("__", "")
        line = re.sub(r"^[-*•]\s+", "", line)
        line = re.sub(r"^\d+[\.\)]\s*", "", line)
        # Drop label lines like "शीर्षक:", "Title:", "कहानी:", "Word count: 95"
        if re.match(r"^(शीर्षक|title|कहानी का नाम|word count|शब्द संख्या|नोट|note)\s*[:：]", line, re.I):
            continue
        line = re.sub(r"^(कहानी|story|script|हुक|hook)\s*[:：]\s*", "", line, flags=re.I)
        line = re.sub(r"\[.*?\]", "", line)
        line = re.sub(r"\((?:[^()]*?)\)", "", line)
        line = line.strip().strip('"').strip("“”").strip()
        if line:
            lines.append(line)

    # A short first line without sentence punctuation is usually a title.
    if len(lines) > 1 and count_words(lines[0]) <= 8 and not re.search(r"[।!?.]$", lines[0]):
        lines = lines[1:]

    text = " ".join(lines)
    text = _strip_emojis(text)
    text = text.replace("|", "।")
    text = re.sub(r"\s+([।!?,.])", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def detect_animals(text: str) -> list:
    """Return English footage words for animals mentioned in Hindi text (in order)."""
    tokens = [t.strip("।!?,.\"'“”‘’-:;") for t in text.split()]
    found = []
    for tok in tokens:
        if not tok:
            continue
        for animal in ANIMALS:
            if animal["en"] in found:
                continue
            for name in animal["hi"]:
                if any(tok == name + suf for suf in _HINDI_SUFFIXES):
                    found.append(animal["en"])
                    break
    # English words too (in case the AI used them)
    lower = text.lower()
    for animal in ANIMALS:
        if animal["en"] not in found and re.search(rf"\b{animal['en']}s?\b", lower):
            found.append(animal["en"])
    return found


def _one_line(text: str) -> str:
    text = clean_story_text(text)
    return text.split("\n")[0].strip().strip('"').strip("'")


# ------------------------------------------------------------------
# 1. Story idea
# ------------------------------------------------------------------
def generate_viral_idea(trending_topics: list, niche: dict) -> str:
    """Create a one-line Hindi idea for an original kids' animal story."""
    themes = niche.get("themes") or ["दोस्ती", "दया", "चतुराई"]
    theme = random.choice(themes)
    animals = random.sample(ANIMALS, 2)
    names = random.sample(CHARACTER_NAMES, 2)
    hero = f"{animals[0]['hi'][0]} {names[0]}"
    friend = f"{animals[1]['hi'][0]} {names[1]}"
    _current_story.update(
        {"animals": [a["en"] for a in animals], "theme": theme, "name": names[0]}
    )

    prompt = f"""एक बिल्कुल नई, मौलिक बच्चों की कहानी का आइडिया एक लाइन में लिखो।

मुख्य किरदार: {hero}
दोस्त: {friend}
सीख/विषय: {theme}

नियम:
- सिर्फ़ सरल हिंदी, देवनागरी लिपि में
- 10 से 20 शब्द
- एक छोटी सी परेशानी और उसका प्यारा, समझदारी भरा हल
- डरावना, हिंसक या दुखद कुछ भी नहीं
- दोनों जानवरों के नाम ज़रूर लिखो

सिर्फ़ आइडिया की एक लाइन लौटाओ, और कुछ नहीं।"""

    for attempt in range(2):
        idea = _one_line(ask_ollama(prompt, temperature=0.9, max_tokens=800))
        idea = re.sub(r"^\d+[\.\)]\s*", "", idea).strip()
        if idea and devanagari_ratio(idea) >= 0.8 and 5 <= count_words(idea) <= 35 and is_child_safe(idea):
            log.info(f"Generated idea: {idea}")
            return idea
        log.warning(f"Idea rejected (attempt {attempt + 1}): {idea[:80]!r}")

    idea = f"{hero} और {friend} मिलकर {theme} से एक छोटी सी मुश्किल हल करते हैं"
    log.info(f"Using fallback idea: {idea}")
    return idea


# ------------------------------------------------------------------
# 2. Story script
# ------------------------------------------------------------------
def _story_prompt(idea: str, feedback: str = "") -> str:
    return f"""Write an ORIGINAL children's animal story in Hindi for a YouTube Shorts video (about 40 seconds of narration).

STORY IDEA: {idea}

REQUIREMENTS:
- Language: simple, natural, spoken Hindi in Devanagari script only (no English words, no Roman letters).
- Length: {STORY_MIN_WORDS}-{STORY_MAX_WORDS} Hindi words. This is important.
- Cute animal characters with the names from the idea.
- Sentence 1 must be a short, exciting opening (under 12 words) that makes kids want to keep listening.
- Then: a small problem, a clever or kind solution, and a happy ending.
- Last sentence: a short, gentle lesson (सीख) for kids.
- Short sentences (5-12 words). End each sentence with "।", "!" or "?".
- Safe for young children: no violence, injury, death, weapons, fear or sadness.
- Output ONLY the narration as one paragraph. No title, no headings, no markdown, no emojis, no scene directions, no explanations, no word count.
{feedback}"""


def generate_script(idea: str) -> str:
    """Generate a Hindi kids' story (~80-110 words). Returns "" if it fails."""
    best, best_gap = "", None
    feedback = ""

    for attempt in range(1, 4):
        raw = ask_ollama(_story_prompt(idea, feedback), temperature=0.8, max_tokens=2500)
        story = clean_story_text(raw)
        words = count_words(story)
        ratio = devanagari_ratio(story)
        safe = is_child_safe(story)
        log.info(f"Story attempt {attempt}: {words} words, Hindi {ratio:.0%}, safe={safe}")

        if not story:
            feedback = ""
            continue
        if ratio < 0.85:
            feedback = "\nIMPORTANT: Your last answer was not in Hindi. Write ONLY in Hindi (Devanagari)."
            continue
        if not safe:
            feedback = "\nIMPORTANT: Keep the story completely gentle and safe for small children."
            continue

        gap = 0 if STORY_MIN_WORDS <= words <= STORY_MAX_WORDS else min(
            abs(words - STORY_MIN_WORDS), abs(words - STORY_MAX_WORDS))
        if best_gap is None or gap < best_gap:
            best, best_gap = story, gap
        if gap == 0:
            break
        if words < STORY_MIN_WORDS:
            feedback = (f"\nIMPORTANT: Your last story had only {words} words. "
                        f"Write a LONGER story with {STORY_MIN_WORDS}-{STORY_MAX_WORDS} words.")
        else:
            feedback = (f"\nIMPORTANT: Your last story had {words} words. "
                        f"Write a SHORTER story with {STORY_MIN_WORDS}-{STORY_MAX_WORDS} words.")

    # Accept a slightly off-length story rather than failing (voice speed is adjusted later)
    if best and best_gap is not None and best_gap <= 25:
        log.info(f"Generated script ({count_words(best)} words): {best[:120]}...")
        return best

    log.error("Hindi story generation failed or was too short/long. Check GROQ_API_KEY and logs.")
    return ""


# ------------------------------------------------------------------
# 3. Hook
# ------------------------------------------------------------------
def optimize_hook(script: str) -> str:
    """Make the first Hindi sentence a short, curious, child-friendly opening."""
    sentences = split_sentences(script)
    if not sentences:
        return script
    first = sentences[0]
    idx = script.find(first)
    rest = script[idx + len(first):].strip() if idx >= 0 else " ".join(sentences[1:])

    if count_words(first) <= 12 and first.endswith(("!", "?")):
        log.info(f"Hook already good: {first}")
        return script

    prompt = f"""यह बच्चों की हिंदी कहानी की पहली लाइन है:
"{first}"

पूरी कहानी:
{script}

इस पहली लाइन को दोबारा लिखो ताकि बच्चे तुरंत सुनना चाहें।
नियम:
- सिर्फ़ हिंदी, देवनागरी में
- 12 शब्दों से कम
- वही किरदार और वही जानवर रखो, कहानी की बात मत बदलो
- प्यारी, उत्सुकता जगाने वाली, डरावनी बिल्कुल नहीं
- अंत में "!" या "?" लगाओ
सिर्फ़ नई पहली लाइन लौटाओ, और कुछ नहीं।"""

    new_hook = _one_line(ask_ollama(prompt, temperature=0.7, max_tokens=800))
    if (
        new_hook
        and devanagari_ratio(new_hook) >= 0.85
        and 3 <= count_words(new_hook) <= 14
        and is_child_safe(new_hook)
    ):
        if not re.search(r"[।!?]$", new_hook):
            new_hook += "!"
        log.info(f"Optimized hook: {new_hook}")
        return f"{new_hook} {rest}".strip()

    log.info("Hook rewrite not usable, keeping the original opening.")
    return script


# ------------------------------------------------------------------
# 4. SEO metadata
# ------------------------------------------------------------------
BASE_HASHTAGS = ["#Shorts", "#HindiKahani", "#KidsStory", "#BacchonKiKahani", "#AnimalStory", "#हिंदीकहानी"]
BASE_TAGS = ["hindi kahani", "kids story", "hindi kids story", "bachon ki kahani",
             "animal story", "moral story", "cartoon kahani", "हिंदी कहानी",
             "बच्चों की कहानी", "जानवरों की कहानी", "नैतिक कहानी", "shorts"]


def _extract_json(text: str):
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except ValueError:
        return None


def _shorten_title(title: str, limit: int = 95) -> str:
    title = re.sub(r"\s+", " ", title.replace("#Shorts", "").replace("#shorts", "")).strip(" |-")
    title = title[: limit - len(" #Shorts")].rstrip(" |-,")
    return f"{title} #Shorts"


def generate_seo(idea: str, script: str) -> dict:
    """Generate Hindi/English YouTube metadata for a kids' story Short."""
    animals = detect_animals(script) or _current_story.get("animals", [])
    animal_tags = [f"{a} story" for a in animals[:3]]

    prompt = f"""Create YouTube Shorts metadata for this Hindi children's animal story.

STORY IDEA: {idea}
STORY: {script[:600]}

Return ONLY valid JSON with these keys:
{{"title": "...", "description": "...", "tags": ["...", "..."]}}

Rules:
- title: Hindi (Devanagari) story title with one cute emoji, then " | Hindi Kids Story". Under 70 characters. Friendly, no clickbait, no scary words.
- description: 2-3 short Hindi sentences about the story and its lesson, then one English sentence.
- tags: 12-15 tags, mix of Hindi and English (e.g. "हिंदी कहानी", "kids story", animal names).
- Content is made for kids: keep everything positive and family friendly."""

    fallback_title = clean_story_text(idea)
    fallback_title = " ".join(fallback_title.split()[:8])
    seo = {
        "title": _shorten_title(f"🐾 {fallback_title} | Hindi Kids Story"),
        "description": (
            f"{idea}। बच्चों के लिए एक प्यारी सी जानवरों की कहानी।\n"
            "A cute Hindi animal story for kids with a happy ending."
        ),
        "tags": BASE_TAGS + animal_tags,
        "hashtags": list(BASE_HASHTAGS),
        "made_for_kids": True,
    }

    data = _extract_json(ask_ollama(prompt, temperature=0.6, max_tokens=1500,
                                    system="You are a careful YouTube SEO assistant for kids' content. Reply with JSON only."))
    if isinstance(data, dict):
        title = str(data.get("title", "")).strip()
        if title and is_child_safe(title) and len(title) >= 5:
            seo["title"] = _shorten_title(title)
        desc = str(data.get("description", "")).strip()
        if desc and is_child_safe(desc):
            seo["description"] = desc
        tags = data.get("tags")
        if isinstance(tags, list):
            clean = [str(t).strip().lstrip("#") for t in tags if str(t).strip()]
            clean = [t for t in clean if len(t) <= 40 and is_child_safe(t)]
            if clean:
                seen, merged = set(), []
                for t in clean + BASE_TAGS + animal_tags:
                    if t.lower() not in seen:
                        seen.add(t.lower())
                        merged.append(t)
                seo["tags"] = merged[:25]
    else:
        log.warning("SEO reply was not valid JSON, using safe default metadata.")

    seo["description"] = seo["description"].rstrip() + "\n\n" + " ".join(seo["hashtags"])
    log.info(f"Generated SEO - Title: {seo['title']}")
    return seo


# ------------------------------------------------------------------
# 5. Footage search keywords
# ------------------------------------------------------------------
def generate_search_keywords(script: str, idea: str = "") -> list:
    """Return 5 English stock-footage searches that match the story's animals."""
    animals = detect_animals(f"{idea} {script}") or list(_current_story.get("animals", []))
    allowed = {a["en"] for a in ANIMALS}

    prompt = f"""This is a Hindi children's story about animals:
{script[:500]}

Give 5 short ENGLISH search terms for finding cute, real animal stock videos on Pixabay that match this story.
Rules:
- 1-3 words each, each must name an animal (for example: "cute rabbit", "baby elephant", "squirrel eating").
- Only animals that appear in the story: {", ".join(animals) or "any cute animal"}.
- Nothing scary, no people, no text.
- One term per line, no numbering, nothing else."""

    keywords = []
    response = ask_ollama(prompt, temperature=0.4, max_tokens=800,
                          system="You suggest short English stock-video search terms. Reply with plain lines only.")
    for line in response.split("\n"):
        kw = re.sub(r"^[\s\-*\d\.\)]+", "", line).strip().strip('"').strip("'").lower()
        if not kw or not re.fullmatch(r"[a-z][a-z \-]{1,28}", kw) or len(kw.split()) > 3:
            continue
        words = set(kw.replace("-", " ").split())
        if words & (allowed | set(animals)) or any(w.rstrip("s") in allowed for w in words):
            if kw not in keywords:
                keywords.append(kw)

    # Always make sure the story's animals are covered
    for a in animals:
        for kw in (f"cute {a}", f"baby {a}", a):
            if len(keywords) >= 5:
                break
            if kw not in keywords:
                keywords.append(kw)
    for kw in ("cute baby animals", "funny animals", "animals in nature"):
        if len(keywords) >= 5:
            break
        if kw not in keywords:
            keywords.append(kw)

    log.info(f"Search keywords: {keywords[:5]}")
    return keywords[:5]


if __name__ == "__main__":
    print(f"Testing Groq connection (model: {GROQ_MODEL})...")
    result = ask_ollama("एक लाइन में लिखो: AI इंजन काम कर रहा है।", max_tokens=400)
    print(f"Response: {result}" if result else "No response - check GROQ_API_KEY in .env and logs/automation.log")
