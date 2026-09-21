import http from 'k6/http';
import { check } from 'k6';

// One real customer session per VU; exercises Python -> Go -> PostgreSQL.
// This workload never invokes a model or creates a replacement.
export const options = {
  noCookiesReset: true,
  scenarios: { orders: { executor: 'constant-arrival-rate', rate: Number(__ENV.RATE || 10),
    timeUnit: '1s', duration: __ENV.DURATION || '2m', preAllocatedVUs: 5, maxVUs: 10 } },
  thresholds: { http_req_failed: ['rate<0.01'], checks: ['rate>0.99'], dropped_iterations: ['count==0'] },
  tags: { service: 'parceldesk', workload: 'orders', service_version: __ENV.SERVICE_VERSION || 'unknown' },
};
const base = __ENV.BASE_URL || 'http://web:8080';
let signedIn = false;
export default function () {
  if (!signedIn) {
    const response = http.post(`${base}/api/demo-session`, JSON.stringify({ customer_id: 'C1', run_id: __ENV.RUN_ID }),
      { headers: { 'Content-Type': 'application/json' }, tags: { name: 'POST /api/demo-session' } });
    signedIn = check(response, { 'session created': r => r.status === 200 });
    if (!signedIn) return;
  }
  const response = http.get(`${base}/api/orders`, { tags: { name: 'GET /api/orders' } });
  check(response, { 'orders returned': r => r.status === 200 && Array.isArray(r.json('orders')) && r.json('orders').length > 0 });
}
