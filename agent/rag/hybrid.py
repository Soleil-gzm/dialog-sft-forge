"""RRF（Reciprocal Rank Fusion）手写实现 —— 融合多路检索结果。

为什么不直接加权合并分数：
  BM25 得分是无上界的正数，余弦相似度落在 [-1, 1]，两者量纲完全不同，
  直接加权需要先做分数归一化，而归一化依赖当次结果的分布，极不稳定。
  实际企业方案通常用 RRF 把这层归一化显式化，每条查询只使用检索结果的相对位置。
  RRF 只使用「排名」这一个信息，对分值尺度不敏感，因此跨检索器融合更稳。

公式：

    RRF(d) = Σ ─────────────
               k + rank_i(d)

  k 默认 60（原论文经验值）：k 越大，头部排名的优势被压得越平缓。
"""

from typing import Dict, List, Optional, Sequence, Tuple


def rrf_fuse(
    rankings: Sequence[Sequence[str]],
    k: int = 60,
    weights: Optional[Sequence[float]] = None,
) -> List[Tuple[str, float]]:
    """融合多路有序 id 列表，返回 [(id, rrf_score)]，按得分降序。

    rankings 中每个元素是一路检索的结果 id 列表，顺序即排名（从 1 开始）。
    """
    if weights is not None and len(weights) != len(rankings):
        raise ValueError(f"权重数量({len(weights)})与检索路数({len(rankings)})不一致")

    scores: Dict[str, float] = {}
    for route_index, ranking in enumerate(rankings):
        weight = 1.0 if weights is None else weights[route_index]
        for position, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + weight / (k + position)

    # 得分降序；同分按 id 升序，保证结果可复现
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))
