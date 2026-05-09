#!/bin/sh
set -eu

OPTIONS="/data/options.json"

# Read Home Assistant add-on options from JSON (UTF-8)
GATEWAY_API_KEY="$(python -c "import json;print(json.load(open('${OPTIONS}','r',encoding='utf-8')).get('gateway_api_key',''))")"
HA_URL="$(python -c "import json;print(json.load(open('${OPTIONS}','r',encoding='utf-8')).get('ha_url','http://supervisor/core'))")"
HA_TOKEN_OPT="$(python -c "import json;print(json.load(open('${OPTIONS}','r',encoding='utf-8')).get('ha_token',''))")"
USE_SUP="$(python -c "import json;print('1' if json.load(open('${OPTIONS}','r',encoding='utf-8')).get('use_supervisor_token', True) else '0')")"
SH_CORE_ROOT="$(python -c "import json;print(json.load(open('${OPTIONS}','r',encoding='utf-8')).get('sh_core_root','/app/app'))")"
LOG_DIR="$(python -c "import json;print(json.load(open('${OPTIONS}','r',encoding='utf-8')).get('log_dir','/data'))")"
HA_VERIFY_TLS="$(python -c "import json;print('1' if json.load(open('${OPTIONS}','r',encoding='utf-8')).get('ha_verify_tls', True) else '0')")"
HA_TIMEOUT_S="$(python -c "import json;print(str(json.load(open('${OPTIONS}','r',encoding='utf-8')).get('ha_timeout_s', 10)))")"
LLM_BASE_URL="$(python -c "import json;print(json.load(open('${OPTIONS}','r',encoding='utf-8')).get('llm_base_url',''))")"
LLM_MODEL="$(python -c "import json;print(json.load(open('${OPTIONS}','r',encoding='utf-8')).get('llm_model',''))")"

# Prefer explicit ha_token. If empty and use_supervisor_token=true, fall back to SUPERVISOR_TOKEN.
HA_TOKEN="${HA_TOKEN_OPT}"
if [ -z "${HA_TOKEN}" ] && [ "${USE_SUP}" = "1" ] && [ -n "${SUPERVISOR_TOKEN:-}" ]; then
  HA_TOKEN="${SUPERVISOR_TOKEN}"
fi

export GATEWAY_API_KEY="${GATEWAY_API_KEY}"
export HA_URL="${HA_URL}"
export HA_TOKEN="${HA_TOKEN}"
export SH_CORE_ROOT="${SH_CORE_ROOT}"
export GATEWAY_LOG_DIR="${LOG_DIR}"
export HA_VERIFY_TLS="${HA_VERIFY_TLS}"
export HA_TIMEOUT_S="${HA_TIMEOUT_S}"
if [ -n "${LLM_BASE_URL}" ]; then
  export LLM_BASE_URL="${LLM_BASE_URL}"
fi
if [ -n "${LLM_MODEL}" ]; then
  export LLM_MODEL="${LLM_MODEL}"
fi

cd /app/app
exec python -m uvicorn smarthome_gateway.main:app --host 0.0.0.0 --port 8099
