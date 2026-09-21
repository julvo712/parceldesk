package notifications

import (
	"context"
	"errors"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

var ErrRecipientNotCustomer = errors.New("recipient must exactly match the authenticated customer's stored email")
var ErrReplacementNotFound = errors.New("confirmed replacement not found")

type Service struct{ DB *pgxpool.Pool }

func (s Service) SendConfirmation(ctx context.Context, runID, customerID, replacementID, to, idempotencyKey string) error {
	tx, err := s.DB.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(context.Background())
	var email string
	err = tx.QueryRow(ctx, `SELECT c.email FROM customers c JOIN replacements r ON r.run_id=c.run_id AND r.customer_id=c.id WHERE c.run_id=$1 AND c.id=$2 AND r.id=$3 FOR UPDATE OF r`, runID, customerID, replacementID).Scan(&email)
	if errors.Is(err, pgx.ErrNoRows) {
		return ErrReplacementNotFound
	}
	if err != nil {
		return err
	}
	if to != email {
		return ErrRecipientNotCustomer
	}
	if idempotencyKey == "" {
		return errors.New("idempotency_key is required")
	}
	var prior string
	err = tx.QueryRow(ctx, `SELECT replacement_id FROM notification_deliveries WHERE run_id=$1 AND idempotency_key=$2`, runID, idempotencyKey).Scan(&prior)
	if err == nil && prior != replacementID {
		return errors.New("idempotency key belongs to another replacement")
	}
	if err != nil && !errors.Is(err, pgx.ErrNoRows) {
		return err
	}
	_, err = tx.Exec(ctx, `INSERT INTO notification_deliveries(run_id,id,replacement_id,customer_id,recipient,idempotency_key,body) VALUES($1,$2,$3,$4,$5,$6,$7) ON CONFLICT(run_id,replacement_id) DO NOTHING`, runID, uuid.NewString(), replacementID, customerID, email, idempotencyKey, "Your replacement is confirmed. This notification was recorded in the ParcelDesk sandbox; no email was sent.")
	if err != nil {
		return err
	}
	return tx.Commit(ctx)
}
