"""输入语言识别，用于决定需求工件（PRD/BRD/SRS 等）的输出语言。

设计原因：
需求 Agent 的提示词本身是中文写的，但输出语言必须跟随用户输入。
所以这里只负责“判断用户用哪种语言描述需求”，再由 run_with_retry 把
对应的输出语言指令注入到每一次 crew.kickoff 的 inputs 里。
"""

import os
import re

DEFAULT_LANGUAGE = "zh"

# 当前这轮需求工程的输出语言。默认中文，保证存量中文链路行为不变。
_detected_language = (os.getenv("REAGENT_OUTPUT_LANGUAGE", "") or DEFAULT_LANGUAGE).strip().lower()

_LANGUAGE_NAMES = {
    "zh": ("Chinese", "中文"),
    "en": ("English", "English"),
    "ja": ("Japanese", "日本語"),
    "ko": ("Korean", "한국어"),
    "ru": ("Russian", "Русский"),
    "ar": ("Arabic", "العربية"),
    "he": ("Hebrew", "עברית"),
    "th": ("Thai", "ไทย"),
    "hi": ("Hindi", "हिन्दी"),
    "el": ("Greek", "Ελληνικά"),
    "es": ("Spanish", "Español"),
    "fr": ("French", "Français"),
    "de": ("German", "Deutsch"),
    "pt": ("Portuguese", "Português"),
    "it": ("Italian", "Italiano"),
}

# 判定按“词”而不是“字”来比较：一个汉字承载的信息量接近一个英文单词，
# 直接比字符数会把“中文夹杂英文技术名词”的描述误判成英文。
# 表意/音节文字按字统计再折算成词，拼音文字直接按词统计。
_SYLLABIC_SCRIPTS = [
    ("ja", r"[぀-ゟ゠-ヿ]"),  # 假名优先于汉字，日文里也有汉字
    ("ko", r"[가-힯ᄀ-ᇿ]"),
    ("zh", r"[一-鿿㐀-䶿]"),
    ("th", r"[฀-๿]"),
]

_ALPHABETIC_SCRIPTS = [
    ("ru", r"[Ѐ-ӿ]"),
    ("ar", r"[؀-ۿ]"),
    ("he", r"[֐-׿]"),
    ("hi", r"[ऀ-ॿ]"),
    ("el", r"[Ͱ-Ͽ]"),
]

# 表意/音节文字里，一个词大致等于两个字。
_CHARS_PER_WORD = 2

_LATIN_STOPWORDS = {
    "es": {"el", "la", "los", "las", "de", "que", "para", "con", "una", "un", "usuario", "sistema", "debe"},
    "fr": {"le", "la", "les", "des", "une", "un", "que", "pour", "avec", "utilisateur", "doit", "système"},
    "de": {"der", "die", "das", "und", "für", "mit", "eine", "einen", "nicht", "benutzer", "soll", "system"},
    "pt": {"o", "a", "os", "as", "de", "que", "para", "com", "uma", "um", "usuário", "deve", "sistema"},
    "it": {"il", "la", "le", "dei", "che", "per", "con", "una", "un", "utente", "deve", "sistema"},
    "en": {"the", "a", "an", "and", "of", "to", "for", "with", "should", "user", "system", "must"},
}


def _strip_noise(text: str) -> str:
    """去掉 URL、代码块和 markdown 标记，避免它们干扰语言判断。"""
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    return text


def detect_language(text: str) -> str:
    """返回文本的语言代码（zh/en/ja/...），无法判断时返回 DEFAULT_LANGUAGE。"""
    if not text or not text.strip():
        return DEFAULT_LANGUAGE

    cleaned = _strip_noise(text)

    units = {code: len(re.findall(pattern, cleaned)) / _CHARS_PER_WORD for code, pattern in _SYLLABIC_SCRIPTS}
    units.update({code: len(re.findall(pattern + "+", cleaned)) for code, pattern in _ALPHABETIC_SCRIPTS})
    latin_units = len(re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", cleaned))

    # 假名只要出现就足以判定为日文，因为中文里不会有假名。
    if units["ja"] > 0 and units["ja"] * 10 >= units["zh"]:
        return "ja"

    total = latin_units + sum(units.values())
    if total == 0:
        return DEFAULT_LANGUAGE

    dominant = max(units, key=units.get)
    if units[dominant] / total > 0.2:
        return dominant

    return _detect_latin_language(cleaned)


def _detect_latin_language(text: str) -> str:
    words = {w for w in re.findall(r"[a-zà-öø-ÿ]+", text.lower()) if len(w) <= 12}
    if not words:
        return "en"
    scores = {code: len(words & stopwords) for code, stopwords in _LATIN_STOPWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else "en"


def get_output_language_instruction(lang: str) -> str:
    """把语言代码翻译成给 LLM 的输出语言约束。"""
    code = (lang or DEFAULT_LANGUAGE).strip().lower()
    if code == "zh":
        return "你的输出内容必须使用中文，只有涉及数据结构的字段名可以使用英文。"

    english_name, endonym = _LANGUAGE_NAMES.get(code, ("English", "English"))
    label = english_name if english_name == endonym else f"{english_name} ({endonym})"
    return (
        f"You MUST write ALL output content in {label}. "
        f"Every heading, table cell, list item, diagram label and explanatory sentence must be in {english_name}, "
        "even when the instructions above are written in another language. "
        "Only data-structure field names and code identifiers may stay in English."
    )


def set_detected_language(lang: str) -> str:
    global _detected_language
    if lang and lang.strip():
        _detected_language = lang.strip().lower()
    return _detected_language


def get_detected_language() -> str:
    return _detected_language


def detect_and_set_language(text: str) -> str:
    return set_detected_language(detect_language(text))


def apply_output_language_instruction(inputs):
    """给一次 crew.kickoff 的 inputs 补上输出语言指令。

    agents.yaml 与 tasks*.yaml 里都写了 {output_language_instruction} 占位符，
    CrewAI 只会替换 inputs 里存在的键，所以每条 kickoff 路径都必须经过这里。
    """
    prepared = dict(inputs or {})
    prepared.setdefault(
        "output_language_instruction",
        get_output_language_instruction(get_detected_language()),
    )
    return prepared
