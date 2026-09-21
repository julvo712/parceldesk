package server

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"github.com/jackc/pgx/v5"
	"github.com/parceldesk/operations/internal/store"
	"sync"
	"time"
)

type lease struct {
	cancel context.CancelFunc
	done   chan struct{}
}
type Scenarios struct {
	store  *store.Store
	mu     sync.Mutex
	opMu   sync.Mutex
	leases map[string]lease
}

func (s *Scenarios) Active(ctx context.Context, run string) string {
	var name string
	e := s.store.DB.QueryRow(ctx, `SELECT CASE WHEN scenario_expires_at>now() THEN scenario ELSE 'healthy' END FROM runs WHERE id=$1`, run).Scan(&name)
	if e != nil {
		return "healthy"
	}
	return name
}
func (s *Scenarios) Reset(ctx context.Context, run string) error {
	s.opMu.Lock()
	defer s.opMu.Unlock()
	return s.reset(ctx, run)
}
func (s *Scenarios) reset(ctx context.Context, run string) error {
	s.mu.Lock()
	l, ok := s.leases[run]
	if ok {
		delete(s.leases, run)
		l.cancel()
	}
	s.mu.Unlock()
	if ok {
		select {
		case <-l.done:
		case <-ctx.Done():
			return ctx.Err()
		}
	}
	_, e := s.store.DB.Exec(ctx, `UPDATE runs SET scenario='healthy',scenario_expires_at=NULL WHERE id=$1`, run)
	return e
}
func (s *Scenarios) Activate(ctx context.Context, run, name string, ttl int) (map[string]any, error) {
	s.opMu.Lock()
	defer s.opMu.Unlock()
	allowed := map[string]bool{"healthy": true, "supplier_injection": true, "prompt_overstrict": true, "llm_boundary_delay": true, "db_lock": true, "shipping_mapping_bug": true, "cpu_regression": true, "cpu_pressure": true, "tool_retry_loop": true, "guard_unavailable": true, "ui_render_error": true}
	if !allowed[name] || ttl < 1 || ttl > 300 {
		return nil, errors.New("invalid scenario or TTL (1..300 seconds)")
	}
	if e := s.reset(ctx, run); e != nil {
		return nil, e
	}
	now := time.Now().UTC()
	expiry := now.Add(time.Duration(ttl) * time.Second)
	tag, e := s.store.DB.Exec(ctx, `UPDATE runs SET scenario=$2,scenario_expires_at=$3 WHERE id=$1`, run, name, expiry)
	if e != nil {
		return nil, e
	}
	if tag.RowsAffected() != 1 {
		return nil, errors.New("run not found")
	}
	lc, cancel := context.WithDeadline(context.Background(), expiry)
	done := make(chan struct{})
	var tx pgx.Tx
	if name == "db_lock" {
		tx, e = s.store.DB.Begin(lc)
		if e == nil {
			_, e = tx.Exec(lc, `SELECT available FROM stock WHERE run_id=$1 AND sku='ARC-01' FOR UPDATE`, run)
		}
		if e != nil {
			cancel()
			if tx != nil {
				_ = tx.Rollback(context.Background())
			}
			_ = s.reset(context.Background(), run)
			return nil, e
		}
	}
	s.mu.Lock()
	s.leases[run] = lease{cancel, done}
	s.mu.Unlock()
	go func() {
		defer close(done)
		defer cancel()
		if tx != nil {
			defer tx.Rollback(context.Background())
		}
		if name == "cpu_pressure" {
			cpuWork(lc, time.Duration(ttl)*time.Second)
		} else {
			<-lc.Done()
		}
		cleanup, c := context.WithTimeout(context.Background(), 3*time.Second)
		defer c()
		_, _ = s.store.DB.Exec(cleanup, `UPDATE runs SET scenario='healthy',scenario_expires_at=NULL WHERE id=$1 AND scenario_expires_at=$2`, run, expiry)
	}()
	return map[string]any{"demo_run_id": run, "scenario": name, "activated_at": now.Format(time.RFC3339Nano), "expires_at": expiry.Format(time.RFC3339Nano), "target_service": "operations"}, nil
}

// Hashes real data repeatedly; the bounded deadline and cancellation apply independently of the requester.
func cpuWork(ctx context.Context, duration time.Duration) string {
	deadline := time.Now().Add(duration)
	buf := make([]byte, 65536)
	var sum [32]byte
	for time.Now().Before(deadline) {
		select {
		case <-ctx.Done():
			return hex.EncodeToString(sum[:])
		default:
		}
		for i := 0; i < 64; i++ {
			sum = sha256.Sum256(buf)
			copy(buf, sum[:])
		}
	}
	return hex.EncodeToString(sum[:])
}

// Recover resets leases whose owning process no longer exists after startup.
// This deployment has a single operations instance and run-scoped fault ownership.
func (s *Scenarios) Recover(ctx context.Context) error {
	_, err := s.store.DB.Exec(ctx, `UPDATE runs SET scenario='healthy',scenario_expires_at=NULL WHERE scenario<>'healthy' OR scenario_expires_at IS NOT NULL`)
	return err
}
func (s *Scenarios) Close(ctx context.Context) error {
	s.mu.Lock()
	runs := make([]string, 0, len(s.leases))
	for run := range s.leases {
		runs = append(runs, run)
	}
	s.mu.Unlock()
	var err error
	for _, run := range runs {
		err = errors.Join(err, s.Reset(ctx, run))
	}
	return err
}
