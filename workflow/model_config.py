"""
Model configuration.

Two providers are supported:

  MODEL_PROVIDER=groq   (default) -- routes through LiteLlm to Groq, which
                          is what avoided Gemini free-tier quota limits
                          during development.
  MODEL_PROVIDER=gemini -- uses Google's Gemini directly via google.adk.models.Gemini.

Set the provider and the matching API key as environment variables before
running app.py:

  export MODEL_PROVIDER=groq
  export GROQ_API_KEY=...

  # or

  export MODEL_PROVIDER=gemini
  export GOOGLE_API_KEY=...
"""

# import os


# def get_model():
#     provider = os.environ.get("MODEL_PROVIDER", "groq").lower()

#     if provider == "gemini":
#         from google.adk.models import Gemini
#         return Gemini(model=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"))

#     # default: groq via LiteLlm
#     from google.adk.models.lite_llm import LiteLlm
#     return LiteLlm(model=os.environ.get("GROQ_MODEL", "groq/llama-3.3-70b-versatile"))

import os
from google.adk.models import LiteLlm


def get_model():

    provider = os.getenv(
        "MODEL_PROVIDER",
        "gemini"
    )

    print("Provider =", provider)


    if provider == "openrouter":
        return LiteLlm(
            model=f"openrouter/{os.getenv('OPENROUTER_MODEL')}",
            api_key=os.getenv("OPENROUTER_API_KEY")
        )


    elif provider == "groq":

        return LiteLlm(
            model="groq/llama-3.3-70b-versatile",
            api_key=os.getenv(
                "GROQ_API_KEY"
            )
        )


    else:

        from google.adk.models import Gemini

        return Gemini(
            model="gemini-2.5-flash",
            api_key=os.getenv(
                "GOOGLE_API_KEY"
            )
        )