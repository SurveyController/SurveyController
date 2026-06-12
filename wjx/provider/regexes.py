from __future__ import annotations

import re

WJX_TITLE_SUFFIX_RE = re.compile(
    r"""
    (?:\s*[-|｜丨_－—]+\s*)?
    问卷星
    (?P<suffix>.*)?
    $
    """,
    re.IGNORECASE | re.VERBOSE,
)

WJX_QUESTION_PREFIX_RE = re.compile(
    r"""
    ^\*?\s*
    (?:
        第\s*(?P<cn_num>\d+)\s*题
        |
        Q\s*(?P<q_num>\d+)
        |
        (?P<plain_num>\d+)\s*[.．、]
    )
    \s*
    """,
    re.IGNORECASE | re.VERBOSE,
)

WJX_PAUSED_SURVEY_RE = re.compile(
    r"""
    此问卷
    [（(]
    \s*(?P<survey_id>\d+)\s*
    [）)]
    已暂停
    """,
    re.VERBOSE,
)

WJX_NOT_OPEN_TIME_RE = re.compile(
    r"""
    此问卷将于\s*
    (?P<year>\d{4})\s*(?:-|/|年)\s*
    (?P<month>\d{1,2})\s*(?:-|/|月)\s*
    (?P<day>\d{1,2})\s*(?:日)?
    \s*
    (?P<hour>\d{1,2})
    \s*(?::|时)\s*
    (?P<minute>\d{1,2})
    (?:
        \s*(?::|分)\s*
        (?P<second>\d{1,2})
        \s*秒?
    )?
    \s*开放
    """,
    re.VERBOSE,
)

WJX_JUMP_TARGET_RE = re.compile(
    r"""
    ^
    (?:
        (?P<signed>-?\d+)
        |
        跳到第\s*(?P<target>\d+)\s*题
    )
    $
    """,
    re.VERBOSE,
)

WJX_RELATION_CHUNK_RE = re.compile(
    r"""
    ^
    (?P<source>\d+)
    \s*,\s*
    (?P<options>\d+(?:\s*,\s*\d+)*)
    $
    """,
    re.VERBOSE,
)

WJX_FORCE_SELECT_COMMAND_RE = re.compile(r"请(?:务必|一定|必须|直接)?\s*选(?:择)?")
WJX_FORCE_SELECT_SENTENCE_SPLIT_RE = re.compile(r"[。；;！？!\n\r]")
WJX_FORCE_SELECT_CLEAN_RE = re.compile(r"[\s`'\"“”‘’【】\[\]\(\)（）<>《》,，、。；;:：!?！？]")
WJX_FORCE_SELECT_INDEX_TARGET_RE = re.compile(
    r"""
    ^
    第?\s*
    (?P<index>\d{1,3})
    \s*(?:个|项|选项|分|星)?
    $
    """,
    re.VERBOSE,
)
WJX_FORCE_SELECT_LABEL_TARGET_RE = re.compile(
    r"""
    ^
    (?P<label>[A-Za-z])
    \s*(?:项|选项|答案)?
    $
    """,
    re.VERBOSE,
)
WJX_FORCE_SELECT_OPTION_LABEL_RE = re.compile(
    r"""
    ^
    (?:第\s*)?
    [\(（【\[]?\s*
    (?P<label>[A-Za-z])
    \s*[\)）】\]]?
    (?=$|[.、:：\-\s]|[\u4e00-\u9fff])
    """,
    re.VERBOSE,
)

WJX_SCENE_ID_PATTERNS = (
    re.compile(
        r"""
        \bsceneId
        \s*[:=]\s*
        ["'](?P<value>[^"']+)["']
        """,
        re.IGNORECASE | re.VERBOSE,
    ),
    re.compile(
        r"""
        \bscene_id
        \s*[:=]\s*
        ["'](?P<value>[^"']+)["']
        """,
        re.IGNORECASE | re.VERBOSE,
    ),
    re.compile(
        r"""
        \bdata-scene-id
        \s*=\s*
        ["'](?P<value>[^"']+)["']
        """,
        re.IGNORECASE | re.VERBOSE,
    ),
)

WJX_MODLEN_CLASS_RE = re.compile(r"modlen(?P<count>\d+)")


__all__ = [
    "WJX_FORCE_SELECT_CLEAN_RE",
    "WJX_FORCE_SELECT_COMMAND_RE",
    "WJX_FORCE_SELECT_INDEX_TARGET_RE",
    "WJX_FORCE_SELECT_LABEL_TARGET_RE",
    "WJX_FORCE_SELECT_OPTION_LABEL_RE",
    "WJX_FORCE_SELECT_SENTENCE_SPLIT_RE",
    "WJX_JUMP_TARGET_RE",
    "WJX_MODLEN_CLASS_RE",
    "WJX_NOT_OPEN_TIME_RE",
    "WJX_PAUSED_SURVEY_RE",
    "WJX_QUESTION_PREFIX_RE",
    "WJX_RELATION_CHUNK_RE",
    "WJX_SCENE_ID_PATTERNS",
    "WJX_TITLE_SUFFIX_RE",
]
