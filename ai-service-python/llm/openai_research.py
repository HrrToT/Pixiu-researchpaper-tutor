"""OpenAI transport for the research graph's bounded model requests."""

from dataclasses import replace

import requests

from llm.client import CompletionHTTPClient
from llm.provider import DEFAULT_RESEARCH_OUTPUT_TOKENS
from llm.responses_transport import API_KEY


class OpenAIResearchLLM(CompletionHTTPClient):
    provider = "openai"
    provider_label = "OpenAI"
    request_flags = {"allow_redirects": False}

    def __init__(self, *, model, api_key, timeout_seconds):
        super().__init__(model=model, api_key=api_key, timeout_seconds=timeout_seconds,
                         base_url="https://api.openai.com/v1")

    def configured_key(self):
        return self.api_key

    def _counted_context(self, messages):
        return {
            "model": self.model, "input": messages, "text": {"format": {"type": "json_object"}},
            "truncation": "disabled", "reasoning": {"effort": "low"},
        }

    def _counted_request(self, request):
        body = request.extra_body
        cap = body.get("max_tokens")
        if (request.stop or not request.messages or body.get("response_format") != {"type": "json_object"}
                or API_KEY in body or type(cap) is not int or cap <= 0):
            raise ValueError("Counted audit requires bounded JSON-object Responses input")
        return replace(request, extra_body={API_KEY: "responses", "response_format": body["response_format"],
                                            "max_tokens": cap})

    def count_audit_input(self, request):
        from llm.deadline import call_with_deadline
        from services.operation_control import check_cancelled

        request = self._counted_request(request)
        check_cancelled()
        if not self.configured_key():
            return None
        timeout = min(5, self.timeout_seconds, request.timeout_seconds or self.timeout_seconds)
        try:
            response = call_with_deadline(lambda: requests.post(
                f"{self.base_url}/responses/input_tokens",
                headers={"Authorization": f"Bearer {self.configured_key()}"},
                json=self._counted_context(request.messages),
                timeout=timeout,
                **self.request_flags,
            ), timeout)
            if response.status_code != 200:
                return None
            body = response.json()
        except (requests.RequestException, TimeoutError, ValueError):
            return None
        if isinstance(body, dict) and body.get("object") == "response.input_tokens":
            count = body.get("input_tokens")
            if type(count) is int and count > 0:
                return count
        return None

    def invoke_counted_audit(self, request):
        return self.invoke(self._counted_request(request))

    def build_responses_payload(self, messages, options):
        if options.get("response_format") == {"type": "json_object"}:
            if set(options) != {API_KEY, "response_format", "max_tokens"} or options[API_KEY] != "responses":
                raise ValueError("Invalid OpenAI counted audit transport")
            return {**self._counted_context(messages), "max_output_tokens": options["max_tokens"], "store": False}
        return super().build_responses_payload(messages, options)

    def adapt_payload(self, payload, *, responses_mode):
        # The graph validates returned objects against its own schema, including
        # optional fields and constraints outside OpenAI's strict subset.
        if responses_mode:
            if payload["text"]["format"] == {"type": "json_object"}:
                return payload
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
