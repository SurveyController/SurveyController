package main

import (
	"flag"
	"image"
	"image/png"
	"io"
	"log"
	"os"
	"path/filepath"
)

func main() {
	root := flag.String("root", "..", "desktop application root")
	flag.Parse()

	desktopRoot, err := filepath.Abs(*root)
	if err != nil {
		log.Fatal(err)
	}
	repoRoot := filepath.Clean(filepath.Join(desktopRoot, "..", ".."))
	assetsDir := filepath.Join(repoRoot, "assets")
	buildDir := filepath.Join(desktopRoot, "build")

	sourcePNG := filepath.Join(assetsDir, "icon.png")
	sourceICO := filepath.Join(assetsDir, "icon.ico")
	sourceSVG := filepath.Join(assetsDir, "icon.svg")

	must(copyFile(sourcePNG, filepath.Join(buildDir, "appicon.png")))
	must(copyFile(sourceICO, filepath.Join(buildDir, "windows", "icon.ico")))
	must(copyFile(sourceSVG, filepath.Join(buildDir, "appicon.icon", "Assets", "wails_icon_vector.svg")))
	must(copyFile(sourcePNG, filepath.Join(desktopRoot, "frontend", "public", "appicon.png")))

	source, err := loadPNG(sourcePNG)
	must(err)

	msixAssets := filepath.Join(buildDir, "windows", "msix", "Assets")
	must(saveResizedPNG(source, 50, 50, filepath.Join(msixAssets, "StoreLogo.png")))
	must(saveResizedPNG(source, 44, 44, filepath.Join(msixAssets, "Square44x44Logo.png")))
	must(saveResizedPNG(source, 150, 150, filepath.Join(msixAssets, "Square150x150Logo.png")))
	must(saveResizedPNG(source, 310, 150, filepath.Join(msixAssets, "Wide310x150Logo.png")))
	must(saveResizedPNG(source, 620, 300, filepath.Join(msixAssets, "SplashScreen.png")))
	must(saveResizedPNG(source, 256, 256, filepath.Join(msixAssets, "AppIcon.png")))

	androidRes := filepath.Join(buildDir, "android", "app", "src", "main", "res")
	androidSizes := map[string]int{
		"mipmap-mdpi":    48,
		"mipmap-hdpi":    72,
		"mipmap-xhdpi":   96,
		"mipmap-xxhdpi":  144,
		"mipmap-xxxhdpi": 192,
	}
	for dir, size := range androidSizes {
		targetDir := filepath.Join(androidRes, dir)
		must(saveResizedPNG(source, size, size, filepath.Join(targetDir, "ic_launcher.png")))
		must(saveResizedPNG(source, size, size, filepath.Join(targetDir, "ic_launcher_round.png")))
	}
}

func must(err error) {
	if err != nil {
		log.Fatal(err)
	}
}

func copyFile(source, destination string) error {
	if err := os.MkdirAll(filepath.Dir(destination), 0o755); err != nil {
		return err
	}

	input, err := os.Open(source)
	if err != nil {
		return err
	}
	defer input.Close()

	output, err := os.Create(destination)
	if err != nil {
		return err
	}
	defer output.Close()

	_, err = io.Copy(output, input)
	return err
}

func loadPNG(path string) (image.Image, error) {
	file, err := os.Open(path)
	if err != nil {
		return nil, err
	}
	defer file.Close()

	return png.Decode(file)
}

func saveResizedPNG(source image.Image, width, height int, destination string) error {
	if err := os.MkdirAll(filepath.Dir(destination), 0o755); err != nil {
		return err
	}

	target := image.NewRGBA(image.Rect(0, 0, width, height))
	bounds := source.Bounds()
	sourceWidth := bounds.Dx()
	sourceHeight := bounds.Dy()
	for y := 0; y < height; y++ {
		sourceY := bounds.Min.Y + y*sourceHeight/height
		for x := 0; x < width; x++ {
			sourceX := bounds.Min.X + x*sourceWidth/width
			target.Set(x, y, source.At(sourceX, sourceY))
		}
	}

	file, err := os.Create(destination)
	if err != nil {
		return err
	}
	defer file.Close()

	return png.Encode(file, target)
}
