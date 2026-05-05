package main

import (
	"errors"
	"log"
	"net"
	"net/http"
	"os"
	"strconv"
	"strings"
)

func newMux(svc *poolService) *http.ServeMux {
	mux := http.NewServeMux()
	mux.HandleFunc("/config/apply", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			writeJSON(w, http.StatusMethodNotAllowed, errorResponse{Error: "method not allowed"})
			return
		}
		var request proxyConfig
		if err := readJSON(r, &request); err != nil {
			writeJSON(w, http.StatusBadRequest, errorResponse{Error: err.Error()})
			return
		}
		applied := svc.applyConfig(request)
		writeJSON(w, http.StatusOK, applied)
	})
	mux.HandleFunc("/pool/prefetch", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			writeJSON(w, http.StatusMethodNotAllowed, errorResponse{Error: "method not allowed"})
			return
		}
		var request prefetchRequest
		if err := readJSON(r, &request); err != nil {
			writeJSON(w, http.StatusBadRequest, errorResponse{Error: err.Error()})
			return
		}
		if err := svc.prefetch(request.ExpectedCount); err != nil {
			writeJSON(w, http.StatusBadGateway, errorResponse{Error: err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, svc.status())
	})
	mux.HandleFunc("/lease/acquire", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			writeJSON(w, http.StatusMethodNotAllowed, errorResponse{Error: "method not allowed"})
			return
		}
		var request acquireRequest
		if err := readJSON(r, &request); err != nil {
			writeJSON(w, http.StatusBadRequest, errorResponse{Error: err.Error()})
			return
		}
		lease, err := svc.acquireLease(request.ThreadName, request.Wait)
		if err != nil {
			writeJSON(w, http.StatusBadGateway, errorResponse{Error: err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, acquireResponse{Lease: lease})
	})
	mux.HandleFunc("/lease/release", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			writeJSON(w, http.StatusMethodNotAllowed, errorResponse{Error: "method not allowed"})
			return
		}
		var request releaseRequest
		if err := readJSON(r, &request); err != nil {
			writeJSON(w, http.StatusBadRequest, errorResponse{Error: err.Error()})
			return
		}
		lease := svc.releaseLease(request.ThreadName, request.Requeue)
		writeJSON(w, http.StatusOK, acquireResponse{Lease: lease})
	})
	mux.HandleFunc("/lease/mark-success", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			writeJSON(w, http.StatusMethodNotAllowed, errorResponse{Error: "method not allowed"})
			return
		}
		var request addressRequest
		if err := readJSON(r, &request); err != nil {
			writeJSON(w, http.StatusBadRequest, errorResponse{Error: err.Error()})
			return
		}
		svc.markSuccess(request.ProxyAddress, request.ThreadName)
		writeJSON(w, http.StatusOK, svc.status())
	})
	mux.HandleFunc("/lease/mark-bad", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			writeJSON(w, http.StatusMethodNotAllowed, errorResponse{Error: "method not allowed"})
			return
		}
		var request markBadRequest
		if err := readJSON(r, &request); err != nil {
			writeJSON(w, http.StatusBadRequest, errorResponse{Error: err.Error()})
			return
		}
		svc.markBad(request.ProxyAddress, request.CooldownSeconds, request.ThreadName)
		writeJSON(w, http.StatusOK, svc.status())
	})
	mux.HandleFunc("/health/check", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			writeJSON(w, http.StatusMethodNotAllowed, errorResponse{Error: "method not allowed"})
			return
		}
		var request healthCheckRequest
		if err := readJSON(r, &request); err != nil {
			writeJSON(w, http.StatusBadRequest, errorResponse{Error: err.Error()})
			return
		}
		writeJSON(w, http.StatusOK, healthResponse{
			Responsive: svc.checkHealth(request.ProxyAddress, request.SkipForOfficial),
		})
	})
	mux.HandleFunc("/status", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			writeJSON(w, http.StatusMethodNotAllowed, errorResponse{Error: "method not allowed"})
			return
		}
		writeJSON(w, http.StatusOK, svc.status())
	})
	return mux
}

func resolveServerConfig() (string, int) {
	baseURL := strings.TrimSpace(os.Getenv("SURVEY_PROXY_BASE_URL"))
	if baseURL == "" {
		baseURL = "http://127.0.0.1:9010"
	}
	portText := strings.TrimSpace(os.Getenv("SURVEY_PROXY_PORT"))
	if portText == "" {
		log.Fatal("SURVEY_PROXY_PORT 未设置")
	}
	port, err := strconv.Atoi(portText)
	if err != nil || port <= 0 {
		log.Fatalf("SURVEY_PROXY_PORT 非法: %s", portText)
	}
	return baseURL, port
}

func main() {
	baseURL, port := resolveServerConfig()
	svc := newPoolService(baseURL)
	server := &http.Server{
		Addr:         net.JoinHostPort("127.0.0.1", strconv.Itoa(port)),
		Handler:      newMux(svc),
		ReadTimeout:  serverReadTimeout,
		WriteTimeout: serverWriteTimeout,
		IdleTimeout:  serverIdleTimeout,
	}

	log.Printf("proxy_service listening on 127.0.0.1:%d base=%s", port, baseURL)
	if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
		log.Fatal(err)
	}
}
