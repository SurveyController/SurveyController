package credamo

func choicePayload(raw map[string]any, fillText string) map[string]any {
	return map[string]any{
		"choiceId":      idFromMapping(raw, "choiceId", "id"),
		"choiceContent": fillText,
	}
}

func idFromMapping(item map[string]any, keys ...string) any {
	for _, key := range keys {
		value := item[key]
		if value != nil && stringValue(value) != "" {
			return normalizeID(value)
		}
	}
	return ""
}

func normalizeID(value any) any {
	text := stringValue(value)
	if text == "" {
		return ""
	}
	if number, ok := parseInt(text); ok {
		return number
	}
	return text
}
