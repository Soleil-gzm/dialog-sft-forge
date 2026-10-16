"""轻量 tokenizer：零依赖的中英混合切分。

设计取舍（为什么不用 jieba）：
- 本模块坚持零第三方依赖，方便 CI 离线运行，也让检索原理完全可控；
- 中文按「字符 bigram」切分，覆盖「积分/到期/优惠券」这类高频双字词；
- 仅当整段中文只剩单字时（如原文中的「满」「减」或单字查询「券」）才输出该单字，
  避免无差别输出 unigram 造成噪声——实测单字 token 会稀释 `vip` 这类高 IDF 词的区分度；
- 英文与数字按连续字母数字串整体切分，不做词干还原（对政策类文档足够）。
"""

import re
from typing import List

# 单次匹配：连续的英文/数字串，或单个中文字
_PIECE_PATTERN = re.compile(r"[a-z0-9]+|[\u4e00-\u9fff]")

_CJK_START, _CJK_END = "\u4e00", "\u9fff"


def _is_cjk(piece: str) -> bool:
    return len(piece) == 1 and _CJK_START <= piece <= _CJK_END


def _cjk_tokens(chars: List[str]) -> List[str]:
    """中文串 → 相邻 bigram；单字串原样返回。"""
    if len(chars) == 1:
        return list(chars)
    return ["".join(chars[i : i + 2]) for i in range(len(chars) - 1)]


def tokenize(text: str) -> List[str]:
    """把文本切分为检索 token 列表。"""
    if not text:
        return []

    tokens: List[str] = []
    cjk_buffer: List[str] = []

    for piece in _PIECE_PATTERN.findall(text.lower()):
        if _is_cjk(piece):
            cjk_buffer.append(piece)
            continue
        # 遇到英文/数字，先把积压的中文串冲出去
        if cjk_buffer:
            tokens.extend(_cjk_tokens(cjk_buffer))
            cjk_buffer = []
        tokens.append(piece)

    if cjk_buffer:
        tokens.extend(_cjk_tokens(cjk_buffer))
    return tokens
