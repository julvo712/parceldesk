import os
from pathlib import Path

def secret(name: str, env: str = '') -> str:
    p=Path(os.getenv('SECRETS_DIR','/run/secrets'))/name
    return p.read_text().strip() if p.exists() else os.getenv(env,'')

SERVICE_TOKEN=secret('service_token','INTERNAL_SERVICE_TOKEN')
SESSION_KEY=secret('session_key','SESSION_KEY')
CLOUD_TOKEN=secret('cloud_token','AGENTO11Y_AUTH_TOKEN')
ANTHROPIC_KEY=secret('anthropic_key','ANTHROPIC_API_KEY')
OPS_URL=os.getenv('OPERATIONS_URL','http://operations:8080')
AGENT_DIR=Path(os.getenv('AGENT_DIR','/app/agents/replacement'))
PROVIDER=os.getenv('LLM_PROVIDER','anthropic')
GEMINI_KEY=secret('gemini_key','GEMINI_API_KEY')
OPENAI_KEY=secret('openai_key','OPENAI_API_KEY')
MODEL=os.getenv('LLM_MODEL',{'gemini':'gemini-2.5-flash','openai':'gpt-4.1-mini-2025-04-14','anthropic':'claude-sonnet-4-5-20250929'}[PROVIDER])
GRAPH_URL=os.getenv('GRAFANA_URL','https://demotests.grafana.net')
GEN_ENDPOINT=os.getenv('AGENTO11Y_ENDPOINT','https://agento11y-prod-eu-west-2.grafana.net')
CLOUD_TENANT=os.getenv('CLOUD_TENANT','1708469')
