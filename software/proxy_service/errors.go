package main

import (
	"fmt"
	"strings"
)

func (e *upstreamError) Error() string {
	if e == nil {
		return ""
	}
	if strings.TrimSpace(e.Message) != "" {
		return e.Message
	}
	return fmt.Sprintf("upstream error (%d)", e.StatusCode)
}

func (e *authError) Error() string {
	if e == nil {
		return ""
	}
	return strings.TrimSpace(e.Detail)
}
