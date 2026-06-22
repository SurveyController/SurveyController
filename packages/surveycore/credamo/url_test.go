package credamo

import "testing"

func TestShortURLFromURL(t *testing.T) {
	tests := map[string]string{
		"https://www.credamo.com/s/A73QR3ano":              "A73QR3ano",
		"https://www.credamo.com/answer.html#/s/demo_":     "demo_",
		"https://www.credamo.com/answer.html#/s/demo_?x=1": "demo_",
	}
	for rawURL, want := range tests {
		got, err := shortURLFromURL(rawURL)
		if err != nil {
			t.Fatalf("shortURLFromURL(%q) returned error: %v", rawURL, err)
		}
		if got != want {
			t.Fatalf("shortURLFromURL(%q) = %q, want %q", rawURL, got, want)
		}
	}
}

func TestNoAuthShortURL(t *testing.T) {
	got, err := noAuthShortURL("demo_")
	if err != nil {
		t.Fatal(err)
	}
	if got != "demoano" {
		t.Fatalf("got %q", got)
	}

	got, err = noAuthShortURL("demoano")
	if err != nil {
		t.Fatal(err)
	}
	if got != "demoano" {
		t.Fatalf("got %q", got)
	}

	if _, err := noAuthShortURL("demo"); err == nil {
		t.Fatal("expected error")
	}
}
