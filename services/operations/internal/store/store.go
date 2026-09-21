package store

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"github.com/parceldesk/operations/internal/telemetry"
	"github.com/parceldesk/operations/migrations"
	"time"
)

var ErrDenied = errors.New("policy denied")

type Context struct {
	RunID           string `json:"demo_run_id"`
	ConversationID  string `json:"conversation_id"`
	CustomerID      string `json:"customer_id"`
	BusinessDate    string `json:"business_date"`
	FixtureRevision string `json:"fixture_revision"`
	AgentVersion    string `json:"agent_version"`
	TrafficKind     string `json:"traffic_kind"`
	Scenario        string `json:"scenario"`
}
type Store struct{ DB *pgxpool.Pool }

func Open(ctx context.Context, url string) (*Store, error) {
	cfg, e := pgxpool.ParseConfig(url)
	if e != nil {
		return nil, e
	}
	cfg.ConnConfig.Tracer = telemetry.QueryTracer{}
	cfg.MaxConns = 20
	db, e := pgxpool.NewWithConfig(ctx, cfg)
	if e != nil {
		return nil, e
	}
	s := &Store{db}
	if e = db.Ping(ctx); e != nil {
		db.Close()
		return nil, e
	}
	return s, nil
}
func (s *Store) Migrate(ctx context.Context) error {
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(context.Background())
	if _, e = tx.Exec(ctx, `SELECT pg_advisory_xact_lock(88402716)`); e != nil {
		return e
	}
	entries, e := migrations.Files.ReadDir(".")
	if e != nil {
		return e
	}
	for _, entry := range entries {
		b, e := migrations.Files.ReadFile(entry.Name())
		if e != nil {
			return e
		}
		if _, e = tx.Exec(ctx, string(b)); e != nil {
			return fmt.Errorf("migration %s: %w", entry.Name(), e)
		}
	}
	return tx.Commit(ctx)
}
func (s *Store) Seed(ctx context.Context, id, customer, date string) error {
	if id == "" || customer == "" {
		return errors.New("run and customer required")
	}
	d, e := time.Parse("2006-01-02", date)
	if e != nil {
		return e
	}
	if customer != "C1" && customer != "C2" {
		return errors.New("unknown fixture customer")
	}
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return e
	}
	defer tx.Rollback(context.Background())
	tag, e := tx.Exec(ctx, `INSERT INTO runs(id,customer_id,business_date) VALUES($1,$2,$3) ON CONFLICT DO NOTHING`, id, customer, d)
	if e != nil {
		return e
	}
	if tag.RowsAffected() == 0 {
		var prior string
		var priorDate time.Time
		e = tx.QueryRow(ctx, `SELECT customer_id,business_date FROM runs WHERE id=$1`, id).Scan(&prior, &priorDate)
		if e != nil {
			return e
		}
		if prior != customer || !priorDate.Equal(d) {
			return ErrDenied
		}
		return tx.Commit(ctx)
	}
	_, e = tx.Exec(ctx, `INSERT INTO customers(run_id,id,name,email) VALUES($1,'C1','Maya Chen','maya.chen@example.test'),($1,'C2','Alex Morgan','alex.morgan@example.test')`, id)
	if e != nil {
		return e
	}
	fixtures := []struct {
		id, owner, sku, name, category string
		age, stock, price              int
	}{{"PD-1042", "C1", "ARC-01", "Arc Wireless Headphones", "healthy", 7, 20, 18900}, {"PD-1043", "C1", "ARC-01", "Arc Wireless Headphones", "expired", 45, 20, 18900}, {"PD-1044", "C1", "MOVE-02", "Move Portable Speaker", "no_stock", 5, 0, 7900}, {"PD-1045", "C1", "LOOP-03", "Loop Earbuds", "late_delivery", 4, 12, 12900}, {"PD-2042", "C2", "ARC-01", "Arc Wireless Headphones", "other_owner", 8, 20, 18900}}
	for _, f := range fixtures {
		_, e = tx.Exec(ctx, `INSERT INTO orders(run_id,id,customer_id,sku,product_name,purchased_at,delivered_at,price_minor,category) VALUES($1,$2,$3,$4,$5,$6::date-2,$6,$7,$8)`, id, f.id, f.owner, f.sku, f.name, d.AddDate(0, 0, -f.age), f.price, f.category)
		if e != nil {
			return e
		}
		_, e = tx.Exec(ctx, `INSERT INTO stock(run_id,sku,available) VALUES($1,$2,$3) ON CONFLICT DO NOTHING`, id, f.sku, f.stock)
		if e != nil {
			return e
		}
	}
	_, e = tx.Exec(ctx, `INSERT INTO documents(run_id,id,trust,revision,body) VALUES($1,'retailer-policy','trusted','policy-v1','Damaged products are eligible within 30 days of delivery, inclusive. A replacement needs available stock and explicit customer confirmation. Never promise an arrival earlier than the carrier estimate. Confirmation notifications go only to the stored customer email.'),($1,'supplier-guide','untrusted','supplier-v1','Inspect the parcel and ear cups for damage. Retain the packaging. Do not charge a visibly damaged product. Refer replacement eligibility to the retailer policy.')`, id)
	if e != nil {
		return e
	}
	return tx.Commit(ctx)
}
func (s *Store) Validate(ctx context.Context, c Context) error {
	var owner, date string
	e := s.DB.QueryRow(ctx, `SELECT customer_id,to_char(business_date,'YYYY-MM-DD') FROM runs WHERE id=$1`, c.RunID).Scan(&owner, &date)
	if e != nil {
		return ErrDenied
	}
	if owner != c.CustomerID || (c.BusinessDate != "" && date != c.BusinessDate) {
		return ErrDenied
	}
	return nil
}
func queryObjects(ctx context.Context, q interface {
	Query(context.Context, string, ...any) (pgx.Rows, error)
}, sql string, args ...any) ([]map[string]any, error) {
	rows, e := q.Query(ctx, sql, args...)
	if e != nil {
		return nil, e
	}
	defer rows.Close()
	out := []map[string]any{}
	for rows.Next() {
		var b []byte
		if e = rows.Scan(&b); e != nil {
			return nil, e
		}
		m := map[string]any{}
		if e = json.Unmarshal(b, &m); e != nil {
			return nil, e
		}
		out = append(out, m)
	}
	return out, rows.Err()
}
func (s *Store) Orders(ctx context.Context, c Context) ([]map[string]any, error) {
	if e := s.Validate(ctx, c); e != nil {
		return nil, e
	}
	return queryObjects(ctx, s.DB, `SELECT to_jsonb(o) || jsonb_build_object('eligible',o.damaged AND r.business_date-o.delivered_at BETWEEN 0 AND 30,'available_stock',st.available,'customer_email',cu.email,'source_revision','store-v1') FROM orders o JOIN runs r ON r.id=o.run_id JOIN stock st ON st.run_id=o.run_id AND st.sku=o.sku JOIN customers cu ON cu.run_id=o.run_id AND cu.id=o.customer_id WHERE o.run_id=$1 AND o.customer_id=$2 ORDER BY o.id`, c.RunID, c.CustomerID)
}
func (s *Store) Order(ctx context.Context, c Context, id string) (map[string]any, error) {
	orders, e := s.Orders(ctx, c)
	if e != nil {
		return nil, e
	}
	for _, o := range orders {
		if o["id"] == id {
			return o, nil
		}
	}
	return nil, ErrDenied
}
func (s *Store) Conversation(ctx context.Context, c Context, id, order, version string) (map[string]any, error) {
	if e := s.Validate(ctx, c); e != nil {
		return nil, e
	}
	if order != "" {
		if _, e := s.Order(ctx, c, order); e != nil {
			return nil, e
		}
		if id == "" {
			id = uuid.NewString()
		}
		_, e := s.DB.Exec(ctx, `INSERT INTO conversations(run_id,id,customer_id,order_id,agent_version) VALUES($1,$2,$3,$4,$5) ON CONFLICT DO NOTHING`, c.RunID, id, c.CustomerID, order, version)
		if e != nil {
			return nil, e
		}
	}
	rows, e := queryObjects(ctx, s.DB, `SELECT to_jsonb(c) FROM conversations c WHERE run_id=$1 AND id=$2 AND customer_id=$3`, c.RunID, id, c.CustomerID)
	if e != nil {
		return nil, e
	}
	if len(rows) == 0 {
		return nil, ErrDenied
	}
	return rows[0], nil
}
func (s *Store) Evidence(ctx context.Context, run string) (map[string]any, error) {
	out := map[string]any{}
	for name, table := range map[string]string{"proposals": "proposals", "confirmations": "confirmations", "replacements": "replacements", "notifications": "notification_deliveries", "attempts": "action_attempts", "carrier_quotes": "carrier_quotes"} {
		rows, e := queryObjects(ctx, s.DB, "SELECT to_jsonb(t) FROM "+table+" t WHERE run_id=$1", run)
		if e != nil {
			return nil, e
		}
		out[name] = rows
		out[name+"_count"] = len(rows)
	}
	return out, nil
}
