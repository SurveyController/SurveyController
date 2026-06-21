package configio

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"surveycontroller/surveycore"
)

func BuildDefaultConfigFilename(surveyTitle string) string {
	return sanitizeFilename(surveyTitle) + ".json"
}

func Load(path string, strict bool) (surveycore.RuntimeConfig, error) {
	if strings.TrimSpace(path) == "" {
		return surveycore.RuntimeConfig{}, fmt.Errorf("配置路径不能为空")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		if strict {
			return surveycore.RuntimeConfig{}, fmt.Errorf("读取配置失败: %s -> %w", path, err)
		}
		return surveycore.RuntimeConfig{}, nil
	}
	cleaned := StripJSONComments(string(data))
	if strings.TrimSpace(cleaned) == "" {
		if strict {
			return surveycore.RuntimeConfig{}, fmt.Errorf("配置文件为空")
		}
		return surveycore.RuntimeConfig{}, nil
	}
	var payload map[string]any
	if err := json.Unmarshal([]byte(cleaned), &payload); err != nil {
		if strict {
			return surveycore.RuntimeConfig{}, fmt.Errorf("读取配置失败: %s -> %w", path, err)
		}
		return surveycore.RuntimeConfig{}, nil
	}
	cfg, err := DeserializeRuntimeConfig(payload)
	if err != nil {
		if strict {
			return surveycore.RuntimeConfig{}, fmt.Errorf("配置不兼容: %s -> %w", path, err)
		}
		return surveycore.RuntimeConfig{}, nil
	}
	return cfg, nil
}

func Save(config surveycore.RuntimeConfig, path string) (string, error) {
	if strings.TrimSpace(path) == "" {
		return "", fmt.Errorf("配置路径不能为空")
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return "", err
	}
	payload := SerializeRuntimeConfig(config)
	data, err := json.MarshalIndent(payload, "", "  ")
	if err != nil {
		return "", err
	}
	if err := os.WriteFile(path, append(data, '\n'), 0o644); err != nil {
		return "", err
	}
	return path, nil
}

func StripJSONComments(raw string) string {
	text := strings.TrimLeft(raw, "\ufeff")
	var out strings.Builder
	inString := false
	escaped := false
	inLineComment := false
	inBlockComment := false
	for i := 0; i < len(text); i++ {
		ch := text[i]
		var next byte
		if i+1 < len(text) {
			next = text[i+1]
		}
		if inLineComment {
			if ch == '\n' {
				inLineComment = false
				out.WriteByte(ch)
			}
			continue
		}
		if inBlockComment {
			if ch == '*' && next == '/' {
				inBlockComment = false
				i++
			}
			continue
		}
		if inString {
			out.WriteByte(ch)
			if escaped {
				escaped = false
			} else if ch == '\\' {
				escaped = true
			} else if ch == '"' {
				inString = false
			}
			continue
		}
		if ch == '"' {
			inString = true
			out.WriteByte(ch)
			continue
		}
		if ch == '/' && next == '/' {
			inLineComment = true
			i++
			continue
		}
		if ch == '/' && next == '*' {
			inBlockComment = true
			i++
			continue
		}
		out.WriteByte(ch)
	}
	return out.String()
}

func sanitizeFilename(value string) string {
	normalized := strings.TrimSpace(value)
	if normalized == "" {
		return "wjx_config"
	}
	var out strings.Builder
	for _, ch := range normalized {
		if strings.ContainsRune(`\/:*?"<>|`, ch) || !strconvPrintable(ch) {
			continue
		}
		if ch == ' ' {
			out.WriteRune('_')
			continue
		}
		out.WriteRune(ch)
	}
	text := out.String()
	if text == "" {
		return "wjx_config"
	}
	if len([]rune(text)) > 80 {
		return string([]rune(text)[:80])
	}
	return text
}

func strconvPrintable(ch rune) bool {
	return ch >= 32 && ch != 127
}
