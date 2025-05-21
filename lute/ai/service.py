"""
AI Service module for Lute.

Handles communication with various AI providers to get term explanations, translations, etc.
"""

import os
import json
import requests
from abc import ABC, abstractmethod

# For accessing Lute's global settings
from lute.settings.current import current_settings


class AIError(Exception):
    """Custom exception for AI service errors."""


class AIService(ABC):
    """Abstract base class for AI services."""

    def __init__(self, api_key: str, model_name: str = None):
        if not api_key:
            raise ValueError("API key is required.")
        self.api_key = api_key
        self.model_name = model_name

    @abstractmethod
    def _prepare_request_payload(self, prompt: str, **kwargs) -> dict:
        """Prepares the JSON payload for the AI provider."""

    @abstractmethod
    def _call_api(self, payload: dict) -> dict:
        """Makes the actual HTTP request to the AI provider."""

    @abstractmethod
    def _parse_response(self, response_data: dict) -> str:
        """Extracts the relevant text from the AI provider's response."""

    def get_llm_response(self, prompt: str, **kwargs) -> str:
        """
        Generic method to get a response from the LLM.
        """
        if not prompt:
            raise ValueError("Prompt cannot be empty.")

        try:
            payload = self._prepare_request_payload(prompt, **kwargs)
            raw_response = self._call_api(payload)
            return self._parse_response(raw_response)
        except requests.exceptions.RequestException as e:
            raise AIError(f"Network error connecting to AI service: {e}") from e
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            raise AIError(f"Error parsing AI service response: {e}") from e
        # AIError from _call_api (e.g. HTTP status error) will propagate

    def get_contextual_explanation(
        self, term_text: str, context_sentence: str, language: str, custom_prompt_template: str
    ) -> str:
        """
        Generates a contextual explanation for a term.
        """
        prompt = custom_prompt_template.format(
            term=term_text,
            context=context_sentence,
            lang=language
        )
        return self.get_llm_response(prompt)

    def get_translation(
        self, term_text: str, language: str, target_language: str, custom_prompt_template: str
    ) -> str:
        """
        Generates a translation for a term.
        """
        # Note: target_language might not always be used if the prompt template implies it.
        prompt = custom_prompt_template.format(
            term=term_text,
            lang=language,
            target_lang=target_language 
        )
        return self.get_llm_response(prompt)


class OpenAIService(AIService):
    """OpenAI service client."""

    DEFAULT_MODEL = "gpt-3.5-turbo"
    API_ENDPOINT = "https://api.openai.com/v1/chat/completions"

    def __init__(self, api_key: str, model_name: str = None):
        super().__init__(api_key, model_name or self.DEFAULT_MODEL)

    def _prepare_request_payload(self, prompt: str, **kwargs) -> dict:
        return {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": kwargs.get("temperature", 0.7),
            "max_tokens": kwargs.get("max_tokens", 150),
        }

    def _call_api(self, payload: dict) -> dict:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        response = requests.post(self.API_ENDPOINT, headers=headers, json=payload, timeout=30)
        if response.status_code != 200:
            err_msg = response.json().get("error", {}).get("message", response.text)
            raise AIError(f"OpenAI API error ({response.status_code}): {err_msg}")
        return response.json()

    def _parse_response(self, response_data: dict) -> str:
        return response_data["choices"][0]["message"]["content"].strip()


class GeminiService(AIService):
    """Google Gemini service client."""

    DEFAULT_MODEL = "gemini-pro" # Or gemini-1.5-flash, etc.
    # Note: v1beta is more current for some models as of mid-2024
    API_ENDPOINT_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:{method}"


    def __init__(self, api_key: str, model_name: str = None):
        super().__init__(api_key, model_name or self.DEFAULT_MODEL)

    def _prepare_request_payload(self, prompt: str, **kwargs) -> dict:
        # Gemini has specific generationConfig
        generation_config = {
            "temperature": kwargs.get("temperature", 0.7),
            "maxOutputTokens": kwargs.get("max_tokens", 150),
        }
        return {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": generation_config
        }

    def _call_api(self, payload: dict) -> dict:
        url = self.API_ENDPOINT_TEMPLATE.format(model=self.model_name, method="generateContent")
        headers = {"Content-Type": "application/json"}
        # API key is part of the URL for Gemini's REST API
        response = requests.post(f"{url}?key={self.api_key}", headers=headers, json=payload, timeout=30)

        if response.status_code != 200:
            error_details = response.json().get("error", {})
            err_msg = error_details.get("message", response.text)
            # Gemini might also have details in error_details.get("details")
            raise AIError(f"Gemini API error ({response.status_code}): {err_msg}")
        return response.json()

    def _parse_response(self, response_data: dict) -> str:
        # Ensure candidates exist and have content and parts
        if not response_data.get("candidates") or \
           not response_data["candidates"][0].get("content") or \
           not response_data["candidates"][0]["content"].get("parts"):
            raise AIError("Invalid response structure from Gemini: Missing candidates, content, or parts.")
        return response_data["candidates"][0]["content"]["parts"][0]["text"].strip()


class ClaudeService(AIService):
    """Anthropic Claude service client."""

    DEFAULT_MODEL = "claude-3-haiku-20240307" # A cost-effective and fast model
    API_ENDPOINT = "https://api.anthropic.com/v1/messages"

    def __init__(self, api_key: str, model_name: str = None):
        super().__init__(api_key, model_name or self.DEFAULT_MODEL)

    def _prepare_request_payload(self, prompt: str, **kwargs) -> dict:
        return {
            "model": self.model_name,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": kwargs.get("max_tokens", 1024), # Claude's max_tokens is different from OpenAI's
            "temperature": kwargs.get("temperature", 0.7),
        }

    def _call_api(self, payload: dict) -> dict:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }
        response = requests.post(self.API_ENDPOINT, headers=headers, json=payload, timeout=30)
        if response.status_code != 200:
            err_details = response.json().get("error", {})
            err_type = err_details.get("type")
            err_msg = err_details.get("message", response.text)
            raise AIError(f"Claude API error ({response.status_code} - {err_type}): {err_msg}")
        return response.json()

    def _parse_response(self, response_data: dict) -> str:
        # Claude's response structure is a list of content blocks
        if not response_data.get("content") or not isinstance(response_data["content"], list) or \
           not response_data["content"][0].get("text"):
            raise AIError("Invalid response structure from Claude: Missing content or text.")
        return response_data["content"][0]["text"].strip()


# Factory function to get the appropriate AI service
def get_ai_service():
    """
    Factory function to instantiate and return an AI service client
    based on current Lute settings.
    Returns None if AI integration is not configured or provider is unknown.
    """
    provider = current_settings.get("ai_provider")
    api_key = current_settings.get("ai_api_key")

    if not provider or not api_key:
        # Consider logging this instead of print, or return a specific status/exception
        # print("AI provider or API key not configured.")
        return None

    # Optionally, get model_name from settings too, if we add that to settings
    # model_name = current_settings.get(f"{provider}_model_name") 

    if provider == "openai":
        return OpenAIService(api_key=api_key) # model_name=model_name if configured
    if provider == "gemini":
        return GeminiService(api_key=api_key) # model_name=model_name
    if provider == "claude":
        return ClaudeService(api_key=api_key) # model_name=model_name
    
    # print(f"Unknown AI provider: {provider}")
    return None

# Example usage (for testing or integration into Lute):
# if __name__ == '__main__':
#     # This part would require lute.settings.current.current_settings to be populated,
#     # typically by running the Lute app or a mock setup.
#     # For standalone testing, you might mock current_settings or manually set them.
#
#     # Mock current_settings for local testing:
#     current_settings["ai_provider"] = "openai"  # or "gemini" or "claude"
#     current_settings["ai_api_key"] = os.environ.get("OPENAI_API_KEY") # Load from env for testing
#     # current_settings["ai_api_key"] = os.environ.get("GEMINI_API_KEY")
#     # current_settings["ai_api_key"] = os.environ.get("CLAUDE_API_KEY")
# 
#     # Prompts would also come from settings
#     current_settings["ai_prompt_translation"] = "Translate this to Spanish: {text}"
#     current_settings["ai_prompt_summary"] = "Summarize this: {text}"
#     current_settings["ai_prompt_explanation"] = \
#          "Explain the term \"{term}\" in the context of \"{context}\" (language: {lang})."

#     ai_client = get_ai_service()
# 
#     if ai_client:
#         try:
#             term_to_explain = "consternation"
#             sentence_context = "The news filled him with consternation."
#             language_name = "English"
#             explanation_prompt_template = current_settings["ai_prompt_explanation"]
# 
#             explanation = ai_client.get_contextual_explanation(
#                 term_to_explain, sentence_context, language_name, explanation_prompt_template
#             )
#             print(f"\nExplanation for '{term_to_explain}':\n{explanation}")
# 
#             text_to_translate = "Hello, world!"
#             translation_prompt_template = current_settings["ai_prompt_translation"]
#             translation = ai_client.get_translation(
#                  text_to_translate, "English", "Spanish", translation_prompt_template
#             )
#             print(f"\nTranslation of '{text_to_translate}':\n{translation}")
# 
#         except AIError as e:
#             print(f"An AI error occurred: {e}")
#         except ValueError as e:
#             print(f"Input error: {e}")
#     else:
#         print("AI service could not be initialized. Check settings.")
