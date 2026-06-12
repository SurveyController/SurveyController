import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from software.core.persona.generator import get_current_persona




@dataclass
class AnsweredQuestion:
    
    question_num: int
    question_type: str          
    selected_indices: List[int] = field(default_factory=list)   
    selected_texts: List[str] = field(default_factory=list)     
    text_answer: str = ""       
    row_answers: Dict[int, List[int]] = field(default_factory=dict)  




_thread_local = threading.local()


PERSONA_BOOST_FACTOR = 3.0


def reset_context() -> None:
    
    _thread_local.answered = {}


def record_answer(
    question_num: int,
    question_type: str,
    selected_indices: Optional[List[int]] = None,
    selected_texts: Optional[List[str]] = None,
    text_answer: str = "",
    row_index: Optional[int] = None,
) -> None:
    
    ctx = getattr(_thread_local, "answered", None)
    if ctx is None:
        _thread_local.answered = {}
        ctx = _thread_local.answered
    if row_index is not None:
        
        if question_num not in ctx:
            ctx[question_num] = AnsweredQuestion(
                question_num=question_num,
                question_type=question_type,
            )
        ctx[question_num].row_answers[row_index] = selected_indices or []
    else:
        ctx[question_num] = AnsweredQuestion(
            question_num=question_num,
            question_type=question_type,
            selected_indices=selected_indices or [],
            selected_texts=selected_texts or [],
            text_answer=text_answer,
        )


def get_answered() -> Dict[int, AnsweredQuestion]:
    
    return getattr(_thread_local, "answered", {})




def apply_persona_boost(
    option_texts: List[str],
    base_weights: List[float],
) -> List[float]:
    
    persona = get_current_persona()
    if persona is None:
        return list(base_weights)

    keyword_map = persona.to_keyword_map()
    if not keyword_map:
        return list(base_weights)

    
    all_keywords: List[str] = []
    for keywords in keyword_map.values():
        all_keywords.extend(keywords)

    if not all_keywords:
        return list(base_weights)

    boosted = list(base_weights)
    for i, text in enumerate(option_texts):
        if not text or i >= len(boosted):
            continue
        text_lower = text.strip()
        for keyword in all_keywords:
            if keyword in text_lower:
                boosted[i] *= PERSONA_BOOST_FACTOR
                logging.info(
                    "画像约束：选项[%d]「%s」匹配关键词「%s」，权重 x%.1f",
                    i, text[:20], keyword, PERSONA_BOOST_FACTOR,
                )
                break  
    return boosted


def build_ai_context_prompt() -> str:
    
    parts: List[str] = []

    
    persona = get_current_persona()
    if persona:
        desc = persona.to_description()
        parts.append(f"你扮演的角色是：{desc}。")

    
    answered = get_answered()
    if answered:
        sorted_questions = sorted(answered.items(), key=lambda x: x[0])
        
        recent = sorted_questions[-10:]
        if recent:
            summary_lines = []
            for q_num, record in recent:
                if record.question_type == "text" and record.text_answer:
                    summary_lines.append(f"  第{q_num}题(填空): {record.text_answer[:50]}")
                elif record.selected_texts:
                    texts = "、".join(record.selected_texts[:3])
                    summary_lines.append(f"  第{q_num}题: 选了「{texts}」")
            if summary_lines:
                parts.append("你在这份问卷中前面的作答记录：")
                parts.extend(summary_lines)
                parts.append("请保持与前面回答的一致性。")

    return "\n".join(parts)


