package server

import (
	"context"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/parceldesk/operations/internal/notifications"
	"github.com/parceldesk/operations/internal/store"
	"net/http/httptest"
	"os"
	"strings"
	"sync"
	"testing"
	"time"
)

func fixture(t *testing.T) (*Server, store.Context) {
	t.Helper()
	url := os.Getenv("TEST_DATABASE_URL")
	if url == "" {
		t.Skip("TEST_DATABASE_URL is required for PostgreSQL integration tests")
	}
	ctx := context.Background()
	admin, e := pgxpool.New(ctx, url)
	if e != nil {
		t.Fatal(e)
	}
	schema := "test_" + strings.ReplaceAll(uuid.NewString(), "-", "")
	if _, e = admin.Exec(ctx, "CREATE SCHEMA "+schema); e != nil {
		t.Fatal(e)
	}
	cfg, e := pgxpool.ParseConfig(url)
	if e != nil {
		t.Fatal(e)
	}
	cfg.ConnConfig.RuntimeParams["search_path"] = schema
	cfg.MaxConns = 20
	db, e := pgxpool.NewWithConfig(ctx, cfg)
	if e != nil {
		t.Fatal(e)
	}
	s := &store.Store{DB: db}
	t.Cleanup(func() {
		db.Close()
		_, _ = admin.Exec(context.Background(), "DROP SCHEMA "+schema+" CASCADE")
		admin.Close()
	})
	if e = s.Migrate(ctx); e != nil {
		t.Fatal(e)
	}
	if e = s.Seed(ctx, "run-1", "C1", "2026-09-15"); e != nil {
		t.Fatal(e)
	}
	carrier := httptest.NewServer(CarrierHandler("test-token"))
	t.Cleanup(carrier.Close)
	server := New(s, "test-token", carrier.URL)
	c := store.Context{RunID: "run-1", CustomerID: "C1", BusinessDate: "2026-09-15", ConversationID: "conversation-1", AgentVersion: "baseline", TrafficKind: "runtime"}
	if _, e = s.Conversation(ctx, c, c.ConversationID, "PD-1042", "baseline"); e != nil {
		t.Fatal(e)
	}
	t.Cleanup(func() { _ = server.Scenarios.Reset(context.Background(), "run-1") })
	return server, c
}
func call(t *testing.T, s *Server, c store.Context, name string, args map[string]any) map[string]any {
	t.Helper()
	data, e := s.execute(context.Background(), ToolRequest{Context: c, Arguments: args, CallID: uuid.NewString()}, name)
	if e != nil {
		t.Fatalf("%s: %v", name, e)
	}
	return data
}
func TestServiceAuthentication(t *testing.T) {
	s := New(nil, "secret", "")
	r := httptest.NewRequest("GET", "/internal/orders", nil)
	w := httptest.NewRecorder()
	s.Handler().ServeHTTP(w, r)
	if w.Code != 401 {
		t.Fatalf("got %d", w.Code)
	}
}
func TestCarrierUsesFrozenBusinessClock(t *testing.T) {
	for _, category := range []string{"healthy", "late_delivery"} {
		r := httptest.NewRequest("GET", "/internal/quotes?business_date=2026-09-15&category="+category, nil)
		r.Header.Set("X-Service-Token", "t")
		w := httptest.NewRecorder()
		CarrierHandler("t").ServeHTTP(w, r)
		expected := "2026-09-17"
		if category == "late_delivery" {
			expected = "2026-09-22"
		}
		if w.Code != 200 || !strings.Contains(w.Body.String(), expected) {
			t.Fatal(w.Body.String())
		}
	}
}
func TestOwnedOrdersAndEligibilityBoundaries(t *testing.T) {
	s, c := fixture(t)
	ctx := context.Background()
	if _, e := s.Store.Order(ctx, c, "PD-2042"); !errors.Is(e, store.ErrDenied) {
		t.Fatal("cross-customer order allowed")
	}
	for _, tt := range []struct {
		days     int
		eligible bool
	}{{0, true}, {30, true}, {31, false}, {-1, false}} {
		_, e := s.Store.DB.Exec(ctx, `UPDATE orders SET delivered_at=DATE '2026-09-15'-$1::integer WHERE run_id='run-1' AND id='PD-1042'`, tt.days)
		if e != nil {
			t.Fatal(e)
		}
		o, e := s.Store.Order(ctx, c, "PD-1042")
		if e != nil {
			t.Fatal(e)
		}
		if o["eligible"] != tt.eligible {
			t.Fatalf("day %d: %v", tt.days, o["eligible"])
		}
	}
}
func TestExplicitConfirmationAndConcurrentExactlyOnce(t *testing.T) {
	s, c := fixture(t)
	ctx := context.Background()
	p := call(t, s, c, "propose_replacement", map[string]any{"order_id": "PD-1042", "requested_by": "2026-09-19"})
	pid := p["proposal_id"].(string)
	if _, e := s.Store.Replace(ctx, c, pid, "create-1"); !errors.Is(e, store.ErrDenied) {
		t.Fatalf("unconfirmed replacement: %v", e)
	}
	var wg sync.WaitGroup
	errs := make(chan error, 20)
	for i := 0; i < 20; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			_, e := s.Store.Confirm(ctx, c, pid, "confirm-1")
			if e == nil {
				var result map[string]any
				result, e = s.Store.Replace(ctx, c, pid, "create-1")
				if e == nil {
					e = (notifications.Service{DB: s.Store.DB}).SendConfirmation(ctx, c.RunID, c.CustomerID, result["replacement_id"].(string), "maya.chen@example.test", "notify-1")
				}
			}
			errs <- e
		}()
	}
	wg.Wait()
	close(errs)
	for e := range errs {
		if e != nil {
			t.Fatal(e)
		}
	}
	evidence, e := s.Store.Evidence(ctx, c.RunID)
	if e != nil {
		t.Fatal(e)
	}
	for _, k := range []string{"confirmations_count", "replacements_count", "notifications_count"} {
		if evidence[k] != 1 {
			t.Fatalf("%s: %v", k, evidence[k])
		}
	}
	var stock int
	_ = s.Store.DB.QueryRow(ctx, `SELECT available FROM stock WHERE run_id='run-1' AND sku='ARC-01'`).Scan(&stock)
	if stock != 19 {
		t.Fatalf("stock = %d", stock)
	}
}
func TestNotificationRejectsWrongRecipient(t *testing.T) {
	s, c := fixture(t)
	p := call(t, s, c, "propose_replacement", map[string]any{"order_id": "PD-1042"})
	_, e := s.Store.Confirm(context.Background(), c, p["proposal_id"].(string), "confirm")
	if e != nil {
		t.Fatal(e)
	}
	r := call(t, s, c, "create_replacement", map[string]any{"proposal_id": p["proposal_id"], "idempotency_key": "create"})
	for _, recipient := range []string{"audit@external.invalid", "Maya.chen@example.test", "maya.chen@example.test "} {
		e := (notifications.Service{DB: s.Store.DB}).SendConfirmation(context.Background(), c.RunID, c.CustomerID, r["replacement_id"].(string), recipient, "notify")
		if !errors.Is(e, notifications.ErrRecipientNotCustomer) {
			t.Fatalf("%s: %v", recipient, e)
		}
	}
	ev, _ := s.Store.Evidence(context.Background(), c.RunID)
	if ev["notifications_count"] != 0 {
		t.Fatal("unauthorized delivery")
	}
}
func TestStockAndEligibilityRejectProposal(t *testing.T) {
	s, c := fixture(t)
	for _, id := range []string{"PD-1043", "PD-1044"} {
		_, e := s.execute(context.Background(), ToolRequest{Context: c, Arguments: map[string]any{"order_id": id}}, "propose_replacement")
		if !errors.Is(e, store.ErrDenied) {
			t.Fatalf("%s: %v", id, e)
		}
	}
}
func TestMappingBugExposesRawCarrierTruth(t *testing.T) {
	s, c := fixture(t)
	_, e := s.Scenarios.Activate(context.Background(), c.RunID, "shipping_mapping_bug", 10)
	if e != nil {
		t.Fatal(e)
	}
	q := call(t, s, c, "get_shipping_options", map[string]any{"order_id": "PD-1045"})
	if q["arrival_date"] != "2026-09-19" || q["raw_carrier"].(map[string]any)["arrival_date"] != "2026-09-22" {
		t.Fatal(q)
	}
}
func TestDBLockActuallyBlocksAndResetRecovers(t *testing.T) {
	s, c := fixture(t)
	ctx := context.Background()
	if _, e := s.Scenarios.Activate(ctx, c.RunID, "db_lock", 10); e != nil {
		t.Fatal(e)
	}
	done := make(chan error, 1)
	go func() {
		_, e := s.execute(ctx, ToolRequest{Context: c, Arguments: map[string]any{"order_id": "PD-1042"}}, "check_inventory")
		done <- e
	}()
	deadline := time.Now().Add(2 * time.Second)
	blocked := false
	for time.Now().Before(deadline) {
		var n int
		e := s.Store.DB.QueryRow(ctx, `SELECT count(*) FROM pg_stat_activity WHERE cardinality(pg_blocking_pids(pid))>0`).Scan(&n)
		if e != nil {
			t.Fatal(e)
		}
		if n > 0 {
			blocked = true
			break
		}
		time.Sleep(10 * time.Millisecond)
	}
	if !blocked {
		t.Fatal("no actual PostgreSQL lock waiter")
	}
	if e := s.Scenarios.Reset(ctx, c.RunID); e != nil {
		t.Fatal(e)
	}
	select {
	case e := <-done:
		if e != nil {
			t.Fatal(e)
		}
	case <-time.After(time.Second):
		t.Fatal("reset failed to release lock")
	}
	if e := s.Scenarios.Reset(ctx, c.RunID); e != nil {
		t.Fatal(e)
	}
}
func TestScenarioExpiryAndCancellation(t *testing.T) {
	s, c := fixture(t)
	if _, e := s.Scenarios.Activate(context.Background(), c.RunID, "db_lock", 1); e != nil {
		t.Fatal(e)
	}
	time.Sleep(1200 * time.Millisecond)
	if name := s.Scenarios.Active(context.Background(), c.RunID); name != "healthy" {
		t.Fatal(name)
	}
	call(t, s, c, "check_inventory", map[string]any{"order_id": "PD-1042"})
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	start := time.Now()
	cpuWork(ctx, 5*time.Second)
	if time.Since(start) > 100*time.Millisecond {
		t.Fatal("CPU work ignored cancellation")
	}
}
func TestSessionAndConversationOwnership(t *testing.T) {
	s, c := fixture(t)
	other := c
	other.CustomerID = "C2"
	if _, e := s.Store.Conversation(context.Background(), other, c.ConversationID, "", ""); !errors.Is(e, store.ErrDenied) {
		t.Fatal(e)
	}
}

func TestSecondConversationCannotReplaceSameOrderAgain(t *testing.T) {
	s, c := fixture(t)
	ctx := context.Background()
	p := call(t, s, c, "propose_replacement", map[string]any{"order_id": "PD-1042"})
	_, e := s.Store.Confirm(ctx, c, p["proposal_id"].(string), "confirm-1")
	if e != nil {
		t.Fatal(e)
	}
	call(t, s, c, "create_replacement", map[string]any{"proposal_id": p["proposal_id"], "idempotency_key": "create-1"})
	c.ConversationID = "conversation-2"
	if _, e = s.Store.Conversation(ctx, c, c.ConversationID, "PD-1042", "baseline"); e != nil {
		t.Fatal(e)
	}
	p = call(t, s, c, "propose_replacement", map[string]any{"order_id": "PD-1042"})
	_, e = s.Store.Confirm(ctx, c, p["proposal_id"].(string), "confirm-2")
	if e != nil {
		t.Fatal(e)
	}
	if _, e = s.Store.Replace(ctx, c, p["proposal_id"].(string), "create-2"); !errors.Is(e, store.ErrDenied) {
		t.Fatalf("second order replacement: %v", e)
	}
	ev, _ := s.Store.Evidence(ctx, c.RunID)
	if ev["replacements_count"] != 1 {
		t.Fatal(ev)
	}
}
func TestProposalLookupChecksOwnership(t *testing.T) {
	s, c := fixture(t)
	p := call(t, s, c, "propose_replacement", map[string]any{"order_id": "PD-1042"})
	for _, customer := range []string{"C1", "C2"} {
		r := httptest.NewRequest("GET", "/internal/proposals/"+p["proposal_id"].(string)+"?run_id=run-1&customer_id="+customer, nil)
		r.Header.Set("X-Service-Token", "test-token")
		w := httptest.NewRecorder()
		s.Handler().ServeHTTP(w, r)
		expected := 200
		if customer == "C2" {
			expected = 403
		}
		if w.Code != expected {
			t.Fatalf("customer %s: %d", customer, w.Code)
		}
		if customer == "C1" && !strings.Contains(w.Body.String(), "conversation-1") {
			t.Fatal(w.Body.String())
		}
	}
}

func TestRepeatedProposalKeepsPersistedDeadline(t *testing.T) {
	s, c := fixture(t)
	first := call(t, s, c, "propose_replacement", map[string]any{"order_id": "PD-1042", "requested_by": "2026-09-16"})
	second := call(t, s, c, "propose_replacement", map[string]any{"order_id": "PD-1042", "requested_by": "2026-09-30"})
	if first["proposal_id"] != second["proposal_id"] || second["deadline_met"] != false {
		t.Fatalf("duplicate proposal changed persisted promise: %v", second)
	}
}
