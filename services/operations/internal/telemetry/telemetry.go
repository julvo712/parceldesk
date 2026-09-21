package telemetry

import (
	"context"
	"errors"
	otelpyroscope "github.com/grafana/otel-profiling-go"
	"github.com/grafana/pyroscope-go"
	"github.com/jackc/pgx/v5"
	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/codes"
	"go.opentelemetry.io/otel/exporters/otlp/otlpmetric/otlpmetrichttp"
	"go.opentelemetry.io/otel/exporters/otlp/otlptrace/otlptracehttp"
	"go.opentelemetry.io/otel/propagation"
	sdkmetric "go.opentelemetry.io/otel/sdk/metric"
	"go.opentelemetry.io/otel/sdk/resource"
	sdktrace "go.opentelemetry.io/otel/sdk/trace"
	"go.opentelemetry.io/otel/trace"
	"log/slog"
	"os"
	"strings"
	"time"
)

func Init(ctx context.Context, service string) (func(context.Context) error, error) {
	slog.SetDefault(slog.New(slog.NewJSONHandler(os.Stdout, nil)))
	version := os.Getenv("SERVICE_VERSION")
	if version == "" {
		version = "0.1.0"
	}
	environment := os.Getenv("DEPLOYMENT_ENVIRONMENT")
	if environment == "" {
		environment = "demo-local"
	}
	attributes := []attribute.KeyValue{attribute.String("service.name", service), attribute.String("service.version", version), attribute.String("service.namespace", "parceldesk"), attribute.String("deployment.environment.name", environment)}
	tags := map[string]string{"service_name": service, "service_namespace": "parceldesk", "deployment_environment": environment, "service_version": version, "service_root_path": "services/operations"}
	if sha := os.Getenv("GIT_COMMIT"); sha != "" {
		attributes = append(attributes, attribute.String("vcs.ref.head.revision", sha))
		tags["service_git_ref"] = sha
	}
	if repo := os.Getenv("SERVICE_REPOSITORY"); repo != "" {
		attributes = append(attributes, attribute.String("vcs.repository.url.full", repo))
		tags["service_repository"] = repo
	}
	r, err := resource.Merge(resource.Default(), resource.NewSchemaless(attributes...))
	if err != nil {
		return nil, err
	}
	opts := []sdktrace.TracerProviderOption{sdktrace.WithResource(r), sdktrace.WithSampler(sdktrace.AlwaysSample())}
	if os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT") != "" || os.Getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") != "" {
		exporter, e := otlptracehttp.New(ctx)
		if e != nil {
			return nil, e
		}
		opts = append(opts, sdktrace.WithBatcher(exporter))
	}
	metricOptions := []sdkmetric.Option{sdkmetric.WithResource(r)}
	if os.Getenv("OTEL_EXPORTER_OTLP_ENDPOINT") != "" || os.Getenv("OTEL_EXPORTER_OTLP_METRICS_ENDPOINT") != "" {
		exporter, e := otlpmetrichttp.New(ctx)
		if e != nil {
			return nil, e
		}
		metricOptions = append(metricOptions, sdkmetric.WithReader(sdkmetric.NewPeriodicReader(exporter, sdkmetric.WithInterval(10*time.Second))))
	}
	mp := sdkmetric.NewMeterProvider(metricOptions...)
	otel.SetMeterProvider(mp)
	tp := sdktrace.NewTracerProvider(opts...)
	otel.SetTracerProvider(otelpyroscope.NewTracerProvider(tp))
	otel.SetTextMapPropagator(propagation.NewCompositeTextMapPropagator(propagation.TraceContext{}, propagation.Baggage{}))
	var profiler *pyroscope.Profiler
	if endpoint := os.Getenv("PYROSCOPE_SERVER_ADDRESS"); endpoint != "" {
		profiler, err = pyroscope.Start(pyroscope.Config{ApplicationName: service, ServerAddress: endpoint, Tags: tags, ProfileTypes: []pyroscope.ProfileType{pyroscope.ProfileCPU, pyroscope.ProfileAllocObjects, pyroscope.ProfileAllocSpace, pyroscope.ProfileInuseObjects, pyroscope.ProfileInuseSpace}})
		if err != nil {
			return nil, err
		}
	}
	return func(c context.Context) error {
		if profiler != nil {
			_ = profiler.Stop()
		}
		return errors.Join(tp.Shutdown(c), mp.Shutdown(c))
	}, nil
}

// QueryTracer deliberately records an operation name, never SQL literals or bind values.
type QueryTracer struct{}

func (QueryTracer) TraceQueryStart(ctx context.Context, _ *pgx.Conn, d pgx.TraceQueryStartData) context.Context {
	op := "QUERY"
	f := strings.Fields(d.SQL)
	if len(f) > 0 {
		op = strings.ToUpper(f[0])
	}
	ctx, _ = otel.Tracer("parceldesk/postgres").Start(ctx, "postgresql "+op, trace.WithSpanKind(trace.SpanKindClient), trace.WithAttributes(attribute.String("db.system.name", "postgresql"), attribute.String("db.namespace", "parceldesk"), attribute.String("db.operation.name", op)))
	return ctx
}
func (QueryTracer) TraceQueryEnd(ctx context.Context, _ *pgx.Conn, d pgx.TraceQueryEndData) {
	s := trace.SpanFromContext(ctx)
	if d.Err != nil {
		s.RecordError(d.Err)
		s.SetStatus(codes.Error, "database operation failed")
	}
	s.End()
}
