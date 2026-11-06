#!/bin/sh
set -eu

model="${LOCAL_MODEL_NAME:-qwen3-vl:8b-instruct}"
if [ "${MODEL_NAME:-$model}" != "$model" ]; then
  echo "MODEL_NAME and LOCAL_MODEL_NAME must match for local inference. For an external API, start backend/frontend with --no-deps." >&2
  exit 1
fi
case "$model" in
  qwen3-vl:8b-instruct) expected=70e58e37beb15464e19aa903dedb2cba828b89c0fb186f75ff2738c7347b96eb ;;
  qwen3-vl:4b-instruct) expected=84f7ed8042fa7cdbd902f7dcb7d0370e032095047cc3244179f263b77b5bc318 ;;
  *) echo "Unsupported local model tag. Use a verified Qwen tag or an external API." >&2; exit 1 ;;
esac

ollama pull "$model"
variant="${model#*:}"
manifest="/root/.ollama/models/manifests/registry.ollama.ai/library/qwen3-vl/$variant"
printf '%s  %s\n' "$expected" "$manifest" | sha256sum -c -
