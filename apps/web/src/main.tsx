import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './style.css';
// Load telemetry separately so the first screen does not wait for the tracing SDK.
if (import.meta.env.VITE_FARO_ENABLED !== 'false') void import('./telemetry').then(({ startTelemetry }) => startTelemetry()).catch(() => { /* Application remains usable; collector health is checked by the presenter. */ });
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>);
