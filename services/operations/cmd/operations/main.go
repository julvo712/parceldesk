package main

import (
	"context"
	"github.com/parceldesk/operations/internal/server"
	"github.com/parceldesk/operations/internal/store"
	"github.com/parceldesk/operations/internal/telemetry"
	"log/slog"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

func main() {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	shutdown, e := telemetry.Init(ctx, "parceldesk-operations")
	if e != nil {
		slog.Error("telemetry init failed", "error", e)
		os.Exit(1)
	}
	if os.Getenv("INTERNAL_SERVICE_TOKEN") == "" {
		slog.Error("INTERNAL_SERVICE_TOKEN required")
		os.Exit(1)
	}
	db, e := store.Open(ctx, os.Getenv("DATABASE_URL"))
	if e != nil {
		slog.Error("database unavailable", "error", e)
		os.Exit(1)
	}
	defer db.DB.Close()
	if e = db.Migrate(ctx); e != nil {
		slog.Error("migration failed", "error", e)
		os.Exit(1)
	}
	carrier := os.Getenv("CARRIER_URL")
	if carrier == "" {
		carrier = "http://carrier:8081"
	}
	addr := os.Getenv("LISTEN_ADDRESS")
	if addr == "" {
		addr = ":8080"
	}
	app := server.New(db, os.Getenv("INTERNAL_SERVICE_TOKEN"), carrier)
	if e = app.Scenarios.Recover(ctx); e != nil {
		slog.Error("scenario recovery failed", "error", e)
		os.Exit(1)
	}
	srv := &http.Server{Addr: addr, Handler: app.Handler(), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second, WriteTimeout: 30 * time.Second, IdleTimeout: 60 * time.Second}
	go func() {
		slog.Info("operations listening", "address", addr)
		if e := srv.ListenAndServe(); e != nil && e != http.ErrServerClosed {
			slog.Error("server failed", "error", e)
			cancel()
		}
	}()
	<-ctx.Done()
	stop, c := context.WithTimeout(context.Background(), 10*time.Second)
	defer c()
	_ = app.Scenarios.Close(stop)
	_ = srv.Shutdown(stop)
	_ = shutdown(stop)
}
