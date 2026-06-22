package main

import (
	"embed"
	"log"

	"github.com/wailsapp/wails/v3/pkg/application"
)

// Wails uses Go's `embed` package to embed the frontend files into the binary.
// Any files in the frontend/dist folder will be embedded into the binary and
// made available to the frontend.
// See https://pkg.go.dev/embed for more information.

//go:embed all:frontend/dist
var assets embed.FS

func main() {
	service := NewAppService()
	app := application.New(application.Options{
		Name:        "SurveyController",
		Description: "SurveyController Desktop UI",
		Services: []application.Service{
			application.NewService(service),
		},
		Assets: application.AssetOptions{
			Handler: application.AssetFileServerFS(assets),
		},
		Mac: application.MacOptions{
			ApplicationShouldTerminateAfterLastWindowClosed: true,
		},
	})

	window := app.Window.NewWithOptions(application.WebviewWindowOptions{
		Title:     "SurveyController",
		Width:     1180,
		Height:    720,
		MinWidth:  900,
		MinHeight: 560,
		Frameless: true,
		BackgroundColour: application.NewRGBA(0, 0, 0, 0),
		URL:              "/",
		Mac: application.MacWindow{
			TitleBar: application.MacTitleBar{
				AppearsTransparent: true,
				HideTitle:          true,
				FullSizeContent:    true,
			},
			Backdrop:                application.MacBackdropTranslucent,
			InvisibleTitleBarHeight: 44,
		},
		Windows: application.WindowsWindow{
			DisableFramelessWindowDecorations: false,
		},
	})
	window.Center()
	window.Show()

	err := app.Run()
	if err != nil {
		log.Fatal(err)
	}
}
