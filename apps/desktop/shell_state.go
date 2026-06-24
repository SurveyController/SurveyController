package main

func initialShellState(version string) ShellState {
	return ShellState{
		AppTitle:    "SurveyController",
		AppVersion:  version,
		ThemeMode:   "system",
		CurrentPage: "dashboard",
		TopNav: []NavItem{
			{ID: "dashboard", Label: "概览", Icon: "home", Section: "top", Selected: true},
			{ID: "runtime", Label: "运行参数", Icon: "settings", Section: "top"},
			{ID: "strategy", Label: "题目策略", Icon: "flow", Section: "top"},
			{ID: "reverse-fill", Label: "反填", Icon: "refresh", Section: "top"},
			{ID: "logs", Label: "日志", Icon: "document", Section: "top"},
		},
		BottomNav: []NavItem{
			{ID: "community", Label: "社区", Icon: "chat", Section: "bottom"},
			{ID: "settings", Label: "设置", Icon: "sliders", Section: "bottom"},
			{ID: "more", Label: "更多", Icon: "grid", Section: "bottom"},
		},
		Dashboard: DashboardState{
			SurveyTitle:        "未命名问卷",
			TargetCount:        1,
			ThreadCount:        1,
			RandomIPQuotaLabel: "未同步",
			RandomIPStatus:     "未连接代理服务",
			ProxySource:        "默认",
			ProgressTarget:     1,
			StatusText:         "等待配置",
			PlatformLabel:      "问卷星",
			Metrics: []PageMetric{
				{Label: "已解析题目", Value: "0"},
				{Label: "当前并发", Value: "1"},
				{Label: "随机 IP", Value: "未启用"},
				{Label: "反填", Value: "未启用"},
			},
			QuickActions: []QuickAction{
				{ID: "parse", Label: "解析问卷", Icon: "scan", Emphasis: "primary"},
				{ID: "load-config", Label: "载入配置", Icon: "folder"},
				{ID: "save-config", Label: "保存配置", Icon: "save"},
				{ID: "open-runtime", Label: "高级参数", Icon: "tune"},
			},
			QuestionRows: []QuestionRow{},
			SessionRows:  []SessionRow{},
		},
		RuntimeGroups:   []SettingsGroup{},
		StrategyRules:   []StrategyRule{},
		DimensionGroups: []string{},
		ReverseFillPlan: []ReverseFillRow{},
		LogLines:        []string{},
		CommunityItems:  []string{},
		AboutItems: []PageMetric{
			{Label: "版本", Value: version},
			{Label: "前端栈", Value: "React + react-windows-ui + Wails v3"},
			{Label: "桌面壳", Value: "Wails v3"},
		},
		DonateItems:  []PageMetric{},
		IPUsageItems: []PageMetric{},
		SettingsGroups: []SettingsGroup{
			{
				Title: "界面外观",
				Fields: []SettingField{
					{ID: "theme", Label: "主题", Kind: "select", Value: "system", Options: []string{"system", "light", "dark"}},
					{ID: "nav-text", Label: "显示导航文本", Kind: "toggle", Value: "true"},
					{ID: "mica", Label: "启用 Mica 背景", Kind: "toggle", Value: "true"},
				},
			},
			{
				Title: "行为设置",
				Fields: []SettingField{
					{ID: "topmost", Label: "窗口置顶", Kind: "toggle", Value: "false"},
					{ID: "notifications", Label: "系统通知", Kind: "toggle", Value: "true"},
					{ID: "autosave", Label: "自动保存日志", Kind: "select", Value: "5", Options: []string{"3", "5", "10"}},
					{ID: "config-directory", Label: "配置目录", Kind: "text"},
				},
			},
		},
	}
}
