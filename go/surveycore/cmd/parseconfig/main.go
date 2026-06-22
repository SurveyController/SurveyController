package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"time"

	"surveycontroller/surveycore"
)

type configFile struct {
	URL string `json:"url"`
}

type summary struct {
	Provider      string         `json:"provider"`
	Title         string         `json:"title"`
	QuestionCount int            `json:"question_count"`
	Types         map[string]int `json:"types"`
	FirstQuestion any            `json:"first_question,omitempty"`
}

func main() {
	configPath := flag.String("config", "", "SurveyController config JSON path")
	timeout := flag.Duration("timeout", 30*time.Second, "parse timeout")
	flag.Parse()

	if *configPath == "" {
		fmt.Fprintln(os.Stderr, "missing -config")
		os.Exit(2)
	}
	data, err := os.ReadFile(*configPath)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	var cfg configFile
	if err := json.Unmarshal(data, &cfg); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}

	ctx, cancel := context.WithTimeout(context.Background(), *timeout)
	defer cancel()

	definition, err := surveycore.Parse(ctx, cfg.URL)
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	types := map[string]int{}
	for _, question := range definition.Questions {
		types[question.TypeCode]++
	}
	out := summary{
		Provider:      definition.Provider,
		Title:         definition.Title,
		QuestionCount: len(definition.Questions),
		Types:         types,
	}
	if len(definition.Questions) > 0 {
		out.FirstQuestion = definition.Questions[0]
	}
	encoded, err := json.MarshalIndent(out, "", "  ")
	if err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
	fmt.Println(string(encoded))
}
