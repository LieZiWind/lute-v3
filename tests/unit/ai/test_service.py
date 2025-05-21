"""
Unit tests for the AI service module.
"""

import pytest
from unittest.mock import patch, MagicMock
import requests

from lute.ai.service import (
    OpenAIService,
    GeminiService,
    ClaudeService,
    get_ai_service,
    AIError,
)
from lute.settings.current import current_settings # To mock it

# pylint: disable=missing-function-docstring, too-many-arguments


@pytest.fixture(name="mock_current_settings")
def fixture_mock_current_settings():
    """Fixture to mock lute.settings.current.current_settings."""
    with patch('lute.ai.service.current_settings', new_callable=MagicMock) as mock_settings:
        # Set default mock values, can be overridden in tests
        mock_settings.get.side_effect = lambda key, default='': {
            "ai_provider": "openai",
            "ai_api_key": "test_key_openai",
            "ai_prompt_explanation": "Explain {term} in {context} for {lang}.",
            "ai_prompt_translation": "Translate {term} to {target_lang} ({lang}).",
        }.get(key, default)
        yield mock_settings


class TestGetAIService:
    """Tests for the get_ai_service factory function."""

    def test_get_openai_service(self, mock_current_settings):
        mock_current_settings.get.side_effect = lambda key, default='': {
            "ai_provider": "openai", "ai_api_key": "key_openai"
        }.get(key, default)
        service = get_ai_service()
        assert isinstance(service, OpenAIService)
        assert service.api_key == "key_openai"

    def test_get_gemini_service(self, mock_current_settings):
        mock_current_settings.get.side_effect = lambda key, default='': {
            "ai_provider": "gemini", "ai_api_key": "key_gemini"
        }.get(key, default)
        service = get_ai_service()
        assert isinstance(service, GeminiService)
        assert service.api_key == "key_gemini"

    def test_get_claude_service(self, mock_current_settings):
        mock_current_settings.get.side_effect = lambda key, default='': {
            "ai_provider": "claude", "ai_api_key": "key_claude"
        }.get(key, default)
        service = get_ai_service()
        assert isinstance(service, ClaudeService)
        assert service.api_key == "key_claude"

    def test_no_provider_configured(self, mock_current_settings):
        mock_current_settings.get.side_effect = lambda key, default='': {
            "ai_provider": "", "ai_api_key": "some_key" # No provider
        }.get(key, default)
        assert get_ai_service() is None

    def test_no_api_key_configured(self, mock_current_settings):
        mock_current_settings.get.side_effect = lambda key, default='': {
            "ai_provider": "openai", "ai_api_key": "" # No API key
        }.get(key, default)
        assert get_ai_service() is None

    def test_unknown_provider(self, mock_current_settings):
        mock_current_settings.get.side_effect = lambda key, default='': {
            "ai_provider": "unknown_provider", "ai_api_key": "some_key"
        }.get(key, default)
        assert get_ai_service() is None


@pytest.mark.parametrize("service_class, default_model, api_key_name, mock_success_response, expected_text, mock_api_error_response, mock_api_error_message_path", [
    (OpenAIService, "gpt-3.5-turbo", "openai_key",
     {"choices": [{"message": {"content": " OpenAI explanation "}}]}, "OpenAI explanation",
     {"error": {"message": "OpenAI API Error"}}, ["error", "message"]),
    (GeminiService, "gemini-pro", "gemini_key",
     {"candidates": [{"content": {"parts": [{"text": " Gemini explanation "}]}}]}, "Gemini explanation",
     {"error": {"message": "Gemini API Error"}}, ["error", "message"]),
    (ClaudeService, "claude-3-haiku-20240307", "claude_key",
     {"content": [{"type": "text", "text": " Claude explanation "}]}, "Claude explanation",
     {"error": {"type": "auth_error", "message": "Claude API Error"}}, ["error", "message"]),
])
class TestAIServiceProviders:
    """Tests for specific AI service provider classes."""

    def test_init_requires_api_key(self, service_class, default_model, api_key_name, mock_success_response, expected_text, mock_api_error_response, mock_api_error_message_path):
        with pytest.raises(ValueError, match="API key is required."):
            service_class(api_key="")

    def test_init_with_default_model(self, service_class, default_model, api_key_name, mock_success_response, expected_text, mock_api_error_response, mock_api_error_message_path):
        service = service_class(api_key="test_key")
        assert service.model_name == default_model

    def test_init_with_custom_model(self, service_class, default_model, api_key_name, mock_success_response, expected_text, mock_api_error_response, mock_api_error_message_path):
        service = service_class(api_key="test_key", model_name="custom-model")
        assert service.model_name == "custom-model"

    @patch('requests.post')
    def test_get_llm_response_success(self, mock_post, service_class, default_model, api_key_name, mock_success_response, expected_text, mock_api_error_response, mock_api_error_message_path):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_success_response
        mock_post.return_value = mock_response

        service = service_class(api_key="test_key")
        response = service.get_llm_response("Test prompt")
        assert response == expected_text
        mock_post.assert_called_once() # Verifies _call_api was reached

    @patch('requests.post')
    def test_get_llm_response_api_error(self, mock_post, service_class, default_model, api_key_name, mock_success_response, expected_text, mock_api_error_response, mock_api_error_message_path):
        mock_response = MagicMock()
        mock_response.status_code = 400 # Example client error
        mock_response.json.return_value = mock_api_error_response
        mock_post.return_value = mock_response
        
        # Extract expected error message based on path
        err_msg_val = mock_api_error_response
        for key in mock_api_error_message_path:
            err_msg_val = err_msg_val[key]

        service = service_class(api_key="test_key")
        with pytest.raises(AIError, match=err_msg_val):
            service.get_llm_response("Test prompt")

    @patch('requests.post')
    def test_get_llm_response_network_error(self, mock_post, service_class, default_model, api_key_name, mock_success_response, expected_text, mock_api_error_response, mock_api_error_message_path):
        mock_post.side_effect = requests.exceptions.RequestException("Network issue")
        service = service_class(api_key="test_key")
        with pytest.raises(AIError, match="Network error connecting to AI service: Network issue"):
            service.get_llm_response("Test prompt")

    def test_get_llm_response_empty_prompt(self, service_class, default_model, api_key_name, mock_success_response, expected_text, mock_api_error_response, mock_api_error_message_path):
        service = service_class(api_key="test_key")
        with pytest.raises(ValueError, match="Prompt cannot be empty."):
            service.get_llm_response("")

    @patch.object(OpenAIService, '_call_api', autospec=True) # Patching one specific class for this example
    @patch.object(OpenAIService, '_parse_response', return_value="Parsed content", autospec=True)
    def test_get_contextual_explanation_prompt_formatting(self, mock_parse, mock_call_api, service_class, default_model, api_key_name, mock_success_response, expected_text, mock_api_error_response, mock_api_error_message_path):
        # This test focuses on prompt formatting for OpenAIService, can be adapted for others
        if service_class != OpenAIService:
            pytest.skip("Prompt formatting test specific to OpenAIService structure for this example")

        service = OpenAIService(api_key="test_key_openai")
        prompt_template = "Explain term '{term}' (lang: {lang}) in sentence '{context}'."
        
        service.get_contextual_explanation(
            term_text="apple",
            context_sentence="An apple a day.",
            language="English",
            custom_prompt_template=prompt_template
        )

        # Check the payload passed to _call_api, which comes from _prepare_request_payload
        # This requires _call_api to be called by get_llm_response.
        # We are checking the input to _call_api.
        # The first argument to a method mock is 'self'.
        payload_sent = mock_call_api.call_args[0][1] # self, payload
        expected_prompt_content = "Explain term 'apple' (lang: English) in sentence 'An apple a day.'."
        assert payload_sent["messages"][0]["content"] == expected_prompt_content

    @patch.object(OpenAIService, '_call_api', autospec=True)
    @patch.object(OpenAIService, '_parse_response', return_value="Translated text", autospec=True)
    def test_get_translation_prompt_formatting(self, mock_parse, mock_call_api, service_class, default_model, api_key_name, mock_success_response, expected_text, mock_api_error_response, mock_api_error_message_path):
        if service_class != OpenAIService:
            pytest.skip("Prompt formatting test specific to OpenAIService structure for this example")

        service = OpenAIService(api_key="test_key_openai")
        prompt_template = "Translate '{term}' from {lang} to {target_lang}."
        
        service.get_translation(
            term_text="hello",
            language="English",
            target_language="Spanish",
            custom_prompt_template=prompt_template
        )
        payload_sent = mock_call_api.call_args[0][1]
        expected_prompt_content = "Translate 'hello' from English to Spanish."
        assert payload_sent["messages"][0]["content"] == expected_prompt_content

    @patch('requests.post')
    def test_invalid_response_structure(self, mock_post, service_class, default_model, api_key_name, mock_success_response, expected_text, mock_api_error_response, mock_api_error_message_path):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"unexpected_field": "unexpected_value"} # Invalid structure
        mock_post.return_value = mock_response

        service = service_class(api_key="test_key")
        with pytest.raises(AIError, match="Error parsing AI service response"):
            service.get_llm_response("Test prompt")

# Specific tests for payload structure if they differ significantly beyond the prompt itself.
# For example, if Gemini needs a very different top-level payload structure for some calls.
# The current _prepare_request_payload is quite generic for chat-like interactions.

# Note: The prompt formatting tests are currently specific to OpenAIService's payload.
# To make them generic for all providers in the parameterized test,
# we'd need to know the exact path to the prompt string within each provider's
# _prepare_request_payload structure, or mock _prepare_request_payload itself
# and check the prompt passed to it.
# For now, keeping them specific to OpenAI as an example of how to test it.
# A more robust way would be to have each service class test its own prompt formatting.
# Or, the get_llm_response could be mocked and we check the prompt passed to it.
