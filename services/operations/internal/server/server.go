package server

import (
	"context"
	"crypto/subtle"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/parceldesk/operations/internal/store"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel/trace"
	"io"
	"log/slog"
	"net/http"
	"strconv"
	"strings"
	"time"
)

type Server struct {
	Store             *store.Store
	Token, CarrierURL string
	HTTP              *http.Client
	Scenarios         *Scenarios
}

func New(s *store.Store, token, carrier string) *Server {
	return &Server{Store: s, Token: token, CarrierURL: strings.TrimRight(carrier, "/"), HTTP: &http.Client{Timeout: 8 * time.Second, Transport: otelhttp.NewTransport(http.DefaultTransport)}, Scenarios: &Scenarios{store: s, leases: map[string]lease{}}}
}
func write(w http.ResponseWriter, status int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(v)
}
func decode(w http.ResponseWriter, r *http.Request, v any) bool {
	r.Body = http.MaxBytesReader(w, r.Body, 1<<20)
	d := json.NewDecoder(r.Body)
	d.DisallowUnknownFields()
	if e := d.Decode(v); e != nil {
		write(w, 400, map[string]any{"error": "invalid JSON request"})
		return false
	}
	if e := d.Decode(&struct{}{}); e != io.EOF {
		write(w, 400, map[string]any{"error": "request must contain one JSON object"})
		return false
	}
	return true
}
func fail(w http.ResponseWriter, e error) {
	code := 500
	message := "operation failed"
	if errors.Is(e, store.ErrDenied) {
		code = 403
		message = "This action is not permitted for the signed-in customer."
	}
	slog.Error("request failed", "error", e)
	write(w, code, map[string]any{"error": message})
}
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health/live", func(w http.ResponseWriter, r *http.Request) { write(w, 200, map[string]any{"status": "ok"}) })
	mux.HandleFunc("GET /health/ready", func(w http.ResponseWriter, r *http.Request) {
		ctx, c := context.WithTimeout(r.Context(), 2*time.Second)
		defer c()
		if e := s.Store.DB.Ping(ctx); e != nil {
			write(w, 503, map[string]any{"status": "unavailable"})
			return
		}
		write(w, 200, map[string]any{"status": "ready"})
	})
	mux.HandleFunc("POST /internal/runs", s.runs)
	mux.HandleFunc("GET /internal/runs/{id}/evidence", s.evidence)
	mux.HandleFunc("GET /internal/runs/{id}", s.run)
	mux.HandleFunc("GET /internal/orders", s.orders)
	mux.HandleFunc("POST /internal/conversations", s.conversationCreate)
	mux.HandleFunc("GET /internal/conversations/{id}", s.conversationGet)
	mux.HandleFunc("PUT /internal/conversations/{id}/state", s.conversationState)
	mux.HandleFunc("POST /internal/proposals/{id}/confirm", s.confirm)
	mux.HandleFunc("GET /internal/proposals/{id}", s.proposalGet)
	mux.HandleFunc("POST /internal/tools/{name}", s.tool)
	mux.HandleFunc("POST /internal/runs/{id}/scenario", s.scenario)
	mux.HandleFunc("DELETE /internal/runs/{id}/scenario", s.reset)
	mux.HandleFunc("POST /internal/sessions", s.sessionCreate)
	mux.HandleFunc("GET /internal/sessions/{id}", s.sessionGet)
	mux.HandleFunc("POST /internal/runs/{id}/attempts", s.recordAttempt)
	mux.HandleFunc("GET /internal/cpu-probe", func(w http.ResponseWriter, r *http.Request) {
		ms, _ := strconv.Atoi(r.URL.Query().Get("duration_ms"))
		if ms < 100 {
			ms = 600
		}
		if ms > 3000 {
			ms = 3000
		}
		sum := cpuWork(r.Context(), time.Duration(ms)*time.Millisecond)
		write(w, 200, map[string]any{"checksum": sum, "duration_ms": ms})
	})
	return otelhttp.NewHandler(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasPrefix(r.URL.Path, "/internal/") && (s.Token == "" || subtle.ConstantTimeCompare([]byte(r.Header.Get("X-Service-Token")), []byte(s.Token)) != 1) {
			write(w, 401, map[string]any{"error": "service authentication required"})
			return
		}
		start := time.Now()
		mux.ServeHTTP(w, r)
		sc := trace.SpanContextFromContext(r.Context())
		slog.Info("http request", "method", r.Method, "route", r.Pattern, "duration_ms", time.Since(start).Milliseconds(), "trace_id", sc.TraceID().String(), "span_id", sc.SpanID().String())
	}), "operations", otelhttp.WithSpanNameFormatter(func(_ string, r *http.Request) string {
		if r.Pattern != "" {
			return r.Pattern
		}
		return r.Method + " operations"
	}))
}
func (s *Server) runs(w http.ResponseWriter, r *http.Request) {
	var b struct {
		RunID           string `json:"run_id"`
		CustomerID      string `json:"customer_id"`
		Scenario        string `json:"scenario"`
		BusinessDate    string `json:"business_date"`
		FixtureRevision string `json:"fixture_revision"`
	}
	if !decode(w, r, &b) {
		return
	}
	if b.RunID == "" {
		b.RunID = uuid.NewString()
	}
	if b.CustomerID == "" {
		b.CustomerID = "C1"
	}
	if b.BusinessDate == "" {
		b.BusinessDate = "2026-09-15"
	}
	if e := s.Store.Seed(r.Context(), b.RunID, b.CustomerID, b.BusinessDate); e != nil {
		fail(w, e)
		return
	}
	if b.Scenario != "" && b.Scenario != "healthy" {
		if _, e := s.Scenarios.Activate(r.Context(), b.RunID, b.Scenario, 300); e != nil {
			fail(w, e)
			return
		}
	}
	write(w, 201, map[string]any{"run_id": b.RunID, "demo_run_id": b.RunID, "customer_id": b.CustomerID, "business_date": b.BusinessDate, "fixture_revision": "store-v1", "scenario": s.Scenarios.Active(r.Context(), b.RunID)})
}
func (s *Server) run(w http.ResponseWriter, r *http.Request) {
	var customer, date string
	e := s.Store.DB.QueryRow(r.Context(), `SELECT customer_id,to_char(business_date,'YYYY-MM-DD') FROM runs WHERE id=$1`, r.PathValue("id")).Scan(&customer, &date)
	if e != nil {
		write(w, 404, map[string]any{"error": "run not found"})
		return
	}
	write(w, 200, map[string]any{"run_id": r.PathValue("id"), "customer_id": customer, "business_date": date, "fixture_revision": "store-v1", "scenario": s.Scenarios.Active(r.Context(), r.PathValue("id"))})
}
func (s *Server) evidence(w http.ResponseWriter, r *http.Request) {
	data, e := s.Store.Evidence(r.Context(), r.PathValue("id"))
	if e != nil {
		fail(w, e)
		return
	}
	data["scenario"] = s.Scenarios.Active(r.Context(), r.PathValue("id"))
	write(w, 200, data)
}
func (s *Server) orders(w http.ResponseWriter, r *http.Request) {
	data, e := s.Store.Orders(r.Context(), store.Context{RunID: r.URL.Query().Get("run_id"), CustomerID: r.URL.Query().Get("customer_id")})
	if e != nil {
		fail(w, e)
		return
	}
	write(w, 200, map[string]any{"orders": data})
}
func (s *Server) conversationCreate(w http.ResponseWriter, r *http.Request) {
	var b struct {
		RunID          string `json:"run_id"`
		CustomerID     string `json:"customer_id"`
		OrderID        string `json:"order_id"`
		ConversationID string `json:"conversation_id"`
		AgentVersion   string `json:"agent_version"`
	}
	if !decode(w, r, &b) {
		return
	}
	if b.AgentVersion == "" {
		b.AgentVersion = "baseline"
	}
	data, e := s.Store.Conversation(r.Context(), store.Context{RunID: b.RunID, CustomerID: b.CustomerID}, b.ConversationID, b.OrderID, b.AgentVersion)
	if e != nil {
		fail(w, e)
		return
	}
	write(w, 201, data)
}
func (s *Server) conversationGet(w http.ResponseWriter, r *http.Request) {
	data, e := s.Store.Conversation(r.Context(), store.Context{RunID: r.URL.Query().Get("run_id"), CustomerID: r.URL.Query().Get("customer_id")}, r.PathValue("id"), "", "")
	if e != nil {
		fail(w, e)
		return
	}
	write(w, 200, data)
}
func (s *Server) conversationState(w http.ResponseWriter, r *http.Request) {
	var b struct {
		RunID      string          `json:"run_id"`
		CustomerID string          `json:"customer_id"`
		State      json.RawMessage `json:"state"`
	}
	if !decode(w, r, &b) {
		return
	}
	if _, e := s.Store.Conversation(r.Context(), store.Context{RunID: b.RunID, CustomerID: b.CustomerID}, r.PathValue("id"), "", ""); e != nil {
		fail(w, e)
		return
	}
	_, e := s.Store.DB.Exec(r.Context(), `UPDATE conversations SET state=$1 WHERE run_id=$2 AND id=$3 AND customer_id=$4`, b.State, b.RunID, r.PathValue("id"), b.CustomerID)
	if e != nil {
		fail(w, e)
		return
	}
	write(w, 200, map[string]any{"saved": true})
}
func (s *Server) confirm(w http.ResponseWriter, r *http.Request) {
	var b struct {
		Context store.Context `json:"context"`
		Key     string        `json:"idempotency_key"`
	}
	if !decode(w, r, &b) {
		return
	}
	data, e := s.Store.Confirm(r.Context(), b.Context, r.PathValue("id"), b.Key)
	if e != nil {
		fail(w, e)
		return
	}
	write(w, 200, data)
}
func (s *Server) scenario(w http.ResponseWriter, r *http.Request) {
	var b struct {
		Scenario string `json:"scenario"`
		TTL      int    `json:"ttl_seconds"`
	}
	if !decode(w, r, &b) {
		return
	}
	data, e := s.Scenarios.Activate(r.Context(), r.PathValue("id"), b.Scenario, b.TTL)
	if e != nil {
		write(w, 400, map[string]any{"error": e.Error()})
		return
	}
	write(w, 200, data)
}
func (s *Server) reset(w http.ResponseWriter, r *http.Request) {
	if e := s.Scenarios.Reset(r.Context(), r.PathValue("id")); e != nil {
		fail(w, e)
		return
	}
	write(w, 200, map[string]any{"scenario": "healthy", "reset": true})
}
func (s *Server) sessionCreate(w http.ResponseWriter, r *http.Request) {
	var b struct {
		ID         string `json:"id"`
		RunID      string `json:"run_id"`
		CustomerID string `json:"customer_id"`
		TTL        int    `json:"ttl_seconds"`
	}
	if !decode(w, r, &b) {
		return
	}
	if e := s.Store.Validate(r.Context(), store.Context{RunID: b.RunID, CustomerID: b.CustomerID}); e != nil {
		fail(w, e)
		return
	}
	if b.ID == "" {
		b.ID = uuid.NewString()
	}
	if b.TTL < 1 || b.TTL > 86400 {
		b.TTL = 14400
	}
	expiry := time.Now().Add(time.Duration(b.TTL) * time.Second)
	_, e := s.Store.DB.Exec(r.Context(), `INSERT INTO sessions(id,run_id,customer_id,expires_at) VALUES($1,$2,$3,$4)`, b.ID, b.RunID, b.CustomerID, expiry)
	if e != nil {
		fail(w, e)
		return
	}
	write(w, 201, map[string]any{"id": b.ID, "run_id": b.RunID, "customer_id": b.CustomerID, "expires_at": expiry})
}
func (s *Server) sessionGet(w http.ResponseWriter, r *http.Request) {
	var run, customer string
	var expiry time.Time
	e := s.Store.DB.QueryRow(r.Context(), `SELECT run_id,customer_id,expires_at FROM sessions WHERE id=$1 AND expires_at>now()`, r.PathValue("id")).Scan(&run, &customer, &expiry)
	if e != nil {
		write(w, 401, map[string]any{"error": "session expired"})
		return
	}
	write(w, 200, map[string]any{"id": r.PathValue("id"), "run_id": run, "customer_id": customer, "expires_at": expiry})
}
func (s *Server) recordAttempt(w http.ResponseWriter, r *http.Request) {
	var b struct {
		ConversationID string `json:"conversation_id"`
		CallID         string `json:"call_id"`
		ToolName       string `json:"tool_name"`
		Status         string `json:"status"`
		Reason         string `json:"reason"`
		TraceID        string `json:"trace_id"`
	}
	if !decode(w, r, &b) {
		return
	}
	_, e := s.Store.DB.Exec(r.Context(), `INSERT INTO action_attempts(run_id,conversation_id,call_id,tool_name,status,reason,trace_id) VALUES($1,$2,$3,$4,$5,$6,$7)`, r.PathValue("id"), b.ConversationID, b.CallID, b.ToolName, b.Status, b.Reason, b.TraceID)
	if e != nil {
		fail(w, e)
		return
	}
	write(w, 201, map[string]any{"recorded": true})
}

func (s *Server) proposalGet(w http.ResponseWriter, r *http.Request) {
	c := store.Context{RunID: r.URL.Query().Get("run_id"), CustomerID: r.URL.Query().Get("customer_id")}
	if e := s.Store.Validate(r.Context(), c); e != nil {
		fail(w, e)
		return
	}
	var raw []byte
	e := s.Store.DB.QueryRow(r.Context(), `SELECT to_jsonb(p) FROM proposals p WHERE run_id=$1 AND id=$2 AND customer_id=$3`, c.RunID, r.PathValue("id"), c.CustomerID).Scan(&raw)
	if e != nil {
		fail(w, store.ErrDenied)
		return
	}
	var data map[string]any
	if e = json.Unmarshal(raw, &data); e != nil {
		fail(w, e)
		return
	}
	data["proposal_id"] = data["id"]
	write(w, 200, data)
}
