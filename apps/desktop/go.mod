module github.com/hungrym0/SurveyController/apps/desktop

go 1.26

require github.com/wailsapp/wails/v3 v3.0.0-alpha2.104

require (
	github.com/xuri/excelize/v2 v2.10.1
	surveycontroller/proxycore v0.0.0
	surveycontroller/surveycore v0.0.0
)

replace surveycontroller/proxycore => ../../packages/proxycore

replace surveycontroller/surveycore => ../../packages/surveycore

require (
	github.com/adrg/xdg v0.5.3 // indirect
	github.com/coder/websocket v1.8.14 // indirect
	github.com/ebitengine/purego v0.9.1 // indirect
	github.com/go-ole/go-ole v1.3.0 // indirect
	github.com/godbus/dbus/v5 v5.2.2 // indirect
	github.com/jchv/go-winloader v0.0.0-20250406163304-c1995be93bd1 // indirect
	github.com/mattn/go-colorable v0.1.14 // indirect
	github.com/mattn/go-isatty v0.0.20 // indirect
	github.com/richardlehane/mscfb v1.0.6 // indirect
	github.com/richardlehane/msoleps v1.0.6 // indirect
	github.com/tiendc/go-deepcopy v1.7.2 // indirect
	github.com/wailsapp/wails/webview2 v1.0.24 // indirect
	github.com/xuri/efp v0.0.1 // indirect
	github.com/xuri/nfp v0.0.2-0.20250530014748-2ddeb826f9a9 // indirect
	golang.org/x/crypto v0.50.0 // indirect
	golang.org/x/net v0.53.0 // indirect
	golang.org/x/sys v0.43.0 // indirect
	golang.org/x/text v0.37.0 // indirect
)
