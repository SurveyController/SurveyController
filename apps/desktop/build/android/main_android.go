//go:build android

package main

import "github.com/wailsapp/wails/v3/pkg/application"

func init() {

	application.RegisterAndroidMain(main)
}
