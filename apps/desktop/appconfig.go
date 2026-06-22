package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"runtime"
	"strings"

	"surveycontroller/surveycore"
	"surveycontroller/surveycore/configio"
)

type AppSettings struct {
	ConfigDirectory    string            `json:"configDirectory"`
	ThemeMode          string            `json:"themeMode"`
	ShowNavigationText bool              `json:"showNavigationText"`
	MicaEnabled        bool              `json:"micaEnabled"`
	Topmost            bool              `json:"topmost"`
	Notifications      bool              `json:"notifications"`
	AutosaveLogCount   int               `json:"autosaveLogCount"`
	RuntimeDefaults    map[string]string `json:"runtimeDefaults,omitempty"`
}

type LoadConfigRequest struct {
	Path string `json:"path"`
}

type SaveConfigRequest struct {
	Path   string                   `json:"path"`
	Config surveycore.RuntimeConfig `json:"config"`
}

type SaveSettingsRequest struct {
	Settings AppSettings `json:"settings"`
}

type ConfigFileState struct {
	Path   string                    `json:"path"`
	Config *surveycore.RuntimeConfig `json:"config,omitempty"`
}

func defaultAppSettings() AppSettings {
	return AppSettings{
		ConfigDirectory:    defaultConfigDirectory(),
		ThemeMode:          "system",
		ShowNavigationText: true,
		MicaEnabled:        true,
		Notifications:      true,
		AutosaveLogCount:   5,
		RuntimeDefaults:    map[string]string{},
	}
}

func loadAppSettings() (AppSettings, error) {
	settings := defaultAppSettings()
	data, err := os.ReadFile(settingsPath())
	if err != nil {
		if os.IsNotExist(err) {
			return settings, nil
		}
		return settings, err
	}
	if err := json.Unmarshal(data, &settings); err != nil {
		return defaultAppSettings(), err
	}
	settings = normalizeAppSettings(settings)
	return settings, nil
}

func saveAppSettings(settings AppSettings) (AppSettings, error) {
	normalized := normalizeAppSettings(settings)
	if err := os.MkdirAll(userConfigRoot(), 0o755); err != nil {
		return normalized, err
	}
	data, err := json.MarshalIndent(normalized, "", "  ")
	if err != nil {
		return normalized, err
	}
	if err := os.WriteFile(settingsPath(), append(data, '\n'), 0o644); err != nil {
		return normalized, err
	}
	return normalized, nil
}

func normalizeAppSettings(settings AppSettings) AppSettings {
	if strings.TrimSpace(settings.ConfigDirectory) == "" {
		settings.ConfigDirectory = defaultConfigDirectory()
	}
	if strings.TrimSpace(settings.ThemeMode) == "" {
		settings.ThemeMode = "system"
	}
	if settings.AutosaveLogCount <= 0 {
		settings.AutosaveLogCount = 5
	}
	if settings.RuntimeDefaults == nil {
		settings.RuntimeDefaults = map[string]string{}
	}
	return settings
}

func defaultRuntimeConfigPath() string {
	return filepath.Join(userConfigRoot(), "config.json")
}

func defaultConfigDirectory() string {
	return filepath.Join(userConfigRoot(), "configs")
}

func settingsPath() string {
	return filepath.Join(userConfigRoot(), "settings.json")
}

func userConfigRoot() string {
	if override := strings.TrimSpace(os.Getenv("SURVEYCONTROLLER_CONFIG_HOME")); override != "" {
		return filepath.Clean(override)
	}
	home, err := os.UserHomeDir()
	if err != nil || strings.TrimSpace(home) == "" {
		return filepath.Join(".", "SurveyController")
	}
	switch runtime.GOOS {
	case "windows":
		if appData := strings.TrimSpace(os.Getenv("APPDATA")); appData != "" {
			return filepath.Join(appData, "SurveyController")
		}
		return filepath.Join(home, "AppData", "Roaming", "SurveyController")
	case "darwin":
		return filepath.Join(home, "Library", "Application Support", "SurveyController")
	default:
		if xdg := strings.TrimSpace(os.Getenv("XDG_CONFIG_HOME")); xdg != "" {
			return filepath.Join(xdg, "SurveyController")
		}
		return filepath.Join(home, ".config", "SurveyController")
	}
}

func configPathFromRequest(path string, settings AppSettings) string {
	cleaned := strings.TrimSpace(path)
	if cleaned != "" {
		return filepath.Clean(cleaned)
	}
	return defaultRuntimeConfigPath()
}

func defaultSavePath(config surveycore.RuntimeConfig, settings AppSettings) string {
	dir := strings.TrimSpace(settings.ConfigDirectory)
	if dir == "" {
		dir = defaultConfigDirectory()
	}
	title := config.SurveyTitle
	if strings.TrimSpace(title) == "" {
		title = "wjx_config"
	}
	return filepath.Join(dir, configio.BuildDefaultConfigFilename(title))
}
