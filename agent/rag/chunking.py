"""知识库文档加载与分块。

分块策略（两级切分）：
  1. 按 Markdown 二级标题（## ）把文档拆成语义章节，章节标题并入正文，
     保证「积分有效期」这类标题词能被检索命中；
  2. 章节正文过长时按固定字符窗口滑窗切分，相邻块保留 overlap 重叠，
     避免关键句被切断导致跨块语义丢失。

每个块都记录 doc_title / section，用于在 Agent 回答时展示「出处」。
"""

import glob
import os
from dataclasses import dataclass, field
from typing import List

_SECTION_PREFIX = "## "


@dataclass
class Chunk:
    """知识库中的一个检索单元。"""

    chunk_id: str  # 全局唯一，如 "points.md#2"
    doc_title: str  # 文档标题（一级标题）
    section: str  # 所属章节标题
    text: str  # 参与检索的正文（含章节标题）
    source: str  # 相对路径，如 "knowledge/points.md"

    def citation(self) -> str:
        """用于展示的出处标注。"""
        return f"{self.doc_title} · {self.section}"

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "doc_title": self.doc_title,
            "section": self.section,
            "text": self.text,
            "source": self.source,
            "citation": self.citation(),
        }


@dataclass
class _Section:
    title: str
    body: str = ""
    lines: List[str] = field(default_factory=list)


def _split_sections(content: str) -> List[_Section]:
    """按二级标题切分文档，标题行之前的内容归入「概述」。"""
    sections: List[_Section] = []
    current = _Section(title="概述")

    for line in content.splitlines():
        if line.startswith(_SECTION_PREFIX):
            if current.lines:
                current.body = "\n".join(current.lines).strip()
                sections.append(current)
            current = _Section(title=line[len(_SECTION_PREFIX) :].strip())
        else:
            current.lines.append(line)

    if current.lines:
        current.body = "\n".join(current.lines).strip()
        sections.append(current)

    return [s for s in sections if s.body]


def _split_text(text: str, chunk_size: int, overlap: int) -> List[str]:
    """固定窗口滑窗切分，带重叠。"""
    if len(text) <= chunk_size:
        return [text]

    step = max(1, chunk_size - overlap)
    pieces: List[str] = []
    for start in range(0, len(text), step):
        piece = text[start : start + chunk_size].strip()
        if piece:
            pieces.append(piece)
        if start + chunk_size >= len(text):
            break
    return pieces


def load_chunks(knowledge_dir: str, chunk_size: int = 300, overlap: int = 50) -> List[Chunk]:
    """加载目录下所有 .md 知识文档并切分为 Chunk 列表。"""
    if not os.path.isdir(knowledge_dir):
        raise FileNotFoundError(f"知识库目录不存在: {knowledge_dir}")

    paths = sorted(glob.glob(os.path.join(knowledge_dir, "*.md")))
    if not paths:
        raise FileNotFoundError(f"知识库目录下没有 .md 文档: {knowledge_dir}")

    chunks: List[Chunk] = []
    for path in paths:
        filename = os.path.basename(path)
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        doc_title = filename[:-3]
        for line in content.splitlines():
            if line.startswith("# "):
                doc_title = line[2:].strip()
                break

        for sec_index, section in enumerate(_split_sections(content), start=1):
            section_text = f"{section.title}\n{section.body}"
            for piece in _split_text(section_text, chunk_size, overlap):
                chunks.append(
                    Chunk(
                        chunk_id=f"{filename}#{sec_index}-{len(chunks)}",
                        doc_title=doc_title,
                        section=section.title,
                        text=piece,
                        source=f"knowledge/{filename}",
                    )
                )
    return chunks
