package main

import (
	"context"
	"github.com/parceldesk/operations/internal/server"
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
	shutdown, e := telemetry.Init(ctx, "parceldesk-carrier")
	if e != nil {
		slog.Error("telemetry init failed", "error", e)
		os.Exit(1)
	}
	if os.Getenv("INTERNAL_SERVICE_TOKEN") == "" {
		slog.Error("INTERNAL_SERVICE_TOKEN required")
		os.Exit(1)
	}
	addr := os.Getenv("LISTEN_ADDRESS")
	if addr == "" {
		addr = ":8081"
	}
	srv := &http.Server{Addr: addr, Handler: server.CarrierHandler(os.Getenv("INTERNAL_SERVICE_TOKEN")), ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second, WriteTimeout: 10 * time.Second, IdleTimeout: 60 * time.Second}
	go func() {
		if e := srv.ListenAndServe(); e != nil && e != http.ErrServerClosed {
			cancel()
		}
	}()
	<-ctx.Done()
	stop, c := context.WithTimeout(context.Background(), 10*time.Second)
	defer c()
	_ = srv.Shutdown(stop)
	_ = shutdown(stop)
}
