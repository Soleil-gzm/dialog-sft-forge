"""
分析器模块：对 trace 文件进行分析并生成报告。
提供抽象基类和默认实现，支持可扩展的分析方式。
"""

import json
import os
import re
from abc import ABC, abstractmethod
from collections import Counter
from typing import Dict, List, Optional

import numpy as np

try:
    import plotly.express as px
    import plotly.graph_objects as go

    HAS_PLOTLY = True
except ImportError:
    HAS_PLOTLY = False
    import matplotlib.pyplot as plt


def extract_timestamp_from_filename(filepath: str) -> str:
    basename = os.path.basename(filepath)
    match = re.search(r"traces_(\d{8}_\d{6})\.json", basename)
    if match:
        return match.group(1)
    import time

    return time.strftime("%Y%m%d_%H%M%S", time.localtime(os.path.getmtime(filepath)))


def simplify_reason(reason: str) -> str:
    if not reason:
        return reason
    return re.sub(r"_\d+$", "", reason)


def analyze_traces_data(traces: List[Dict]) -> Dict:
    """
    核心统计逻辑，适配新版 trace 结构（嵌套字段）
    """
    pressure_positions = []
    goodbye_normalized = []
    stop_reason_counter = Counter()
    dialogue_lengths = []
    goodbye_handling = {
        "triggered_and_stopped": 0,
        "triggered_but_not_stopped": 0,
        "natural_end": 0,
    }

    dialogue_with_pressure = 0
    dialogue_without_pressure = 0

    for trace in traces:
        path = trace.get("path", [])
        modules = trace.get("modules", [])
        final_reason = trace.get("overall_stop_reason", None)
        path_len = len(path)

        if final_reason:
            simplified = simplify_reason(final_reason)
            stop_reason_counter[simplified] += 1

        # 计算总轮数
        total_turns = trace.get(
            "total_turns", sum(mod.get("turn_count", 0) for mod in modules)
        )
        dialogue_lengths.append(total_turns)

        # 统计再见处理结果
        has_triggered = False  # 是否有模块实际触发了再见（goodbye_triggered=True）
        has_goodbye_value_1_ignored = (
            False  # 是否有模块 goodbye_value=1 但未触发（忽略）
        )

        for mod in modules:
            goodbye = mod.get("goodbye", {})
            if goodbye.get("goodbye_triggered", False):
                has_triggered = True
            if goodbye.get("goodbye_value") == 1 and not goodbye.get(
                "goodbye_triggered", False
            ):
                has_goodbye_value_1_ignored = True

        is_stopped = final_reason and final_reason.startswith("goodbye")

        if has_triggered:
            if is_stopped:
                goodbye_handling["triggered_and_stopped"] += 1
            else:
                # 触发再见但未停止（理论上不会发生，因为触发必停止）
                goodbye_handling["triggered_but_not_stopped"] += 1
        elif has_goodbye_value_1_ignored:
            # 存在 goodbye_value=1 但被概率忽略，导致未触发
            goodbye_handling["triggered_but_not_stopped"] += 1
        else:
            goodbye_handling["natural_end"] += 1

        # 再见触发位置
        if has_triggered:
            trigger_idx = None
            for idx, mod in enumerate(modules):
                goodbye = mod.get("goodbye", {})
                if goodbye.get("goodbye_triggered", False):
                    trigger_idx = idx
                    break
            if trigger_idx is not None:
                if path_len > 1:
                    goodbye_normalized.append(trigger_idx / (path_len - 1))
                else:
                    goodbye_normalized.append(0.0)

        # ---- 促销相关统计（兼容新旧字段） ----
        # 检查是否有任何促销（优先使用 triggered，若没有则回退到 applied）
        has_pressure = False
        for mod in modules:
            pressure = mod.get("pressure", {})
            # 优先使用 triggered，如果不存在则检查 applied（向后兼容）
            if pressure.get("triggered", False) or pressure.get("applied", False):
                has_pressure = True
                break

        if has_pressure:
            dialogue_with_pressure += 1
        else:
            dialogue_without_pressure += 1

        # 促销位置（同样兼容）
        for idx, mod in enumerate(modules):
            pressure = mod.get("pressure", {})
            if pressure.get("applied", False):
                if path_len > 1:
                    pressure_positions.append(idx / (path_len - 1))
                else:
                    pressure_positions.append(0.0)

    return {
        "pressure_positions": pressure_positions,
        "goodbye_normalized": goodbye_normalized,
        "stop_reason_counter": stop_reason_counter,
        "dialogue_lengths": dialogue_lengths,
        "goodbye_handling": goodbye_handling,
        "total_conversations": len(traces),
        "dialogue_with_pressure": dialogue_with_pressure,
        "dialogue_without_pressure": dialogue_without_pressure,
    }


class Analyzer(ABC):
    @abstractmethod
    def analyze(self, trace_path: str, output_dir: str, **kwargs) -> None:
        pass


class DefaultAnalyzer(Analyzer):
    def __init__(self, format: str = "html", pressure_config: Optional[Dict] = None):
        self.format = format
        self.pressure_config = pressure_config or {}

    def _save_text_report(self, stats: Dict, output_file: str):
        with open(output_file, "w", encoding="utf-8") as f:
            f.write("=== Trace Analysis Report ===\n")
            f.write(f"Total conversations: {stats['total_conversations']}\n")
            # 新增促销对话统计
            f.write(f"Conversations with pressure: {stats['dialogue_with_pressure']}\n")
            f.write(
                f"Conversations without pressure: {stats['dialogue_without_pressure']}\n"
            )
            f.write(
                f"Pressure coverage rate: {stats['dialogue_with_pressure'] / stats['total_conversations']:.2%}\n"
            )

            f.write("\nStop reason distribution:\n")
            for reason, cnt in sorted(
                stats["stop_reason_counter"].items(), key=lambda x: x[1], reverse=True
            ):
                f.write(f"  {reason}: {cnt}\n")

            f.write("\nGoodbye handling:\n")
            f.write(
                f"  triggered_and_stopped (再见触发并停止): {stats['goodbye_handling']['triggered_and_stopped']}\n"
            )
            f.write(
                f"  triggered_but_not_stopped (再见存在但被忽略): {stats['goodbye_handling']['triggered_but_not_stopped']}\n"
            )
            f.write(
                f"  natural_end (无再见行，自然结束): {stats['goodbye_handling']['natural_end']}\n"
            )

            if stats["pressure_positions"]:
                arr = np.array(stats["pressure_positions"])
                f.write(
                    f"\nPressure position (normalized) mean: {np.mean(arr):.3f}, median: {np.median(arr):.3f}, std: {np.std(arr):.3f}\n"
                )
            if stats["goodbye_normalized"]:
                arr = np.array(stats["goodbye_normalized"])
                f.write(
                    f"Goodbye trigger position (normalized) mean: {np.mean(arr):.3f}, median: {np.median(arr):.3f}, std: {np.std(arr):.3f}\n"
                )
            if stats["dialogue_lengths"]:
                arr = np.array(stats["dialogue_lengths"])
                f.write(
                    f"Dialogue length (number of turns) mean: {np.mean(arr):.2f}, median: {np.median(arr):.2f}, min: {np.min(arr)}, max: {np.max(arr)}\n"
                )
        print(f"Report saved: {output_file}")

    def _create_histogram(
        self, data, title, xlabel, ylabel, output_html, nbins=20, bin_size=None
    ):
        if not data:
            print(f"警告: 没有数据可绘制 {title}")
            return
        hist_kwargs = dict(x=data, marker_color="#1f77b4", opacity=0.75)
        layout_kwargs = dict(
            title=title,
            xaxis_title=xlabel,
            yaxis_title=ylabel,
            template="plotly_white",
            bargap=0.1,
        )
        if bin_size is not None:
            hist_kwargs["xbins"] = dict(size=bin_size)
            layout_kwargs["xaxis_dtick"] = bin_size
        else:
            hist_kwargs["nbinsx"] = nbins
        fig = go.Figure(data=[go.Histogram(**hist_kwargs)])
        fig.update_layout(**layout_kwargs)
        fig.write_html(output_html)
        print(f"保存直方图: {output_html}")

    def _create_bar_chart(self, counter_or_dict, title, xlabel, ylabel, output_html):
        if not counter_or_dict:
            return
        if isinstance(counter_or_dict, dict):
            categories = list(counter_or_dict.keys())
            counts = list(counter_or_dict.values())
        else:
            categories = list(counter_or_dict.keys())
            counts = list(counter_or_dict.values())
        fig = go.Figure(
            data=[
                go.Bar(
                    x=categories,
                    y=counts,
                    text=counts,
                    textposition="auto",
                    marker_color=px.colors.qualitative.Plotly[: len(categories)],
                )
            ]
        )
        fig.update_layout(
            title=title,
            xaxis_title=xlabel,
            yaxis_title=ylabel,
            template="plotly_white",
            xaxis_tickangle=-45,
        )
        fig.write_html(output_html)
        print(f"保存条形图: {output_html}")

    def _create_pie_chart(self, stats: Dict, output_html: str):
        """生成促销覆盖率的饼图"""
        if not HAS_PLOTLY:
            print("Plotly 未安装，无法生成饼图")
            return
        labels = ["有促销的对话", "无促销的对话"]
        values = [stats["dialogue_with_pressure"], stats["dialogue_without_pressure"]]
        fig = go.Figure(
            data=[
                go.Pie(
                    labels=labels,
                    values=values,
                    textinfo="label+percent",
                    insidetextorientation="radial",
                    marker=dict(colors=["#1f77b4", "#ff7f0e"]),
                )
            ]
        )
        fig.update_layout(
            title="促销话术覆盖情况 (对话级别)",
            template="plotly_white",
        )
        fig.write_html(output_html)
        print(f"保存饼图: {output_html}")

    def _generate_html_charts(self, stats: Dict, output_dir: str):
        if not HAS_PLOTLY:
            print("Plotly 未安装，无法生成 HTML 图表")
            return
        subtitle_parts = []
        if self.pressure_config:
            for key, value in self.pressure_config.items():
                subtitle_parts.append(f"{key}={value}")
        subtitle = (
            "<br><sub>" + ", ".join(subtitle_parts) + "</sub>" if subtitle_parts else ""
        )

        self._create_histogram(
            stats["pressure_positions"],
            f"Pressure Utterance Position Distribution{subtitle}",
            "Normalized Position (0=start, 1=end)",
            "Frequency",
            os.path.join(output_dir, "pressure_position_histogram.html"),
        )
        if stats["goodbye_normalized"]:
            self._create_histogram(
                stats["goodbye_normalized"],
                f"Goodbye Trigger Position Distribution{subtitle}",
                "Normalized Position (0=start, 1=end)",
                "Frequency",
                os.path.join(output_dir, "goodbye_position_histogram.html"),
            )
        else:
            print("No goodbye triggers found, skipping goodbye position histogram.")

        self._create_bar_chart(
            stats["stop_reason_counter"],
            "Stop Reason Distribution",
            "Stop Reason",
            "Number of Conversations",
            os.path.join(output_dir, "stop_reason_bar.html"),
        )
        self._create_histogram(
            stats["dialogue_lengths"],
            "Dialogue Length Distribution",
            "Number of Turns (user+assistant pairs)",
            "Frequency",
            os.path.join(output_dir, "dialogue_length_histogram.html"),
            bin_size=1,
        )
        self._create_bar_chart(
            stats["goodbye_handling"],
            "Goodbye Handling Outcome",
            "Category",
            "Number of Conversations",
            os.path.join(output_dir, "goodbye_handling_bar.html"),
        )

        # 新增：促销覆盖饼图
        self._create_pie_chart(
            stats,
            os.path.join(output_dir, "pressure_coverage_pie.html"),
        )

    def _generate_png_charts(self, stats: Dict, output_dir: str):
        # 保持原有 PNG 降级逻辑不变（略）
        pass

    def analyze(self, trace_path: str, output_dir: str, **kwargs) -> None:
        if not os.path.exists(trace_path):
            raise FileNotFoundError(f"Trace file not found: {trace_path}")
        os.makedirs(output_dir, exist_ok=True)

        with open(trace_path, "r", encoding="utf-8") as f:
            traces = json.load(f)
        print(f"Loaded {len(traces)} conversations from {trace_path}")

        stats = analyze_traces_data(traces)
        self._save_text_report(stats, os.path.join(output_dir, "analysis_report.txt"))

        if self.format == "html" and HAS_PLOTLY:
            self._generate_html_charts(stats, output_dir)
        elif self.format == "png":
            self._generate_png_charts(stats, output_dir)
        else:
            print(
                f"Format '{self.format}' not supported or plotly missing, skipping charts."
            )


class ModuleDiversityAnalyzer(Analyzer):
    """
    模块条件 × UID 多样性分析器。
    只生成 txt 报告，不生成图表，不输出到终端。
    """

    def __init__(self, modules: List[str]):
        self.modules = modules

    def analyze(self, trace_path: str, output_dir: str, **kwargs) -> None:
        if not os.path.exists(trace_path):
            raise FileNotFoundError(f"Trace file not found: {trace_path}")
        os.makedirs(output_dir, exist_ok=True)

        with open(trace_path, "r", encoding="utf-8") as f:
            traces = json.load(f)

        for module_name in self.modules:
            self._analyze_single_module(traces, module_name, output_dir)

    def _analyze_single_module(
        self, traces: List[Dict], module_name: str, output_dir: str
    ):
        """分析单个模块，输出 txt 报告。"""
        from collections import Counter, defaultdict

        condition_uid_counter = defaultdict(Counter)
        condition_total_counter = Counter()

        for trace in traces:
            for mod in trace.get("modules", []):
                if mod.get("module") != module_name:
                    continue
                cond_text = mod.get("condition_text", "")
                if not cond_text or cond_text == "无条件":
                    cond_text = "无条件(空)"
                uid = mod.get("selected_uid", -1)
                if uid == -1:
                    continue
                condition_uid_counter[cond_text][uid] += 1
                condition_total_counter[cond_text] += 1

        report_file = os.path.join(output_dir, f"diversity_report_{module_name}.txt")

        with open(report_file, "w", encoding="utf-8") as f:
            if not condition_uid_counter:
                f.write(f"模块 '{module_name}' 无数据\n")
                return

            all_conditions = condition_total_counter.most_common()
            f.write(f"模块 '{module_name}' 条件 × UID 多样性报告\n")
            f.write("=" * 80 + "\n")
            f.write(f"共 {len(all_conditions)} 个条件\n")
            f.write(
                f"{'条件':<30} {'总次数':>8} {'不同UID数':>10} {'最大UID占比':>12} {'多样性评分':>10}\n"
            )
            f.write("-" * 80 + "\n")

            for cond, total in all_conditions:
                uid_counts = condition_uid_counter[cond]
                unique_uids = len(uid_counts)
                max_count = max(uid_counts.values()) if uid_counts else 0
                max_ratio = max_count / total if total > 0 else 0
                diversity = 1 - max_ratio
                f.write(
                    f"{cond:<30} {total:>8} {unique_uids:>10} {max_ratio:>11.2%} {diversity:>9.2f}\n"
                )

            f.write("\n" + "=" * 80 + "\n")
            f.write("多样性警报 (最大UID占比 > 50%):\n")
            f.write("-" * 80 + "\n")
            alert_count = 0
            for cond, total in all_conditions:
                uid_counts = condition_uid_counter[cond]
                unique_uids = len(uid_counts)
                max_count = max(uid_counts.values()) if uid_counts else 0
                max_ratio = max_count / total if total > 0 else 0
                if max_ratio > 0.5:
                    f.write(
                        f"  [!] {cond}: 最大UID占比 {max_ratio:.1%} (仅 {unique_uids} 个不同UID)\n"
                    )
                    alert_count += 1
            if alert_count == 0:
                f.write("  所有条件多样性良好，无明显单调问题。\n")

            f.write("\n" + "=" * 80 + "\n")
            f.write("解读指南:\n")
            f.write(
                "- '最大UID占比' 越接近 100%，说明该条件只命中固定的1-2句话术，多样性差。\n"
            )
            f.write("- '多样性评分' 越接近 1.0，说明该条件下各 UID 分布越均匀。\n")
            f.write(
                "- 建议关注 '最大UID占比 > 50%' 的条件，检查 Excel 里的 'parent(继承)' 或 'flexible_stop' 是否限制了随机性。\n"
            )


def _normalize_condition(value) -> str:
    """规范化条件字符串：None / NaN / 空串 → '无条件(空)'"""
    if value is None:
        return "无条件(空)"
    s = str(value)
    if s.strip() == "" or s.lower() == "nan":
        return "无条件(空)"
    return s


def _normalize_uid(value) -> str:
    """规范化 uid：1.0 → '1'，保证 Excel 与 trace 两侧类型一致"""
    try:
        f = float(value)
        if f.is_integer():
            return str(int(f))
    except (TypeError, ValueError):
        pass
    return str(value)


class ModuleCoverageAnalyzer(Analyzer):
    """
    模块覆盖率分析器。
    统计内容：
      1. 每个模块被访问的对话数 / 总轮次数
      2. 每个模块内每个条件的话术行覆盖率（已覆盖行 / Excel 总行）
      3. 每行话术（uid）的抽取次数
    输出：coverage_report.txt + 条形图（html，需 plotly）
    """

    def __init__(self, df_dict: Dict, format: str = "html"):
        self.df_dict = df_dict
        self.format = format

    def analyze(self, trace_path: str, output_dir: str, **kwargs) -> None:
        from collections import defaultdict

        if not os.path.exists(trace_path):
            raise FileNotFoundError(f"Trace file not found: {trace_path}")
        os.makedirs(output_dir, exist_ok=True)

        with open(trace_path, "r", encoding="utf-8") as f:
            traces = json.load(f)
        print(f"Loaded {len(traces)} conversations from {trace_path} (coverage)")

        # ---- 1. 聚合 trace：模块对话数 / 轮次 / 条件×uid 抽取次数 ----
        module_dialogues = Counter()
        module_turns = Counter()
        # module → condition → uid → 次数
        cond_uid_hits: Dict[str, Dict[str, Counter]] = defaultdict(
            lambda: defaultdict(Counter)
        )

        for trace in traces:
            seen_in_dialogue = set()
            for mod in trace.get("modules", []):
                name = mod.get("module")
                if not name:
                    continue
                if name not in seen_in_dialogue:
                    module_dialogues[name] += 1
                    seen_in_dialogue.add(name)
                module_turns[name] += mod.get("turn_count", 0)
                uid = mod.get("selected_uid", -1)
                if uid is None or uid == -1:
                    continue
                cond = _normalize_condition(mod.get("condition_text"))
                cond_uid_hits[name][cond][_normalize_uid(uid)] += 1

        # ---- 2. Excel 侧分母：module → condition → [uid, ...] ----
        excel_rows: Dict[str, Dict[str, List[str]]] = defaultdict(
            lambda: defaultdict(list)
        )
        for name, df in self.df_dict.items():
            for _, row in df.iterrows():
                cond = _normalize_condition(row.get("conditions(条件)"))
                excel_rows[name][cond].append(_normalize_uid(row.get("uid")))

        # ---- 3. 文本报告 ----
        self._write_report(
            len(traces),
            module_dialogues,
            module_turns,
            cond_uid_hits,
            excel_rows,
            os.path.join(output_dir, "coverage_report.txt"),
        )

        # ---- 4. 条形图 ----
        if self.format == "html" and HAS_PLOTLY:
            self._create_charts(
                module_dialogues, module_turns, cond_uid_hits, excel_rows, output_dir
            )
        else:
            print(f"Format '{self.format}' 不支持或 plotly 缺失，跳过覆盖率图表")

    def _write_report(
        self,
        total: int,
        module_dialogues: Counter,
        module_turns: Counter,
        cond_uid_hits: Dict,
        excel_rows: Dict,
        report_file: str,
    ) -> None:
        all_modules = list(
            dict.fromkeys(list(excel_rows.keys()) + list(module_dialogues.keys()))
        )
        alerts = []

        with open(report_file, "w", encoding="utf-8") as f:
            f.write("=== 模块覆盖率报告 ===\n")
            f.write(f"总对话数: {total}\n\n")

            # 一、模块访问统计
            f.write("一、模块访问统计\n")
            f.write("-" * 90 + "\n")
            f.write(
                f"{'模块':<12} {'对话数':>8} {'对话覆盖率':>10} {'总轮次':>8} {'平均轮次/对话':>12}\n"
            )
            f.write("-" * 90 + "\n")
            for m in all_modules:
                dlg = module_dialogues.get(m, 0)
                turns = module_turns.get(m, 0)
                avg = turns / dlg if dlg else 0
                f.write(
                    f"{m:<12} {dlg:>8} {dlg / total:>9.2%} {turns:>8} {avg:>12.2f}\n"
                )

            # 二、条件与话术行覆盖详情
            f.write("\n二、条件与话术行覆盖详情\n")
            for m in all_modules:
                cond_rows = excel_rows.get(m, {})
                total_rows = sum(len(v) for v in cond_rows.values())
                covered_rows = 0
                for cond, uids in cond_rows.items():
                    hit = cond_uid_hits.get(m, {}).get(cond, Counter())
                    covered_rows += sum(1 for u in uids if u in hit)
                rate = covered_rows / total_rows if total_rows else 0
                f.write(
                    f"\n### {m}  (Excel行数: {total_rows}, 已覆盖: {covered_rows}, "
                    f"行覆盖率: {rate:.2%})\n"
                )
                f.write(
                    f"{'条件':<28} {'行数':>6} {'已覆盖':>6} {'覆盖率':>9} {'抽取总次数':>10}\n"
                )
                for cond, uids in cond_rows.items():
                    hit = cond_uid_hits.get(m, {}).get(cond, Counter())
                    cov = sum(1 for u in uids if u in hit)
                    hits_total = sum(hit.values())
                    f.write(
                        f"{cond:<28} {len(uids):>6} {cov:>6} "
                        f"{cov / len(uids):>8.2%} {hits_total:>10}\n"
                    )
                    if cov < len(uids):
                        missing = [u for u in uids if u not in hit]
                        alerts.append((m, cond, len(uids), cov, missing))
                # 行级抽取明细
                f.write("  行级抽取明细:\n")
                for cond, uids in cond_rows.items():
                    hit = cond_uid_hits.get(m, {}).get(cond, Counter())
                    for u in uids:
                        f.write(f"    uid={u} [{cond}]: {hit.get(u, 0)} 次\n")

            # 三、覆盖率警报
            f.write("\n三、覆盖率警报（存在未覆盖的话术行）\n")
            f.write("-" * 90 + "\n")
            if not alerts:
                f.write("  所有话术行均被覆盖。\n")
            else:
                for m, cond, rows, cov, missing in alerts:
                    f.write(
                        f"  [!] {m} / {cond}: {rows} 行仅覆盖 {cov} 行，"
                        f"未覆盖 uid: {', '.join(missing)}\n"
                    )

            f.write("\n解读指南:\n")
            f.write("- '对话覆盖率' = 访问过该模块的对话数 / 总对话数\n")
            f.write("- '行覆盖率' = 被抽取过的话术行数 / Excel 中该模块该条件的总行数\n")
            f.write(
                "- 未覆盖的行通常是条件苛刻（如积分阈值）或继承链（parent）限制导致\n"
            )
        print(f"覆盖率报告已保存: {report_file}")

    def _create_charts(
        self,
        module_dialogues: Counter,
        module_turns: Counter,
        cond_uid_hits: Dict,
        excel_rows: Dict,
        output_dir: str,
    ) -> None:
        modules = list(
            dict.fromkeys(list(excel_rows.keys()) + list(module_dialogues.keys()))
        )

        # 1. 模块级：对话数 + 总轮次（分组条形图）
        fig = go.Figure(
            data=[
                go.Bar(
                    name="对话数",
                    x=modules,
                    y=[module_dialogues.get(m, 0) for m in modules],
                ),
                go.Bar(
                    name="总轮次",
                    x=modules,
                    y=[module_turns.get(m, 0) for m in modules],
                ),
            ]
        )
        fig.update_layout(
            barmode="group",
            title="模块访问覆盖（对话数 / 总轮次）",
            xaxis_title="模块",
            yaxis_title="次数",
            template="plotly_white",
            xaxis_tickangle=-45,
        )
        out = os.path.join(output_dir, "coverage_module_bar.html")
        fig.write_html(out)
        print(f"保存条形图: {out}")

        # 2. 条件级行覆盖率（%）
        labels, rates = [], []
        for m in modules:
            for cond, uids in excel_rows.get(m, {}).items():
                hit = cond_uid_hits.get(m, {}).get(cond, Counter())
                cov = sum(1 for u in uids if u in hit)
                labels.append(f"{m}|{cond}")
                rates.append(cov / len(uids) * 100)
        if labels:
            fig2 = go.Figure(
                go.Bar(
                    x=labels,
                    y=rates,
                    text=[f"{r:.0f}%" for r in rates],
                    textposition="auto",
                    marker_color="#2ca02c",
                )
            )
            fig2.update_layout(
                title="各模块条件的话术行覆盖率",
                xaxis_title="模块|条件",
                yaxis_title="行覆盖率 (%)",
                yaxis=dict(range=[0, 110]),
                template="plotly_white",
                xaxis_tickangle=-45,
            )
            out2 = os.path.join(output_dir, "coverage_condition_bar.html")
            fig2.write_html(out2)
            print(f"保存条形图: {out2}")

        # 3. 每个模块的行级抽取次数
        for m in modules:
            cond_rows = excel_rows.get(m, {})
            if not cond_rows:
                continue
            labels, counts = [], []
            for cond, uids in cond_rows.items():
                hit = cond_uid_hits.get(m, {}).get(cond, Counter())
                for u in uids:
                    labels.append(f"uid{u}|{cond}")
                    counts.append(hit.get(u, 0))
            figm = go.Figure(
                go.Bar(
                    x=labels,
                    y=counts,
                    text=counts,
                    textposition="auto",
                    marker_color="#1f77b4",
                )
            )
            figm.update_layout(
                title=f"模块[{m}] 话术行抽取次数",
                xaxis_title="uid|条件",
                yaxis_title="抽取次数",
                template="plotly_white",
                xaxis_tickangle=-45,
            )
            outm = os.path.join(output_dir, f"coverage_rows_{m}.html")
            figm.write_html(outm)
        print(f"保存 {len(modules)} 个模块的行级抽取条形图")
