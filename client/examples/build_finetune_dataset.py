"""
A real "chunk of work" toward building an LLM, run on Omnigrid: distributed
synthetic instruction-dataset generation.

This isn't distributed training -- Omnigrid can't do that (no synchronized
gradients, no shared optimizer state, providers can join/drop anytime). What
it's genuinely good at is exactly this shape: N independent jobs, one per
topic, each asking whichever model is currently hosted on the network to
write instruction/response pairs for that topic. No coordination needed
between jobs, and every provider online works on a different topic in
parallel.

Run it:
    cd client
    .venv/bin/python3 examples/build_finetune_dataset.py --api-key YOUR_KEY

Produces finetune_dataset.jsonl, shaped for fine-tuning:
    {"instruction": "...", "response": "..."}
"""

import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import client_sdk as cc

TOPICS = [
    "how photosynthesis works",
    "the causes of the French Revolution",
    "how a hash table resolves collisions",
    "why the sky is blue",
    "the difference between TCP and UDP",
]


def generate_pairs_for_topic(topic: str, *, model_name: str, api_key: str, coordinator: str) -> list[dict]:
    prompt = (
        f"Write 3 instruction/response training pairs about '{topic}', "
        'as a JSON list like [{"instruction": "...", "response": "..."}]. '
        "Return only the JSON, nothing else."
    )
    text = cc.run_llm_infer(
        prompt, model_name=model_name, api_key=api_key, coordinator=coordinator,
        max_tokens=512, timeout_s=120, max_wait_s=180,
    )
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print(f"[{topic}] model didn't return clean JSON, skipping: {text[:200]!r}", file=sys.stderr)
        return []


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--coordinator", default="https://chanza.ai")
    parser.add_argument("--model", default="qwen3-8b-m4", help="see chanza.ai for what's currently hosted")
    parser.add_argument("--out", default="finetune_dataset.jsonl")
    args = parser.parse_args()

    pairs = []
    with ThreadPoolExecutor(max_workers=len(TOPICS)) as pool:
        futures = {
            pool.submit(generate_pairs_for_topic, topic, model_name=args.model,
                        api_key=args.api_key, coordinator=args.coordinator): topic
            for topic in TOPICS
        }
        for future in as_completed(futures):
            topic = futures[future]
            topic_pairs = future.result()
            print(f"[{topic}] got {len(topic_pairs)} pairs")
            pairs.extend(topic_pairs)

    with open(args.out, "w") as f:
        for pair in pairs:
            f.write(json.dumps(pair) + "\n")
    print(f"Wrote {len(pairs)} training pairs to {args.out}")


if __name__ == "__main__":
    main()
