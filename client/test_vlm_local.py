#!/usr/bin/env python3
"""
Direct local test of a GGUF vision-language model (SmolVLM-256M-Instruct) via
llama-cpp-python. Bypasses the omnigrid coordinator/job-queue entirely --
loads the model straight from disk and runs one image-description prompt
on this machine.

Usage:
    .venv/bin/python3 test_vlm_local.py <image_path> ["prompt"]
"""

import base64
import mimetypes
import os
import sys

from llama_cpp import Llama
from llama_cpp.llama_chat_format import MTMDChatHandler

MODEL_PATH = "../models/SmolVLM-256M-Instruct-Q8_0.gguf"
MMPROJ_PATH = "../models/mmproj-SmolVLM-256M-Instruct-Q8_0.gguf"


def main():
    if len(sys.argv) < 2:
        raise SystemExit(f'Usage: {sys.argv[0]} <image_path> ["prompt"]')
    image_path = sys.argv[1]
    prompt = sys.argv[2] if len(sys.argv) > 2 else "Describe this image in detail."

    mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode()

    chat_handler = MTMDChatHandler(clip_model_path=MMPROJ_PATH, verbose=False)
    llm = Llama(
        model_path=MODEL_PATH,
        chat_handler=chat_handler,
        n_ctx=2048,
        n_gpu_layers=-1,
        verbose=False,
    )
    completion = llm.create_chat_completion(
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
            ],
        }],
        max_tokens=512,
    )
    print(completion["choices"][0]["message"]["content"])

    # llama.cpp's Metal backend has a known cleanup-on-exit assertion bug
    # (ggml-metal-device.m, triggered during normal interpreter shutdown).
    # The result above is already correct and printed -- flush it, then skip
    # Python's object-teardown/atexit path entirely so it can't crash on the
    # way out (os._exit doesn't flush stdio buffers itself).
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
