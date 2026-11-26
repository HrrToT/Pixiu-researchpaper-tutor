"""OpenAI transport for the research graph's bounded model requests."""

from llm.client import CompletionHTTPClient
from llm.provider import DEFAULT_RESEARCH_OUTPUT_TOKENS


class OpenAIResearchLLM(CompletionHTTPClient):
    provider = "openai"
    provider_label = "OpenAI"
    request_flags = {"allow_redirects": False}

    def __init__(self, *, model, api_key, timeout_seconds):
        super().__init__(model=model, api_key=api_key, timeout_seconds=timeout_seconds,
                         base_url="https://api.openai.com/v1")

    def configured_key(self):
        return self.api_key

    def adapt_payload(self, payload, *, responses_mode):
        # The graph validates returned objects against its own schema, including
        # optional fields and constraints outside OpenAI's strict subset.
        if responses_mode:
            effort = payload["reasoning"]["effort"]
            return {
                "model": self.model,
                "input": payload["input"],
                "max_output_tokens": payload["max_output_tokens"],
                "reasoning": {"effort": "high" if effort == "max" else effort},
                "text": {"format": {**payload["text"]["format"], "strict": False}},
                "store": False,
            }

        thinking = payload.get("thinking")
        effort = payload.get("reasoning_effort", "low") if thinking == {"type": "enabled"} else "none"
        result = {
            "model": self.model,
            "messages": payload["messages"],
            "reasoning_effort": "high" if effort == "max" else effort,
            "max_completion_tokens": payload.get("max_tokens", DEFAULT_RESEARCH_OUTPUT_TOKENS),
            "store": False,
        }
        if "response_format" in payload:
            result["response_format"] = payload["response_format"]
        if "stop" in payload:
            result["stop"] = payload["stop"]
        return result

    def http_error_code(self, response):
        if response.status_code == 429:
            try:
                data = response.json()
            except ValueError:
                return 429
            error = data.get("error") if isinstance(data, dict) else None
            if isinstance(error, dict) and error.get("code") in {"credit_balance_exhausted", "insufficient_quota"}:
                return 402  # Existing ledger category for a confirmed payment rejection.
        return response.status_code
