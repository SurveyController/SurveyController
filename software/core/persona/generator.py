import random
import threading
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass
class Persona:
    
    gender: str = ""                    
    age_group: str = ""                 
    education: str = ""                 
    occupation: str = ""                
    income_level: str = ""              
    marital_status: str = ""            
    has_children: bool = False
    satisfaction_tendency: float = 0.5  

    def to_keyword_map(self) -> Dict[str, List[str]]:
        
        mapping: Dict[str, List[str]] = {}
        if self.gender:
            mapping["gender"] = (
                ["男", "男性", "先生", "男生"]
                if self.gender == "男"
                else ["女", "女性", "女士", "女生"]
            )
        if self.age_group:
            age_keywords = {
                "18-25": ["18", "19", "20", "21", "22", "23", "24", "25",
                           "18-25", "18~25", "18岁", "20岁", "大学", "青年"],
                "26-35": ["26", "27", "28", "29", "30", "31", "32", "33", "34", "35",
                           "26-35", "26~35", "30岁", "青年", "中青年"],
                "36-45": ["36", "37", "38", "39", "40", "41", "42", "43", "44", "45",
                           "36-45", "36~45", "40岁", "中年"],
                "46-60": ["46", "47", "48", "49", "50", "51", "52", "53", "54", "55",
                           "56", "57", "58", "59", "60",
                           "46-60", "46~60", "50岁", "中年", "中老年"],
            }
            mapping["age_group"] = age_keywords.get(self.age_group, [])
        if self.education:
            edu_keywords = {
                "高中及以下": ["高中", "初中", "中专", "职高", "小学", "高中及以下",
                             "高中以下", "中学"],
                "大专": ["大专", "专科", "高职"],
                "本科": ["本科", "大学", "学士", "大学本科"],
                "研究生及以上": ["研究生", "硕士", "博士", "博士后", "研究生及以上",
                              "硕士及以上"],
            }
            mapping["education"] = edu_keywords.get(self.education, [])
        if self.occupation:
            occ_keywords = {
                "学生": ["学生", "在校", "在读", "校园"],
                "上班族": ["上班", "在职", "企业", "公司", "职员", "白领",
                          "员工", "工作", "在职人员"],
                "自由职业": ["自由职业", "自由", "个体", "创业", "自营",
                           "个体户", "自由职业者"],
                "退休": ["退休", "离退休", "退休人员"],
            }
            mapping["occupation"] = occ_keywords.get(self.occupation, [])
        if self.income_level:
            income_keywords = {
                "低": ["3000以下", "3000元以下", "5000以下", "5000元以下",
                       "低收入", "无收入", "2000以下"],
                "中": ["5000-10000", "5000~10000", "5001-10000",
                       "10000-20000", "10000~20000", "万元", "中等收入",
                       "1万", "一万"],
                "高": ["20000以上", "20000元以上", "2万以上", "3万以上",
                       "50000以上", "高收入", "5万"],
            }
            mapping["income_level"] = income_keywords.get(self.income_level, [])
        if self.marital_status:
            mapping["marital_status"] = (
                ["未婚", "单身", "恋爱", "未婚/单身"]
                if self.marital_status == "未婚"
                else ["已婚", "已婚已育", "已婚未育", "结婚"]
            )
        
        if self.has_children:
            mapping["has_children"] = ["有孩子", "有子女", "已育", "有小孩"]
        else:
            mapping["no_children"] = ["无子女", "无孩子", "未育", "没有孩子", "没有小孩"]
        return mapping

    def to_description(self) -> str:
        
        parts = []
        if self.gender:
            parts.append(f"{self.gender}性")
        if self.age_group:
            parts.append(f"{self.age_group}岁")
        if self.education:
            parts.append(f"学历{self.education}")
        if self.occupation:
            parts.append(self.occupation)
        if self.income_level:
            income_text = {"低": "收入较低", "中": "收入中等", "高": "收入较高"}
            parts.append(income_text.get(self.income_level, ""))
        if self.marital_status:
            parts.append(self.marital_status)
        if self.has_children:
            parts.append("有孩子")
        if not parts:
            return "一名普通用户"
        return "、".join(parts)





def generate_persona() -> Persona:
    
    p = Persona()

    
    p.gender = random.choice(["男", "女"])

    
    p.age_group = random.choices(
        ["18-25", "26-35", "36-45", "46-60"],
        weights=[35, 35, 20, 10],
        k=1,
    )[0]

    
    if p.age_group == "18-25":
        p.education = random.choices(
            ["高中及以下", "大专", "本科", "研究生及以上"],
            weights=[15, 20, 50, 15],
            k=1,
        )[0]
    elif p.age_group in ("26-35", "36-45"):
        p.education = random.choices(
            ["高中及以下", "大专", "本科", "研究生及以上"],
            weights=[10, 20, 45, 25],
            k=1,
        )[0]
    else:
        p.education = random.choices(
            ["高中及以下", "大专", "本科", "研究生及以上"],
            weights=[25, 25, 35, 15],
            k=1,
        )[0]

    
    if p.age_group == "18-25":
        p.occupation = random.choices(
            ["学生", "上班族", "自由职业"],
            weights=[55, 35, 10],
            k=1,
        )[0]
    elif p.age_group == "46-60":
        p.occupation = random.choices(
            ["上班族", "自由职业", "退休"],
            weights=[50, 25, 25],
            k=1,
        )[0]
    else:
        p.occupation = random.choices(
            ["上班族", "自由职业"],
            weights=[75, 25],
            k=1,
        )[0]

    
    if p.occupation == "学生":
        p.income_level = random.choices(["低", "中"], weights=[85, 15], k=1)[0]
    elif p.occupation == "退休":
        p.income_level = random.choices(["低", "中", "高"], weights=[30, 50, 20], k=1)[0]
    elif p.age_group in ("36-45", "46-60"):
        p.income_level = random.choices(["低", "中", "高"], weights=[15, 45, 40], k=1)[0]
    elif p.age_group == "26-35":
        p.income_level = random.choices(["低", "中", "高"], weights=[20, 50, 30], k=1)[0]
    else:
        p.income_level = random.choices(["低", "中", "高"], weights=[40, 45, 15], k=1)[0]

    
    if p.age_group == "18-25":
        p.marital_status = random.choices(["未婚", "已婚"], weights=[90, 10], k=1)[0]
    elif p.age_group == "26-35":
        p.marital_status = random.choices(["未婚", "已婚"], weights=[45, 55], k=1)[0]
    elif p.age_group == "36-45":
        p.marital_status = random.choices(["未婚", "已婚"], weights=[15, 85], k=1)[0]
    else:
        p.marital_status = random.choices(["未婚", "已婚"], weights=[10, 90], k=1)[0]

    
    if p.marital_status == "未婚":
        p.has_children = random.random() < 0.03  
    elif p.age_group in ("36-45", "46-60"):
        p.has_children = random.random() < 0.90
    elif p.age_group == "26-35":
        p.has_children = random.random() < 0.50
    else:
        p.has_children = random.random() < 0.10

    
    raw = random.gauss(0.6, 0.15)
    p.satisfaction_tendency = max(0.1, min(0.9, raw))

    return p




_thread_local = threading.local()


def set_current_persona(persona: Persona) -> None:
    
    _thread_local.persona = persona


def get_current_persona() -> Optional[Persona]:
    
    return getattr(_thread_local, "persona", None)


def reset_persona() -> None:
    
    _thread_local.persona = None
