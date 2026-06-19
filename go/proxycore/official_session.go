package proxycore

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"sync"
)

type SessionStore interface {
	LoadSession(ctx context.Context) (RandomIPSession, bool, error)
	SaveSession(ctx context.Context, session RandomIPSession) error
	ClearSession(ctx context.Context, keepDeviceID string) error
}

type DeviceIDGenerator interface {
	DeviceID(ctx context.Context) (string, error)
}

type DeviceIDGeneratorFunc func(ctx context.Context) (string, error)

func (fn DeviceIDGeneratorFunc) DeviceID(ctx context.Context) (string, error) {
	return fn(ctx)
}

type OfficialSessionManagerOptions struct {
	Store             SessionStore
	DeviceIDGenerator DeviceIDGenerator
	InitialSession    RandomIPSession
}

type OfficialSessionManager struct {
	mu                sync.Mutex
	loaded            bool
	session           RandomIPSession
	store             SessionStore
	deviceIDGenerator DeviceIDGenerator
}

func NewOfficialSessionManager(options OfficialSessionManagerOptions) *OfficialSessionManager {
	generator := options.DeviceIDGenerator
	if generator == nil {
		generator = DeviceIDGeneratorFunc(generateDeviceID)
	}
	return &OfficialSessionManager{
		session:           normalizeSession(options.InitialSession),
		loaded:            options.InitialSession.DeviceID != "" || options.InitialSession.UserID > 0,
		store:             options.Store,
		deviceIDGenerator: generator,
	}
}

func (m *OfficialSessionManager) EnsureLoaded(ctx context.Context) (RandomIPSession, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.loaded {
		return m.session, nil
	}
	if m.store != nil {
		session, ok, err := m.store.LoadSession(ctx)
		if err != nil {
			return RandomIPSession{}, err
		}
		if ok {
			m.session = normalizeSession(session)
			m.loaded = true
			if m.session.DeviceID != "" {
				return m.session, nil
			}
		}
	}
	deviceID, err := m.deviceIDGenerator.DeviceID(ctx)
	if err != nil {
		return RandomIPSession{}, err
	}
	m.session.DeviceID = deviceID
	m.session = normalizeSession(m.session)
	m.loaded = true
	if m.store != nil {
		if err := m.store.SaveSession(ctx, m.session); err != nil {
			return RandomIPSession{}, err
		}
	}
	return m.session, nil
}

func (m *OfficialSessionManager) Snapshot(ctx context.Context) (RandomIPSession, error) {
	return m.EnsureLoaded(ctx)
}

func (m *OfficialSessionManager) QuotaSnapshot(ctx context.Context) (QuotaSnapshot, error) {
	session, err := m.EnsureLoaded(ctx)
	if err != nil {
		return QuotaSnapshot{}, err
	}
	return normalizeQuotaSnapshot(session), nil
}

func (m *OfficialSessionManager) RequireAuthenticated(ctx context.Context) (RandomIPSession, error) {
	session, err := m.EnsureLoaded(ctx)
	if err != nil {
		return RandomIPSession{}, err
	}
	if !session.Authenticated() {
		return RandomIPSession{}, RandomIPError{Detail: "not_authenticated"}
	}
	return session, nil
}

func (m *OfficialSessionManager) SetSession(ctx context.Context, session RandomIPSession) (RandomIPSession, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	session = normalizeSession(session)
	m.session = session
	m.loaded = true
	if m.store != nil {
		if err := m.store.SaveSession(ctx, session); err != nil {
			return RandomIPSession{}, err
		}
	}
	return session, nil
}

func (m *OfficialSessionManager) ApplyQuotaPayload(ctx context.Context, payload map[string]any) (RandomIPSession, error) {
	session, err := m.EnsureLoaded(ctx)
	if err != nil {
		return RandomIPSession{}, err
	}
	quota, known := resolveQuotaFromPayload(payload, session)
	session.RemainingQuota = quota.RemainingQuota
	session.TotalQuota = quota.TotalQuota
	session.UsedQuota = quota.UsedQuota
	session.QuotaKnown = known
	return m.SetSession(ctx, session)
}

func (m *OfficialSessionManager) Clear(ctx context.Context) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	keepDeviceID := m.session.DeviceID
	m.session = RandomIPSession{DeviceID: keepDeviceID}
	m.loaded = true
	if m.store != nil {
		return m.store.ClearSession(ctx, keepDeviceID)
	}
	return nil
}

type MemorySessionStore struct {
	mu      sync.Mutex
	session RandomIPSession
	ok      bool
}

func NewMemorySessionStore(session RandomIPSession) *MemorySessionStore {
	return &MemorySessionStore{session: normalizeSession(session), ok: session.DeviceID != "" || session.UserID > 0}
}

func (s *MemorySessionStore) LoadSession(_ context.Context) (RandomIPSession, bool, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.session, s.ok, nil
}

func (s *MemorySessionStore) SaveSession(_ context.Context, session RandomIPSession) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.session = normalizeSession(session)
	s.ok = true
	return nil
}

func (s *MemorySessionStore) ClearSession(_ context.Context, keepDeviceID string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.session = RandomIPSession{DeviceID: keepDeviceID}
	s.ok = keepDeviceID != ""
	return nil
}

func generateDeviceID(_ context.Context) (string, error) {
	var raw [16]byte
	if _, err := rand.Read(raw[:]); err != nil {
		return "", err
	}
	return "sc-go-" + hex.EncodeToString(raw[:]), nil
}
