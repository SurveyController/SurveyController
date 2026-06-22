package main

import (
	_ "embed"
	"strings"
)

//go:embed build/config.yml
var desktopBuildConfig string

func displayAppVersion() string {
	return configVersionFromText(desktopBuildConfig)
}

func configVersionFromText(text string) string {
	inInfo := false
	for _, line := range strings.Split(text, "\n") {
		trimmed := strings.TrimSpace(line)
		if trimmed == "info:" {
			inInfo = true
			continue
		}
		if inInfo && line != "" && line[0] != ' ' && line[0] != '\t' {
			break
		}
		if inInfo && strings.HasPrefix(trimmed, "version:") {
			value := strings.TrimSpace(strings.TrimPrefix(trimmed, "version:"))
			if commentIndex := strings.Index(value, "#"); commentIndex >= 0 {
				value = strings.TrimSpace(value[:commentIndex])
			}
			value = strings.Trim(value, `"'`)
			if value != "" {
				return value
			}
		}
	}
	return "unknown"
}
