package store

import (
	"context"
	"encoding/json"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"time"
)

func (s *Store) Propose(ctx context.Context, c Context, order, requested string, quote map[string]any) (map[string]any, error) {
	o, e := s.Order(ctx, c, order)
	if e != nil {
		return nil, e
	}
	if o["eligible"] != true {
		return nil, ErrDenied
	}
	arrival, _ := quote["arrival_date"].(string)
	if _, e = time.Parse("2006-01-02", arrival); e != nil {
		return nil, e
	}
	var requestedDate any
	if requested != "" {
		d, e := time.Parse("2006-01-02", requested)
		if e != nil {
			return nil, e
		}
		requestedDate = d
	}
	if c.ConversationID == "" {
		return nil, errors.New("conversation_id required")
	}
	conversation, e := s.Conversation(ctx, c, c.ConversationID, "", "")
	if e != nil {
		return nil, e
	}
	if conversation["order_id"] != order {
		return nil, ErrDenied
	}
	raw, _ := json.Marshal(quote["raw_carrier"])
	id := uuid.NewString()
	rows, e := queryObjects(ctx, s.DB, `INSERT INTO proposals(run_id,id,conversation_id,customer_id,order_id,sku,arrival_date,requested_by,raw_carrier) SELECT $1,$2,$3,$4,$5,$6,$7,$8,$9 WHERE EXISTS(SELECT 1 FROM stock WHERE run_id=$1 AND sku=$6 AND available>0) ON CONFLICT(run_id,conversation_id,order_id) DO UPDATE SET id=proposals.id RETURNING to_jsonb(proposals)`, c.RunID, id, c.ConversationID, c.CustomerID, order, o["sku"], arrival, requestedDate, raw)
	if e != nil {
		return nil, e
	}
	if len(rows) == 0 {
		return nil, ErrDenied
	}
	p := rows[0]
	p["proposal_id"] = p["id"]
	p["requires_confirmation"] = p["confirmed_at"] == nil
	storedArrival, _ := p["arrival_date"].(string)
	storedDeadline, _ := p["requested_by"].(string)
	p["deadline_met"] = storedDeadline == "" || storedArrival <= storedDeadline
	p["source_revision"] = "store-v1"
	return p, nil
}
func (s *Store) Confirm(ctx context.Context, c Context, id, key string) (map[string]any, error) {
	if e := s.Validate(ctx, c); e != nil {
		return nil, e
	}
	if key == "" {
		return nil, errors.New("idempotency_key required")
	}
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return nil, e
	}
	defer tx.Rollback(context.Background())
	var proposal string
	e = tx.QueryRow(ctx, `SELECT id FROM proposals WHERE run_id=$1 AND id=$2 AND customer_id=$3 AND conversation_id=$4 FOR UPDATE`, c.RunID, id, c.CustomerID, c.ConversationID).Scan(&proposal)
	if errors.Is(e, pgx.ErrNoRows) {
		return nil, ErrDenied
	}
	if e != nil {
		return nil, e
	}
	var prior string
	e = tx.QueryRow(ctx, `SELECT proposal_id FROM confirmations WHERE run_id=$1 AND idempotency_key=$2`, c.RunID, key).Scan(&prior)
	if e == nil && prior != id {
		return nil, ErrDenied
	}
	if e != nil && !errors.Is(e, pgx.ErrNoRows) {
		return nil, e
	}
	_, e = tx.Exec(ctx, `INSERT INTO confirmations(run_id,idempotency_key,proposal_id,customer_id) VALUES($1,$2,$3,$4) ON CONFLICT(run_id,proposal_id) DO NOTHING`, c.RunID, key, id, c.CustomerID)
	if e != nil {
		return nil, e
	}
	_, e = tx.Exec(ctx, `UPDATE proposals SET confirmed_at=COALESCE(confirmed_at,now()) WHERE run_id=$1 AND id=$2`, c.RunID, id)
	if e != nil {
		return nil, e
	}
	if e = tx.Commit(ctx); e != nil {
		return nil, e
	}
	return map[string]any{"proposal_id": id, "confirmed": true}, nil
}
func (s *Store) Replace(ctx context.Context, c Context, proposal, key string) (map[string]any, error) {
	if e := s.Validate(ctx, c); e != nil {
		return nil, e
	}
	if key == "" {
		return nil, errors.New("idempotency_key required")
	}
	tx, e := s.DB.Begin(ctx)
	if e != nil {
		return nil, e
	}
	defer tx.Rollback(context.Background())
	var id, order, sku string
	var confirmed *time.Time
	var arrival time.Time
	e = tx.QueryRow(ctx, `SELECT id,order_id,sku,confirmed_at,arrival_date FROM proposals WHERE run_id=$1 AND id=$2 AND customer_id=$3 AND conversation_id=$4 FOR UPDATE`, c.RunID, proposal, c.CustomerID, c.ConversationID).Scan(&id, &order, &sku, &confirmed, &arrival)
	if errors.Is(e, pgx.ErrNoRows) {
		return nil, ErrDenied
	}
	if e != nil {
		return nil, e
	}
	if confirmed == nil {
		return nil, ErrDenied
	}
	rows, e := queryObjects(ctx, tx, `SELECT to_jsonb(r) FROM replacements r WHERE run_id=$1 AND proposal_id=$2`, c.RunID, proposal)
	if e != nil {
		return nil, e
	}
	if len(rows) > 0 {
		rows[0]["replacement_id"] = rows[0]["id"]
		return rows[0], nil
	}
	var eligible bool
	e = tx.QueryRow(ctx, `SELECT o.damaged AND r.business_date-o.delivered_at BETWEEN 0 AND 30 FROM orders o JOIN runs r ON r.id=o.run_id WHERE o.run_id=$1 AND o.id=$2 AND o.customer_id=$3 FOR UPDATE OF o`, c.RunID, order, c.CustomerID).Scan(&eligible)
	if e != nil {
		return nil, e
	}
	if !eligible {
		return nil, ErrDenied
	}
	var alreadyReplaced bool
	if e = tx.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM replacements WHERE run_id=$1 AND order_id=$2)`, c.RunID, order).Scan(&alreadyReplaced); e != nil {
		return nil, e
	}
	if alreadyReplaced {
		return nil, ErrDenied
	}
	tag, e := tx.Exec(ctx, `UPDATE stock SET available=available-1 WHERE run_id=$1 AND sku=$2 AND available>0`, c.RunID, sku)
	if e != nil {
		return nil, e
	}
	if tag.RowsAffected() != 1 {
		return nil, ErrDenied
	}
	replacement := uuid.NewString()
	rows, e = queryObjects(ctx, tx, `INSERT INTO replacements(run_id,id,proposal_id,customer_id,order_id,idempotency_key,arrival_date) VALUES($1,$2,$3,$4,$5,$6,$7) RETURNING to_jsonb(replacements)`, c.RunID, replacement, proposal, c.CustomerID, order, key, arrival)
	if e != nil {
		return nil, e
	}
	if e = tx.Commit(ctx); e != nil {
		return nil, e
	}
	rows[0]["replacement_id"] = replacement
	return rows[0], nil
}
