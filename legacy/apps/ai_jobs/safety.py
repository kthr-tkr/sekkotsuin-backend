import re
from dataclasses import dataclass
from typing import List, Tuple, Dict

@dataclass
class SafetyHit:
    field: str      # s/o/a/p
    pattern: str
    found: str
    replaced: str

# 断定・診断ワード（柔整の返戻/監査で怖いやつ）
REPLACEMENTS: List[Tuple[str, str]] = [
    # 診断確定系 → “示唆/可能性”へ
    (r"骨折(です|である|疑いなし|確定)?", "骨折の可能性（要確認）"),
    (r"ヘルニア(です|である|確定)?", "椎間板由来の症状の可能性（要確認）"),
    (r"神経根症(です|である|確定)?", "神経症状の可能性（要確認）"),
    (r"坐骨神経痛(です|である|確定)?", "下肢への放散痛の可能性（要確認）"),
    (r"脱臼(です|である|確定)?", "脱臼の可能性（要確認）"),
    (r"捻挫(です|である|確定)?", "捻挫が疑われる（要確認）"),
    (r"打撲(です|である|確定)?", "打撲が疑われる（要確認）"),
    (r"診断(する|した|です|である)", "所見より考えられる"),
    (r"確定", "可能性"),
    (r"断定", "示唆"),
]

# 強い断定口調の緩和（文章トーン）
TONE_DOWN: List[Tuple[str, str]] = [
    (r"〜である。", "〜と考えられる。"),
    (r"と判断する。", "可能性がある。"),
    (r"と断定する。", "可能性が示唆される。"),
]

def _apply_rules(text: str) -> Tuple[str, List[Tuple[str, str, str]]]:
    hits = []
    out = text or ""

    for pat, rep in REPLACEMENTS:
        for m in re.finditer(pat, out):
            hits.append((pat, m.group(0), rep))
        out = re.sub(pat, rep, out)

    for pat, rep in TONE_DOWN:
        for m in re.finditer(pat, out):
            hits.append((pat, m.group(0), rep))
        out = re.sub(pat, rep, out)

    return out, hits

def sanitize_soap(soap: Dict[str, str]) -> Tuple[Dict[str, str], List[SafetyHit]]:
    """
    soap: {"s": "...", "o": "...", "a": "...", "p": "..."}
    """
    result = {}
    all_hits: List[SafetyHit] = []

    for field in ["s", "o", "a", "p"]:
        cleaned, hits = _apply_rules(soap.get(field, ""))
        result[field] = cleaned
        for pat, found, rep in hits:
            all_hits.append(SafetyHit(field=field, pattern=pat, found=found, replaced=rep))

    return result, all_hits
