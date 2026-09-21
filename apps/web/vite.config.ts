import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({plugins:[react()],server:{proxy:{'/api':'http://127.0.0.1:8000','/control':'http://127.0.0.1:8001','/collect':'http://127.0.0.1:12347'}},build:{rollupOptions:{output:{manualChunks:{observability:['@grafana/faro-web-sdk','@grafana/faro-web-tracing']}}}}});
