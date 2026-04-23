"""题目配置校验。"""

from __future__ import annotations

from typing import Any, List, Optional

from software.core.questions.schema import QuestionEntry

__all__ = ["validate_question_config"]


def validate_question_config(entries: List[QuestionEntry], questions_info: Optional[List[dict]] = None) -> Optional[str]:
    """验证题目配置是否存在冲突，返回错误信息。"""
    if not entries:
        return "未配置任何题目"

    def _count_positive_weights(raw_weights: Any) -> int:
        if not isinstance(raw_weights, (list, tuple)):
            return 0
        count = 0
        for value in raw_weights:
            try:
                if float(value) > 0:
                    count += 1
            except Exception:
                continue
        return count

    def _pick_config_weights(entry: QuestionEntry) -> Any:
        distribution_mode = str(getattr(entry, "distribution_mode", "") or "").strip().lower()
        custom_weights = getattr(entry, "custom_weights", None)
        probabilities = getattr(entry, "probabilities", None)
        return custom_weights if distribution_mode == "custom" and custom_weights not in (None, []) else probabilities

    errors: List[str] = []
    question_info_map = {}
    unsupported_questions: List[dict] = []
    for item in questions_info or []:
        if not isinstance(item, dict):
            continue
        q_num = item.get("num")
        if q_num is None:
            continue
        try:
            q_num = int(q_num)
        except Exception:
            q_num = None
        if q_num is not None:
            question_info_map[q_num] = item
        if bool(item.get("unsupported")):
            unsupported_questions.append(item)

    if unsupported_questions:
        lines = ["当前问卷包含暂不支持的题型，已禁止启动："]
        for item in unsupported_questions[:12]:
            title = str(item.get("title") or f"第{item.get('num')}题").strip()
            provider_type = str(item.get("provider_type") or item.get("type_code") or "未知类型").strip()
            reason = str(item.get("unsupported_reason") or "").strip()
            suffix = f"（{provider_type}，{reason}）" if reason else f"（{provider_type}）"
            lines.append(f"  - 第 {item.get('num')} 题：{title}{suffix}")
        if len(unsupported_questions) > 12:
            lines.append(f"  - 其余 {len(unsupported_questions) - 12} 道暂不支持题目已省略")
        return "\n".join(lines)

    for idx, entry in enumerate(entries):
        question_num = getattr(entry, "question_num", idx + 1)
        question_type = getattr(entry, "question_type", "")
        try:
            normalized_question_num = int(question_num)
        except Exception:
            normalized_question_num = idx + 1

        if question_type == "multiple":
            multi_min_limit: Optional[int] = None
            question_info = question_info_map.get(normalized_question_num)
            if question_info:
                multi_min_limit = question_info.get("multi_min_limit")

            probs = getattr(entry, "custom_weights", None) or getattr(entry, "probabilities", None)
            if isinstance(probs, list):
                positive_count = 0
                for prob in probs:
                    try:
                        if float(prob) > 0:
                            positive_count += 1
                    except Exception:
                        continue
                if positive_count <= 0:
                    errors.append(
                        f"第 {question_num} 题（多选题）配置无效：\n"
                        "  - 当前所有选项概率都小于等于 0%\n"
                        "  - 请至少将 1 个选项的概率设为大于 0%"
                    )
                    continue
                if multi_min_limit is not None and multi_min_limit > 0 and positive_count < multi_min_limit:
                    errors.append(
                        f"第 {question_num} 题（多选题）配置冲突：\n"
                        f"  - 题目要求最少选择 {multi_min_limit} 项\n"
                        f"  - 但只有 {positive_count} 个选项的概率大于 0%\n"
                        f"  - 请至少将 {multi_min_limit} 个选项的概率设为大于 0%"
                    )
                # 多选题的概率表示“候选命中概率”，不是“本次一定同时勾选”。
                # 运行时会在抽样后按题目最大可选数量自动收口，因此不能因为
                # 正概率选项数超过题目上限就提前拦截启动，否则像“4个候选项，
                # 题目最多选3项”这种正常配置会被误杀。

        configured_weights = _pick_config_weights(entry)
        if question_type in ("single", "dropdown", "scale", "score") and isinstance(configured_weights, list):
            if configured_weights and _count_positive_weights(configured_weights) <= 0:
                errors.append(
                    f"第 {question_num} 题（{question_type}）配置无效：\n"
                    "  - 当前所有选项配比都小于等于 0\n"
                    "  - 请至少将 1 个选项的配比设为大于 0"
                )

        if question_type == "matrix":
            row_weights_source = configured_weights
            if isinstance(row_weights_source, list) and any(isinstance(item, (list, tuple)) for item in row_weights_source):
                for row_idx, row_weights in enumerate(row_weights_source, start=1):
                    if isinstance(row_weights, (list, tuple)) and row_weights and _count_positive_weights(row_weights) <= 0:
                        errors.append(
                            f"第 {question_num} 题（矩阵题）配置无效：\n"
                            f"  - 第 {row_idx} 行所有选项配比都小于等于 0\n"
                            "  - 请至少将 1 个选项的配比设为大于 0"
                        )
            elif isinstance(row_weights_source, list) and row_weights_source and _count_positive_weights(row_weights_source) <= 0:
                errors.append(
                    f"第 {question_num} 题（矩阵题）配置无效：\n"
                    "  - 当前所有选项配比都小于等于 0\n"
                    "  - 请至少将 1 个选项的配比设为大于 0"
                )

        for cfg_idx, cfg in enumerate(list(getattr(entry, "attached_option_selects", []) or []), start=1):
            if not isinstance(cfg, dict):
                continue
            weights = cfg.get("weights")
            if isinstance(weights, list) and weights and _count_positive_weights(weights) <= 0:
                option_text = str(cfg.get("option_text") or "").strip()
                errors.append(
                    f"第 {question_num} 题（嵌入式下拉）配置无效：\n"
                    f"  - 第 {cfg_idx} 组（{option_text or '未命名选项'}）所有配比都小于等于 0\n"
                    "  - 请至少将 1 个选项的配比设为大于 0"
                )

    if errors:
        return "\n\n".join(errors)
    return None
