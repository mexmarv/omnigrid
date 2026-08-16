#!/bin/bash
# Downloads SmolVLM-256M-Instruct (GGUF text model + vision projector) into
# ../models, next to SmolLM2-135M-Instruct-Q4_K_M.gguf, for local
# image-recognition testing via test_vlm_local.py -- no coordinator round trip.
set -e
cd "$(dirname "$0")/../models"
BASE_URL="https://huggingface.co/ggml-org/SmolVLM-256M-Instruct-GGUF/resolve/main"
curl -L -o SmolVLM-256M-Instruct-Q8_0.gguf "$BASE_URL/SmolVLM-256M-Instruct-Q8_0.gguf"
curl -L -o mmproj-SmolVLM-256M-Instruct-Q8_0.gguf "$BASE_URL/mmproj-SmolVLM-256M-Instruct-Q8_0.gguf"
echo "Done. Files are in $(pwd)"
