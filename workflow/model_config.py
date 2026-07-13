"""
Model configuration.

Three providers are supported, matching the reference project exactly:

  MODEL_PROVIDER=openrouter -- routes through LiteLlm to OpenRouter.
                                Model comes from OPENROUTER_MODEL (never
                                hardcoded).
  MODEL_PROVIDER=groq       -- routes through LiteLlm to Groq.
  MODEL_PROVIDER=gemini     -- uses Google's Gemini directly via
                                google.adk.models.Gemini. (default)

Set the provider and the matching API key as environment variables before
running app.py / streamlit_app.py:

  export MODEL_PROVIDER=openrouter
  export OPENROUTER_MODEL=...
  export OPENROUTER_API_KEY=...

  # or
  export MODEL_PROVIDER=groq
  export GROQ_API_KEY=...

  # or
  export MODEL_PROVIDER=gemini
  export GOOGLE_API_KEY=...

Every agent must call get_model() -- never instantiate a model class
directly -- so the provider is switchable in one place.
"""

import os

from google.adk.models import LiteLlm


def get_model():
    provider = os.getenv("MODEL_PROVIDER", "gemini")
    print(f"[model_config] MODEL_PROVIDER={provider!r}")

    if provider == "openrouter":
        return LiteLlm(
            model=f"openrouter/{os.getenv('OPENROUTER_MODEL')}",
            api_key=os.getenv("OPENROUTER_API_KEY"),
        )

    elif provider == "groq":
        return LiteLlm(
            model=os.getenv("GROQ_MODEL", "groq/llama-3.3-70b-versatile"),
            api_key=os.getenv("GROQ_API_KEY"),
        )

    else:
        from google.adk.models import Gemini

        return Gemini(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            api_key=os.getenv("GOOGLE_API_KEY"),
        )
