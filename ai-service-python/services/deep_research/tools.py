"""Injectable domain tools for Deep Research v2.

All retrieval and model calls are tracked via repository call ledger.
Scope validation happens BEFORE every retrieval/model send.
No hidden retries or untracked helper calls.
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Callable, Protocol

from services.deep_research.contracts import (
    CALL_STATUS_FAILED,
    CALL_STATUS_SUCCEEDED,
    DeepResearchError,
    digest,
)

logger = logging.getLogger(__name__)


# ── Protocols for Injectable Dependencies ──────────────────────────────────────

class ScopeValidator(Protocol):
    """Validates material authorization before EVERY retrieval/model send.
    
    Production facade needs authoritative Java callback or validated scope
    revision endpoint. Default validator cannot silently authorize revoked
    sources - fail closed if unavailable.
    """
    def __call__(self, run_id: str, material_id: str) -> bool: ...


class Retriever(Protocol):
    """Local retrieval interface matching research_executor.retrieve_current_paper_evidence.
    
    Uses keyword limit parameter (not positional) for clarity.
    """
    def __call__(self, query: str, pdf_id: str, *, limit: int = 5) -> list[dict[str, Any]]: ...


class SourceReader(Protocol):
    """Read source content from trusted snapshot."""
    def __call__(self, run_id: str, source_id: str) -> dict[str, Any]: ...


class LLMInvoker(Protocol):
    """Direct structured LLM call with budget tracking."""
    def __call__(self, prompt: str, extra_body: dict[str, Any]) -> dict[str, Any]: ...


# ── Default Implementations ────────────────────────────────────────────────────

class DefaultScopeValidator:
    """Fail-closed validator that checks material against snapshot.
    
    In production, this MUST be replaced with authoritative Java callback
    or validated scope revision endpoint. This default implementation only
    checks against the initial material snapshot and cannot detect revocations.
    """
    
    def __init__(self, get_run_fn: Callable[[str], dict | None]):
        self._get_run = get_run_fn
    
    def __call__(self, run_id: str, material_id: str) -> bool:
        record = self._get_run(run_id)
        if not record:
            return False
        
        materials = record.get("materials", [])
        allowed_ids = {m.get("materialId") for m in materials}
        
        # Fail closed: material must be explicitly in snapshot
        return material_id in allowed_ids


class TrackedRetriever:
    """Wraps retrieval with call ledger tracking and scope validation."""
    
    def __init__(
        self,
        base_retriever: Retriever,
        scope_validator: ScopeValidator,
        reserve_call_fn: Callable[..., tuple],
        complete_call_fn: Callable[..., dict],
    ):
        self._retrieve = base_retriever
        self._validate = scope_validator
        self._reserve = reserve_call_fn
        self._complete = complete_call_fn
    
    def __call__(self, run_id: str, query: str, pdf_id: str, *, limit: int = 5) -> list[dict[str, Any]]:
        # Validate scope BEFORE retrieval
        if not self._validate(run_id, pdf_id):
            logger.warning("Scope validation failed for %s in run %s", pdf_id, run_id)
            return []
        
        args_digest = digest({"query": query, "pdfId": pdf_id, "limit": limit})
        
        # Reserve call BEFORE network
        try:
            call_record, reused = self._reserve(
                run_id=run_id,
                node="acquire",
                tool="retrieve",
                args_digest=args_digest,
                budget_delta={"modelCalls": 0, "tokens": 0},  # Retrieval doesn't count as model call
            )
            
            if reused:
                result = call_record.get("result") or {}
                return result.get("items", []) if isinstance(result, dict) else []
            
        except Exception as exc:
            logger.exception("Failed to reserve retrieve call for run %s", run_id)
            return []
        
        # Execute retrieval
        try:
            items = self._retrieve(query, pdf_id, limit=limit)
            
            # Normalize source IDs via full hash (not truncated)
            normalized = []
            for item in items:
                source_id = item.get("sourceId", "")
                if not source_id:
                    # Generate stable ID from content - FULL hash, not [:16]
                    content_key = f"{item.get('pdfId', '')}:{item.get('chunkIndex', 0)}:{item.get('text', '')}"
                    source_id = "src_" + hashlib.sha256(content_key.encode()).hexdigest()
                
                normalized.append({
                    **item,
                    "sourceId": source_id,
                    "sourceWorkId": item.get("pdfId", pdf_id),
                    "contentHash": item.get("contentHash") or hashlib.sha256(item.get("text", "").encode()).hexdigest(),
                })
            
            # Complete call with result
            self._complete(
                call_record["callId"],
                status=CALL_STATUS_SUCCEEDED,
                result={"items": normalized},
                reservation_token=call_record.get("reservationToken"),
            )
            
            return normalized
            
        except Exception as exc:
            logger.exception("Retrieval failed for run %s", run_id)
            self._complete(
                call_record["callId"],
                status=CALL_STATUS_FAILED,
                error={"message": str(exc)},
                reservation_token=call_record.get("reservationToken"),
            )
            return []


class TrackedSourceReader:
    """Read source content with scope validation and ledger tracking.
    
    Note: Scope validation here uses source_id directly. The graph node
    does authoritative validation using work_id (materialId) before calling
    this reader, so this is a secondary check.
    """
    
    def __init__(
        self,
        base_reader: SourceReader,
        scope_validator: ScopeValidator,
        reserve_call_fn: Callable[..., tuple],
        complete_call_fn: Callable[..., dict],
    ):
        self._read = base_reader
        self._validate = scope_validator
        self._reserve = reserve_call_fn
        self._complete = complete_call_fn
    
    def __call__(self, run_id: str, source_id: str, work_id: str | None = None) -> dict[str, Any]:
        # Validate scope BEFORE read
        # Use work_id if provided (for material-based validation), else source_id
        validate_id = work_id if work_id else source_id
        if not self._validate(run_id, validate_id):
            logger.warning("Scope validation failed for source %s (work %s) in run %s", source_id, validate_id, run_id)
            return {}
        
        args_digest = digest({"sourceId": source_id})
        
        try:
            call_record, reused = self._reserve(
                run_id=run_id,
                node="read",
                tool="read_source",
                args_digest=args_digest,
                budget_delta={"modelCalls": 0, "tokens": 0},
            )
            
            if reused:
                return call_record.get("result") or {}
            
        except Exception as exc:
            logger.exception("Failed to reserve read call for source %s", source_id)
            return {}
        
        try:
            content = self._read(run_id, source_id)
            
            self._complete(
                call_record["callId"],
                status=CALL_STATUS_SUCCEEDED,
                result=content,
                reservation_token=call_record.get("reservationToken"),
            )
            
            return content
            
        except Exception as exc:
            logger.exception("Read failed for source %s", source_id)
            self._complete(
                call_record["callId"],
                status=CALL_STATUS_FAILED,
                error={"message": str(exc)},
                reservation_token=call_record.get("reservationToken"),
            )
            return {}


class TrackedLLMInvoker:
    """Direct LLM calls with reservation BEFORE network and usage tracking.
    
    All model calls use get_structured_llm().invoke(LLMRequest(...)).
    No hidden calls/retries. Ambiguous timeout = unknown, do not auto retry.
    Send-only try separate from settlement; never catch completion exception
    then overwrite as failed.
    """
    
    def __init__(
        self,
        llm_client: Any,  # LLM provider instance
        reserve_call_fn: Callable[..., tuple],
        complete_call_fn: Callable[..., dict],
        max_input_tokens: int = 24000,
        request_options: Callable | None = None,
    ):
        self._client = llm_client
        self._reserve = reserve_call_fn
        self._complete = complete_call_fn
        self._max_input = max_input_tokens
        self._request_options = request_options
    
    def __call__(
        self,
        run_id: str,
        node: str,
        prompt: str,
        extra_body: dict[str, Any] | None = None,
        use_reserve: bool = False,
    ) -> dict[str, Any]:
        from llm.provider import LLMRequest, LLMProviderError

        if self._request_options:
            extra_body = self._request_options(node, dict(extra_body or {}))
        
        # Full prompt digest for stable IDs - NOT truncated
        args_digest = digest({"prompt": prompt, "extra": extra_body or {}})
        
        # Reserve a conservative UTF-8 byte bound, then settle measured usage.
        prompt_byte_length = len(prompt.encode("utf-8"))
        estimated_input = prompt_byte_length + 1024  # Bound the fixed system message and framing too.
        max_output = (extra_body or {}).get("max_tokens", 2000)
        
        # Reject overlarge input BEFORE reserve - enforce UTF-8 byte size limit
        # Reject instead of silently clipping evidence or under-reserving it.
        max_byte_length = self._max_input
        if prompt_byte_length > max_byte_length:
            raise ValueError(
                f"Prompt too large: {prompt_byte_length} bytes (~{estimated_input} tokens) "
                f"exceeds max {max_byte_length} bytes (~{self._max_input} tokens)"
            )
        
        # Reserve BEFORE network
        call_record, reused = self._reserve(
            run_id=run_id,
            node=node,
            tool="llm_invoke",
            args_digest=args_digest,
            budget_delta={
                "modelCalls": 1,
                "tokens": estimated_input + max_output,
            },
            use_reserve=use_reserve,
        )
        
        if reused:
            return call_record.get("result", {"content": "", "usage": {}})
        
        # Execute LLM call - send-only try
        request = LLMRequest(
            prompt=prompt,
            extra_body=extra_body or {},
            timeout_seconds=(extra_body or {}).get("timeout_seconds"),
        )
        
        try:
            client = self._client.for_node(node) if callable(getattr(type(self._client), "for_node", None)) else self._client
            result = client.invoke(request)
        except LLMProviderError as exc:
            # LLMProviderError with no status_code means unknown (timeout/connection)
            # Rejected HTTP status means failed
            is_unknown = exc.status_code is None or exc.retryable
            self._complete(
                call_record["callId"],
                status="unknown" if is_unknown else CALL_STATUS_FAILED,
                error={"message": str(exc), "type": "provider_error", "status_code": exc.status_code},
                reservation_token=call_record.get("reservationToken"),
            )
            raise
        except Exception as exc:
            # Timeout/connection errors = unknown, do not auto retry
            error_msg = str(exc).lower()
            is_timeout = "timeout" in error_msg or "timed out" in error_msg or "connection" in error_msg
            
            self._complete(
                call_record["callId"],
                status="unknown" if is_timeout else CALL_STATUS_FAILED,
                error={"message": str(exc), "type": "timeout" if is_timeout else "error"},
                reservation_token=call_record.get("reservationToken"),
            )
            raise
        
        # Settlement - separate from send try
        actual_tokens = estimated_input + max_output
        if hasattr(result, "usage") and result.usage and not result.usage.estimated:
            actual_tokens = result.usage.total_tokens
        
        response = {
            "content": result.content if hasattr(result, "content") else "",
            "provider": getattr(result, "provider", ""),
            "model": getattr(result, "model", ""),
            "finishReason": getattr(result, "finish_reason", None),
            "usage": {
                "total_tokens": actual_tokens,
                "input_tokens": result.usage.input_tokens if hasattr(result.usage, "input_tokens") else 0,
                "output_tokens": result.usage.output_tokens if hasattr(result.usage, "output_tokens") else 0,
            },
        }
        
        # Settle with actual usage delta
        token_delta = actual_tokens - (estimated_input + max_output)
        settlement_delta = {"tokens": token_delta} if token_delta != 0 else {}
        
        self._complete(
            call_record["callId"],
            status=CALL_STATUS_SUCCEEDED,
            result=response,
            reservation_token=call_record.get("reservationToken"),
            budget_delta=settlement_delta,
        )
        
        return response


# ── External Academic Integration ──────────────────────────────────────────────

class ExternalAcademicAdapter:
    """Integrates AcademicSourceClient with call ledger.
    
    Each network call (discover/fulltext) is separately ledgered.
    Abstract vs fulltext distinction preserved.
    """
    
    def __init__(
        self,
        academic_client: Any,  # AcademicSourceClient instance
        reserve_call_fn: Callable[..., tuple],
        complete_call_fn: Callable[..., dict],
    ):
        self._client = academic_client
        self._reserve = reserve_call_fn
        self._complete = complete_call_fn
    
    def discover(self, run_id: str, query: str, limit: int = 6) -> list[dict[str, Any]]:
        args_digest = digest({"query": query, "limit": limit, "type": "discover"})
        
        try:
            call_record, reused = self._reserve(
                run_id=run_id,
                node="acquire",
                tool="external_discover",
                args_digest=args_digest,
                budget_delta={"externalSearches": 1},
            )
            
            if reused:
                return (call_record.get("result") or {}).get("items", [])
            
        except Exception as exc:
            logger.exception("Failed to reserve external discover call")
            return []
        
        try:
            results = self._client.discover(query, limit)
            
            self._complete(
                call_record["callId"],
                status=CALL_STATUS_SUCCEEDED,
                result={"items": results},
                reservation_token=call_record.get("reservationToken"),
            )
            
            return results
            
        except Exception as exc:
            logger.exception("External discover failed")
            self._complete(
                call_record["callId"],
                status=CALL_STATUS_FAILED,
                error={"message": str(exc)},
                reservation_token=call_record.get("reservationToken"),
            )
            return []
    
    def fetch_fulltext(self, run_id: str, arxiv_id: str) -> dict[str, Any]:
        args_digest = digest({"arxivId": arxiv_id, "type": "fulltext"})
        
        try:
            call_record, reused = self._reserve(
                run_id=run_id,
                node="read",
                tool="external_fulltext",
                args_digest=args_digest,
                budget_delta={"fulltextFetches": 1},
            )
            
            if reused:
                return call_record.get("result") or {}
            
        except Exception as exc:
            logger.exception("Failed to reserve external fulltext call")
            return {}
        
        try:
            result = self._client.fetch_fulltext(arxiv_id)
            
            self._complete(
                call_record["callId"],
                status=CALL_STATUS_SUCCEEDED,
                result=result,
                reservation_token=call_record.get("reservationToken"),
            )
            
            return result
            
        except Exception as exc:
            logger.exception("External fulltext fetch failed")
            self._complete(
                call_record["callId"],
                status=CALL_STATUS_FAILED,
                error={"message": str(exc)},
                reservation_token=call_record.get("reservationToken"),
            )
            return {}


# ── Semantic Check Adapter ─────────────────────────────────────────────────────

class BudgetedSemanticChecker:
    """Semantic verification using reserved model calls.
    
    Checks factual support and the logic of proposed experiments separately.
    Uses reserve pool explicitly.
    """
    
    def __init__(
        self,
        llm_invoker: TrackedLLMInvoker,
        run_id: str,
    ):
        self._invoke = llm_invoker
        self._run_id = run_id
    
    def __call__(self, claims: list[dict], evidence: list[dict]) -> list[dict]:
        if not claims:
            return []
        # Check a prospective design jointly once: splitting its equations and
        # definitions across three calls repeats reasoning and loses context.
        # Facts remain separately checked against their own citations. Every
        # call still goes through the same ledger, budget and scope validation.
        proposals = [c for c in claims if c.get('kind') in {'proposal', 'suggestion', 'hypothesis'}]
        facts = [c for c in claims if c.get('kind') not in {'proposal', 'suggestion', 'hypothesis'}]
        fact_slots = 2 if proposals else 3
        size = max(1, (len(facts) + fact_slots - 1) // fact_slots)
        batches = ([proposals] if proposals else []) + [facts[i:i + size] for i in range(0, len(facts), size)]
        verdicts = []
        for batch in batches:
            targets = {c['claimId'] for c in batch}
            context = [{'claimId': c.get('claimId'), 'text': c.get('text'), 'kind': c.get('kind')}
                       for c in proposals if c['claimId'] not in targets]
            verdicts.extend(self._check_batch(batch, evidence, context))
        by_id = {v['claimId']: v for v in verdicts}
        return [by_id[c['claimId']] for c in claims]

    def _check_batch(self, claims: list[dict], evidence: list[dict], proposal_context: list[dict]) -> list[dict]:
        from services.deep_research.selection import surrounding_context
        # Format claims and evidence for checking
        claims_text = json.dumps([{
            "claimId": c.get("claimId"),
            "text": c.get("text", ""),
            "kind": c.get("kind"),
            "evidenceRefs": c.get("evidenceRefs", []),
            "conditions": c.get("conditions", {}),
            "tableBindings": c.get("tableBindings", []),
            "designRole": c.get("designRole"),
        } for c in claims], ensure_ascii=False)
        
        referenced = {ref for claim in claims for ref in claim.get("evidenceRefs", [])}
        evidence_map = {e["evidenceId"]: {"quote": e.get("quote", ""), "conditions": e.get("conditions", {}),
                        "sourceContext": surrounding_context(e), "location": e.get("location", {}),
                        "sourceTitle": e.get("sourceTitle", ""),
                        "tableData": e.get("tableData"),
                        "workId": e.get("sourceWorkId"), "versionId": e.get("sourceVersionId"),
                        "accessLevel": e.get("accessLevel")} for e in evidence if e["evidenceId"] in referenced}
        evidence_text = json.dumps(evidence_map, ensure_ascii=False)
        
        prompt = f"""Verify these claims against the evidence. For each claim, determine if the evidence supports it.

Claims:
{claims_text}

Evidence:
{evidence_text}

Return JSON array of verdicts:
[{{"claimId": "...", "status": "passed" or "failed", "reason": "..."}}]

Be strict: evidence must directly support EVERY clause and condition of the specific claim.
For each claim use ONLY its own evidenceRefs; evidence cited by another claim is not its support.
Check each number's method, dataset, metric, unit and experimental setting, not just its presence.
SourceContext is the original passage around the exact quote, not additional permission to invent facts.
Use it to detect lost experimental scope. A numeric comparison must identify its dataset/protocol
or explicitly say that those conditions are unknown in the available passage. Reject an isolated
supplemental or ablation result presented as the paper's general outcome. If necessary, remove
the numerical example rather than approving it without its scope.
Reject claims that confuse a similar PSNR with unchanged image quality, or infer universal/exclusive
conditions from a limited tested range. Missing passages do not prove the authors never tested it.
For inference, verify the stated premises and reasoning; reject invented calculations or generalization.
For proposal/suggestion/hypothesis, do not demand that an unexecuted experiment already has results.
Instead verify that it is clearly prospective, contains no disguised established fact, and is logically valid.
Check formulas, metric direction, conditional versus averaged factorial effects, and sign interpretations.
An interaction formula must define whether larger values mean better quality or greater loss; never use
one sign interpretation for PSNR/SSIM and LPIPS together. Non-significance does not prove no effect.
Truncating coefficients is a proposed intervention, not automatically the paper's distillation procedure.
Do not accept vague connections. A partly supported claim must fail until its wording is narrowed."""
        
        if any(c.get("kind") in {"proposal", "suggestion", "hypothesis"} for c in claims):
            from services.deep_research.experimental_reasoning import FACTORIAL_REFERENCE, design_requirements
            prompt += "\nReview all claims jointly for conflicting definitions. For every formula claim, " \
                      "derive its meaning before issuing a verdict; state any counterexample in the reason.\n" \
                      + FACTORIAL_REFERENCE
            prompt += '\nOther proposed statements, for consistency only (not evidence and not verdict targets):\n' + json.dumps(proposal_context, ensure_ascii=False)
            if any(c.get('designRole') for c in claims):
                prompt += '\nFor every designRole, verify BOTH logical correctness AND fulfillment of its entire ' \
                          'requirement below. A role label, heading or vague promise is not fulfillment. Fail the ' \
                          'specific claim if its budget, split, procedure or decision criterion is unspecified. ' \
                          'Use the other target claims for shared definitions but not as factual evidence.\n' + design_requirements()
        try:
            result = self._invoke(
                run_id=self._run_id,
                node="verify",
                prompt=prompt,
                extra_body={"max_tokens": 4000, "temperature": 0.0},
                use_reserve=True,  # Use reserve pool for verification
            )
            
            content = result.get("content", "[]")
            from services.deep_research.graph import _safe_parse_json
            parsed = _safe_parse_json(content)
            
            expected = {claim['claimId'] for claim in claims}
            if (result.get('finishReason') == 'length' or not isinstance(parsed, list)
                    or len(parsed) != len(expected)
                    or any(not isinstance(v, dict) or v.get('status') not in {'passed', 'failed'}
                           for v in parsed)
                    or {v.get('claimId') for v in parsed} != expected):
                raise DeepResearchError('invalid_verification_response',
                                        '声明核验未完整返回；不能据此判断材料不足。')
            return parsed
            
        except DeepResearchError:
            # Preserve budget, authorization and unknown-call recovery semantics.
            # A missing verdict is an execution failure, not evidence of insufficiency.
            raise
        except Exception as exc:
            logger.exception("Semantic check failed for run %s", self._run_id)
            raise DeepResearchError('invalid_verification_response',
                                    '声明核验未完成；已取得的资料仍保留。') from exc
