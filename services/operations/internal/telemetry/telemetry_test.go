package telemetry

import (
	"context"
	"github.com/stretchr/testify/require"
	"go.opentelemetry.io/contrib/instrumentation/net/http/otelhttp"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/trace"
	collectormetrics "go.opentelemetry.io/proto/otlp/collector/metrics/v1"
	collectortrace "go.opentelemetry.io/proto/otlp/collector/trace/v1"
	"google.golang.org/protobuf/proto"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
)

func TestNativeOTLPAndSpanProfileBridge(t *testing.T) {
	var mu sync.Mutex
	var traces collectortrace.ExportTraceServiceRequest
	var metrics collectormetrics.ExportMetricsServiceRequest
	receiver := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		b, e := io.ReadAll(r.Body)
		if e != nil {
			w.WriteHeader(400)
			return
		}
		mu.Lock()
		defer mu.Unlock()
		switch r.URL.Path {
		case "/v1/traces":
			e = proto.Unmarshal(b, &traces)
		case "/v1/metrics":
			e = proto.Unmarshal(b, &metrics)
		default:
			w.WriteHeader(404)
			return
		}
		if e != nil {
			w.WriteHeader(400)
			return
		}
		w.Header().Set("Content-Type", "application/x-protobuf")
		w.WriteHeader(200)
	}))
	defer receiver.Close()
	t.Setenv("OTEL_EXPORTER_OTLP_ENDPOINT", receiver.URL)
	t.Setenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT", "")
	t.Setenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT", "")
	t.Setenv("PYROSCOPE_SERVER_ADDRESS", "")
	t.Setenv("SERVICE_VERSION", "test-version")
	shutdown, e := Init(context.Background(), "parceldesk-operations")
	require.NoError(t, e)
	handler := otelhttp.NewHandler(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, span := otel.Tracer("test").Start(r.Context(), "inventory", trace.WithAttributes(attribute.String("demo_run_id", "isolated-test")))
		span.End()
		w.WriteHeader(200)
	}), "GET /probe", otelhttp.WithSpanNameFormatter(func(operation string, _ *http.Request) string { return operation }))
	r := httptest.NewRequest("GET", "http://local/probe", nil)
	r.Header.Set("traceparent", "00-12345678901234567890123456789012-1234567890123456-01")
	handler.ServeHTTP(httptest.NewRecorder(), r)
	require.NoError(t, shutdown(context.Background()))
	mu.Lock()
	defer mu.Unlock()
	require.NotEmpty(t, traces.ResourceSpans)
	require.NotEmpty(t, metrics.ResourceMetrics)
	foundRoot, foundProfile, foundVersion := false, false, false
	for _, rs := range traces.ResourceSpans {
		for _, a := range rs.Resource.Attributes {
			if a.Key == "service.version" && a.Value.GetStringValue() == "test-version" {
				foundVersion = true
			}
		}
		for _, ss := range rs.ScopeSpans {
			for _, span := range ss.Spans {
				if span.Name == "GET /probe" {
					foundRoot = true
					require.Equal(t, "12345678901234567890123456789012", fmtTraceID(span.TraceId))
					for _, a := range span.Attributes {
						if a.Key == "pyroscope.profile.id" && a.Value.GetStringValue() != "" {
							foundProfile = true
						}
					}
				}
			}
		}
	}
	require.True(t, foundRoot, "inbound HTTP server span")
	require.True(t, foundProfile, "profile bridge ID on local root span")
	require.True(t, foundVersion, "service version resource")
	metricFound := false
	for _, rm := range metrics.ResourceMetrics {
		for _, sm := range rm.ScopeMetrics {
			for _, m := range sm.Metrics {
				if m.Name == "http.server.request.duration" || m.Name == "http.server.duration" {
					metricFound = true
				}
			}
		}
	}
	require.True(t, metricFound, "native HTTP duration metric exported")
}
func fmtTraceID(b []byte) string {
	const digits = "0123456789abcdef"
	out := make([]byte, len(b)*2)
	for i, v := range b {
		out[i*2] = digits[v>>4]
		out[i*2+1] = digits[v&15]
	}
	return string(out)
}
