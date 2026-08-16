"""Provider model configuration: YAML loading/validation, legacy CLI-flag
translation, and merge-time duplicate detection."""

import pytest

from inference.config import ConfigError, legacy_llamacpp_config, load_model_configs, merge_configs


def test_load_valid_config(tmp_path):
    path = tmp_path / "models.yaml"
    path.write_text("""
models:
  - public_name: qwen3-8b-m4
    backend: ollama
    endpoint: http://127.0.0.1:11434
    local_model: qwen3:8b
    max_context_tokens: 16384
    max_output_tokens: 4096
    max_concurrency: 1
""")
    configs = load_model_configs(str(path))
    assert len(configs) == 1
    assert configs[0].public_name == "qwen3-8b-m4"
    assert configs[0].backend == "ollama"


def test_missing_path_returns_empty_list():
    assert load_model_configs(None) == []


def test_nonexistent_file_raises(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_model_configs(str(tmp_path / "nope.yaml"))


def test_unknown_field_is_rejected(tmp_path):
    path = tmp_path / "models.yaml"
    path.write_text("""
models:
  - public_name: m
    backend: ollama
    local_model: m:latest
    max_context_tokens: 4096
    max_output_tokens: 512
    download_url: http://evil.example/model.bin
""")
    with pytest.raises(ConfigError, match="unsupported field"):
        load_model_configs(str(path))


def test_invalid_backend_is_rejected(tmp_path):
    path = tmp_path / "models.yaml"
    path.write_text("""
models:
  - public_name: m
    backend: shell_exec
    max_context_tokens: 4096
    max_output_tokens: 512
""")
    with pytest.raises(ConfigError, match="backend must be one of"):
        load_model_configs(str(path))


def test_output_exceeding_context_is_rejected(tmp_path):
    path = tmp_path / "models.yaml"
    path.write_text("""
models:
  - public_name: m
    backend: ollama
    local_model: m:latest
    max_context_tokens: 512
    max_output_tokens: 4096
""")
    with pytest.raises(ConfigError, match="max_output_tokens"):
        load_model_configs(str(path))


def test_ollama_requires_local_model(tmp_path):
    path = tmp_path / "models.yaml"
    path.write_text("""
models:
  - public_name: m
    backend: ollama
    max_context_tokens: 4096
    max_output_tokens: 512
""")
    with pytest.raises(ConfigError, match="local_model"):
        load_model_configs(str(path))


def test_duplicate_public_name_is_rejected(tmp_path):
    path = tmp_path / "models.yaml"
    path.write_text("""
models:
  - public_name: m
    backend: ollama
    local_model: m:latest
    max_context_tokens: 4096
    max_output_tokens: 512
  - public_name: m
    backend: ollama
    local_model: m2:latest
    max_context_tokens: 4096
    max_output_tokens: 512
""")
    with pytest.raises(ConfigError, match="duplicate public_name"):
        load_model_configs(str(path))


def test_legacy_llamacpp_config_builds_valid_entry():
    cfg = legacy_llamacpp_config(
        public_name="smollm2-135m", model_path="/models/model.gguf", n_gpu_layers=-1,
    )
    assert cfg.backend == "llamacpp"
    assert cfg.vision is False
    assert cfg.model_path == "/models/model.gguf"


def test_legacy_vlm_config_sets_vision_flag():
    cfg = legacy_llamacpp_config(
        public_name="smolvlm", model_path="/models/vlm.gguf", n_gpu_layers=-1,
        mmproj_path="/models/mmproj.gguf",
    )
    assert cfg.vision is True


def test_merge_configs_detects_cross_source_duplicates(tmp_path):
    path = tmp_path / "models.yaml"
    path.write_text("""
models:
  - public_name: dupe
    backend: ollama
    local_model: m:latest
    max_context_tokens: 4096
    max_output_tokens: 512
""")
    yaml_configs = load_model_configs(str(path))
    legacy = [legacy_llamacpp_config(public_name="dupe", model_path="/x.gguf", n_gpu_layers=0)]
    with pytest.raises(ConfigError, match="duplicate public_name"):
        merge_configs(yaml_configs, legacy)


def test_merge_configs_combines_distinct_sources(tmp_path):
    path = tmp_path / "models.yaml"
    path.write_text("""
models:
  - public_name: a
    backend: ollama
    local_model: m:latest
    max_context_tokens: 4096
    max_output_tokens: 512
""")
    yaml_configs = load_model_configs(str(path))
    legacy = [legacy_llamacpp_config(public_name="b", model_path="/x.gguf", n_gpu_layers=0)]
    merged = merge_configs(yaml_configs, legacy)
    assert {c.public_name for c in merged} == {"a", "b"}
