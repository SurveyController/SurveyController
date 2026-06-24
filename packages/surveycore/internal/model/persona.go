package model

import "strings"

type Persona struct {
	Gender               string
	AgeGroup             string
	Education            string
	Occupation           string
	IncomeLevel          string
	MaritalStatus        string
	HasChildren          bool
	SatisfactionTendency float64
}

func (p Persona) KeywordMap() map[string][]string {
	mapping := map[string][]string{}
	if p.Gender == "男" {
		mapping["gender"] = []string{"男", "男性", "先生", "男生"}
	} else if p.Gender == "女" {
		mapping["gender"] = []string{"女", "女性", "女士", "女生"}
	}
	if p.AgeGroup != "" {
		ageKeywords := map[string][]string{
			"18-25": []string{"18", "19", "20", "21", "22", "23", "24", "25", "18-25", "18~25", "18岁", "20岁", "大学", "青年"},
			"26-35": []string{"26", "27", "28", "29", "30", "31", "32", "33", "34", "35", "26-35", "26~35", "30岁", "青年", "中青年"},
			"36-45": []string{"36", "37", "38", "39", "40", "41", "42", "43", "44", "45", "36-45", "36~45", "40岁", "中年"},
			"46-60": []string{"46", "47", "48", "49", "50", "51", "52", "53", "54", "55", "56", "57", "58", "59", "60", "46-60", "46~60", "50岁", "中年", "中老年"},
		}
		mapping["age_group"] = append([]string(nil), ageKeywords[p.AgeGroup]...)
	}
	if p.Education != "" {
		eduKeywords := map[string][]string{
			"高中及以下":  []string{"高中", "初中", "中专", "职高", "小学", "高中及以下", "高中以下", "中学"},
			"大专":     []string{"大专", "专科", "高职"},
			"本科":     []string{"本科", "大学", "学士", "大学本科"},
			"研究生及以上": []string{"研究生", "硕士", "博士", "博士后", "研究生及以上", "硕士及以上"},
		}
		mapping["education"] = append([]string(nil), eduKeywords[p.Education]...)
	}
	if p.Occupation != "" {
		occupationKeywords := map[string][]string{
			"学生":   []string{"学生", "在校", "在读", "校园"},
			"上班族":  []string{"上班", "在职", "企业", "公司", "职员", "白领", "员工", "工作", "在职人员"},
			"自由职业": []string{"自由职业", "自由", "个体", "创业", "自营", "个体户", "自由职业者"},
			"退休":   []string{"退休", "离退休", "退休人员"},
		}
		mapping["occupation"] = append([]string(nil), occupationKeywords[p.Occupation]...)
	}
	if p.IncomeLevel != "" {
		incomeKeywords := map[string][]string{
			"低": []string{"3000以下", "3000元以下", "5000以下", "5000元以下", "低收入", "无收入", "2000以下"},
			"中": []string{"5000-10000", "5000~10000", "5001-10000", "10000-20000", "10000~20000", "万元", "中等收入", "1万", "一万"},
			"高": []string{"20000以上", "20000元以上", "2万以上", "3万以上", "50000以上", "高收入", "5万"},
		}
		mapping["income_level"] = append([]string(nil), incomeKeywords[p.IncomeLevel]...)
	}
	if p.MaritalStatus == "未婚" {
		mapping["marital_status"] = []string{"未婚", "单身", "恋爱", "未婚/单身"}
	} else if p.MaritalStatus == "已婚" {
		mapping["marital_status"] = []string{"已婚", "已婚已育", "已婚未育", "结婚"}
	}
	if p.HasChildren {
		mapping["has_children"] = []string{"有孩子", "有子女", "已育", "有小孩"}
	} else {
		mapping["no_children"] = []string{"无子女", "无孩子", "未育", "没有孩子", "没有小孩"}
	}
	return mapping
}

func (p Persona) Description() string {
	parts := make([]string, 0, 7)
	if p.Gender != "" {
		parts = append(parts, p.Gender+"性")
	}
	if p.AgeGroup != "" {
		parts = append(parts, p.AgeGroup+"岁")
	}
	if p.Education != "" {
		parts = append(parts, "学历"+p.Education)
	}
	if p.Occupation != "" {
		parts = append(parts, p.Occupation)
	}
	if p.IncomeLevel != "" {
		incomeText := map[string]string{"低": "收入较低", "中": "收入中等", "高": "收入较高"}
		if text := incomeText[p.IncomeLevel]; text != "" {
			parts = append(parts, text)
		}
	}
	if p.MaritalStatus != "" {
		parts = append(parts, p.MaritalStatus)
	}
	if p.HasChildren {
		parts = append(parts, "有孩子")
	}
	if len(parts) == 0 {
		return "一名普通用户"
	}
	return strings.Join(parts, "、")
}
