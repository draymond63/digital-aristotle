from types import SimpleNamespace
from unittest.mock import Mock, patch
import os

from brains.comms.agent_base import Agent, Task, get_control_model, get_teacher_model


def test_task_ollama_model_routes_to_ollama_client():
    fake_client = Mock()
    fake_client.chat.return_value = SimpleNamespace(
        message=SimpleNamespace(content="hello")
    )

    with (
        patch.dict(os.environ, {}, clear=True),
        patch("brains.comms.agent_base.dotenv.load_dotenv"),
        patch("brains.comms.agent_base.Client", return_value=fake_client),
    ):
        agent = Agent()
        task = Task("test", "You are concise.", model="qwen2.5:3b-instruct-q4_K_M")
        assert agent.run_task(task) == "hello"

    request = fake_client.chat.call_args.kwargs
    assert request["model"] == "qwen2.5:3b-instruct-q4_K_M"


def test_openai_model_routes_to_openai_client():
    fake_client = Mock()
    fake_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="hello")
            )
        ]
    )

    with (
        patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-key",
            },
            clear=True,
        ),
        patch("brains.comms.agent_base.dotenv.load_dotenv"),
        patch("brains.comms.agent_base.OpenAI", return_value=fake_client),
    ):
        agent = Agent()
        task = Task("test", "You are concise.", model="gpt-test")
        assert agent.run_task(task) == "hello"

    request = fake_client.chat.completions.create.call_args.kwargs
    assert request["model"] == "gpt-test"


def test_missing_task_model_fails():
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("brains.comms.agent_base.dotenv.load_dotenv"),
    ):
        agent = Agent()
        try:
            agent.run_task(Task("test", "You are concise."))
        except ValueError as error:
            assert str(error) == "Task model must be specified"
        else:
            raise AssertionError("Expected missing task model to fail")


def test_model_helpers_use_local_models_without_use_api():
    with (
        patch.dict(os.environ, {}, clear=True),
        patch("brains.comms.agent_base.dotenv.load_dotenv"),
    ):
        assert get_teacher_model() == "phi4-mini:3.8b-q4_K_M"
        assert get_control_model() == "qwen2.5:3b-instruct-q4_K_M"


def test_model_helpers_use_api_model_when_use_api_is_present():
    with (
        patch.dict(os.environ, {"USE_API": "1"}, clear=True),
        patch("brains.comms.agent_base.dotenv.load_dotenv"),
    ):
        assert get_teacher_model() == "gpt-4.1-mini"
        assert get_control_model() == "gpt-4.1-mini"


def test_can_mix_task_providers():
    fake_ollama_client = Mock()
    fake_ollama_client.chat.return_value = SimpleNamespace(
        message=SimpleNamespace(content="local")
    )
    fake_openai_client = Mock()
    fake_openai_client.chat.completions.create.return_value = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content="hello")
            )
        ]
    )

    with (
        patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}, clear=True),
        patch("brains.comms.agent_base.dotenv.load_dotenv"),
        patch("brains.comms.agent_base.Client", return_value=fake_ollama_client),
        patch("brains.comms.agent_base.OpenAI", return_value=fake_openai_client),
    ):
        agent = Agent()
        local_task = Task("local", "You are concise.", model="qwen2.5:3b-instruct-q4_K_M")
        api_task = Task("api", "You are concise.", model="gpt-test")
        assert agent.run_task(local_task) == "local"
        assert agent.run_task(api_task) == "hello"

    request = fake_openai_client.chat.completions.create.call_args.kwargs
    assert request["model"] == "gpt-test"


if __name__ == "__main__":
    test_task_ollama_model_routes_to_ollama_client()
    test_openai_model_routes_to_openai_client()
    test_missing_task_model_fails()
    test_model_helpers_use_local_models_without_use_api()
    test_model_helpers_use_api_model_when_use_api_is_present()
    test_can_mix_task_providers()
    print("agent provider tests passed")
