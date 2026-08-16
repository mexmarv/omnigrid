"""
LlamaCppBackend tests: supervises a persistent `llama-server` subprocess
instead of reloading a model per job. Everything here mocks subprocess.Popen
and the backend's HTTP session -- no real llama-server binary or GPU
required.
"""

import io

import pytest
import requests

from inference.errors import BackendUnavailableError
from inference.llamacpp_backend import LlamaCppBackend
from inference.types import GenerateRequest, Message


class FakeProcess:
    def __init__(self, exit_code=None):
        self._alive = exit_code is None
        self.returncode = exit_code
        self.terminate_called = False
        self.kill_called = False
        self.stdout = io.StringIO("llama-server: model loaded\n")

    def poll(self):
        return None if self._alive else self.returncode

    def terminate(self):
        self.terminate_called = True
        self._alive = False
        self.returncode = 0

    def wait(self, timeout=None):
        return self.returncode

    def kill(self):
        self.kill_called = True
        self._alive = False


class FakePopenFactory:
    def __init__(self, exit_code=None):
        self.calls = []
        self.exit_code = exit_code
        self.processes = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        proc = FakeProcess(exit_code=self.exit_code)
        self.processes.append(proc)
        return proc


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self):
        self.headers = {}
        self.get_calls = 0
        self.post_calls = []
        self.get_status = 200
        self.post_response = FakeResponse(200, {
            "choices": [{"message": {"content": "a description"}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 6},
        })
        self.post_side_effect = None

    def get(self, url, timeout=None):
        self.get_calls += 1
        return FakeResponse(self.get_status)

    def post(self, url, json=None, timeout=None):
        self.post_calls.append((url, json))
        if self.post_side_effect:
            raise self.post_side_effect
        return self.post_response

    def close(self):
        pass


def _request(text="describe this"):
    return GenerateRequest(messages=[Message(role="user", content=text)], max_output_tokens=64)


@pytest.fixture
def fake_session(monkeypatch):
    session = FakeSession()
    monkeypatch.setattr("inference.llamacpp_backend.requests.Session", lambda: session)
    return session


@pytest.fixture
def fast_poll(monkeypatch):
    async def _no_sleep(_):
        return None
    monkeypatch.setattr("inference.llamacpp_backend.asyncio.sleep", _no_sleep)


@pytest.fixture
def binary_present(monkeypatch):
    monkeypatch.setattr("inference.llamacpp_backend.shutil.which", lambda name: "/usr/local/bin/" + name)


async def test_health_fails_cleanly_when_binary_missing(monkeypatch, fake_session):
    monkeypatch.setattr("inference.llamacpp_backend.shutil.which", lambda name: None)
    backend = LlamaCppBackend("/models/model.gguf")
    health = await backend.health()
    assert health.healthy is False
    assert "llama-server" in health.detail
    assert "not found" in health.detail


async def test_generate_raises_when_binary_missing(monkeypatch, fake_session):
    monkeypatch.setattr("inference.llamacpp_backend.shutil.which", lambda name: None)
    backend = LlamaCppBackend("/models/model.gguf")
    with pytest.raises(BackendUnavailableError):
        await backend.generate(_request())


async def test_starts_server_once_and_reuses_it_across_jobs(monkeypatch, fake_session, binary_present):
    popen = FakePopenFactory()
    monkeypatch.setattr("inference.llamacpp_backend.subprocess.Popen", popen)
    backend = LlamaCppBackend("/models/model.gguf", port=8123)

    for _ in range(3):
        response = await backend.generate(_request())
        assert response.text == "a description"

    assert len(popen.calls) == 1  # the model process was only ever launched once
    assert len(fake_session.post_calls) == 3
    launch_args = popen.calls[0]
    assert "/models/model.gguf" in launch_args


async def test_startup_failure_when_process_exits_immediately(monkeypatch, fake_session, binary_present):
    popen = FakePopenFactory(exit_code=1)
    monkeypatch.setattr("inference.llamacpp_backend.subprocess.Popen", popen)
    backend = LlamaCppBackend("/models/model.gguf", port=8124)

    with pytest.raises(BackendUnavailableError, match="exited during startup"):
        await backend.generate(_request())


async def test_startup_timeout_when_never_healthy(monkeypatch, fake_session, binary_present, fast_poll):
    popen = FakePopenFactory()
    monkeypatch.setattr("inference.llamacpp_backend.subprocess.Popen", popen)
    fake_session.get_status = 503  # never reports healthy
    backend = LlamaCppBackend("/models/model.gguf", port=8125, startup_timeout_s=0.05)

    with pytest.raises(BackendUnavailableError, match="did not become healthy"):
        await backend.generate(_request())
    assert popen.processes[0].terminate_called  # cleaned up, not left running


async def test_crash_during_generation_marks_backend_for_restart(monkeypatch, fake_session, binary_present):
    popen = FakePopenFactory()
    monkeypatch.setattr("inference.llamacpp_backend.subprocess.Popen", popen)
    backend = LlamaCppBackend("/models/model.gguf", port=8126)

    await backend.generate(_request())  # starts the server successfully
    fake_session.post_side_effect = requests.ConnectionError("broken pipe")
    with pytest.raises(BackendUnavailableError):
        await backend.generate(_request())
    assert backend._proc is None  # next generate() call will attempt a fresh start


async def test_image_content_is_attached_to_last_message(monkeypatch, fake_session, binary_present):
    popen = FakePopenFactory()
    monkeypatch.setattr("inference.llamacpp_backend.subprocess.Popen", popen)
    backend = LlamaCppBackend("/models/vlm.gguf", mmproj_path="/models/mmproj.gguf", port=8127)

    request = GenerateRequest(
        messages=[Message(role="user", content="what is this?")],
        max_output_tokens=64, image_b64="ZmFrZQ==", image_mime="image/png",
    )
    await backend.generate(request)

    _, payload = fake_session.post_calls[0]
    content = payload["messages"][-1]["content"]
    assert isinstance(content, list)
    assert content[0] == {"type": "text", "text": "what is this?"}
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


async def test_close_terminates_the_process(monkeypatch, fake_session, binary_present):
    popen = FakePopenFactory()
    monkeypatch.setattr("inference.llamacpp_backend.subprocess.Popen", popen)
    backend = LlamaCppBackend("/models/model.gguf", port=8128)
    await backend.generate(_request())

    proc = popen.processes[0]
    await backend.close()
    assert proc.terminate_called
