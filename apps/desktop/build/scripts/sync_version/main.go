package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"os"
	"path/filepath"
	"regexp"
	"strings"
)

func main() {
	root := flag.String("root", "..", "desktop application root")
	flag.Parse()

	desktopRoot, err := filepath.Abs(*root)
	if err != nil {
		log.Fatal(err)
	}
	buildDir := filepath.Join(desktopRoot, "build")
	configPath := filepath.Join(buildDir, "config.yml")
	configText := mustRead(configPath)
	version := configVersionFromText(configText)
	if version == "" {
		log.Fatalf("version not found in %s", configPath)
	}
	msixVersion := version + ".0"

	must(writeWindowsInfo(filepath.Join(buildDir, "windows", "info.json"), version))
	replaceFile(filepath.Join(buildDir, "windows", "wails.exe.manifest"), func(text string) string {
		pattern := regexp.MustCompile(`(<assemblyIdentity\s+type="win32"\s+name="com\.hungrym0\.surveycontroller"\s+)version="[^"]+"`)
		return pattern.ReplaceAllString(text, fmt.Sprintf(`${1}version="%s"`, version))
	})
	for _, path := range []string{
		filepath.Join(buildDir, "darwin", "Info.plist"),
		filepath.Join(buildDir, "darwin", "Info.dev.plist"),
	} {
		replaceFile(path, func(text string) string {
			text = replacePlistValue(text, "CFBundleShortVersionString", version)
			return replacePlistValue(text, "CFBundleVersion", version)
		})
	}
	replaceFile(filepath.Join(buildDir, "linux", "nfpm", "nfpm.yaml"), func(text string) string {
		return regexp.MustCompile(`(?m)^version:\s*".*"$`).ReplaceAllString(text, fmt.Sprintf(`version: "%s"`, version))
	})
	for _, path := range []string{
		filepath.Join(buildDir, "windows", "msix", "app_manifest.xml"),
		filepath.Join(buildDir, "windows", "msix", "template.xml"),
	} {
		replaceFile(path, func(text string) string {
			return replaceMSIXPackageVersion(text, msixVersion)
		})
	}
	replaceFile(filepath.Join(buildDir, "windows", "nsis", "wails_tools.nsh"), func(text string) string {
		return regexp.MustCompile(`!define INFO_PRODUCTVERSION "[^"]+"`).ReplaceAllString(text, fmt.Sprintf(`!define INFO_PRODUCTVERSION "%s"`, version))
	})
	replaceFile(filepath.Join(buildDir, "android", "app", "build.gradle"), func(text string) string {
		text = regexp.MustCompile(`(?m)^\s*versionCode\s+\d+`).ReplaceAllString(text, fmt.Sprintf("        versionCode %d", versionCode(version)))
		return regexp.MustCompile(`(?m)^\s*versionName\s+"[^"]+"`).ReplaceAllString(text, fmt.Sprintf(`        versionName "%s"`, version))
	})
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
			return strings.Trim(value, `"'`)
		}
	}
	return ""
}

func versionCode(version string) int {
	parts := strings.Split(version, ".")
	code := 0
	multiplier := 10000
	for i := 0; i < 3 && i < len(parts); i++ {
		var part int
		_, _ = fmt.Sscanf(parts[i], "%d", &part)
		code += part * multiplier
		multiplier /= 100
	}
	if code <= 0 {
		return 1
	}
	return code
}

func replacePlistValue(text, key, value string) string {
	pattern := regexp.MustCompile(`(<key>` + regexp.QuoteMeta(key) + `</key>\s*<string>)[^<]*(</string>)`)
	return pattern.ReplaceAllString(text, fmt.Sprintf("${1}%s${2}", value))
}

func replaceMSIXPackageVersion(text, value string) string {
	identityPattern := regexp.MustCompile(`(<Identity[^>]*\sVersion=")[^"]+(")`)
	text = identityPattern.ReplaceAllString(text, fmt.Sprintf("${1}%s${2}", value))

	packagePattern := regexp.MustCompile(`(<PackageInformation[^>]*\sVersion=")[^"]+(")`)
	return packagePattern.ReplaceAllString(text, fmt.Sprintf("${1}%s${2}", value))
}

func writeWindowsInfo(path string, version string) error {
	type versionInfo struct {
		Fixed map[string]string            `json:"fixed"`
		Info  map[string]map[string]string `json:"info"`
	}
	info := versionInfo{
		Fixed: map[string]string{"file_version": version},
		Info: map[string]map[string]string{
			"0000": {
				"ProductVersion":  version,
				"CompanyName":     "HungryM0",
				"FileDescription": "SurveyController Desktop UI",
				"LegalCopyright":  "(c) 2026, HungryM0",
				"ProductName":     "SurveyController",
				"Comments":        "Stable update feed: https://dl.hungrym0.com/surveycontroller/win/stable/",
			},
		},
	}
	data, err := json.MarshalIndent(info, "", "\t")
	if err != nil {
		return err
	}
	return os.WriteFile(path, append(data, '\n'), 0o644)
}

func replaceFile(path string, replace func(string) string) {
	text := mustRead(path)
	next := replace(text)
	if next == text {
		return
	}
	if err := os.WriteFile(path, []byte(next), 0o644); err != nil {
		log.Fatal(err)
	}
}

func mustRead(path string) string {
	data, err := os.ReadFile(path)
	if err != nil {
		log.Fatal(err)
	}
	return string(data)
}

func must(err error) {
	if err != nil {
		log.Fatal(err)
	}
}
