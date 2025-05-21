"""
Integration tests for AI-related routes in the read module.
"""

import json
from unittest.mock import patch, MagicMock
import pytest

from lute.ai.service import AIError
# Assuming app_context and client fixtures are available from conftest.py

# pylint: disable=missing-function-docstring, too-many-arguments

@pytest.fixture(name="mock_ai_service_client")
def fixture_mock_ai_service_client():
    """Creates a mock AI service client."""
    client = MagicMock()
    client.get_contextual_explanation = MagicMock()
    return client

@patch('lute.read.routes.current_settings') # To control settings like prompt
@patch('lute.read.routes.get_ai_service')   # To inject our mock client or None
def test_ai_explanation_success(
    mock_get_ai_service, mock_current_settings, client, mock_ai_service_client
):
    # Setup mocks
    mock_ai_service_client.get_contextual_explanation.return_value = "This is an AI explanation."
    mock_get_ai_service.return_value = mock_ai_service_client
    
    mock_current_settings.get.side_effect = lambda key, default='': {
        "ai_prompt_explanation": "Explain {term} in {context} for {lang}.",
        # Assume ai_provider and ai_api_key are set for get_ai_service to return a client
        "ai_provider": "mock_provider", 
        "ai_api_key": "mock_key"
    }.get(key, default)

    payload = {
        "term_text": "test term",
        "sentence_context": "This is a sentence with the test term.",
        "language_name": "English"
    }
    response = client.post('/read/ai_explanation', json=payload)

    assert response.status_code == 200
    data = response.json
    assert data["explanation"] == "This is an AI explanation."
    assert data["error"] is None
    
    mock_ai_service_client.get_contextual_explanation.assert_called_once_with(
        term_text="test term",
        context_sentence="This is a sentence with the test term.",
        language="English",
        custom_prompt_template="Explain {term} in {context} for {lang}."
    )

@patch('lute.read.routes.current_settings')
@patch('lute.read.routes.get_ai_service')
def test_ai_explanation_ai_error(
    mock_get_ai_service, mock_current_settings, client, mock_ai_service_client
):
    mock_ai_service_client.get_contextual_explanation.side_effect = AIError("AI service down")
    mock_get_ai_service.return_value = mock_ai_service_client
    mock_current_settings.get.return_value = "Explain {term}..." # Dummy prompt

    payload = {
        "term_text": "test term",
        "sentence_context": "This is a sentence.",
        "language_name": "English"
    }
    response = client.post('/read/ai_explanation', json=payload)

    assert response.status_code == 500
    data = response.json
    assert data["explanation"] is None
    assert data["error"] == "AI service down"

@patch('lute.read.routes.get_ai_service')
def test_ai_explanation_ai_not_configured(mock_get_ai_service, client):
    mock_get_ai_service.return_value = None # Simulate AI not configured

    payload = {
        "term_text": "test term",
        "sentence_context": "This is a sentence.",
        "language_name": "English"
    }
    response = client.post('/read/ai_explanation', json=payload)

    assert response.status_code == 400 # Changed from 500 to 400 as per route logic
    data = response.json
    assert data["explanation"] is None
    assert "AI service not available" in data["error"] or \
           "AI provider not selected" in data["error"] or \
           "AI API key not set" in data["error"]


def test_ai_explanation_missing_payload(client):
    response = client.post('/read/ai_explanation', data="not json") # Not sending json
    assert response.status_code == 400
    data = response.json
    assert data["explanation"] is None
    assert data["error"] == "Missing JSON payload"

@pytest.mark.parametrize("missing_field", ["term_text", "sentence_context", "language_name"])
def test_ai_explanation_missing_fields_in_payload(client, missing_field):
    payload = {
        "term_text": "test term",
        "sentence_context": "This is a sentence.",
        "language_name": "English"
    }
    del payload[missing_field] # Remove one required field

    response = client.post('/read/ai_explanation', json=payload)
    assert response.status_code == 400
    data = response.json
    assert data["explanation"] is None
    assert data["error"] == "Missing required data: term_text, sentence_context, or language_name"

@patch('lute.read.routes.current_settings')
@patch('lute.read.routes.get_ai_service')
def test_ai_explanation_unexpected_error(
    mock_get_ai_service, mock_current_settings, client, mock_ai_service_client
):
    # Simulate an unexpected error other than AIError
    mock_ai_service_client.get_contextual_explanation.side_effect = Exception("Something broke badly")
    mock_get_ai_service.return_value = mock_ai_service_client
    mock_current_settings.get.return_value = "Explain {term}..."

    payload = {
        "term_text": "test term",
        "sentence_context": "This is a sentence.",
        "language_name": "English"
    }
    response = client.post('/read/ai_explanation', json=payload)

    assert response.status_code == 500
    data = response.json
    assert data["explanation"] is None
    assert "An unexpected error occurred: Something broke badly" in data["error"]
