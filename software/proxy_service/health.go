package main

import (
	"net/http"
	"net/url"
)

func probeProxyHealth(proxyAddress string) bool {
	proxyURL, err := url.Parse(proxyAddress)
	if err != nil {
		return false
	}
	transport := &http.Transport{
		Proxy:                 http.ProxyURL(proxyURL),
		DisableKeepAlives:     true,
		ResponseHeaderTimeout: proxyHealthCheckTimeout,
	}
	client := &http.Client{
		Timeout:   proxyHealthCheckTimeout,
		Transport: transport,
	}
	response, err := client.Get(proxyHealthCheckURL)
	if err != nil {
		return false
	}
	defer response.Body.Close()
	return response.StatusCode < 400
}
