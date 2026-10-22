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
    IllegalStatusTransitionError,
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
        run_record_fn: Callable | None = None,
        verification_max_input_bytes: int | None = None,
        call_history_fn: Callable | None = None,
        experiment_max_input_bytes: int | None = None,
    ):
        self._client = llm_client
        self._reserve = reserve_call_fn
        self._complete = complete_call_fn
        self._max_input = max_input_tokens
        self._request_options = request_options
        self._run_record = run_record_fn
        self._call_history=call_history_fn
        from services.deep_research.verification_capacity import VERIFICATION_INPUT_BYTES
        if verification_max_input_bytes is not None and (
                type(verification_max_input_bytes) is not int
                or not 1 <= verification_max_input_bytes <= VERIFICATION_INPUT_BYTES):
            raise ValueError('Invalid server verification input limit')
        self._verification_max_input = (max_input_tokens if verification_max_input_bytes is None
                                        else verification_max_input_bytes)
        from services.deep_research.experiment_capacity import EXPERIMENT_INPUT_BYTES
        if experiment_max_input_bytes is not None and (
                type(experiment_max_input_bytes) is not int
                or not 1 <= experiment_max_input_bytes <= EXPERIMENT_INPUT_BYTES):
            raise ValueError('Invalid server experiment input limit')
        self._experiment_max_input = (max_input_tokens if experiment_max_input_bytes is None
                                      else experiment_max_input_bytes)

    def prompt_byte_limit(self, run_id: str, node: str) -> int:
        from services.deep_research.verification_capacity import verification_input_limit
        record = self._run_record(run_id) if self._run_record else None
        from services.deep_research.experiment_capacity import transport_limit
        legacy = verification_input_limit(record, node, self._max_input, self._verification_max_input)
        return transport_limit(record, node, legacy, getattr(self, '_experiment_max_input', self._max_input))

    def uses_verification_input_contract(self, run_id: str, node: str) -> bool:
        from services.deep_research.verification_capacity import has_verification_input_contract
        record = self._run_record(run_id) if self._run_record else None
        return has_verification_input_contract(record, node)
    
    def __call__(
        self,
        run_id: str,
        node: str,
        prompt: str,
        extra_body: dict[str, Any] | None = None,
        use_reserve: bool = False,
    ) -> dict[str, Any]:
        from llm.provider import LLMRequest, LLMProviderError
        from services.deep_research.factual_review import OPTION as REVIEW_OPTION
        from services.deep_research.experiment_template import REASONING_OPTION as EXPERIMENT_OPTION
        bounded_review=(extra_body or {}).get(REVIEW_OPTION,False)
        experiment_reasoning=(extra_body or {}).get(EXPERIMENT_OPTION,False)
        if type(bounded_review) is not bool or type(experiment_reasoning) is not bool:
            raise ValueError('Invalid bounded factual review option')
        if self._request_options:
            extra_body = self._request_options(node, dict(extra_body or {}))
        elif bounded_review or experiment_reasoning:
            from services.deep_research.runtime import research_model_options
            extra_body=research_model_options(node,dict(extra_body or {}))
        elif node == 'repair_claims' and '_repair_output_limit' in (extra_body or {}):
            from services.deep_research.repair_budget import repair_output_options
            extra_body = repair_output_options(extra_body)
        
        from services.deep_research.structured_output import enabled as native_json, messages_for_record
        transport_record = self._run_record(run_id) if self._run_record else None
        structured = native_json(transport_record)
        wire_messages = messages_for_record(transport_record,node,prompt) if structured else None
        if structured:
            if 'messages' in (extra_body or {}):
                raise DeepResearchError('invalid_model_options', '研究模型调用选项无效，尚未发送。')
            extra_body = {**(extra_body or {}), 'response_format': {'type': 'json_object'}}
        # Full actual request digest, including native transport instructions.
        request_identity = {"prompt": prompt, "extra": extra_body or {}}
        if structured:
            request_identity['messages'] = wire_messages
        args_digest = digest(request_identity)
        if bounded_review and self._run_record:
            from services.deep_research.factual_review import admission
            decision=admission(transport_record,self._call_history(run_id) if self._call_history else [],args_digest)
            if decision['allowed'] is not True:
                return {'notStarted':'factual_review_time_budget','admission':decision}
        
        # Reserve a conservative UTF-8 byte bound, then settle measured usage.
        prompt_byte_length = len(prompt.encode("utf-8"))
        estimated_input = prompt_byte_length + 1024  # Bound the fixed system message and framing too.
        max_output = (extra_body or {}).get("max_tokens", 2000)
        
        # Reject overlarge input BEFORE reserve - enforce UTF-8 byte size limit
        # Reject instead of silently clipping evidence or under-reserving it.
        max_byte_length = self.prompt_byte_limit(run_id, node)
        if prompt_byte_length > max_byte_length:
            raise ValueError(
                f"Prompt too large: {prompt_byte_length} bytes (~{estimated_input} tokens) "
                f"exceeds max {max_byte_length} bytes"
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
            messages=wire_messages,
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
            error = {"message": str(exc), "type": "provider_error", "status_code": exc.status_code}
            if exc.failure_kind in {"proxy_error", "tls_error", "connect_timeout", "read_timeout",
                                    "deadline_exceeded", "connection_error", "transport_error"}:
                error["failureKind"] = exc.failure_kind
            self._complete(
                call_record["callId"],
                status="unknown" if is_unknown else CALL_STATUS_FAILED,
                error=error,
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
        reported_model = getattr(result, "reported_model", None)
        if isinstance(reported_model, str) and reported_model.strip() and len(reported_model) <= 256:
            response["reportedModel"] = reported_model
        if structured:
            from services.deep_research.structured_output import normalize
            response = normalize(node, response)
        
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
        self.discovery_outcomes = []
    
    def discover(self, run_id: str, query: str, limit: int = 6) -> list[dict[str, Any]]:
        request_identity = {"query": query, "limit": limit, "type": "discover"}
        if callable(getattr(type(self._client), 'discovery_request', None)):
            request_identity = {"request": self._client.discovery_request(query, limit),
                                "type": "discover"}
        return self._discover_request(run_id, request_identity, lambda: self._client.discover(query, limit))

    def lookup(self, run_id: str, identifiers: list[str], limit: int = 6) -> list[dict[str, Any]]:
        request = self._client.lookup_request(identifiers, limit)
        # Same HTTP request means the same ledger identity, even if a previous
        # plan found it through a query containing the identifier.
        return self._discover_request(run_id, {"request": request, "type": "discover"},
                                      lambda: self._client.lookup(identifiers, limit))

    def _discover_request(self, run_id, request_identity, send):
        args_digest = digest(request_identity)
        
        try:
            call_record, reused = self._reserve(
                run_id=run_id,
                node="acquire",
                tool="external_discover",
                args_digest=args_digest,
                budget_delta={"externalSearches": 1},
            )
            
            if reused:
                self.discovery_outcomes.append(call_record.get('status'))
                return (call_record.get("result") or {}).get("items", [])
            
        except IllegalStatusTransitionError as exc:
            if exc.details != {'currentStatus': 'failed', 'requestedStatus': 'pending'}:
                raise
            # The durable ledger refused an automatic resend of this failure.
            self.discovery_outcomes.append(CALL_STATUS_FAILED)
            return []
        except Exception as exc:
            logger.exception("Failed to reserve external discover call")
            self.discovery_outcomes.append('not_dispatched')
            return []
        
        try:
            results = send()
            
            self._complete(
                call_record["callId"],
                status=CALL_STATUS_SUCCEEDED,
                result={"items": results},
                reservation_token=call_record.get("reservationToken"),
            )
            
            self.discovery_outcomes.append(CALL_STATUS_SUCCEEDED)
            return results
            
        except Exception as exc:
            logger.exception("External discover failed")
            self._complete(
                call_record["callId"],
                status=CALL_STATUS_FAILED,
                error={"message": str(exc)},
                reservation_token=call_record.get("reservationToken"),
            )
            self.discovery_outcomes.append(CALL_STATUS_FAILED)
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
        metric_domains=None,
        research_question=None,
        isolate_factual_claims=False,
        comparison_reasoning=False,
        comparison_audit_version=1,
        audit_source_fields=False,
        audit_target_fields=False,
        factual_scope=False,
        qualitative_inference=False,
        experiment_intent_review=False,
        complete_factual_scope=False,
        result_attribution=False,
        bounded_factual_review=False,
        prospective_review=False,
        configuration_consistency=0,
        prospective_envelope=0,
    ):
        self._invoke = llm_invoker
        self._run_id = run_id
        self._metric_domains = metric_domains
        self._research_question = research_question
        self._isolate_factual_claims = isolate_factual_claims
        self._comparison_reasoning = comparison_reasoning
        self._comparison_audit_version = comparison_audit_version
        self._audit_source_fields = audit_source_fields
        self._audit_target_fields = audit_target_fields
        self._factual_scope = factual_scope
        self._complete_factual_scope=complete_factual_scope
        self._result_attribution=result_attribution
        self._bounded_factual_review=bounded_factual_review
        self._qualitative_inference = qualitative_inference
        self._experiment_intent_review = experiment_intent_review
        self._prospective_review = prospective_review
        self._configuration_consistency = configuration_consistency
        self._prospective_envelope = prospective_envelope
    
    def __call__(self, claims: list[dict], evidence: list[dict], *, proposal_context=()) -> list[dict]:
        return self._check(claims,evidence,list(proposal_context),'verify')

    def check_revisions(self, claims, evidence, accepted_context, *, proposal_context=()):
        """Retain design definitions without rechecking or promoting context facts."""
        targets = {c['claimId'] for c in claims}
        context = [c for c in [*accepted_context,*proposal_context] if c.get('claimId') not in targets
                   and c.get('kind') in {'proposal', 'suggestion', 'hypothesis'}]
        return self._check(claims, evidence, context, 'verify_repair')

    def _check(self, claims, evidence, accepted_context, node):
        if not claims:
            return []
        # Config checks retain operational definitions and explicit dependencies;
        # scientific interpretation receives the complete proposed configuration.
        # Capacity splits happen before dispatch and
        # remain subject to the tracked invoker's existing call/token budget.
        proposals = [c for c in claims if c.get('kind') in {'proposal', 'suggestion', 'hypothesis'}]
        facts = [c for c in claims if c.get('kind') not in {'proposal', 'suggestion', 'hypothesis'}]
        policy = self._experiment_intent_review() if callable(self._experiment_intent_review) else self._experiment_intent_review
        scientific_methods = type(policy) is int and policy == 3
        premise_failures = []
        if scientific_methods:
            from services.deep_research.experiment_intent import missing_paper_operation_premise
            question = self._research_question() if callable(self._research_question) else self._research_question
            premise_failures = [{'claimId':c['claimId'],'status':'failed',
                'reason':'论文所述干预缺少本条自身的已核对全文依据，不能只凭方法名称或拟议参数确认实际操作。'}
                for c in proposals if missing_paper_operation_premise(c,evidence,question)]
        failed_ids = {v['claimId'] for v in premise_failures}
        from services.deep_research.verification_context import CONFIG_ROLES
        def requires_science(c):
            return ((scientific_methods and c.get('designRole')=='groups')
                or (c.get('designRole') == 'controls' and c.get('protocolContractVersion') in (1, 2))
                or (c.get('designRole') == 'steps' and c.get('workflowContractVersion') in (2, 3, 4)))
        config = [c for c in proposals if c['claimId'] not in failed_ids
                  and c.get('designRole') in CONFIG_ROLES and not requires_science(c)]
        science = [c for c in proposals if c not in config and c['claimId'] not in failed_ids]
        science_node = 'verify_design_science' if node == 'verify' else 'verify_repair_design_science'
        config_node='verify_design_config' if node=='verify' else 'verify_repair_design_config'
        proposal_batches = ([(config, config_node)] if config else []) + ([(science, science_node)] if science else [])
        fact_slots = max(1, 3 - len(proposal_batches))
        # Legacy answers keep their original batch. New isolated factual
        # checks never receive another target's citations; all requests still
        # reserve from the unchanged run budget before dispatch.
        isolated = (self._isolate_factual_claims() if callable(self._isolate_factual_claims)
                    else self._isolate_factual_claims) is True
        size = 1 if isolated else max(3, (len(facts) + fact_slots - 1) // fact_slots)
        batches = proposal_batches + [(facts[i:i + size], node) for i in range(0, len(facts), size)]
        verdicts = list(premise_failures)
        envelope=self._prospective_envelope() if callable(self._prospective_envelope) else self._prospective_envelope
        context_states={}
        if type(envelope) is int and envelope in (2,3,4,5,6,7,8):
            context_states={c['claimId']:c['reviewContextState'] for c in accepted_context
                if 'reviewContextState' in c}
            context_states.update({row['claimId']:{'status':'rejected','phase':'source_prerequisite',
                'checks':[row]} for row in premise_failures})
        for batch, batch_node in batches:
            targets = {c['claimId'] for c in batch}
            context = [{'claimId': c.get('claimId'), 'text': c.get('text'), 'kind': c.get('kind'),
                        'conditions': c.get('conditions', {}), 'designRole': c.get('designRole'),
                        'executionSpec': c.get('executionSpec'), 'designContractVersion': c.get('designContractVersion'),
                        'budgetContractVersion': c.get('budgetContractVersion'),
                        'hypothesisContractVersion': c.get('hypothesisContractVersion')}
                        | {'protocolContractVersion':c.get('protocolContractVersion')}
                        | {'workflowContractVersion':c.get('workflowContractVersion')}
                        | ({'reviewContextState':context_states[c['claimId']]}
                           if c['claimId'] in context_states else {})
                       for c in [*accepted_context, *proposals] if c['claimId'] not in targets]
            verdicts.extend(self._check_batch(batch, evidence, context, node=batch_node))
        by_id = {v['claimId']: v for v in verdicts}
        return [by_id[c['claimId']] for c in claims]

    def _check_batch(self, claims: list[dict], evidence: list[dict], proposal_context: list[dict], *, node='verify') -> list[dict]:
        byte_limit = (self._invoke.prompt_byte_limit(self._run_id, node)
                      if isinstance(self._invoke, TrackedLLMInvoker) else 24000)
        config_mode=node in {'verify_design_config','verify_repair_design_config'}
        review_version = self._prospective_review() if callable(self._prospective_review) else self._prospective_review
        if config_mode:
            from services.deep_research.verification_context import configuration_context
            proposal_context=configuration_context(claims,proposal_context)
        from services.deep_research.selection import surrounding_context
        metric_domains = self._metric_domains() if callable(self._metric_domains) else self._metric_domains
        from services.deep_research.verification_aliases import (
            encode_verification_inputs, restore_visible_evidence, restore_verdict_evidence)
        wire_claims, wire_evidence, reverse_aliases = encode_verification_inputs(claims, evidence)
        from services.deep_research.execution_materialization import verification_claim_view
        wire_claims = [verification_claim_view(c) for c in wire_claims]
        # Omit absent optional wrapper fields only. Typed configuration values,
        # including empty collections inside executionSpec, remain untouched.
        def present_fields(row):
            return {key: value for key, value in row.items()
                    if value is not None and value != {} and value != []}
        if (isinstance(self._invoke, TrackedLLMInvoker)
                and self._invoke.uses_verification_input_contract(self._run_id, node)):
            # Our projection adds absent optional versions as None. Remove
            # those wrapper placeholders BEFORE finding the exact generated
            # suffix; a present workflow=None would otherwise hide the valid
            # budget/protocol/hypothesis renderer. Keep every executionSpec
            # value and original prose. Legacy requests retain their wire form.
            wire_context = [verification_claim_view(present_fields(c)) for c in proposal_context]
        else:
            wire_context = [present_fields(verification_claim_view(c)) for c in proposal_context]
        # Format claims and evidence for checking
        claims_text = json.dumps([present_fields({
            "claimId": c.get("claimId"),
            "text": c.get("text", ""),
            "kind": c.get("kind"),
            "evidenceRefs": c.get("evidenceRefs", []),
            "conditions": c.get("conditions", {}),
            "tableBindings": c.get("tableBindings", []),
            "designRole": c.get("designRole"),
            "executionSpec": c.get("executionSpec"),
            "designContractVersion": c.get("designContractVersion"),
            "budgetContractVersion": c.get("budgetContractVersion"),
            "hypothesisContractVersion": c.get("hypothesisContractVersion"),
            "protocolContractVersion": c.get("protocolContractVersion"),
            "workflowContractVersion": c.get("workflowContractVersion"),
        }) for c in wire_claims], ensure_ascii=False, separators=(',', ':'))
        
        referenced = {ref for claim in wire_claims for ref in claim.get("evidenceRefs", [])}
        evidence_map = {e["evidenceId"]: present_fields({"quote": e.get("quote", ""), "conditions": e.get("conditions", {}),
                        "sourceContext": surrounding_context(e), "location": e.get("location", {}),
                        "sourceTitle": e.get("sourceTitle", ""),
                        "tableData": e.get("tableData"),
                        "workId": e.get("sourceWorkId"), "versionId": e.get("sourceVersionId"),
                        "publicationIdentity": e.get('sourcePublicationIdentity'),
                        "accessLevel": e.get("accessLevel")}) for e in wire_evidence if e["evidenceId"] in referenced}
        from uuid import uuid4
        from services.deep_research.prompt_budget import fit_evidence_prompt
        evidence_text = uuid4().hex
        
        prompt = f"""Verify these claims against the evidence. For each claim, determine if the evidence supports it.

Claims:
{claims_text}

Evidence:
{evidence_text}

Return JSON array of verdicts:
[{{"claimId": "...", "status": "passed" or "failed", "reason": "..."}}]

Be strict: evidence must directly support EVERY clause and condition of the specific claim.
For each claim use ONLY its own evidenceRefs; evidence cited by another claim is not its support.
Resolve the subject of EVERY cited clause from its preceding and following sentences.
In contrasts (however, in contrast, on the contrary), distinguish the baseline from
the proposed method. An "it" or "this" is not automatically the paper's own method.
A passage criticizing a baseline cannot support a limitation assigned to the proposed
method. If the subject is unresolved in the supplied context, fail that assertion.
For each verdict's reason, briefly identify the asserted subject, the source subject,
and any mismatch before judging support; do not merely restate the claimed sentence.
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

        if all(c.get('kind') in {'proposal', 'suggestion', 'hypothesis'} for c in claims):
            # Do not inherit factual-entailment instructions for unexecuted choices.
            prompt = f'''Verify these claims as a prospective experimental design. These targets are suggestions,
not claims that the papers already performed this experiment. A proposed seed, split,
factor level, recovery budget or measurement protocol needs NO quotation proving that
the authors used it. Judge whether it is explicit, executable and coherent. Never fail
a clearly labeled proposed choice merely because it is absent from the paper.
Check scientific validity as well as completeness. A role can share definitions and
protocol details with other target/context proposals; do not demand needless repetition.
If a target also asserts an existing paper fact, check only that factual clause against
its own evidenceRefs; shared context is not factual evidence. Reject invented paper facts.

Claims:
{claims_text}

Evidence:
{evidence_text}

Return only a JSON array, one verdict per target:
[{{"claimId":"ID","status":"passed" or "failed","reason":"brief specific finding","designAudit":{{}}}}]
Missing configuration, contradictory choices and invalid parameter syntax fail.
Do not require an unexecuted experiment to have results. Do not judge context claims as targets.'''

        inference_review = (self._qualitative_inference() if callable(self._qualitative_inference)
                            else self._qualitative_inference) is True
        if inference_review and any(c.get('kind') == 'inference' for c in claims):
            from services.deep_research.audience_rewrite import QUALITATIVE_INFERENCE_REVIEW
            prompt += '\n' + QUALITATIVE_INFERENCE_REVIEW
        if any(row.get('publicationIdentity') for row in evidence_map.values()):
            from services.deep_research.publication_identity import GUIDANCE as publication_guidance
            prompt += '\n' + publication_guidance
        from services.deep_research.synthesis import SCIENTIFIC_TERMINOLOGY
        prompt += '\n' + SCIENTIFIC_TERMINOLOGY
        question = self._research_question() if callable(self._research_question) else self._research_question
        experiment_policy = (self._experiment_intent_review() if callable(self._experiment_intent_review)
                             else self._experiment_intent_review)
        experiment_intent = experiment_policy is True or (type(experiment_policy) is int and experiment_policy in (1,2,3))
        if experiment_intent and all(c.get('kind') in {'proposal','suggestion','hypothesis'} for c in claims):
            from services.deep_research.experiment_intent import guidance as experiment_guidance
            prompt += '\n'+experiment_guidance(question,{c.get('designRole') for c in claims},
                policy_version=experiment_policy if type(experiment_policy) is int and experiment_policy in (2,3) else 1)
        if isinstance(question, str) and question.strip():
            prompt += '\nOriginal research question (user objective, not source evidence):\n' + json.dumps(question, ensure_ascii=False)
            prompt += ('\nCheck that each target fulfills its role in answering this actual objective. '
                       'A limitation warning does not make a design capable of identifying the requested effect. '
                       'If the user asks to isolate intervention effects, the primary comparison must hold '
                       'recovery/optimization budgets and other interventions fixed. Unmatched native-pipeline '
                       'budgets can be supplementary, but cannot replace that primary comparison. '
                       'If the user explicitly studies whole pipelines or budgets themselves, judge that '
                       'different estimand instead; do not impose an unrelated matched-budget question.')
        
        if any(c.get('designContractVersion') == 2 for c in [*claims, *proposal_context]):
            prompt += ('\nFor groups, every necessary numeric threshold, rate and degree must appear as '
                       'a numeric parameter with an actual value. Audit each action against its parameters: '
                       'an omitted required parameter or numeric threshold disguised as a categorical choice '
                       'fails. A named symbol in an operation is not a chosen value. Check consistency with '
                       'the rendered control/treatment values and shared definitions.')
            prompt += '\nexecutionSpec is proposed configuration, not paper evidence. The application renders ' \
                      'its exact values into the published protocol; that deterministic suffix is not repeated here. ' \
                      'Check EVERY field and original claim text for concrete meaning and consistency: dataset, ' \
                      'scene selection, split, seeds, replication, formulas and uncertainty. Original prose must ' \
                      'not contradict fields; do not require duplicate prose for an explicit typed choice. Structural validation ' \
                      'does not certify meaningful choices. A scene-seed pair is not automatically independent ' \
                      'of another seed from the same scene; fixed checkpoints with no retraining do not produce ' \
                      'independent training replicates. Require paired groups within units. If resampling is proposed, ' \
                      'resample actual independent clusters. A purely descriptive comparison with explicit scope ' \
                      'needs no confidence interval, bootstrap or population-level inference. Still require concrete ' \
                      'view aggregation, pairing and seed handling when there are multiple seeds. Mixed metric ' \
                      'directions must be reported as a tradeoff, not automatically no improvement or worse. ' \
                      'Quoting a vague choice does not make it concrete.'
        if any(c.get('protocolContractVersion')==1 for c in [*claims,*proposal_context]):
            from services.deep_research.experiment_protocol import PROTOCOL_REVIEW_POLICY
            prompt += '\n'+PROTOCOL_REVIEW_POLICY
        if any(c.get('protocolContractVersion')==2 for c in [*claims,*proposal_context]):
            from services.deep_research.experiment_protocol import PROTOCOL_REVIEW_POLICY_V2
            prompt += '\n' + PROTOCOL_REVIEW_POLICY_V2
        if any(c.get('workflowContractVersion') in (1, 2, 3, 4) for c in [*claims, *proposal_context]):
            versions = sorted({c['workflowContractVersion'] for c in [*claims, *proposal_context]
                if type(c.get('workflowContractVersion')) is int and c['workflowContractVersion'] in (1, 2, 3, 4)})
            prompt += ('\nWorkflow contract ' + '/'.join(map(str, versions)) +
                ' binds steps to exact data/budget/controls/groups definitions. '
                'Check each new component creation rule, per-seed rebuilding or warm starts, '
                'split-before-fitting, train-only/validation-only checkpoint selection and '
                'consistency with all original prose. Nonempty fields do not prove these choices. '
                'Fixed-start replications do not establish independent baseline training. '
                'Contract 2/3 inputs must refer to actually available selected states: a framework name '
                'does not identify a renderer, and a base model does not automatically contain a new enhancement. '
                'Check the transformation and initial values of EVERY new trainable state, not just an RNG seed. '
                'Fresh creation must specify shape/count and values/RNG; deriving requires valid input selectors.')
            if 4 in versions:
                prompt += ('\nWorkflow 4 defines baseline initialization before training and explicit '
                    'stateDefinitions for every component. Independently enumerate ALL states required '
                    'by the chosen representation, then check each name/dtype/shape/initializer, actual '
                    'input axes, broadcasting, normalization and units. A valid distribution or full list '
                    'is not scientific approval. Check whether the creation/rendering/training operations '
                    'are compatible with those exact values; reject omitted states or conflicting prose.')
        if any(c.get('budgetContractVersion') == 1 for c in [*claims, *proposal_context]):
            prompt += '\nBudget contract 1 is the canonical baseline/recovery configuration. ' \
                      'Check prose and all other definitions against these exact typed choices. ' \
                      'matched means equal per-group recovery amounts in one unit; unmatched is ' \
                      'explicitly confounded by budget and cannot answer a matched-budget comparison. ' \
                      'Binary group ID digits correspond to factors order (0=control, 1=treatment). ' \
                      'A finite baseline cap or grounded existing-asset selection is mandatory. ' \
                      'Do not approve a narrative that contradicts its typed budget or promises an ' \
                      'unsupported asset. Structure alone does not prove scientific fairness.'
        if any(c.get('hypothesisContractVersion') == 1 for c in [*claims, *proposal_context]):
            prompt += '\nHypothesis contract 1 links a prospective statement to one analysis ID and exact effect keys. ' \
                      'Check BOTH original prose and typed statement against that actual analysis. ' \
                      'explore permits estimates/uncertainty but no significance or equivalence verdict; ' \
                      'test_zero needs an interval-based zero-effect decision; assess_equivalence needs ' \
                      'declared positive metric tolerances and a valid uncertainty interval. A near-zero ' \
                      'estimate or non-significance does not establish additivity, equivalence or independence. ' \
                      'Reject prose that makes a stronger promise than the linked method; do not infer correctness ' \
                      'from matching IDs, labels or nonempty formulas.'

        from services.deep_research.asset_availability import requires_existing_asset
        if any(requires_existing_asset(c) for c in claims):
            prompt += '''
For an existing-baseline budget target, a passed verdict MUST include assetAvailability:
{"evidenceId":"own fulltext ID","quote":"exact passage from that evidence quote",
 "assetQuote":"exact selected checkpoint/model-weights identity within availabilityQuote",
 "availabilityQuote":"exact clause explicitly stating the checkpoint or pretrained weights are released/available",
 "locator":"published https:// access locator appearing in quote"}.
Verify that this SAME released asset matches the target's selection rule, method, scene
and version. A paper saying its authors trained a model does NOT establish public weights.
A code-only release, future release, available-on-request promise or guessed checkpoint
cannot pass. Separate clauses about code availability and model training are insufficient.
If no release/access evidence is supplied, fail this existing-asset choice; propose finite
baseline training in a revision rather than inventing a locator or treating unknown as available.
This audits a published reference, not a tested download; do not claim to have fetched it.
'''

        if any(c.get('designContractVersion') == 2 and c.get('designRole') == 'data' for c in claims):
            prompt += '''
For each v2 data target, distinguish freely proposed parameters from existing data availability.
An inherited subset is NOT the entire parent dataset. Resolve the exact dataset/subset,
unit and membership from that target's own fulltext evidenceRefs. "Same scenes as [reference]"
alone establishes neither count nor names. Unknown availability must fail, not be guessed.
A passed data verdict MUST additionally include dataAvailability:
{"evidenceId":"own fulltext ID","quote":"exact passage from its quote",
 "scopeQuote":"exact words within that passage identifying the relevant data/subset",
 "availableCount":2,"countQuote":"two","availableNames":[]}
This is schema, not evidence. For sorted_first, bind the actual available unit count using
its exact numeric token (plain decimal digits or English one..twenty), and ensure requested
count does not exceed it. Never quote a count of views, methods, or another dataset as scenes.
For all mode, the proposed count must equal the entire count of that EXACT dataset/subset.
Full-set selection needs no invented ordering or per-unit name list when the quoted complete
benchmark scope is unambiguous. An inherited subset whose identity remains unresolved fails.
For named mode, instead provide availableNames with actual selected names explicitly present
in the quoted passage, including exact capitalization; count fields may be omitted.
Do not silently lowercase a source label in this exact-quotation audit. Verify name membership
and subset identity; a differently capitalized requested name must be resolved explicitly.
Only when the SAME dataset/scene identity is established, add nameBindings:
[{"selectedName":"requested label","sourceLabel":"exact label in availableNames"}].
This permits ASCII letter-case differences only, never synonyms, path normalization, URLs,
version IDs or fuzzy matches. Preserve the requested selection and literal source spelling.
Do not fail named mode solely because an unasserted original view count, resolution or
author-used split is unavailable. Ground the selected scene names and exact dataset;
check the proposed reproducible split as a proposed choice, including nonempty selections.
Any factual count, released asset or paper-attributed setting still requires its own evidence.
Do not infer dataset existence/capacity from a proposed choice or another proposal. Missing
fulltext support or unresolved subset identity fails even when every setting is concrete.
The dataAvailability object is an internal audit, not new experimental results.
'''
            if type(experiment_policy) is int and experiment_policy == 3:
                prompt += ('\nEvidence includes literal-name candidates for named data targets. These only '
                    'identify OWN visible quotes containing selected labels; they do not establish semantic '
                    'membership. Bind dataAvailability to the SAME name-bearing quotation after checking '
                    'dataset/subset identity. A parent-only citation cannot bind a scene name mentioned only '
                    'in another quote. Preserve exact source labels/quotes; fail if no candidate establishes '
                    'the relation. Never combine an evidenceId from one row with words from another.\n')

        if any(c.get("kind") in {"proposal", "suggestion", "hypothesis"} for c in claims):
            from services.deep_research.experimental_reasoning import design_requirements
            from services.deep_research.design_review_policy import REVIEW_DESIGN_POLICY, REVIEW_FACTORIAL_REFERENCE
            from services.deep_research.review_alignment import enabled as aligned_review,DESIGN_POLICY as aligned_design,factorial_reference
            design_policy=aligned_design if aligned_review(review_version) else REVIEW_DESIGN_POLICY
            if config_mode:
                prompt += '\nCheck that the target configurations are executable and mutually consistent. ' \
                          'Check parameter syntax, explicit intervention levels, split/seed rules, budgets ' \
                          'and measurement procedures. Reject a placeholder such as "pre-register a value". ' \
                          'Use the shared scientific definitions for consistency, but do not rederive their ' \
                          'formulas or issue verdicts for context statements.'
            else:
                prompt += '\nCheck target scientific assertions against the complete proposed configuration. ' \
                          'Reject incompatible sampling units, insufficient independent replication, invalid ' \
                          'metric signs and decision rules. Explain a failure concisely; no full derivation ' \
                          'is needed in the returned reason. Shared context is not itself verified by this call.\n' \
                          + factorial_reference(review_version)
                if any(c.get('designRole') in {'controls', 'steps'} for c in claims):
                    prompt += ('\nFor initialization/rendering targets, enumerate the states required by the '
                        'chosen representation and check that EACH has a defined count/shape and initial '
                        'value/distribution or valid source transformation. A seed and one scalar do not '
                        'initialize a whole representation. A general framework name does not specify an '
                        'actual compatible renderer/evaluator. Fail the target when these definitions are '
                        'missing; do not turn the omission into a harmless limitation. Check training and '
                        'rendering losses/parameter updates against that actual state.')
            prompt += '\nOther proposed statements, for consistency only (not evidence and not verdict targets):\n' + json.dumps(wire_context, ensure_ascii=False, separators=(',', ':'))
            if any(c.get('designRole') for c in claims):
                prompt += '\nFor every designRole, verify BOTH logical correctness AND fulfillment of its entire ' \
                          'requirement below. A role label, heading or vague promise is not fulfillment. Fail the ' \
                          'specific claim if its budget, split, procedure or decision criterion is unspecified. ' \
                          'Use the other target claims for shared definitions but not as factual evidence.\n' + design_requirements(
                              metric_domains, roles={c.get('designRole') for c in claims}, policy=design_policy)
                from services.deep_research.design_audit import design_slots_for_claim
                required_slots = {c['designRole']: slots for c in claims if c.get('designRole')
                                  and (slots := design_slots_for_claim(c, metric_domains)) is not None}
                audit_prompt = ('\nPassed verdicts require FLAT designAudit with these slot keys: '
                           + json.dumps(required_slots, separators=(',', ':'))
                           + '. Each slot is {"claimId":"target/context proposal ID","quote":"exact concrete choice"}. '
                           'Missing/vague choices use null and fail. Paper facts cannot supply configuration. '
                           'Check that each choice fulfills the entire slot, not mere keyword presence. '
                           'Promises such as "fixed split", "same seed", "measure FPS" or "predeclare a tolerance" fail. '
                           'For discontinuous text use {"quotes":[{"claimId":"ID","quote":"exact substring"}]} '
                           'with 1 to 32 segments. Copy punctuation exactly; never join, summarize or rewrite. '
                           'Every segment must match its source and together cover the whole slot. No mixed forms.')
                from services.deep_research.design_audit import audit_field_roots
                roots = audit_field_roots(dict.fromkeys(slot for slots in required_slots.values() for slot in slots),
                    workflow_v4=any(c.get('workflowContractVersion') == 4 for c in [*claims, *proposal_context]))
                controls_contract = ('a supported protocol contract' if any(c.get('protocolContractVersion') == 2
                    for c in [*claims, *proposal_context]) else 'protocol contract 1')
                audit_prompt += ('\nTyped choices use {"ref":{"claimId":"target/context ID",'
                           '"path":["executionSpec","existing allowed root"]}}; the server resolves the '
                           'UNCHANGED existing value. For 1-32 choices use {"fields":[{'
                           '"claimId":"ID","path":["executionSpec","existing allowed root"],"value":"exact typed value"}]}. '
                           'Path elements are object keys or zero-based integer list indices. Never quote JSON '
                           'serialization or mix ref/fields with quote/quotes. Allowed slot roots (under '
                           'executionSpec, source role required): ' + json.dumps(roots, separators=(',', ':'))
                           + '. Other slots use literal quotes. Controls require ' + controls_contract + '; budget '
                           'requires budget contract 1; step fields require a supported workflow contract. '
                           'per_group_steps MUST bind recovery; baseline-only refs/fields fail. All choices '
                           'together must fulfill the ENTIRE slot; bindings do not prove scientific correctness.')
                skeleton = [{'claimId': c['claimId'], 'status': 'failed',
                    'reason': '',
                    'designAudit': {slot: None for slot in required_slots.get(c.get('designRole'), ())},
                    **({'dataAvailability': None}
                       if c.get('designContractVersion') == 2 and c.get('designRole') == 'data' else {}),
                    **({'assetAvailability': None} if requires_existing_asset(c) else {})}
                    for c in claims]
                audit_prompt += '\nFill this exact per-target response skeleton. Change status only after checking. ' \
                          'Replace a null slot with a supported quote, quotes or fields binding ' \
                          'only if such a choice is already written; otherwise keep null and fail. ' \
                          'Do not replace slot keys with role names or arrays. Symbolic placeholders such as ' \
                          'an unspecified threshold or degree do not define actual intervention levels. ' \
                          'A dataAvailability null must be replaced with the source-bound object specified above ' \
                          'before a data target can pass; designAudit fields alone do not establish availability.\n' \
                          + json.dumps(skeleton, ensure_ascii=False, separators=(',', ':'))
                # Hypothesis/limits have no configuration-audit slots. Keep
                # their complete scientific requirements and context, without
                # unrelated field-binding schemas for other roles.
                if required_slots:
                    prompt += audit_prompt
        comparison_enabled=(self._comparison_reasoning() if callable(self._comparison_reasoning)
                            else self._comparison_reasoning) is True
        comparison_version=(self._comparison_audit_version() if callable(self._comparison_audit_version)
                            else self._comparison_audit_version)
        if comparison_enabled:
            from services.deep_research.comparison_reasoning import audit_scope,audit_prompt as comparison_audit_prompt
            comparison_targets={c['claimId']:audit_scope(c,evidence) for c in claims if audit_scope(c,evidence)}
            if comparison_targets:
                prompt+=comparison_audit_prompt(comparison_targets, comparison_version)
        scope_enabled=(self._factual_scope() if callable(self._factual_scope) else self._factual_scope) is True
        complete_scope=(self._complete_factual_scope() if callable(self._complete_factual_scope)
                        else self._complete_factual_scope) is True
        if scope_enabled:
            from services.deep_research.factual_scope import audit_prompt as scope_prompt
            targets=[c['claimId'] for c in claims if c.get('kind') in {'reported','inference'}]
            if targets:
                prompt+=scope_prompt(targets,**({'complete_statement':True} if complete_scope else {}))
        attribution_enabled=(self._result_attribution() if callable(self._result_attribution)
                             else self._result_attribution) is True
        if attribution_enabled:
            from services.deep_research.result_attribution import targets as result_targets, audit_prompt as result_prompt
            required={c['claimId']: result_targets(c) for c in claims if result_targets(c)}
            if required:
                prompt+=result_prompt(required)
        field_bindings=(self._audit_source_fields() if callable(self._audit_source_fields)
                        else self._audit_source_fields) is True
        target_bindings=(self._audit_target_fields() if callable(self._audit_target_fields)
                         else self._audit_target_fields) is True
        has_factual_targets=any(c.get('kind') in {'reported','inference'} for c in claims)
        if field_bindings and (scope_enabled or comparison_enabled) and (has_factual_targets or not target_bindings):
            from services.deep_research.audit_source_fields import GUIDANCE as source_field_guidance
            prompt+='\n'+source_field_guidance
        if target_bindings and scope_enabled and has_factual_targets:
            from services.deep_research.audit_source_fields import TARGET_GUIDANCE
            prompt+='\n'+TARGET_GUIDANCE
        from services.deep_research.prospective_review import enabled as prospective_review_enabled, policy as prospective_review_policy
        if prospective_review_enabled(review_version) and all(
                c.get('kind') in {'proposal', 'suggestion', 'hypothesis'} for c in claims):
            prompt += '\n' + prospective_review_policy(review_version)
        from services.deep_research.configuration_consistency import enabled as consistent, facts as config_facts, REVIEW as consistency_review
        consistency_version=(self._configuration_consistency() if callable(self._configuration_consistency)
                             else self._configuration_consistency)
        if consistent(consistency_version) and all(c.get('kind') in {'proposal','suggestion','hypothesis'} for c in claims):
            derived=config_facts([*wire_claims,*wire_context])
            if derived:
                prompt+='\n'+consistency_review+'\nDerived configuration meanings (not evidence):\n'+json.dumps(derived,ensure_ascii=False,separators=(',',':'),allow_nan=False)
        from services.deep_research.review_alignment import enabled as aligned_review,declaration_links
        if aligned_review(review_version) and all(c.get('kind') in {'proposal','suggestion','hypothesis'} for c in claims):
            links=declaration_links([*wire_claims,*wire_context])
            if links:
                prompt+='\nDeclared key presence (not scientific approval):\n'+json.dumps(links,ensure_ascii=False,separators=(',',':'))
        from services.deep_research.experiment_review_envelope import enabled as review_envelope,build as build_review
        envelope_version=(self._prospective_envelope() if callable(self._prospective_envelope)
                          else self._prospective_envelope)
        full_review_inputs=review_envelope(envelope_version,review_version,claims)
        if full_review_inputs:
            prompt=build_review(claims_text=claims_text,context=wire_context,question=question,
                evidence_marker=evidence_text,metric_domains=metric_domains,config_mode=config_mode,
                version=envelope_version)
        template = prompt
        source_keys = ('workId', 'versionId', 'sourceTitle')
        source_registry = {}
        source_aliases = {}
        for row in evidence_map.values():
            identity = tuple(row.get(key) for key in source_keys)
            if identity not in source_aliases:
                alias = f'P{len(source_aliases) + 1}'
                source_aliases[identity] = alias
                source_registry[alias] = {key: row.get(key) for key in source_keys}
                if row.get('publicationIdentity'):
                    source_registry[alias]['publicationIdentity'] = row['publicationIdentity']

        def render_evidence(rows):
            packed, used = {}, set()
            for row in rows:
                alias = source_aliases[tuple(row.get(key) for key in source_keys)]
                used.add(alias)
                packed[row['evidenceId']] = {
                    **{key: value for key, value in row.items()
                       if key not in (*source_keys, 'evidenceId', 'publicationIdentity')}, 'source': alias}
            view = {'sources': {key: value for key, value in source_registry.items() if key in used},
                    'evidence': packed}
            if type(experiment_policy) is int and experiment_policy == 3:
                from services.deep_research.membership_candidates import named_membership_candidates
                candidates = named_membership_candidates(wire_claims,
                    [e for e in wire_evidence if e['evidenceId'] in packed])
                if candidates:
                    view['literalNameCandidatesNotMembershipProof'] = candidates
            return template.replace(evidence_text, json.dumps(
                view, ensure_ascii=False, separators=(',', ':')), 1)

        def split_before_dispatch():
            midpoint = len(claims) // 2
            verdicts = []
            for batch, siblings in ((claims[:midpoint], claims[midpoint:]),
                                    (claims[midpoint:], claims[:midpoint])):
                context = [*proposal_context, *[{
                    key: c[key] for key in ('claimId', 'text', 'kind', 'conditions',
                        'designRole', 'executionSpec', 'designContractVersion', 'budgetContractVersion',
                        'hypothesisContractVersion','protocolContractVersion','workflowContractVersion') if key in c
                } for c in siblings if c.get('kind') in {'proposal', 'suggestion', 'hypothesis'}]]
                verdicts.extend(self._check_batch(batch, evidence, context, node=node))
            return verdicts

        try:
            if full_review_inputs:
                # The original surrounding context resolves method subjects.
                # Split complete targets BEFORE optional-context stripping.
                rows=[{"evidenceId": key, **value} for key,value in evidence_map.items()]
                full_prompt=render_evidence(rows)
                if len(full_prompt.encode('utf8'))>byte_limit:
                    if len(claims)>1:
                        return split_before_dispatch()
                    return [{'claimId':claims[0]['claimId'],'status':'failed',
                        'reason':'完整核验输入超出容量，本条尚未核验，不能据此判断论文证据不足。',
                        'executionState':'not_started','reviewInputCapacity':{
                            'inputBytes':len(full_prompt.encode('utf8')),'maxInputBytes':byte_limit}}]
            prompt, visible_evidence = fit_evidence_prompt(
                [{"evidenceId": key, **value} for key, value in evidence_map.items()], render_evidence,
                max_bytes=byte_limit)
        except ValueError as exc:
            if str(exc) == 'prompt_fixed_content_too_large' and len(claims) > 1:
                return split_before_dispatch()
            if str(exc) == 'prompt_fixed_content_too_large':
                from services.deep_research.contracts import BudgetExhaustedError
                raise BudgetExhaustedError('verificationPromptBytes', byte_limit,
                    len(render_evidence([]).encode('utf-8'))) from exc
            raise DeepResearchError('invalid_verification_input',
                                    '声明核验输入无效；已取得的资料仍保留。') from exc
        # Do not spend a model call on a multi-target request already known to
        # omit its required evidence. Preserve full sibling definitions as
        # consistency context; each target keeps its own evidence permissions.
        if referenced - {row['evidenceId'] for row in visible_evidence}:
            if len(claims) > 1:
                return split_before_dispatch()
            return [{'claimId': claims[0]['claimId'], 'status': 'failed',
                     'reason': '请求容量限制导致引用证据未完整提供，不能确认该声明。'}]
        visible_evidence = restore_visible_evidence(visible_evidence, reverse_aliases)
        try:
            bounded_review=(self._bounded_factual_review() if callable(self._bounded_factual_review)
                            else self._bounded_factual_review) is True
            from services.deep_research.factual_review import eligible as review_eligible,OPTION as REVIEW_OPTION
            review_options={REVIEW_OPTION:True} if bounded_review and node=='verify' and review_eligible(claims) else {}
            result = self._invoke(
                run_id=self._run_id,
                node=node,
                prompt=prompt,
                extra_body={"max_tokens": 4000, "temperature": 0.0,**review_options},
                use_reserve=True,  # Use reserve pool for verification
            )
            
            if result.get('notStarted')=='factual_review_time_budget':
                return [{'claimId':c['claimId'],'status':'failed',
                    'reason':'剩余时间不足以完成独立核验及最终覆盖检查，本条尚未核验。',
                    'executionState':'not_started','reviewTimeAdmission':result['admission']} for c in claims]
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
                                        '声明核验未完整返回；不能据此判断材料不足。',
                                        {'responseState': 'received_invalid'})
            from services.deep_research.design_audit import validate_design_audit
            parsed = [restore_verdict_evidence(v, reverse_aliases) for v in parsed]
            if comparison_enabled:
                from services.deep_research.comparison_reasoning import normalize_audit_scope
                target_by_id = {c['claimId']: c for c in claims}
                parsed = [normalize_audit_scope(target_by_id[v['claimId']], v, visible_evidence,
                          version=comparison_version) for v in parsed]
            by_id = {c['claimId']: c for c in claims}
            from services.deep_research.rejection_audit import enabled as rejection_binding,bind as bind_rejection
            if full_review_inputs and rejection_binding(envelope_version):
                parsed=[bind_rejection(v,[*json.loads(claims_text),*wire_context]) for v in parsed]
            visible_ids = {row["evidenceId"] for row in visible_evidence}
            for verdict in parsed:
                if verdict['status'] != 'passed':
                    continue
                target = by_id[verdict['claimId']]
                if set(target.get('evidenceRefs', [])) - visible_ids:
                    verdict['status'] = 'failed'
                    verdict['reason'] = '请求容量限制导致引用证据未完整提供，不能确认该声明。'
                    continue
                if comparison_enabled:
                    from services.deep_research.comparison_reasoning import validate_audit
                    comparison_errors=validate_audit(target,verdict,visible_evidence,
                        source_field_bindings=field_bindings)
                    if comparison_errors:
                        verdict['status']='failed'
                        verdict['reason']='比较条件或推断前提尚未核实：'+', '.join(comparison_errors)
                        continue
                if scope_enabled:
                    from services.deep_research.factual_scope import validate_audit as validate_scope
                    scope_errors=validate_scope(target,verdict,visible_evidence,
                        source_field_bindings=field_bindings,target_field_bindings=target_bindings,
                        **({'complete_statement':True} if complete_scope else {}))
                    if scope_errors:
                        verdict['status']='failed'
                        verdict['reason']='结论范围或必要条件尚未核实：'+', '.join(scope_errors)
                        continue
                if attribution_enabled:
                    from services.deep_research.result_attribution import validate_audit as validate_attribution
                    attribution_errors=validate_attribution(target,verdict,visible_evidence)
                    if attribution_errors:
                        verdict['status']='failed'
                        verdict['reason']='结果与实验用途的来源归属尚未核实：'+', '.join(attribution_errors)
                        continue
                missing = validate_design_audit(by_id[verdict['claimId']], verdict, [*claims, *proposal_context], metric_domains,
                    **({'direct_fields':True} if type(review_version) is int and review_version in (2,3) else {}))
                if missing:
                    verdict['status'] = 'failed'
                    verdict['reason'] = '实验方案缺少可核对的具体配置：' + ', '.join(missing)
                    continue
                from services.deep_research.data_availability import validate_data_availability
                availability_errors = validate_data_availability(target, verdict, visible_evidence)
                if availability_errors:
                    verdict['status'] = 'failed'
                    verdict['reason'] = '所选数据范围或可用数量尚未核实：' + ', '.join(availability_errors)
            return parsed
            
        except DeepResearchError:
            # Preserve budget, authorization and unknown-call recovery semantics.
            # A missing verdict is an execution failure, not evidence of insufficiency.
            raise
        except Exception as exc:
            logger.exception("Semantic check failed for run %s", self._run_id)
            raise DeepResearchError('invalid_verification_response',
                                    '声明核验未完成；已取得的资料仍保留。') from exc
