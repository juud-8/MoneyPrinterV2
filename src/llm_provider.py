import os

import ollama
import requests

from config import (
    get_gemini_api_key,
    get_gemini_model,
    get_llm_provider,
    get_ollama_base_url,
    get_quality_llm_provider,
    get_verbose,
)

_selected_model: str | None = None


def _client() -> ollama.Client:
    return ollama.Client(host=get_ollama_base_url())


def list_models() -> list[str]:
    """
    Lists all models available on the local Ollama server.

    Returns:
        models (list[str]): Sorted list of model names.
    """
    response = _client().list()
    return sorted(m.model for m in response.models)


def select_model(model: str) -> None:
    """
    Sets the model to use for all subsequent generate_text calls.

    Args:
        model (str): An Ollama model name (must be already pulled).
    """
    global _selected_model
    _selected_model = model


def get_active_model() -> str | None:
    """
    Returns the currently selected model, or None if none has been selected.
    """
    return _selected_model


def _generate_gemini(prompt: str, model: str | None = None) -> str:
    api_key = get_gemini_api_key()
    if not api_key:
        raise RuntimeError("Gemini API key not configured for cloud LLM.")

    model_name = model or get_gemini_model()
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{model_name}:generateContent"
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.85,
            "maxOutputTokens": 8192,
        },
    }
    response = requests.post(
        url,
        headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
        json=payload,
        timeout=120,
    )
    response.raise_for_status()
    body = response.json()

    candidates = body.get("candidates", [])
    if not candidates:
        raise RuntimeError(f"Gemini returned no candidates: {body}")

    parts = candidates[0].get("content", {}).get("parts", [])
    text_parts = [p.get("text", "") for p in parts if p.get("text")]
    if not text_parts:
        raise RuntimeError("Gemini returned empty text.")
    return "".join(text_parts).strip()


def _generate_ollama(prompt: str, model_name: str | None) -> str:
    model = model_name or _selected_model
    if not model:
        raise RuntimeError(
            "No Ollama model selected. Call select_model() first or pass model_name."
        )

    response = _client().chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
    )
    return response["message"]["content"].strip()


def generate_text(
    prompt: str,
    model_name: str = None,
    quality: bool = False,
) -> str:
    """
    Generates text using the configured LLM provider.

    Args:
        prompt (str): User prompt
        model_name (str): Optional model name override (Ollama or Gemini)
        quality (bool): If True, prefer quality_llm_provider (usually Gemini)

    Returns:
        response (str): Generated text
    """
    provider = get_quality_llm_provider() if quality else get_llm_provider()

    if provider == "gemini":
        try:
            return _generate_gemini(prompt, model_name)
        except Exception as gemini_err:
            if get_verbose():
                from status import warning
                warning(f"Gemini failed, falling back to Ollama: {gemini_err}")
            if get_llm_provider() == "ollama" or _selected_model:
                return _generate_ollama(prompt, model_name)
            raise

    return _generate_ollama(prompt, model_name)
