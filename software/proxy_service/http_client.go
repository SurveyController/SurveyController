package main

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
)

func (svc *poolService) httpGet(targetURL string, headers map[string]string) (*http.Response, []byte, error) {
	request, err := http.NewRequestWithContext(context.Background(), http.MethodGet, targetURL, nil)
	if err != nil {
		return nil, nil, err
	}
	for key, value := range headers {
		request.Header.Set(key, value)
	}
	response, err := svc.httpClient.Do(request)
	if err != nil {
		return nil, nil, err
	}
	defer response.Body.Close()
	body, err := io.ReadAll(response.Body)
	if err != nil {
		return nil, nil, err
	}
	return response, body, nil
}

func (svc *poolService) httpPostJSON(targetURL string, payload any, headers map[string]string) (*http.Response, []byte, error) {
	body, err := json.Marshal(payload)
	if err != nil {
		return nil, nil, err
	}
	request, err := http.NewRequestWithContext(
		context.Background(),
		http.MethodPost,
		targetURL,
		bytes.NewReader(body),
	)
	if err != nil {
		return nil, nil, err
	}
	for key, value := range headers {
		request.Header.Set(key, value)
	}
	response, err := svc.httpClient.Do(request)
	if err != nil {
		return nil, nil, err
	}
	defer response.Body.Close()
	responseBody, err := io.ReadAll(response.Body)
	if err != nil {
		return nil, nil, err
	}
	return response, responseBody, nil
}
