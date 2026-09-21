import { initializeFaro, getWebInstrumentations } from '@grafana/faro-web-sdk';
import { TracingInstrumentation, getDefaultOTELInstrumentations } from '@grafana/faro-web-tracing';
let initialized = false;
export function startTelemetry() {
  if (initialized) return;
  initialized = true;
  const ownApi = new RegExp(`^${location.origin.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/api(?:/|$)`);
  initializeFaro({
    url: `${location.origin}/collect`,
    app: { name: 'parceldesk-web', version: '1.0.0', environment: 'demo' },
    sessionTracking: { samplingRate: 1 },
    instrumentations: [...getWebInstrumentations({ captureConsole: false }), new TracingInstrumentation({ instrumentations: getDefaultOTELInstrumentations({ propagateTraceHeaderCorsUrls: [ownApi], ignoreUrls: [/\/collect(?:\/|$)/, /\/control(?:\/|$)/] }) })],
    beforeSend: (item) => {
      // Never attach customer identities, input contents or chat text as browser context.
      if (item.meta.user) item.meta.user = {};
      if (item.meta.page?.url) item.meta.page.url = item.meta.page.url.split('?')[0].split('#')[0];
      return item;
    },
  });
}
