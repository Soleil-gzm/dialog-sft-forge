"""BM25（Okapi）手写实现 —— 关键词检索路。

公式（对每个查询词 t 累加）：

    score(D, Q) = Σ IDF(t) * ─────────────────────────────
                            tf(t,D) + k1 * (1 - b + b * |D| / avgdl)

    IDF(t) = ln(1 + (N - df(t) + 0.5) / (df(t) + 0.5))

参数含义：
- k1：词频饱和系数。词频增长时得分增长逐渐变缓，避免「同一个词刷很多遍」霸榜；
- b ：文档长度归一化系数。b=1 完全按长度归一，b=0 完全忽略长度，0.75 为常用折中。

IDF 用 BM25+ 变体（ln(1 + ...)）保证非负，避免高频词出现负分。
"""

import math
from typing import Dict, List, Tuple

from agent.rag.tokenizer import tokenize


class BM25:
    """基于内存的 BM25 索引，适合小规模知识库。"""

    def __init__(self, corpus_tokens: List[List[str]], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.corpus_tokens = corpus_tokens
        self.n_docs = len(corpus_tokens)
        self.doc_len = [len(tokens) for tokens in corpus_tokens]
        self.avg_len = (sum(self.doc_len) / self.n_docs) if self.n_docs else 0.0

        self.term_freqs: List[Dict[str, int]] = []
        doc_freq: Dict[str, int] = {}
        for tokens in corpus_tokens:
            freq: Dict[str, int] = {}
            for token in tokens:
                freq[token] = freq.get(token, 0) + 1
            self.term_freqs.append(freq)
            for token in freq:
                doc_freq[token] = doc_freq.get(token, 0) + 1

        self.idf: Dict[str, float] = {
            term: math.log(1 + (self.n_docs - df + 0.5) / (df + 0.5))
            for term, df in doc_freq.items()
        }

    def get_scores(self, query_tokens: List[str]) -> List[float]:
        """返回每个文档对查询词的 BM25 得分。"""
        scores = [0.0] * self.n_docs
        if not self.avg_len:
            return scores

        for token in query_tokens:
            idf = self.idf.get(token)
            if idf is None:  # 该词不在词表中（未登录词）直接跳过
                continue
            for index, freq in enumerate(self.term_freqs):
                tf = freq.get(token)
                if not tf:
                    continue
                norm = 1 - self.b + self.b * self.doc_len[index] / self.avg_len
                scores[index] += idf * tf * (self.k1 + 1) / (tf + self.k1 * norm)
        return scores

    def search(self, query: str, top_k: int = 5) -> List[Tuple[int, float]]:
        """返回 [(文档下标, 得分)]，按得分降序，同分按下标升序保证确定性。"""
        scores = self.get_scores(tokenize(query))
        ranked = [(i, s) for i, s in enumerate(scores) if s > 0]
        ranked.sort(key=lambda item: (-item[1], item[0]))
        return ranked[:top_k]
