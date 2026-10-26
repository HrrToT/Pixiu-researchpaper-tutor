"""ResearchFacade - unified entry point for Deep Research v2.

Provides create/get/action API with durable idempotent operations.
Async single instance executor bounded to 2 concurrent runs.
Persist restart recovery before accepting work.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
import uuid
from datetime import datetime, UTC
from concurrent.futures import ThreadPoolExecutor, Future
from copy import deepcopy
from typing import Any, Callable

from services.deep_research.request_context import effective_question

from services.deep_research.contracts import (
    CONTRACT_VERSION,
    ENGINE_VERSION,
    OUTCOME_NONE,
    OUTCOME_PARTIAL,
    OUTCOME_INCONCLUSIVE,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PAUSED,
    STATUS_QUEUED,
    STATUS_RUNNING,
    STATUS_STOPPING,
    STATUS_WAITING_USER,
    EpochConflictError,
    LateCompletionError,
    TERMINAL_STATUSES,
    DeepResearchError,
    IdempotencyConflictError,
    IllegalStatusTransitionError,
    RunNotFoundError,
    RevisionConflictError,
    TerminalGuardError,
    digest,
    new_run_id,
    normalize_run,
    resolve_budget_profile,
    utc_now_iso,
)

logger = logging.getLogger(__name__)


def _execution_failure_message(calls, unknown):
    if unknown:
        return "上一次请求的结果尚未确认，研究已暂停，系统不会自动重发。"
    failed_model_calls = [c for c in calls
                          if c.get('tool') == 'llm_invoke' and c.get('status') == 'failed']
    if failed_model_calls:
        error = failed_model_calls[-1].get('error') or {}
        if error.get('type') == 'provider_error' and error.get('status_code') == 402:
            return "模型服务拒绝了请求（HTTP 402）。请检查模型账户额度与计费状态，确认可用后再发起研究。"
    return "本次研究未能完成，请查看已保存的结果或稍后补查。"


def _elapsed_seconds(record):
    started = record.get("startedAt")
    if not started:
        return 0
    end = record.get("finishedAt")
    if record.get("status") == STATUS_WAITING_USER:
        end = record.get("state", {}).get("waitingSince") or record.get("updatedAt")
    elif record.get("status") in {STATUS_PAUSED, STATUS_CANCELLED}:
        end = end or record.get("updatedAt")
    try:
        start = datetime.fromisoformat(started.replace("Z", "+00:00"))
        finish = datetime.fromisoformat(end.replace("Z", "+00:00")) if end else datetime.now(UTC)
        return round(max(0, (finish - start).total_seconds()), 3)
    except (ValueError, TypeError):
        return record.get("budget", {}).get("elapsedSeconds", 0)


class ResearchFacade:
    """Unified facade for Deep Research v2 operations.
    
    Injectable dependencies for testing. Async execution bounded to 2 instances.
    Deterministic run IDs via UUID5(operationKey) for receipt recovery.
    """
    
    def __init__(
        self,
        repo: Any,  # DeepResearchRepository
        graph_factory: Callable[..., Any],
        *,
        llm_client: Any = None,
        retriever: Callable[[str, str, int], list] | None = None,
        source_reader: Callable[[str, str], dict] | None = None,
        scope_validator: Callable[[str, str], bool] | None = None,
        external_acquire: Callable | None = None,
        max_concurrent: int = 2,
    ):
        self._repo = repo
        self._graph_factory = graph_factory
        self._llm_client = llm_client
        self._retriever = retriever
        self._source_reader = source_reader
        self._scope_validator = scope_validator
        self._external_acquire = external_acquire
        self._max_concurrent = max_concurrent
        self._executor = ThreadPoolExecutor(max_workers=max_concurrent)
        self._active_futures: dict[str, Future] = {}
        self._lock = threading.Lock()
    
    def shutdown(self, wait: bool = True) -> None:
        """Shutdown the executor and wait for active futures to complete.
        
        Args:
            wait: If True, block until all active futures complete
        """
        self._executor.shutdown(wait=wait)
        if wait:
            with self._lock:
                for future in self._active_futures.values():
                    try:
                        future.result(timeout=30)
                    except Exception:
                        pass
                self._active_futures.clear()
    
    def create(
        self,
        request: dict[str, Any],
        *,
        start_async: bool = True,
    ) -> tuple[dict[str, Any], bool]:
        """Create a new research run.
        
        Args:
            request: Research request payload with mandatory workspaceTaskId and operationKey
            start_async: If True, start execution in background
            
        Returns:
            (run_record, created) tuple
            
        Raises:
            DeepResearchError: If llm_client not configured (503, not fake empty result)
        """
        # Validate LLM client is configured - missing client = 503, not fake empty result
        if self._llm_client is None:
            raise DeepResearchError(
                "llm_not_configured",
                "LLM client not configured - cannot execute research",
                {"status_code": 503},
            )
        
        # Mandatory product fields
        workspace_task_id = request.get("workspaceTaskId", "")
        operation_key = request.get("operationKey", "") or request.get("requestId", "")
        
        if not workspace_task_id:
            raise DeepResearchError("missing_workspace_task_id", "workspaceTaskId is mandatory")
        if not operation_key:
            raise DeepResearchError("missing_operation_key", "operationKey is mandatory")
        
        # Generate deterministic run ID from operation key for receipt recovery
        run_id = f"dr_run_{uuid.uuid5(uuid.NAMESPACE_URL, f'{workspace_task_id}:{operation_key}').hex}"
        
        # Build run payload
        budget_profile = request.get("budgetProfile", "standard")
        _, budget_limits = resolve_budget_profile(budget_profile)
        
        # Normalize materialSnapshot (Java-supplied immutable snapshot) into materials list
        # Snapshot may be dict with materialRefs/materialVersions or already a list
        raw_snapshot = request.get("materialSnapshot")
        from services.deep_research.source_labels import source_display_title
        if raw_snapshot is not None:
            if isinstance(raw_snapshot, dict):
                # Extract from dict structure - normalize to list of material objects
                refs = raw_snapshot.get("materialRefs", raw_snapshot.get("materials", []))
                versions = raw_snapshot.get("materialVersions", {})
                if isinstance(versions, list):
                    versions = {item.get("id"): item for item in versions if isinstance(item, dict)}
                materials = []
                for ref in refs:
                    if isinstance(ref, str):
                        # Simple ID reference
                        version_info = versions.get(ref, {})
                        materials.append({
                            "materialId": ref,
                            "pdfId": ref,
                            "workId": ref,
                            "versionId": version_info.get("versionId") or version_info.get("contentHash", ""),
                            "contentHash": version_info.get("contentHash", ""),
                            "title": source_display_title(version_info.get("title"), version_info.get("fileName"), ref),
                        })
                    elif isinstance(ref, dict):
                        # Full material object
                        mat_id = ref.get("materialId", ref.get("id", ""))
                        materials.append({
                            "materialId": mat_id,
                            "pdfId": ref.get("pdfId", mat_id),
                            "workId": ref.get("workId", mat_id),
                            "versionId": ref.get("versionId", ""),
                            "contentHash": ref.get("contentHash", ""),
                            "title": source_display_title(ref.get("title"), ref.get("fileName"), mat_id),
                        })
            elif isinstance(raw_snapshot, list):
                # Already a list - normalize each entry
                materials = []
                for item in raw_snapshot:
                    if isinstance(item, str):
                        materials.append({"materialId": item, "pdfId": item, "workId": item})
                    elif isinstance(item, dict):
                        mat_id = item.get("materialId", item.get("id", ""))
                        materials.append({
                            "materialId": mat_id,
                            "pdfId": item.get("pdfId", mat_id),
                            "workId": item.get("workId", mat_id),
                            "versionId": item.get("versionId", ""),
                            "contentHash": item.get("contentHash", ""),
                            "title": source_display_title(item.get("title"), item.get("fileName"), mat_id),
                        })
            else:
                materials = request.get("materials", [])
        else:
            materials = request.get("materials", [])
        
        # Persist materialSnapshot separately as immutable reference
        material_snapshot = request.get("materialSnapshot")
        inherited_state = {}
        continuation_context = {}
        parent_id = request.get("parentRunId")
        if parent_id:
            parent = self._repo.require_run(parent_id)
            if parent.get("taskId") != workspace_task_id or parent.get("status") not in TERMINAL_STATUSES:
                raise DeepResearchError("invalid_parent", "只能从本任务已结束的研究继续")
            unconfirmed = _unconfirmed_call_ids(self._repo, parent_id)
            if unconfirmed or parent.get('errorCode') == 'unresolved_unknown':
                from services.deep_research.contracts import UnresolvedUnknownError
                raise UnresolvedUnknownError(parent_id, unconfirmed)
            from services.deep_research.continuation import reusable_local_source
            current_materials = {m['materialId']: m for m in materials}
            parent_materials = {m['materialId']: m for m in parent.get('materials', [])}
            refresh = request.get("freshness") == "refresh" or any(word in request.get("question", "").lower()
                                                                    for word in ("最新", "更新到", "latest"))
            external = request.get("sourcePolicy", {}).get("mode") in {"academic_external", "external_only"}
            sources = [s for s in parent.get("state", {}).get("sources", []) if
                       reusable_local_source(s, current_materials.get(s.get('workId')), parent_materials.get(s.get('workId'))) or
                       (s.get("sourceKind") == "arxiv" and external and not refresh)]
            source_ids = {s["sourceId"] for s in sources}
            evidence = [e for e in parent.get("state", {}).get("evidence", []) if e.get("sourceId") in source_ids]
            inherited_state = {"sources": sources, "inheritedSources": sources,
                               "evidence": evidence, "inheritedEvidence": evidence}
            from services.deep_research.request_context import instruction_layers
            from services.deep_research.plan_resume import edited_question_context
            parent_instructions = instruction_layers(parent)
            edited_targets = edited_question_context(parent)
            if edited_targets:
                parent_instructions = [edited_targets, *parent_instructions]
            context = request.get('continuationContext') or {}
            snapshot_contexts = material_snapshot.get('contextMaterials', []) if isinstance(material_snapshot, dict) else []
            if context and (not isinstance(context, dict) or context not in snapshot_contexts
                            or context.get('kind') != 'artifact' or context.get('accessLevel') != 'unverified_context'):
                raise DeepResearchError('invalid_continuation_context', '追问背景未绑定到当前材料快照。')
            continuation_context = {'parentRunId': parent_id, 'parentInstructions': parent_instructions,
                                    'artifactContext': deepcopy(context)}
        
        payload = {
            "runId": run_id,
            "taskId": workspace_task_id,  # Product task ID
            "workspaceId": workspace_task_id,
            "idempotencyKey": operation_key,
            "engineVersion": ENGINE_VERSION,
            "contractVersion": CONTRACT_VERSION,
            "question": request.get("question", ""),
            "materials": materials,
            "materialSnapshot": material_snapshot,  # Immutable Java snapshot
            "contextMaterials": (material_snapshot or {}).get("contextMaterials", []) if isinstance(material_snapshot, dict) else [],
            "promptVersion": "dr-v2.20261026.303",
            "factualReviewContractVersion": 1,
            "citationPresentationContractVersion": 4,
            "configurationConsistencyContractVersion": 2,
            "experimentPlanEncodingContractVersion": 7,
            "experimentOutlineEncodingContractVersion": 2,
            "experimentGenerationEnvelopeContractVersion": 3,
            "experimentInputContractVersion": 1,
            "experimentReviewEnvelopeContractVersion": 10,
            "reviewBatchPlanningContractVersion": 1,
            "executionWorkflowContractVersion": 7,
            "experimentPlanningReasoningContractVersion": 1,
            "scientificOutlineContractVersion": 1,
            "workflowMetadataRowsContractVersion": 2,
            "workflowMetadataRepairContractVersion": 34,
            "workflowInitializationOutputContractVersion": 1,
            "workflowInitializationRepairContractVersion": 2,
            "experimentRepairPriorityContractVersion": 2,
            "experimentExecutionGuidanceContractVersion": 2,
            # New experiments separate a small persisted scientific plan from
            # direct complete configuration, under the same aggregate budget.
            # Saved v1/v2 requests and unknown identities remain unchanged.
            "experimentDraftContractVersion": 6,
            "experimentRepairContractVersion": 6,
            "experimentRepairInputContractVersion": 5,
            "experimentReviewContractVersion": 3,
            "experimentEvidenceContractVersion": 1,
            "factualRepairContractVersion": 2,
            "synthesisEvidenceContractVersion": 6,
            "extractionScheduleContractVersion": 1,
            "experimentIntentContractVersion": 3,
            "tableReferencesContractVersion": 1,
            "factualScopeContractVersion": 4,
            "answerPointIntentContractVersion": 1,
            "scopeExpressionContractVersion": 1,
            "factualReasoningContractVersion": 5,
            "continuationFormatContractVersion": 1,
            "jointEvidenceContractVersion": 1,
            "repairEvidencePriorityVersion": 1,
            "comparisonReasoningContractVersion": 3,
            "namedRowIdentityContractVersion": 1,
            "requestGroundingContractVersion": 3,
            "factRedraftContractVersion": 3,
            "verificationFeedbackContractVersion": 2,
            "quantitySpellingContractVersion": 6,
            "runtimeSemanticContractVersion": 1,
            "evidenceCoverageContractVersion": 3,
            "sourcePrecisionContractVersion": 8,
            "sourceContinuityContractVersion": 2,
            "readingPriorityContractVersion": 5,
            "absenceScopeContractVersion": 7,
            "answerFormatContractVersion": 1,
            "repairProgressContractVersion": 2,
            "reportPresentationContractVersion": 2,
            "auditSourceFieldsContractVersion": 2,
            "structuredOutputContractVersion": 15,
            "claimIsolationContractVersion": 1,
            "dependencyContractVersion": 1,
            "adaptiveExtractionContractVersion": 3,
            "continuationContextContractVersion": 1,
            "continuationContext": continuation_context,
            "planResumeContractVersion": 1,
            "exactDiscoveryContractVersion": 1,
            "planEditContractVersion": 1,
            "clarificationContractVersion": 1,
            "adaptiveResearchContractVersion": 1,
            "audienceRewriteContractVersion": 8,
            "verificationInputContractVersion": 1,
            "workflowContractVersion": 5,
            "extractionPriorityVersion": 10,
            "planCompletionContractVersion": 1,
            "budgetContractVersion": 1,
            "hypothesisContractVersion": 1,
            "protocolContractVersion": 2,
            "experimentPlanContractVersion": 1,
            "retrievalVersion": "task-pdf-context-continuity.4",
            "focusPaperIds": request.get("focusPaperIds", []),
            "sourcePolicy": request.get("sourcePolicy", {"mode": "task_only"}),
            "budgetProfile": budget_profile,
            "budget": {**budget_limits, 'finalizationBudgetVersion': 1, 'releasedReserveTokens': 0,
                       'explorationAllocationVersion': 1},
            "requestDigest": digest(request),
            "parentRunId": request.get("parentRunId", ""),
            "outputKind": request.get("outputKind", "general"),
            "state": inherited_state,
        }
        
        # Persist BEFORE accepting work
        try:
            record, created = self._repo.create_run(payload)
        except IdempotencyConflictError:
            raise
        except Exception as exc:
            logger.exception("Failed to create run")
            raise DeepResearchError("create_failed", str(exc)) from exc
        
        # Start async execution if requested and newly created
        # Java uses deferStart=true to create QUEUED without auto-start, then resume via action
        if start_async and created and record.get("status") == STATUS_QUEUED:
            self._start_execution(record["runId"])
        
        return record, created
    
    def get(self, run_id: str) -> dict[str, Any]:
        """Pure query - no generation, no external requests.
        
        Returns run state with compact activity summary.
        """
        record = self._repo.require_run(run_id)
        
        # Build response without triggering any side effects
        state = record.get("state", {})
        budget = record.get("budget", {})
        visible_sources = self.get_sources(run_id)
        unconfirmed = (record.get('status') not in (STATUS_RUNNING, STATUS_STOPPING)
                       and bool(_unconfirmed_call_ids(self._repo, run_id)))
        unknown = unconfirmed or record.get('errorCode') == 'unresolved_unknown'
        
        return {
            "contractVersion": record.get("contractVersion", CONTRACT_VERSION),
            "engineVersion": record.get("engineVersion", ENGINE_VERSION),
            "promptVersion": record.get("promptVersion", ""),
            "retrievalVersion": record.get("retrievalVersion", ""),
            "taskId": record.get("taskId", ""),
            "runId": record["runId"],
            "runRevision": record.get("runRevision", 0),
            "executionEpoch": record.get("executionEpoch", 0),
            "status": record.get("status", STATUS_QUEUED),
            "outcome": record.get("outcome", OUTCOME_NONE),
            "errorCode": 'unresolved_unknown' if unknown else record.get("errorCode", ""),
            "error": '上次请求结果尚未确认，不会自动重发；已取得的资料仍保留。' if unknown else {
                "invalid_plan_response": "研究计划未能完整生成，本次已停止。可重新发起研究；这会产生新的模型调用。",
                "invalid_brief_response": "研究目标未能正确解析，本次已停止。请简化问题后重新研究。",
                "invalid_synthesis_response": "报告未能完整生成，本次已停止；已取得的资料仍保留。可补查继续，这会产生新的模型调用。",
                "invalid_verification_response": "结论核验未完成，本次已停止；已取得的资料仍保留。这不表示论文证据不足。",
                "external_discovery_unavailable": "外部文献暂时无法获取，本次研究已停止，尚未读到所需资料。这不表示论文缺少证据；可稍后重新研究。",
            }.get(record.get("errorCode", ""), "") or (record.get("error") or {}).get("message", ""),
            "title": state.get("title") or {"direction_survey": "方向调研", "paper_comparison": "论文比较",
                "claim_verification": "主张核查", "experiment_design": "实验方案", "research_entry": "研究切入点"}
                .get(state.get("outputKind", record.get("outputKind")), "学术研究"),
            "outputKind": state.get("outputKind", record.get("outputKind")),
            "activity": None if unknown else _build_activity_summary(record),
            "summary": (record.get("result") or {}).get("summary", ""),
            # Expose full report body for Java/UI consumption
            "report": {
                "artifactId": state.get("publicationId", ""),
                "versionId": state.get("reportVersionId", ""),
                "body": record.get("report", ""),
                "text": state.get("reportText", ""),  # Rendered markdown for Java
            } if record.get("publication", {}).get("publicationId") else None,
            "parentRunId": record.get("parentRunId", ""),
            # Plan metadata for UI
            "plan": state.get("plan", []),
            "planRevision": state.get("planRevision", 0),
            # Clarification state
            "clarification": {
                "needed": state.get("clarificationNeeded", False),
                "question": state.get("clarificationQuestion", ""),
            } if state.get("clarificationNeeded") else None,
            "resumeDeferred": state.get('resumeDeferred')
                if 'resume' in _compute_allowed_actions(record) else None,
            # Source metadata for UI
            "sources": visible_sources,
            "events": self.get_events(run_id),
            "sourceCount": len(visible_sources),
            "allowedActions": _compute_allowed_actions(record, unconfirmed=unconfirmed),
            "budget": {
                "profile": budget.get("profile", "standard"),
                "modelCalls": budget.get("modelCalls", 0) + budget.get("reservedModelCalls", 0),
                "maxModelCalls": budget.get("maxModelCalls", 18),
                "tokens": budget.get("tokens", 0),
                "maxTokens": budget.get("maxTokens", 100000),
                "externalSearches": budget.get("externalSearches", 0),
                "fulltextFetches": budget.get("fulltextFetches", 0),
                "elapsedSeconds": _elapsed_seconds(record),
                "cost": None,  # No configured price table: unknown must never appear as zero cost.
            },
        }
    
    def get_action_receipt(self, run_id: str, request_id: str) -> dict:
        """Pure lookup: pending/failed receipts are never reissued by GET."""
        if not isinstance(request_id,str) or not request_id.strip() or len(request_id)>256:
            raise DeepResearchError('invalid_request_id','操作请求标识无效。',{'status_code':422})
        receipt = self._repo.get_action_receipt(run_id,request_id)
        if receipt is None:
            raise DeepResearchError('action_not_found','未找到已保存的操作回执。',{'status_code':404})
        return receipt

    def action(
        self,
        run_id: str,
        action_name: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute durable idempotent action on a run.
        
        Wires claim_action BEFORE any mutation for crash safety.
        Existing completed receipt returns stored result before revision check.
        Pending receipt raises unknown_action - no automatic reissue.
        Different payload conflicts raise IdempotencyConflictError.
        
        Args:
            run_id: Target run
            action_name: One of pause, cancel, resume, clarify, plan, continue
            payload: Action-specific payload with expectedRunRevision and requestId (required)
            
        Returns:
            Updated run state or stored result from completed receipt
        """
        # Required fields
        request_id = payload.get("requestId", "")
        expected_revision = payload.get("expectedRunRevision")
        
        if not request_id:
            raise DeepResearchError("missing_request_id", "requestId is required for actions")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
            raise DeepResearchError("invalid_revision", "必须提供研究运行的整数版本")
        
        # Full fingerprint: {name, payload, runId}
        action_fingerprint = digest({
            "action": action_name,
            "payload": payload,
            "runId": run_id,
        })
        
        # Claim action BEFORE any mutation
        try:
            receipt, created = self._repo.claim_action(run_id, request_id, action_fingerprint)
        except IdempotencyConflictError:
            raise
        except Exception as exc:
            logger.exception("Failed to claim action %s for run %s", action_name, run_id)
            raise DeepResearchError("claim_action_failed", str(exc)) from exc
        
        # If existing completed receipt, return stored result (idempotent)
        if not created and receipt.get("status") == "completed":
            return receipt.get("result", {})
        if not created and receipt.get("status") == "failed":
            error = receipt.get("result", {}).get("error", {})
            raise DeepResearchError(error.get("code", "action_failed"), error.get("message", "操作未完成"))
        
        # If pending receipt exists, this is uncertain state - no automatic reissue
        if not created and receipt.get("status") == "pending":
            raise DeepResearchError(
                "unknown_action",
                f"Action {action_name} has pending receipt - requires manual resolution",
                {"requestId": request_id},
            )
        
        # Execute action with error handling
        try:
            if action_name == "pause":
                result = self._action_pause(run_id, expected_revision, payload)
            elif action_name == "cancel":
                result = self._action_cancel(run_id, expected_revision, payload)
            elif action_name == "resume":
                result = self._action_resume(run_id, expected_revision, payload)
            elif action_name == "clarify":
                result = self._action_clarify(run_id, expected_revision, payload)
            elif action_name == "plan":
                result = self._action_plan(run_id, expected_revision, payload)
            elif action_name == "continue":
                result = self._action_continue(run_id, expected_revision, payload)
            else:
                raise DeepResearchError("unknown_action", f"Unknown action: {action_name}")
            
            # Finish action with success
            self._repo.finish_action(run_id, request_id, result, status="completed")
            return result
            
        except DeepResearchError as exc:
            # Store safe error receipt - no blind retry
            error_result = {"error": exc.to_dict()}
            try:
                self._repo.finish_action(run_id, request_id, error_result, status="failed")
            except Exception:
                logger.exception("Failed to store error receipt for action %s", action_name)
            raise
        except Exception as exc:
            # Unexpected error - store safe receipt
            error_result = {"error": {"code": "unexpected_error", "message": str(exc)}}
            try:
                self._repo.finish_action(run_id, request_id, error_result, status="failed")
            except Exception:
                logger.exception("Failed to store error receipt for action %s", action_name)
            raise DeepResearchError("action_failed", str(exc)) from exc
    
    def get_sources(
        self,
        run_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Get sources for a run - pure GET, no external requests."""
        record = self._repo.require_run(run_id)
        state = record.get("state", {})
        evidence = state.get("evidence", [])
        sources = []
        candidates = state.get("sources", [])
        owners = {source.get("ownerMaterialId", source.get("workId")) for source in candidates}
        # The production validator checks the entire live snapshot. Repeating
        # that network call for every passage blocks status reads as sources
        # accumulate. Batch within this projection only, without permission
        # caching; simple injected validators retain their per-owner policy.
        batch_filter = getattr(type(self._scope_validator), 'filter_materials', None)
        allowed = (self._scope_validator.filter_materials(run_id, owners) if callable(batch_filter)
                   else {owner for owner in owners if not self._scope_validator
                         or self._scope_validator(run_id, owner)})
        for source in candidates:
            if source.get("ownerMaterialId", source.get("workId")) not in allowed:
                continue
            matched = [item for item in evidence if item.get("sourceWorkId") == source.get("workId")
                       and item.get("contentHash") == source.get("contentHash")
                       and (item.get("sourceId") == source.get("sourceId") if item.get("sourceId")
                            else item.get("location") == source.get("location"))]
            location = (matched[0].get("location") if matched else None) or source.get("location") or {}
            sources.append({**{key: value for key, value in source.items() if key != "text"},
                "pdfId": source.get("ownerMaterialId", source.get("workId")) if source.get("sourceKind") != "arxiv" else None,
                "title": source.get("title") or source.get("workId"),
                "quote": matched[0].get("quote", "") if matched else "",
                "page": location.get("page"), "location": location,
                "evidenceQuotes": {item['evidenceId']: {'quote': item.get('quote', ''),
                    'location': item.get('location') or {}} for item in matched},
                "evidenceIds": [item["evidenceId"] for item in matched]})
        return sources[max(0, offset):max(0, offset) + min(max(0, limit), 50)]
    
    def get_events(
        self,
        run_id: str,
        *,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get structured activity events - pure GET, no external requests."""
        activities = self._repo.require_run(run_id).get("state", {}).get("activities", [])
        return activities[-min(max(0, limit), 100):]
    
    # ── Private Action Implementations ─────────────────────────────────────────
    
    def _action_pause(
        self,
        run_id: str,
        expected_revision: int | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Pause at safe boundary - stop dispatching new steps."""
        
        def mutate(record: dict[str, Any]) -> dict[str, Any]:
            if record["status"] not in {STATUS_RUNNING, STATUS_WAITING_USER}:
                raise IllegalStatusTransitionError(record["status"], STATUS_PAUSED)
            
            # Capture current epoch for resume wrapper
            current_epoch = record.get("executionEpoch", 0)
            
            return {
                **record,
                "status": STATUS_PAUSED,
                "pause": {
                    "requested": True,
                    "node": record.get("stage", ""),
                    "reason": payload.get("reason", "user_requested"),
                    "requestedAt": utc_now_iso(),
                    "pausedAtEpoch": current_epoch,  # Epoch wrapper for resume
                },
            }
        
        updated = self._repo.update_run(run_id, mutate, expected_revision=expected_revision)
        return self.get(run_id)
    
    def _action_cancel(
        self,
        run_id: str,
        expected_revision: int | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Idempotent cancel - stop new work, preserve completed content."""
        
        def mutate(record: dict[str, Any]) -> dict[str, Any]:
            if record["status"] in TERMINAL_STATUSES:
                return record  # Already terminal, idempotent
            
            next_status = STATUS_STOPPING if record["status"] == STATUS_RUNNING else STATUS_CANCELLED
            
            return {
                **record,
                "status": next_status,
                "cancellation": {
                    "requested": True,
                    "requestedAt": utc_now_iso(),
                    "reason": payload.get("reason", "user_cancelled"),
                },
            }
        
        updated = self._repo.update_run(run_id, mutate, expected_revision=expected_revision)
        
        # If was stopping, transition to cancelled
        if updated["status"] == STATUS_STOPPING:
            try:
                self._repo.transition(run_id, STATUS_CANCELLED)
            except Exception:
                pass  # May have already transitioned
        
        return self.get(run_id)
    
    def _action_resume(
        self,
        run_id: str,
        expected_revision: int | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Resume only non-terminal runs from safe state.
        
        Accepts both QUEUED (deferred start) and PAUSED states.
        Validates expectedRunRevision before proceeding.
        Begin execution once and carry latest epoch into checkpoint state.
        """
        record = self._repo.require_run(run_id)
        
        if record["status"] in TERMINAL_STATUSES:
            raise TerminalGuardError(run_id, record["status"])
        
        # Accept QUEUED (deferred start) or PAUSED states
        if record["status"] not in (STATUS_QUEUED, STATUS_PAUSED, STATUS_WAITING_USER):
            raise IllegalStatusTransitionError(record["status"], STATUS_RUNNING)
        
        # Validate expected revision if provided
        if expected_revision is not None and record.get("runRevision", 0) != expected_revision:
            raise RevisionConflictError(run_id, expected_revision, record.get("runRevision", 0))
        
        # Check for unresolved unknown calls
        calls = self._repo.list_calls(run_id)
        unknown_calls = [c for c in calls if c.get("status") == "unknown"]
        if unknown_calls:
            from services.deep_research.contracts import UnresolvedUnknownError
            raise UnresolvedUnknownError(run_id, [c["callId"] for c in unknown_calls])
        
        # Capture pause epoch for wrapper validation
        pause_info = record.get("pause", {})
        paused_at_epoch = pause_info.get("pausedAtEpoch")
        
        # Begin new execution epoch ONCE - this transitions to RUNNING
        # Carry latest epoch into checkpoint state
        with self._lock:
            try:
                if run_id in self._active_futures and not self._active_futures[run_id].done():
                    raise DeepResearchError("execution_busy", "上一轮执行正在停止，请稍后继续")
                self._require_capacity()
            except DeepResearchError as exc:
                if exc.code not in {'execution_busy', 'execution_capacity'}:
                    raise
                # The human resume intent is accepted, but nothing is queued or
                # dispatched automatically. A new revision lets the next click
                # use a new action ID; replaying this action stays read-only.
                self._repo.update_run(run_id, lambda r: {**r, 'state': {**(r.get('state') or {}),
                    'resumeDeferred': {'reason': exc.code, 'requestedAt': utc_now_iso()}}},
                    expected_revision=expected_revision)
                return self.get(run_id)
            self._repo.begin_execution(run_id, expected_epoch=record.get("executionEpoch"),
                                       expected_revision=expected_revision)
            future = self._executor.submit(self._execute_graph, run_id)
            self._active_futures[run_id] = future
        
        return self.get(run_id)
    
    def _action_clarify(
        self,
        run_id: str,
        expected_revision: int | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Submit clarification - validate revision, never broaden materials."""
        if not isinstance(payload.get("answer"), str) or not payload["answer"].strip():
            raise DeepResearchError("invalid_clarification", "请填写需要补充的研究目标")
        
        def mutate(record: dict[str, Any]) -> dict[str, Any]:
            if record["status"] != STATUS_WAITING_USER:
                raise IllegalStatusTransitionError(record["status"], STATUS_RUNNING)
            
            # Update state with clarification
            state = dict(record.get("state") or {})
            state["waitingSince"] = state.get("waitingSince") or record.get("updatedAt")
            from services.deep_research.request_context import enabled, instruction_layers
            if enabled(record):
                # Validate the existing history before appending; never lose a
                # prior answer when another consequential ambiguity is asked.
                instruction_layers(record)
                history = list(state.get('clarificationHistory') or [])
                if not history and state.get('clarification'):
                    history = [{'question': '', 'answer': state['clarification']}]
                state['clarificationHistory'] = [*history, {'question': state.get('clarificationQuestion', ''),
                                                           'answer': payload['answer']}]
            state["clarification"] = payload['answer']
            state["clarifiedAt"] = utc_now_iso()
            state["clarificationNeeded"] = False
            
            return {
                **record,
                "state": state,
            }
        
        updated = self._repo.update_run(run_id, mutate, expected_revision=expected_revision)
        self._action_resume(run_id, updated["runRevision"], payload)
        
        return self.get(run_id)
    
    def _action_plan(
        self,
        run_id: str,
        expected_revision: int | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Update plan after safe pause - validate revision + DAG."""
        from services.deep_research.coverage import validate_plan
        
        new_plan = deepcopy(payload.get("plan", []))
        with self._lock:
            worker = self._active_futures.get(run_id)
            if worker is not None and not worker.done():
                raise DeepResearchError("execution_busy", "上一步仍在结束，请稍后再调整计划")
        if not isinstance(new_plan, list) or not new_plan:
            raise DeepResearchError("invalid_plan", "研究计划至少需要一个问题")
        if new_plan:
            try:
                validate_plan(new_plan)
            except ValueError as ve:
                raise DeepResearchError("invalid_plan", str(ve))
        
        def mutate(record: dict[str, Any]) -> dict[str, Any]:
            if record["status"] != STATUS_PAUSED:
                raise IllegalStatusTransitionError(record["status"], STATUS_PAUSED)

            from services.deep_research.plan_edit import require_plan_revision, source_allowed
            plan_revision = require_plan_revision(record, payload)

            from services.deep_research.completion_criteria import validate_completion_criteria
            try:
                validate_completion_criteria(new_plan, required=record.get('planCompletionContractVersion') == 1)
            except ValueError as exc:
                raise DeepResearchError('invalid_plan', '每个研究问题需保留1至4项有效的回答要点，请检查说明内容与方式。') from exc
            
            state = dict(record.get("state") or {})
            old_items = {item["itemId"]: item for item in state.get("plan", [])}
            for item in new_plan:
                old = old_items.get(item["itemId"], {})
                if item["question"] != old.get("question"):
                    item.pop("searchQuery", None)
                old_obligations = {value["obligationId"]: value for value in old.get("obligations", [])}
                for obligation in item["obligations"]:
                    if obligation["question"] != old_obligations.get(obligation["obligationId"], {}).get("question"):
                        obligation.pop("searchQuery", None)
                    if not all(source_allowed(record, identity) for identity in obligation.get("requiredSources", [])):
                        raise DeepResearchError("invalid_plan", "计划不能增加本轮材料范围")
            from services.deep_research.plan_resume import enabled, retire_outputs
            if enabled(record):
                state = retire_outputs(state, new_plan, plan_revision)
            state["plan"] = new_plan
            state["planRevision"] = plan_revision + 1
            from services.deep_research.dependencies import enabled as ordered_plan, initialize
            if ordered_plan(record):
                state['dependencyExecution'] = initialize(new_plan, state['planRevision'])
                state['plan'] = [{**item, 'status': 'pending'} for item in new_plan]
            
            return {
                **record,
                "state": state,
            }
        
        self._repo.update_run(run_id, mutate, expected_revision=expected_revision)
        return self.get(run_id)
    
    def _action_continue(
        self,
        run_id: str,
        expected_revision: int | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Create child run with explicit budget, retain prior evidence.
        
        Adapts workspaceTaskId and operationKey from parent if not provided.
        """
        parent = self._repo.require_run(run_id)
        if parent.get("runRevision", 0) != expected_revision:
            raise RevisionConflictError(run_id, expected_revision, parent.get("runRevision", 0))
        
        if parent["status"] not in TERMINAL_STATUSES:
            raise DeepResearchError(
                "continue_requires_terminal",
                "Can only continue from terminal runs",
            )
        if payload.get("sourcePolicy", parent.get("sourcePolicy")) != parent.get("sourcePolicy"):
            raise DeepResearchError("scope_change_requires_new_run", "扩大资料范围时请从输入区选择范围并发起新的研究")
        
        # Adapt mandatory fields from parent
        workspace_task_id = payload.get("workspaceTaskId") or parent.get("taskId", "")
        operation_key = payload.get("operationKey") or payload.get("requestId", "")
        
        # If no operation_key provided, generate one based on parent
        if not operation_key:
            parent_op_key = parent.get("idempotencyKey", "")
            operation_key = f"{parent_op_key}_child_{int(time.time())}"
        
        # Check for deferStart in payload - child should respect deferred start
        defer_start = payload.get("deferStart", False)
        
        # Create child run with mandatory product fields
        child_request = {
            "workspaceTaskId": workspace_task_id,  # Mandatory - adapt from parent
            "operationKey": operation_key,          # Mandatory - adapt or generate
            "question": payload.get("question", parent.get("question", "")),
            "materials": parent.get("materials", []),
            "materialSnapshot": parent.get("materialSnapshot"),
            "focusPaperIds": parent.get("focusPaperIds", []),
            "sourcePolicy": parent.get("sourcePolicy", {"mode": "task_only"}),
            "parentRunId": run_id,
            "budgetProfile": payload.get("budgetProfile", "standard"),
            "outputKind": parent.get("outputKind", "general"),
        }
        
        # create() filters inherited sources against the frozen scope and freshness.
        # Do not restore the unfiltered parent state after that validation.
        child_record, _ = self.create(child_request, start_async=False)
        
        if not defer_start:
            self._start_execution(child_record["runId"])
        return self.get(child_record["runId"])
    
    # ── Execution Management ───────────────────────────────────────────────────

    def _require_capacity(self) -> None:
        """Called under _lock, before beginning the budget clock or submitting."""
        self._active_futures = {rid: future for rid, future in self._active_futures.items()
                                if not future.done()}
        if len(self._active_futures) >= self._max_concurrent:
            raise DeepResearchError("execution_capacity", "当前研究任务较多，已保存请求，请稍后点击继续",
                                    {"status_code": 503})
    
    def _start_execution(self, run_id: str) -> None:
        """Start async graph execution with restart recovery."""
        with self._lock:
            if run_id in self._active_futures:
                future = self._active_futures[run_id]
                if not future.done():
                    return  # Already running
            
            # Mark as running first
            try:
                self._require_capacity()
                self._repo.begin_execution(run_id)
            except Exception as exc:
                logger.warning("Could not begin execution for %s: %s", run_id, exc)
                return
            
            # Submit to executor
            future = self._executor.submit(self._execute_graph, run_id)
            self._active_futures[run_id] = future
    
    def _execute_graph(self, run_id: str) -> None:
        """Execute the LangGraph flow with checkpoint persistence."""
        import sqlite3
        
        checkpoint_conn = None
        epoch = -1
        try:
            record = self._repo.require_run(run_id)
            epoch = record["executionEpoch"]

            def guarded_update(rid, mutate, *, expected_revision=None):
                def guarded(current):
                    if current["executionEpoch"] != epoch:
                        raise EpochConflictError(rid, epoch, current["executionEpoch"])
                    if current["status"] not in {STATUS_RUNNING, STATUS_COMPLETED}:
                        raise LateCompletionError(rid, current["status"])
                    previous_stage = current.get("stage")
                    updated = mutate(current)
                    if updated.get("stage") and updated.get("stage") != previous_stage:
                        history = list(updated.get("state", {}).get("activities", []))
                        activity = _build_activity_summary(updated)
                        if activity:
                            history.append({**activity, "eventId": f"{rid}:{updated['runRevision']}:{updated['stage']}",
                                            "at": utc_now_iso()})
                            updated["state"] = {**updated.get("state", {}), "activities": history[-100:]}
                    return updated
                return self._repo.update_run(rid, guarded, expected_revision=expected_revision)
            
            # Open long-lived checkpoint connection (NOT context manager)
            # MUST use check_same_thread=False for LangGraph background thread checkpoints
            checkpoint_path = f"{self._repo.db_path}.checkpoints"
            checkpoint_conn = sqlite3.connect(checkpoint_path, timeout=30, check_same_thread=False)
            
            # Build graph with injected dependencies
            graph = self._graph_factory(
                llm_invoke=self._make_llm_invoker(run_id),
                retrieve_fn=self._make_retriever(run_id),
                read_fn=self._make_reader(run_id),
                scope_validator=self._scope_validator or self._default_scope_validator(),
                make_evidence_fn=self._get_make_evidence(run_id),
                coverage_gaps_fn=self._get_coverage_gaps(),
                verify_claims_fn=self._get_verify_claims(run_id),
                semantic_check_fn=self._make_semantic_checker(run_id),
                external_acquire=self._external_acquire,
                repo_update=guarded_update,
                repo_publish=self._repo.publish_report,
                validate_plan_fn=self._get_validate_plan(),
                checkpoint_conn=checkpoint_conn,  # Long-lived connection, not path
            )
            
            # Initial state with mandatory product fields
            initial_state = {
                "run_id": run_id,
                "workspace_task_id": record.get("taskId", ""),
                "operation_key": record.get("idempotencyKey", ""),
                "execution_epoch": record.get("executionEpoch", 0),
                "plan_revision": (record.get('state') or {}).get('planRevision', 0),
                "brief_id": "",
                "plan_ids": [],
                "source_ids": [],
                "evidence_ids": [],
                "claim_ids": [],
                "coverage_state": {},
                "gaps": [],
                "report_version_id": "",
                "publication_id": "",
                "outcome": OUTCOME_NONE,
                "error_code": "",
                "stop_reason": "",
                "clarification_needed": False,
                "clarification_question": "",
                "requery_count": 0,
                "max_requery_rounds": 4 if record.get("budget", {}).get("profile") == "extended" else 2,
                "budget_exhausted": False,
                "source_policy_mode": record.get("sourcePolicy", {}).get("mode", "task_only"),
                "started_at": __import__("time").monotonic(),
                "deadline_seconds": float(record.get("budget", {}).get("maxWallClockSeconds", 360)),
            }
            
            # Execute with thread_id for checkpoint isolation
            config = {"configurable": {"thread_id": run_id}}
            if type(record.get('adaptiveExtractionContractVersion')) is int and record['adaptiveExtractionContractVersion'] in (1,2,3):
                # Frontier/batch routing adds graph steps, not model allowance.
                # Every dispatched call still obeys the original run budget.
                config['recursion_limit'] = 128
            
            # Check if checkpoint exists - resume if so, otherwise start fresh
            # LangGraph's invoke will automatically resume from checkpoint if one exists
            # We pass None as input to signal resume mode when checkpoint exists
            try:
                checkpointer = graph.checkpointer
                existing_checkpoint = checkpointer.get(config) if checkpointer else None
            except Exception:
                existing_checkpoint = None
            
            from services.deep_research.plan_resume import checkpoint_patch
            edited = checkpoint_patch(record, existing_checkpoint)
            if edited is not None:
                # Rebase at the plan boundary, preserving budget and call ledger.
                # This is a durable checkpoint update, so a later restart resumes
                # the edited route rather than regenerating a model-written plan.
                patch = {**(initial_state if existing_checkpoint is None else {}), **edited,
                         'execution_epoch': epoch}
                graph.update_state(config, patch, as_node='plan')
                final_state = graph.invoke(None, config=config)
            elif existing_checkpoint is not None:
                # Resume from checkpoint using Command for interrupt handling
                logger.info("Resuming run %s from checkpoint", run_id)
                try:
                    from langgraph.types import Command
                    # Use Command to properly handle interrupt resume
                    graph.update_state(config, {"execution_epoch": epoch})
                    answer = record.get("state", {}).get("clarification")
                    final_state = graph.invoke(Command(resume=answer), config=config) if answer else graph.invoke(None, config=config)
                except ImportError:
                    # Fallback for older langgraph versions
                    final_state = graph.invoke(None, config=config)
            else:
                # Fresh start
                final_state = graph.invoke(initial_state, config=config)
            
            # Update final outcome
            outcome = final_state.get("outcome", OUTCOME_NONE)
            error_code = final_state.get("error_code", "")
            
            # Do NOT finalize if interrupted (waiting for clarification)
            # Interrupted state has __interrupt__ in checkpoint metadata or GraphInterrupt exception
            is_interrupted = (
                hasattr(final_state, "__interrupt__") or 
                (isinstance(final_state, dict) and final_state.get("__interrupt__")) or
                (isinstance(final_state, dict) and "__interrupt__" in str(final_state))
            )
            if is_interrupted:
                logger.info("Run %s interrupted, not finalizing", run_id)
                return
            
            def finalize(record: dict[str, Any]) -> dict[str, Any]:
                final_status = STATUS_COMPLETED if not error_code else STATUS_FAILED
                return {
                    **record,
                    "status": final_status,
                    "outcome": outcome,
                    "errorCode": error_code,
                    "finishedAt": utc_now_iso(),
                }
            
            if self._repo.require_run(run_id)["status"] == STATUS_RUNNING:
                guarded_update(run_id, finalize)
            
        except Exception as exc:
            # Check if this is an interrupt exception - don't mark as failed
            exc_type_name = type(exc).__name__
            if "GraphInterrupt" in exc_type_name or "interrupt" in str(exc).lower():
                logger.info("Run %s interrupted via exception, not marking failed", run_id)
                return
            
            logger.exception("Graph execution failed for run %s", run_id)
            calls = self._repo.list_calls(run_id)
            unknown = any(call.get("status") == "unknown" for call in calls)
            
            def mark_failed(record: dict[str, Any]) -> dict[str, Any]:
                if record["status"] != STATUS_RUNNING or record["executionEpoch"] != epoch:
                    return record
                return {
                    **record,
                    "status": STATUS_PAUSED if unknown else STATUS_FAILED,
                    "errorCode": "unresolved_unknown" if unknown else getattr(exc, "code", "execution_failed"),
                    "error": {"message": _execution_failure_message(calls, unknown)},
                    "finishedAt": utc_now_iso(),
                }
            
            try:
                self._repo.update_run(run_id, mark_failed)
            except Exception:
                logger.exception("Failed to mark run %s as failed", run_id)
        
        finally:
            # Close checkpoint connection
            if checkpoint_conn is not None:
                try:
                    checkpoint_conn.close()
                except Exception:
                    pass
            
            with self._lock:
                self._active_futures.pop(run_id, None)
    
    # ── Dependency Factories ───────────────────────────────────────────────────
    
    def _make_llm_invoker(self, run_id: str) -> Callable[..., dict]:
        """Create LLM invoker bound to this run. Each node passes its own label."""
        from services.deep_research.tools import TrackedLLMInvoker
        
        if not self._llm_client:
            # Should not reach here - create() validates llm_client
            raise DeepResearchError("llm_not_configured", "LLM client not configured")
        
        invoker = TrackedLLMInvoker(
            llm_client=self._llm_client,
            reserve_call_fn=lambda **kw: self._repo.reserve_call(**kw),
            complete_call_fn=self._complete_tracked_call,
            run_record_fn=self._repo.require_run,
            call_history_fn=self._repo.list_calls,
            verification_max_input_bytes=32000,
            experiment_max_input_bytes=32000,
        )
        
        # Return invoker directly - nodes call with (run_id, node_name, prompt, extra_body, use_reserve)
        return invoker
    
    def _make_retriever(self, run_id: str) -> Callable[[str, str, int], list]:
        """Create tracked retriever bound to this run with scope validation."""
        from services.deep_research.tools import TrackedRetriever
        
        base = self._retriever or self._default_retriever()
        validator = self._scope_validator or self._default_scope_validator()
        
        tracked = TrackedRetriever(
            base_retriever=base,
            scope_validator=validator,
            reserve_call_fn=lambda **kw: self._repo.reserve_call(**kw),
            complete_call_fn=self._complete_tracked_call,
        )
        
        def retrieve(query: str, pdf_id: str, *, limit: int = 5) -> list:
            return tracked(run_id, query, pdf_id, limit=limit)
        
        return retrieve
    
    def _make_reader(self, run_id: str) -> Callable[[str, str], dict]:
        """Create tracked source reader bound to this run with scope validation."""
        from services.deep_research.tools import TrackedSourceReader
        
        base = self._source_reader or self._default_reader()
        validate_material = self._scope_validator or self._default_scope_validator()
        def validator(rid, sid):
            source = next((s for s in self._repo.require_run(rid).get("state", {}).get("sources", []) if s.get("sourceId") == sid), {})
            return bool(source) and validate_material(rid, source.get("workId"))
        
        tracked = TrackedSourceReader(
            base_reader=base,
            scope_validator=validator,
            reserve_call_fn=lambda **kw: self._repo.reserve_call(**kw),
            complete_call_fn=self._complete_tracked_call,
        )
        
        def read(source_run_id: str, source_id: str) -> dict:
            return tracked(source_run_id, source_id)
        
        return read
    
    def _make_semantic_checker(self, run_id: str) -> Callable[[list, list], list]:
        """Create budgeted semantic checker."""
        from services.deep_research.tools import TrackedLLMInvoker
        
        if not self._llm_client:
            return lambda claims, evidence: []
        
        invoker = TrackedLLMInvoker(
            llm_client=self._llm_client,
            reserve_call_fn=lambda **kw: self._repo.reserve_call(**kw),
            complete_call_fn=self._complete_tracked_call,
            run_record_fn=self._repo.require_run,
            call_history_fn=self._repo.list_calls,
            verification_max_input_bytes=32000,
        )
        
        return self._build_semantic_checker(run_id, invoker)

    def _build_semantic_checker(self, run_id, invoker, *, isolation=None):
        """Share policy wiring with the live-scope production subclass."""
        from services.deep_research.tools import BudgetedSemanticChecker
        from services.deep_research.comparison_reasoning import enabled as comparison_enabled
        from services.deep_research.audit_source_fields import enabled as audit_fields_enabled
        from services.deep_research.factual_scope import enabled as scope_enabled
        from services.deep_research.factual_review import enabled as bounded_review_enabled
        checker = BudgetedSemanticChecker(invoker, run_id,
            metric_domains=lambda: self._repo.require_run(run_id).get('state', {}).get('metricDomains'),
            research_question=lambda: effective_question(self._repo.require_run(run_id)),
            isolate_factual_claims=(lambda: self._repo.require_run(run_id).get('claimIsolationContractVersion') == 1)
                if isolation is None else isolation,
            comparison_reasoning=lambda: comparison_enabled(self._repo.require_run(run_id)),
            comparison_audit_version=lambda: self._repo.require_run(run_id).get('comparisonReasoningContractVersion', 0),
            audit_source_fields=lambda: audit_fields_enabled(self._repo.require_run(run_id)),
            audit_target_fields=lambda: type(self._repo.require_run(run_id).get('auditSourceFieldsContractVersion')) is int
                and self._repo.require_run(run_id)['auditSourceFieldsContractVersion']==2,
            factual_scope=lambda: scope_enabled(self._repo.require_run(run_id)),
            complete_factual_scope=lambda: type(self._repo.require_run(run_id).get('factualScopeContractVersion')) is int
                and self._repo.require_run(run_id)['factualScopeContractVersion'] in (3,4),
            result_attribution=lambda: type(self._repo.require_run(run_id).get('factualScopeContractVersion')) is int
                and self._repo.require_run(run_id)['factualScopeContractVersion']==4,
            bounded_factual_review=lambda: bounded_review_enabled(self._repo.require_run(run_id)),
            qualitative_inference=lambda: type(self._repo.require_run(run_id).get('audienceRewriteContractVersion')) is int
                and self._repo.require_run(run_id)['audienceRewriteContractVersion'] in (4,5,6,7,8),
            experiment_intent_review=lambda: self._repo.require_run(run_id).get('experimentIntentContractVersion',0),
            prospective_review=lambda: self._repo.require_run(run_id).get('experimentReviewContractVersion',0),
            configuration_consistency=lambda: self._repo.require_run(run_id).get('configurationConsistencyContractVersion',0),
            prospective_envelope=lambda: self._repo.require_run(run_id).get('experimentReviewEnvelopeContractVersion',0),
            review_batch_planning=lambda: self._repo.require_run(run_id).get('reviewBatchPlanningContractVersion',0))
        return checker
    
    def _default_scope_validator(self) -> Callable[[str, str], bool]:
        """Default fail-closed validator.
        
        Checks material against snapshot. In production, MUST be replaced with
        authoritative Java callback or validated scope revision endpoint.
        """
        from services.deep_research.tools import DefaultScopeValidator
        return DefaultScopeValidator(self._repo.get_run)
    
    def _default_retriever(self) -> Callable[[str, str, int], list]:
        """Default retriever using research_executor.
        
        Returns empty results with keyword limit parameter if research_executor unavailable.
        """
        try:
            from services.research_executor import retrieve_current_paper_evidence
            return retrieve_current_paper_evidence
        except ImportError:
            # Return empty results with keyword limit parameter
            def empty_retriever(query: str, pdf_id: str, limit: int = 5) -> list:
                return []
            return empty_retriever
    
    def _default_reader(self) -> Callable[[str, str], dict]:
        """Default source reader - returns empty content (fail closed).
        
        In production, MUST be replaced with actual source reader that reads
        from trusted snapshot. Empty fallback ensures graph doesn't proceed
        with missing content.
        """
        from services.deep_research.runtime import read_acquired_source
        return lambda run_id, source_id: read_acquired_source(self._repo, run_id, source_id)

    def _complete_tracked_call(self, *args, **kwargs):
        try:
            return self._repo.complete_call(*args, **kwargs)
        except (LateCompletionError, EpochConflictError):
            self._repo.complete_call(*args, **kwargs, allow_late=True)
            raise
    
    def _get_make_evidence(self, run_id=None) -> Callable[..., dict]:
        from services.deep_research.verification import make_evidence
        return make_evidence
    
    def _get_coverage_gaps(self) -> Callable[[list, list, list], list]:
        from services.deep_research.coverage import coverage_gaps
        return coverage_gaps
    
    def _get_verify_claims(self, run_id=None) -> Callable[[list, list, Callable | None], dict]:
        from services.deep_research.verification import verify_claims
        if run_id is None:
            return verify_claims
        record = self._repo.require_run(run_id)
        version = record.get('absenceScopeContractVersion', 0)
        spelling = record.get('quantitySpellingContractVersion', 0)
        feedback = record.get('verificationFeedbackContractVersion', 0)
        table_references = record.get('tableReferencesContractVersion',0)
        context_version=record.get('experimentReviewEnvelopeContractVersion',0)
        return lambda claims, evidence, semantic=None: verify_claims(
            claims, evidence, semantic, absence_scope_version=version, quantity_spelling_version=spelling,
            feedback_version=feedback,table_references_version=table_references,
            review_context_version=context_version)
    
    def _get_validate_plan(self) -> Callable[[list], list]:
        from services.deep_research.coverage import validate_plan
        return validate_plan
    
    # ── Lifecycle ──────────────────────────────────────────────────────────────
    


# ── Helpers ────────────────────────────────────────────────────────────────────

def _build_activity_summary(record: dict[str, Any]) -> dict[str, Any] | None:
    """Build compact activity summary for GET response."""
    status = record.get("status", "")
    stage = record.get("stage", "")
    
    if status not in (STATUS_QUEUED, STATUS_RUNNING, STATUS_STOPPING):
        return None
    
    if not stage:
        return None
    
    stage_labels = {
        "resolve_brief": "理解问题",
        "plan": "制定计划",
        "acquire": "获取资料",
        "read": "阅读论文",
        "extract": "提取证据",
        "assess": "评估覆盖",
        "synthesize": "综合结论",
        "verify": "验证声明",
        "publish": "发布报告",
    }
    
    return {
        "stage": stage,
        "label": stage_labels.get(stage, stage),
    }


def _unconfirmed_call_ids(repository, run_id):
    return repository.unconfirmed_call_ids(run_id)


def _compute_allowed_actions(record: dict[str, Any], *, unconfirmed=False) -> list[str]:
    """Compute allowed actions based on current state."""
    status = record.get("status", "")
    outcome = record.get("outcome", OUTCOME_NONE)
    if unconfirmed or record.get('errorCode') == 'unresolved_unknown':
        if status == STATUS_COMPLETED:
            return ['open_report', 'view_sources']
        return [] if status in TERMINAL_STATUSES else ['cancel']
    
    actions = []
    
    if status == STATUS_QUEUED:
        actions.extend(["resume", "cancel"])
    elif status == STATUS_RUNNING:
        actions.extend(["pause", "cancel"])
    elif status == STATUS_WAITING_USER:
        state = record.get('state') or {}
        answered = (state.get('clarificationNeeded') is False
                    and isinstance(state.get('clarification'), str) and state['clarification'].strip())
        actions.extend(["resume", "cancel"] if answered else ["clarify", "cancel"])
    elif status == STATUS_PAUSED:
        actions.extend(["resume", "cancel", "plan"])
    elif status == STATUS_COMPLETED:
        # A complete report can still be the parent of a NEW explicit question.
        # This projection never regenerates the parent or issues a model call.
        actions.extend(["open_report", "view_sources", "continue"])
    elif status == STATUS_CANCELLED:
        if outcome != OUTCOME_NONE:
            actions.append("view_partial")
        actions.append("continue")
    elif status == STATUS_FAILED:
        actions.append("view_error")
        actions.append("continue")
    
    return actions
