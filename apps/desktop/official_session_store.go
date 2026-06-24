package main

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"

	"surveycontroller/proxycore"
)

type officialSessionFileStore struct {
	path string
}

func newOfficialSessionFileStore() officialSessionFileStore {
	return officialSessionFileStore{path: filepath.Join(userConfigRoot(), "random_ip_session.json")}
}

func (s officialSessionFileStore) LoadSession(_ context.Context) (proxycore.RandomIPSession, bool, error) {
	data, err := os.ReadFile(s.path)
	if err != nil {
		if os.IsNotExist(err) {
			return proxycore.RandomIPSession{}, false, nil
		}
		return proxycore.RandomIPSession{}, false, err
	}
	var session proxycore.RandomIPSession
	if err := json.Unmarshal(data, &session); err != nil {
		return proxycore.RandomIPSession{}, false, err
	}
	return session, session.DeviceID != "" || session.UserID > 0, nil
}

func (s officialSessionFileStore) SaveSession(_ context.Context, session proxycore.RandomIPSession) error {
	if err := os.MkdirAll(filepath.Dir(s.path), 0o755); err != nil {
		return err
	}
	data, err := json.MarshalIndent(session, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(s.path, append(data, '\n'), 0o644)
}

func (s officialSessionFileStore) ClearSession(ctx context.Context, keepDeviceID string) error {
	return s.SaveSession(ctx, proxycore.RandomIPSession{DeviceID: keepDeviceID})
}
