"""Durable LangGraph flow for Deep Research v2.

Nodes: resolve_brief, plan, acquire, read, extract, assess, synthesize, verify, publish.
Uses SqliteSaver with long-lived connection for persistent checkpoints.
Graph state contains only compact IDs; large evidence/domain content lives in repository.
"""
from __future__ import annotations

import json
import hashlib
import logging
import re
import sqlite3
import time
from copy import deepcopy
from typing import Any, Callable, TypedDict

from services.deep_research.request_context import effective_question, separate_clarification

try:
    from langgraph.graph import StateGraph, END
    from langgraph.checkpoint.sqlite import SqliteSaver
except ImportError:  # pragma: no cover - offline tests may not have langgraph installed
    StateGraph = None  # type: ignore
    END = None  # type: ignore
    SqliteSaver = None  # type: ignore

from services.deep_research.contracts import (
    ENGINE_VERSION,
    OUTCOME_COMPLETE,
    OUTCOME_INCONCLUSIVE,
    OUTCOME_NONE,
    OUTCOME_PARTIAL,
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PAUSED,
    STATUS_RUNNING,
    STATUS_WAITING_USER,
    TERMINAL_STATUSES,
    digest,
    utc_now_iso,
)

logger = logging.getLogger(__name__)


# ── Graph State ────────────────────────────────────────────────────────────────

class GraphState(TypedDict, total=False):
    """Compact graph state - only IDs and control flags.
    
    Large content (evidence, claims, report body) is stored in the repository
    and referenced by ID to keep checkpoint size bounded.
    """
    run_id: str
    workspace_task_id: str  # Product task ID (mandatory)
    operation_key: str      # Idempotency key for receipt recovery
    execution_epoch: int
    brief_id: str
    plan_ids: list[str]
    plan_revision: int
    source_ids: list[str]
    evidence_ids: list[str]
    claim_ids: list[str]
    coverage_state: dict[str, Any]
    gaps: list[dict[str, Any]]
    report_version_id: str
    publication_id: str
    outcome: str
    error_code: str
    stop_reason: str
    clarification_needed: bool
    clarification_question: str
    refresh_brief: bool
    requery_count: int
    max_requery_rounds: int
    requery_queries: list[dict[str, Any]]
    budget_exhausted: bool
    started_at: float  # Monotonic timestamp for deadline calculation
    deadline_seconds: float  # Max wall clock seconds
    source_policy_mode: str  # task_only, academic_external, external_only
    previous_evidence_hashes: list[str]  # For incremental child dedup
    inherited_source_ids: list[str]  # Inherited from parent run
    inherited_evidence_ids: list[str]  # Inherited from parent run
    assess_inherited: bool  # Check reused evidence before issuing new retrieval
    prev_source_count: int  # Track no-new-evidence stopping
    prev_assessment_evidence_digest: str
    assess_after_extraction_stop: bool
    extraction_pending: bool
    dependency_transition: str
    dependency_wave: int


# ── Node Functions ─────────────────────────────────────────────────────────────

def make_wait_for_clarification_node(repo_update=None) -> Callable[[GraphState], dict]:
    """Wait for user clarification using LangGraph interrupt mechanism.
    
    Interrupt pauses execution until resume with clarification answer.
    """
    try:
        from langgraph.types import interrupt
    except ImportError:
        # Fallback for older langgraph versions
        def interrupt(value: Any) -> Any:
            raise RuntimeError("LangGraph interrupt not available")
    
    def node(state: GraphState) -> dict:
        question = state.get("clarification_question", "Please clarify your question.")
        
        # Interrupt pauses the graph here until resumed
        answer = interrupt({
            "type": "clarification_needed",
            "question": question,
            "run_id": state.get("run_id", ""),
        })

        refresh = False
        if repo_update is not None:
            from services.deep_research.request_context import enabled
            record = repo_update(state['run_id'], lambda r: r, expected_revision=None)
            refresh = enabled(record)
        
        # When resumed, answer contains the clarification
        return {
            "clarification_needed": False,
            "clarification_question": "",
            "refresh_brief": refresh,
        }
    
    return node


def make_resolve_brief_node(
    llm_invoke: Callable[..., dict],
    repo_update: Callable[[str, Callable, dict | None], dict],
) -> Callable[[GraphState], dict]:
    """Resolve user question into structured brief with outputKind."""
    
    def node(state: GraphState) -> dict:
        run_id = state.get("run_id", "")
        if not run_id:
            return {"error_code": "missing_run_id", "outcome": OUTCOME_NONE}
        
        record = repo_update(run_id, lambda r: {**r, "stage": "resolve_brief"}, expected_revision=None)
        question = effective_question(record)
        materials = record.get("materials", [])
        
        prompt = f"""Analyze this research question and determine the output kind.
Question: {question}
Materials count: {len(materials)}
Selected materials: {json.dumps([{'id': m.get('materialId'), 'title': m.get('title', '')} for m in materials], ensure_ascii=False)}
Primary papers: {json.dumps(record.get('focusPaperIds', []))}
Source policy: {json.dumps(record.get('sourcePolicy', {'mode': 'task_only'}))}

Return JSON with:
- outputKind: one of direction_survey, paper_comparison, claim_verification, experiment_design, research_entry
- title: a short Chinese report title (12-24 characters); do not repeat the full request or its instructions
- assumptions: list of inferred conditions
- clarification: string if ambiguous, empty if clear
- constraints: any explicit limitations
- measurementScope: for experiment_design, list of {{domain: quality|speed|storage, requestExcerpt: exact words from Question}}
  for EVERY measurement domain explicitly requested. Never infer these from paper titles.
  Use [] when the measurement target is unspecified. Quality-only experiments do not
  require speed or storage protocols; include those domains when the user asks for them.

Clarify only consequential ambiguity about the research target or permitted materials.
An experiment-design request is a proposed, unexecuted plan: unknown numeric settings can be
explicitly proposed and fixed across controls. Do not pause merely to ask for optional implementation
preferences or for facts that can be read from the selected papers. Never widen material permissions."""
        
        result = llm_invoke(run_id, "resolve_brief", prompt, {"max_tokens": 1500, "temperature": 0.1})
        
        # Handle LLMResult dataclass - extract content attribute
        if hasattr(result, "content"):
            content = result.content
        elif isinstance(result, dict):
            content = result.get("content", "{}")
        else:
            content = str(result)
        
        parsed = _safe_parse_json(content)
        
        # Validate parsed is a dict before accessing fields
        if not isinstance(parsed, dict):
            logger.warning("resolve_brief response not a dict: %s", type(parsed))
            return {"error_code": "invalid_brief_response", "outcome": OUTCOME_NONE}
        
        output_kind = parsed.get("outputKind", "direction_survey")
        from services.deep_research.synthesis import resolve_output_kind, OUTPUT_KIND_SECTIONS
        output_kind = resolve_output_kind(record.get("outputKind") if record.get("outputKind") not in {None, "general"} else output_kind)
        if output_kind not in OUTPUT_KIND_SECTIONS:
            return {"error_code": "invalid_brief_response", "outcome": OUTCOME_NONE}
        clarification = parsed.get("clarification", "")
        
        brief_id = f"brief_{run_id}"
        from services.deep_research.metric_scope import grounded_metric_domains
        update_payload = {
            "briefId": brief_id,
            "outputKind": output_kind,
            "metricDomains": grounded_metric_domains(parsed.get('measurementScope'), question),
            "assumptions": parsed.get("assumptions", []),
            "constraints": parsed.get("constraints", ""),
            "title": parsed.get("title", "")[:40] if isinstance(parsed.get("title"), str) else "",
        }
        
        repo_update(run_id, lambda r: {**r,
            "status": STATUS_WAITING_USER if clarification else r["status"],
            "state": {**(r.get("state") or {}), **update_payload,
                      **({"waitingSince": utc_now_iso()} if clarification else {}),
                      "clarificationNeeded": bool(clarification), "clarificationQuestion": clarification}}, expected_revision=None)
        
        if clarification:
            return {
                "brief_id": brief_id,
                "clarification_needed": True,
                "clarification_question": clarification,
                "refresh_brief": False,
            }
        
        return {"brief_id": brief_id, "clarification_needed": False, "refresh_brief": False}
    
    return node


def make_plan_node(
    llm_invoke: Callable[..., dict],
    repo_update: Callable[[str, Callable, dict | None], dict],
    validate_plan: Callable[[list], list],
) -> Callable[[GraphState], dict]:
    """Generate research plan with obligations and dependencies."""
    
    def node(state: GraphState) -> dict:
        run_id = state.get("run_id", "")
        
        record = repo_update(run_id, lambda r: {**r, "stage": "plan"}, expected_revision=None)
        question = effective_question(record)
        brief_state = record.get("state", {})
        output_kind = brief_state.get("outputKind", "direction_survey")
        materials = record.get("materials", [])
        criteria_required = record.get('planCompletionContractVersion') == 1
        obligation_fields = 'obligationId, question, requiredSources, searchQuery, purpose, requestExcerpt'
        if criteria_required:
            obligation_fields += ', completionCriteria'
        from services.deep_research.data_prerequisite import PROPOSED_PLANNING_GUIDANCE
        proposed_protocol = output_kind == 'experiment_design' and record.get('experimentPlanContractVersion') == 1
        data_guidance = PROPOSED_PLANNING_GUIDANCE if proposed_protocol else '''For experiment designs, include dataset/subset availability in the evaluation-conditions investigation:
retrieve the original evaluation's actual unit count or named units, particularly
when a paper inherits a subset from another available paper. Existing data availability
is a necessary factual prerequisite, not an optional historical benchmark retelling.'''

        prompt = f"""Create a research plan for this question.
Question: {question}
Output kind: {output_kind}
User clarification: {separate_clarification(record)}
Materials: {json.dumps([{'id': m.get('materialId'), 'title': m.get('title', '')} for m in materials[:10]], ensure_ascii=False)}
Primary papers: {json.dumps(record.get('focusPaperIds', []))}
Previously acquired source identities (reuse an exact relevant arXiv identifier for lookup):
{json.dumps(list({s.get('workId'): {'workId': s.get('workId'), 'versionId': s.get('versionId'), 'title': s.get('title')} for s in brief_state.get('sources', [])}.values())[:12], ensure_ascii=False)}
User context (notes/old reports, UNVERIFIED; use only for goals and queries, never as paper facts):
{json.dumps(record.get('contextMaterials', []), ensure_ascii=False)}

Return a compact JSON array of 1-4 plan items (prefer 1-2 for a short answer), each with:
- itemId: unique identifier
- question: sub-question to answer
- obligations: array of {{{obligation_fields}}}
- searchQuery: concise English academic search terms, preserving names and identifiers
- dependencies: array of itemIds this depends on
- priority: 1-3 (1=highest)

Ensure DAG structure (no cycles). Each obligation must specify which sources to check.
obligationId must be unique across the ENTIRE array, not just within an item.
Preserve the user's exact limits. If only one sub-question is requested, create exactly one item.
Use short questions and at most two obligations per item. Do not repeat the same obligation.
purpose is answer_requirement for anything the user asks to receive, or supporting_research
for an auxiliary investigation used to inform that deliverable. For supporting_research,
copy requestExcerpt (at least 8 characters) literally from the original question to
identify the deliverable it serves. This label is only a hint: the final audit must
independently judge whether any unanswered support question still matters. Do not mark
requested facts, necessary experimental assumptions or requested comparisons optional.
For experiment proposals, distinguish learning how the original method works from
requiring a retelling of every original benchmark in the proposed experiment.
{data_guidance}
Each obligation should ask for ONE dimension that a short passage can support (e.g. storage,
speed, quality or evaluation conditions), not a compound demand for every result at once.
Completion criteria must be the MINIMUM needed to answer the user's deliverable.
Do not add a requirement to enumerate all scene counts, all metrics or all settings
when a bounded example and essential conditions suffice for the requested short answer.
For mechanism questions, explicitly include the requested entities' relationship,
conditioning inputs and activation/applicability rules in the obligation question.
Do not substitute a generic overview for the user's requested mechanism or conditions.
For evidence limits, ask what the obtained evaluation actually supports and what
cannot be inferred beyond its conditions. Do not require an explicit author admission
of every limitation, or demand a paper-wide absence claim from missing passages.

Return a JSON ARRAY of plan items, NOT an object with items field."""
        
        if criteria_required:
            from services.deep_research.completion_criteria import CRITERIA_GUIDANCE
            # D1-v8 matched the shorter schema and omitted the criteria requested
            # in later prose. Give one complete shape. Its requirements describe
            # deliverables, never guessed paper facts.
            shape = [{'itemId': 'item_1', 'question': '<one requested sub-question>',
                      'obligations': [{'obligationId': 'ob_1', 'question': '<one requested dimension>',
                                       'requiredSources': ['<permitted material id>'],
                                       'searchQuery': '<concise query>', 'purpose': 'answer_requirement',
                                       'requestExcerpt': '<literal excerpt from Question>',
                                       'completionCriteria': [{'criterionId': 'requirement_1',
                                           'requirement': '<neutral description of what the answer must explain>',
                                           'responseType': 'explanation'}]}],
                      'searchQuery': '<concise query>', 'dependencies': [], 'priority': 1}]
            prompt += '\n' + CRITERIA_GUIDANCE + '\n\nRequired output shape (replace every placeholder; '
            prompt += 'choose the appropriate responseType; include completionCriteria on EVERY obligation):\n'
            prompt += json.dumps(shape, ensure_ascii=False, separators=(',', ':'))
            prompt += '\nReturn only the complete JSON array, with no Markdown fences or extra commentary.'
        result = llm_invoke(run_id, "plan", prompt, {"max_tokens": 5000, "temperature": 0.1})
        
        # Handle LLMResult dataclass - extract content attribute
        if hasattr(result, "content"):
            content = result.content
        elif isinstance(result, dict):
            content = result.get("content", "[]")
        else:
            content = str(result)
        
        parsed = _safe_parse_json(content)

        def invalid_plan(reason):
            # Keep the rejected response in the existing settled call ledger;
            # persist a compact diagnostic without another generation or repair.
            repo_update(run_id, lambda r: {**r, 'state': {**(r.get('state') or {}),
                'planFormatValidation': {'status': 'rejected', 'reason': str(reason)[:500]}}},
                expected_revision=None)
            return {"error_code": "invalid_plan_response", "outcome": OUTCOME_NONE, "plan_ids": []}

        finish_reason = getattr(result, 'finish_reason', None) if not isinstance(result, dict) else result.get('finishReason')
        if finish_reason == 'length':
            return invalid_plan('Plan response was truncated')
        
        # Handle {items: [...]} wrapper format - extract items array
        if isinstance(parsed, dict) and "items" in parsed:
            parsed = parsed.get("items", [])
        
        # Fail closed: malformed JSON list must not proceed to retrieval
        if not isinstance(parsed, list):
            logger.warning("Plan response not a list, failing closed: %s", type(parsed))
            return invalid_plan('Plan response is not a JSON array')
        
        try:
            from services.deep_research.plan_identity import normalize_generated_obligation_ids
            generated, identity_changes = normalize_generated_obligation_ids(parsed[:4])
            validated = validate_plan(generated)
            from services.deep_research.completion_criteria import validate_completion_criteria
            validate_completion_criteria(validated, required=criteria_required)
        except ValueError as ve:
            logger.warning("Plan validation failed: %s", ve)
            return invalid_plan(ve)
        
        if not validated:
            return invalid_plan('Plan has no research items')

        from services.deep_research.evidence_requirements import enabled as requirements_enabled, normalize_generated_requirements, grounded, imperative_grounded
        from services.deep_research.request_dimensions import enabled as dimensions_enabled
        requirement_changes = []
        if requirements_enabled(record):
            try:
                validated, requirement_changes = normalize_generated_requirements(validated, question,
                    literal_questions=grounded(record),literal_imperatives=imperative_grounded(record),atomic_dimensions=dimensions_enabled(record))
                validated = validate_plan(validated)
            except ValueError as exc:
                return invalid_plan(exc)

        from services.deep_research.obligation_purpose import normalize_obligation_purposes
        validated = normalize_obligation_purposes(validated, question)
        allowed = [material.get("materialId") for material in materials]
        required_default = allowed if output_kind == "paper_comparison" else record.get("focusPaperIds") or allowed
        for item in validated:
            for obligation in item.get("obligations", []):
                requested = obligation.get("requiredSources", [])
                external_ids = []
                if record.get("sourcePolicy", {}).get("mode") in {"academic_external", "external_only"}:
                    from services.deep_research_academic import checked_arxiv_id
                    for sid in requested:
                        if sid.lower().startswith("arxiv:"):
                            try:
                                external_ids.append("arxiv:" + __import__('re').sub(r'v\d+$', '', checked_arxiv_id(sid.split(':', 1)[1])))
                            except ValueError:
                                pass
                obligation["requiredSources"] = [sid for sid in requested if sid in allowed] + external_ids or required_default
        # Each comparison must inspect every selected paper, while paper-specific
        # obligations should not require irrelevant evidence from all other papers.
        if output_kind == "paper_comparison":
            covered = {sid for item in validated for obl in item["obligations"] for sid in obl["requiredSources"]}
            for sid in allowed:
                if sid not in covered:
                    validated[0]["obligations"][0]["requiredSources"].append(sid)

        if output_kind == 'experiment_design':
            from services.deep_research.data_prerequisite import ensure_data_prerequisite
            # All task materials are permitted candidates; no invented external source.
            candidates = allowed or list(dict.fromkeys(sid for item in validated
                for obligation in item['obligations'] for sid in obligation['requiredSources']))
            validated = validate_plan(ensure_data_prerequisite(validated, candidates, question,
                proposed_protocol=proposed_protocol))
            if record.get('experimentPlanContractVersion')==1:
                from services.deep_research.experiment_deliverable import ensure_experiment_deliverable
                validated=validate_plan(ensure_experiment_deliverable(validated,question,required_default or candidates))
            validate_completion_criteria(validated, required=record.get('planCompletionContractVersion') == 1)
        
        plan_ids = [item["itemId"] for item in validated]
        from services.deep_research.continuation import rebind_inherited_state
        inherited = bool(brief_state.get('inheritedEvidence'))
        
        repo_update(
            run_id,
            lambda r: {**r, "state": {
                **(rebind_inherited_state(r.get('state') or {}, validated)
                   if inherited else {**(r.get("state") or {}), "plan": validated}),
                'planIdNormalization': identity_changes,
                **({'planRequirementNormalization': requirement_changes} if requirements_enabled(record) else {}),
                'planFormatValidation': {'status': 'validated', 'requiresCompletionCriteria': criteria_required}}},
            expected_revision=None,
        )

        from services.deep_research.dependencies import enabled as ordered_plan, initialize
        if ordered_plan(record):
            repo_update(run_id, lambda r: {**r, 'state': {**r['state'],
                'dependencyExecution': initialize(validated, brief_state.get('planRevision', 0)),
                'plan': [{**item, 'status': 'pending'} for item in validated]}}, expected_revision=None)
        
        return {"plan_ids": plan_ids, "assess_inherited": inherited,
                "plan_revision": brief_state.get('planRevision', 0)}
    
    return node


def make_acquire_node(
    retrieve_fn: Callable[[str, str, int], list],
    scope_validator: Callable[[str, str], bool],
    repo_update: Callable[[str, Callable, dict | None], dict],
    external_acquire: Callable[[str, list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
) -> Callable[[GraphState], dict]:
    """Acquire sources for each plan obligation, iterating EVERY selected paper.
    
    On requery rounds, uses gap-specific changed queries instead of original obligation questions.
    Deduplicates by sourceId (not workId) to retain all relevant chunks per obligation.
    Merges sources and evidence across rounds, preserving exact source identity and conditions.
    Persists normalized source metadata (workId/versionId/contentHash/accessLevel/text/location).
    
    Optional external_acquire: called only when sourcePolicy.mode is academic_external or
    external_only. Returns normalized external sources with sourceKind/workId/versionId/
    contentHash/title/arxivId/accessLevel/text/location/obligationIds. Merged into domain
    sources. Scope-validator accepts external work IDs ONLY after source persisted.
    For external_only with no materials, requiredSources use acquired external work IDs.
    """
    
    def node(state: GraphState) -> dict:
        run_id = state.get("run_id", "")
        requery_queries = state.get("requery_queries", [])
        
        record = repo_update(run_id, lambda r: {**r, "stage": "acquire"}, expected_revision=None)
        source_policy_mode = record.get("sourcePolicy", {}).get("mode", "task_only")
        materials = record.get("materials", [])
        plan = record.get("state", {}).get("plan", [])
        existing_sources = record.get("state", {}).get("sources", [])
        
        # Build existing source index for merging across rounds
        existing_by_id = {s["sourceId"]: s for s in existing_sources}
        normalized_sources = list(existing_sources)
        
        # Determine query set: gap-specific changed queries on requery, else original obligations
        if requery_queries:
            query_targets = requery_queries
        else:
            query_targets = []
            for plan_item in plan:
                for obligation in plan_item.get("obligations", []):
                    obl_id = obligation.get("obligationId", "")
                    question = obligation.get("question", "")
                    if obl_id and question:
                        query_targets.append({"obligationId": obl_id, "query": obligation.get("searchQuery") or question,
                                              "question": question,
                                              "requiredSources": obligation.get("requiredSources", [])})
        
        # Build material owner map for scope validation
        material_owner_map = {}
        for m in materials:
            mat_id = m.get("materialId", "")
            if mat_id:
                material_owner_map[mat_id] = mat_id
            if m.get("pdfId"):
                material_owner_map[m["pdfId"]] = mat_id
            if m.get("workId"):
                material_owner_map[m["workId"]] = mat_id
        
        # Local retrieval for task materials
        if source_policy_mode != "external_only":
            def local_jobs():
                for material in materials:
                    material_id = material.get("materialId", "")
                    pdf_id = material.get("pdfId", material_id)
                
                    if not scope_validator(run_id, material_id):
                        continue

                    for target in query_targets:
                        if target.get("requiredSources") and material_id not in target["requiredSources"]:
                            continue
                        if target.get("missingSource") and target["missingSource"] != material_id:
                            continue
                        query = target.get("query", "")
                        if query:
                            yield {'query': query, 'pdfId': pdf_id, 'materialId': material_id,
                                   'obligationId': target.get('obligationId', '')}
            from services.deep_research.retrieval_jobs import retrieve_jobs
            from services.deep_research.dependencies import enabled as ordered_plan
            allowed = (lambda: repo_update(run_id, lambda r: r, expected_revision=None).get('status') == 'running') if ordered_plan(record) else None
            for job, results in retrieve_jobs(local_jobs(), retrieve_fn, parallel=ordered_plan(record), allowed=allowed):
                material_id, obl_id = job['materialId'], job['obligationId']
                material = next(m for m in materials if m['materialId'] == material_id)
                for item in results:
                    source_id = item.get("sourceId", "")
                    if not source_id:
                        continue
                        
                    source_work_id = item.get("sourceWorkId", item.get("pdfId", ""))
                    owner_material_id = material_owner_map.get(source_work_id)
                    if owner_material_id != material_id:
                        continue

                    existing = existing_by_id.get(source_id)
                    if existing:
                        if ordered_plan(record) and (existing.get('workId') != source_work_id
                                or existing.get('text', '') != item.get('text', '')):
                            from services.deep_research.contracts import DeepResearchError
                            raise DeepResearchError('source_identity_conflict', '相同来源身份返回了不同原文，已停止合并。')
                        if obl_id and obl_id not in existing.get("obligationIds", []):
                            existing["obligationIds"].append(obl_id)
                    else:
                        from services.deep_research.source_labels import source_display_title
                        new_source = {
                                "sourceId": source_id,
                                "workId": source_work_id,
                                "ownerMaterialId": owner_material_id,
                                "versionId": material.get("versionId") or item.get("versionId", source_id),
                                "contentHash": item.get("contentHash") or hashlib.sha256(item.get("text", "").encode()).hexdigest(),
                                "materialContentHash": material.get("contentHash"),
                                "accessLevel": item.get("accessLevel", "fulltext"),
                                "text": item.get("text", ""),
                                "tableData": item.get("tableData"),
                                "location": item.get("location", {"chunkIndex": item.get("chunkIndex", 0)}),
                                "obligationIds": [obl_id] if obl_id else [],
                                "sourceKind": "task_paper",
                                "title": source_display_title(item.get("title"), material.get("title")),
                                "url": item.get("url", ""),
                        }
                        from services.deep_research.publication_identity import validated as valid_publication
                        publication = valid_publication(item.get('publicationIdentity'),material.get('contentHash'))
                        if publication:
                            new_source['publicationIdentity'] = publication
                        normalized_sources.append(new_source)
                        existing_by_id[source_id] = new_source
        
        # External acquisition: only when policy permits and callback provided
        use_external = source_policy_mode in ("academic_external", "external_only") and external_acquire is not None
        if use_external:
            from services.deep_research.contracts import DeepResearchError
            try:
                ext_sources = external_acquire(run_id, query_targets)
            except DeepResearchError as exc:
                # Retain usable local/inherited sources when only the supplement failed.
                if exc.code != 'external_discovery_unavailable' or not normalized_sources:
                    raise
                ext_sources = []
            for ext in ext_sources:
                ext_source_id = ext.get("sourceId", "")
                if not ext_source_id:
                    continue
                
                # Persist external source first so scope validator can accept it
                ext_work_id = ext.get("workId", "")
                existing = existing_by_id.get(ext_source_id)
                if existing:
                    ext_obl_ids = ext.get("obligationIds", [])
                    for oid in ext_obl_ids:
                        if oid and oid not in existing.get("obligationIds", []):
                            existing["obligationIds"].append(oid)
                else:
                    new_ext = {
                        "sourceId": ext_source_id,
                        "workId": ext_work_id,
                        "ownerMaterialId": ext_work_id,
                        "versionId": ext.get("versionId", ext_source_id),
                        "contentHash": ext.get("contentHash", ""),
                        "accessLevel": ext.get("accessLevel", "abstract"),
                        "text": ext.get("text", ""),
                        "location": ext.get("location", {}),
                        "obligationIds": ext.get("obligationIds", []),
                        "sourceKind": ext.get("sourceKind", "arxiv"),
                        "title": ext.get("title", ""),
                        "url": ext.get("url", ""),
                        "arxivId": ext.get("arxivId", ""),
                        "sourceType": "academic_paper",
                    }
                    normalized_sources.append(new_ext)
                    existing_by_id[ext_source_id] = new_ext
        
        from services.deep_research.dependencies import enabled as ordered_plan
        if ordered_plan(record):
            normalized_sources.sort(key=lambda source: source['sourceId'])
            for source in normalized_sources:
                source['obligationIds'] = sorted(set(source.get('obligationIds', [])))
        source_ids = [s["sourceId"] for s in normalized_sources]
        
        repo_update(
            run_id,
            lambda r: {**r, "state": {**(r.get("state") or {}), "sourceIds": source_ids, "sources": normalized_sources}},
            expected_revision=None,
        )
        
        return {"source_ids": source_ids}
    
    return node


def make_read_node(
    read_fn: Callable[[str, str], dict],
    scope_validator: Callable[[str, str], bool],
    repo_update: Callable[[str, Callable, dict | None], dict],
) -> Callable[[GraphState], dict]:
    """Read source content with location preservation.
    
    Validates scope by mapping source to owner work/material before validation.
    Preserves full source metadata for evidence identity contract.
    Note: Scope validation is done in graph node using work_id; TrackedSourceReader
    also validates but uses source_id directly - this is acceptable since the
    graph node does the authoritative check first.
    """
    
    def node(state: GraphState) -> dict:
        run_id = state.get("run_id", "")
        source_ids = state.get("source_ids", [])
        
        record = repo_update(run_id, lambda r: {**r, "stage": "read"}, expected_revision=None)
        
        # Get normalized sources from acquire node (contains workId/ownerMaterialId mapping)
        sources_map = {s["sourceId"]: s for s in record.get("state", {}).get("sources", [])}
        
        read_results = []
        from services.deep_research.selection import balanced_sample
        extracted = {(e.get("sourceId"), e.get("contentHash")) for e in record.get("state", {}).get("evidence", [])}
        available = [sources_map[sid] for sid in source_ids if sid in sources_map]
        available.sort(key=lambda source: (source["sourceId"], source.get("contentHash")) in extracted)
        read_limit = 24 if record.get("budget", {}).get("profile") == "extended" else 12
        if type(record.get('readingPriorityContractVersion')) is int and record['readingPriorityContractVersion'] in (1,2,3,4,5):
            from services.deep_research.reading_priority import select_read_sources
            from services.deep_research.source_continuity import enabled as continuity_enabled,method_enabled
            obligations={o['obligationId']:o for item in record.get('state',{}).get('plan',[]) for o in item.get('obligations',[])}
            selected=select_read_sources(available,obligations,read_limit,extracted=extracted,
                **({'priority_version':{2:7,3:8,4:9,5:10}[record['readingPriorityContractVersion']]}
                   if record['readingPriorityContractVersion'] in (2,3,4,5) else {}),
                **({'illustrative_context':True} if continuity_enabled(record) else {}),
                **({'method_context':True} if method_enabled(record) else {}))
        else:
            selected = balanced_sample(available,
                lambda source: (source.get("workId"), tuple(source.get("obligationIds", []))),read_limit)
        for source_meta in selected:
            source_id = source_meta["sourceId"]
            # Map source to owner material for scope validation
            source_meta = sources_map.get(source_id, {})
            # Use ownerMaterialId (resolved in acquire) for scope validation, not source_id directly
            owner_material_id = source_meta.get("ownerMaterialId", source_meta.get("workId", source_id))
            
            # Validate scope using owner material ID
            if not scope_validator(run_id, owner_material_id):
                logger.warning("Scope validation failed for source %s (owner %s)", source_id, owner_material_id)
                continue
            
            # Read content - reader may return empty if no content available
            content = read_fn(run_id, source_id)
            
            # Use source metadata text as fallback if reader returns empty pages
            pages = content.get("pages", []) if content else []
            if not pages and source_meta.get("text"):
                # Fallback to chunk text from acquire node
                pages = [{"page": 0, "text": source_meta.get("text", "")}]
            
            if pages:
                # Preserve full source metadata for evidence identity contract
                read_results.append({
                    "sourceId": source_id,
                    "workId": source_meta.get("workId", source_id),
                    "ownerMaterialId": owner_material_id,
                    "versionId": source_meta.get("versionId", source_id),
                    "contentHash": source_meta.get("contentHash", ""),
                    "accessLevel": content.get("accessLevel", source_meta.get("accessLevel", "unknown")) if content else source_meta.get("accessLevel", "unknown"),
                    "pages": pages,
                    "text": source_meta.get("text", ""),  # Original chunk text
                    "tableData": source_meta.get("tableData"),
                    "location": source_meta.get("location", {}),
                    "sourceKind": source_meta.get("sourceKind", "local"),
                    "title": source_meta.get("title", ""),
                    "url": source_meta.get("url", ""),
                    "obligationIds": source_meta.get("obligationIds", []),
                    **({'publicationIdentity':source_meta['publicationIdentity']} if source_meta.get('publicationIdentity') else {}),
                })
        
        repo_update(
            run_id,
            lambda r: {**r, "state": {**(r.get("state") or {}), "readResults": read_results}},
            expected_revision=None,
        )
        
        return {"source_ids": source_ids}  # Pass through
    
    return node


def make_extract_node(
    llm_invoke: Callable[..., dict],
    make_evidence_fn: Callable[..., dict],
    scope_validator: Callable[[str, str], bool],
    repo_update: Callable[[str, Callable, dict | None], dict],
) -> Callable[[GraphState], dict]:
    """Extract evidence from read content with literal preservation.
    
    Uses full source metadata from read node to satisfy evidence identity contract.
    Extract prompts supply obligation IDs for relevance binding.
    Merges evidence across requery rounds by evidence ID.
    Skips re-extraction of sources already extracted (same contentHash) for incremental children.
    Preserves sourceKind/title/url in evidence records.
    """
    
    def node(state: GraphState) -> dict:
        run_id = state.get("run_id", "")
        previous_hashes = set(state.get("previous_evidence_hashes", []))
        
        record = repo_update(run_id, lambda r: {**r, "stage": "extract"}, expected_revision=None)
        read_results = record.get("state", {}).get("readResults", [])
        plan = record.get("state", {}).get("plan", [])
        existing_evidence = record.get("state", {}).get("evidence", [])
        
        # Build obligation lookup for prompt context
        obligation_map = {}
        obligation_definitions = {}
        for plan_item in plan:
            for obl in plan_item.get("obligations", []):
                obl_id = obl.get("obligationId", "")
                if obl_id:
                    obligation_map[obl_id] = obl.get("question", "")
                    obligation_definitions[obl_id] = obl
        
        # Index existing evidence for merge
        existing_by_id = {e["evidenceId"]: e for e in existing_evidence}
        # Track which content hashes have already been extracted
        extracted_hashes = {(e.get("sourceId"), e.get("contentHash")) for e in existing_evidence if e.get("sourceId")}
        all_evidence = list(existing_evidence)
        
        for read_result in read_results:
            source_id = read_result.get("sourceId", "")
            work_id = read_result.get("workId", source_id)
            pages = read_result.get("pages", [])
            access_level = read_result.get("accessLevel", "abstract")
            content_hash = read_result.get("contentHash", "")
            source_kind = read_result.get("sourceKind", "local")
            source_title = read_result.get("title", "")
            source_url = read_result.get("url", "")
            from services.deep_research.obligation_binding import eligible_obligation_ids
            eligible = eligible_obligation_ids(read_result, obligation_definitions)
            if not eligible:
                continue
            
            # Skip re-extraction of already-extracted content (incremental child dedup)
            if (source_id, content_hash) in extracted_hashes:
                for ev in all_evidence:
                    if ev.get("sourceId") == source_id and ev.get("contentHash") == content_hash:
                        ev["obligationIds"] = eligible
                continue
            
            if not scope_validator(run_id, work_id):
                continue
            
            # Get obligation IDs relevant to this source
            source_obl_ids = eligible
            
            for page in pages[:5]:
                text = page.get("text", "")[:3000]
                if not text or len(text) < 50:
                    continue
                
                # Supply obligation IDs in extract prompt
                obl_context = [{"obligationId": oid, "question": obligation_map.get(oid, "")} for oid in source_obl_ids if oid in obligation_map]
                
                prompt = f"""Extract evidence from this text relevant to the research obligations.
Text (page {page.get('page', '?')}): {text[:3000]}

Obligations (with IDs): {json.dumps(obl_context[:5], ensure_ascii=False)}

Return a JSON array of at most THREE self-contained, relevant evidence items. Return [] if none.
Keep complete sentences with their conditions; omit fragmentary labels, dangling numbers and unrelated captions.
For requested mechanisms, retain conditioning inputs and activation/applicability rules.
Each item has:
- quote: exact literal text from source
- location: {{page, section, chunk}}
- obligationIds: which obligation IDs this supports (must match provided IDs)
- conditions: any dataset/model/hardware conditions mentioned
- kind: reported/inference/suggestion"""
                
                result = llm_invoke(run_id, "extract", prompt, {"max_tokens": 1500, "temperature": 0.0})
                
                if hasattr(result, "content"):
                    content = result.content
                elif isinstance(result, dict):
                    content = result.get("content", "[]")
                else:
                    content = str(result)
                
                parsed = _safe_parse_json(content)
                
                if not isinstance(parsed, list):
                    continue
                
                for ev in parsed[:3]:
                    if not isinstance(ev, dict):
                        continue
                    from services.deep_research.literal_quote import original_quote_span
                    quote = original_quote_span(ev.get("quote", ""), text)
                    if quote is None:
                        continue
                    
                    # Validate obligation IDs are from the supplied set
                    ev_obl_ids = ev.get("obligationIds", [])
                    if not isinstance(ev_obl_ids, list):
                        ev_obl_ids = []
                    ev_obl_ids = [oid for oid in ev_obl_ids if oid in source_obl_ids[:5]]
                    if not ev_obl_ids:
                        continue
                    
                    try:
                        evidence = make_evidence_fn(
                            source={
                                "workId": work_id,
                                "versionId": read_result.get("versionId", source_id),
                                "contentHash": content_hash,
                                "accessLevel": access_level,
                            },
                            quote=quote,
                            original=text,
                            location={**read_result.get("location", {}), **{k: v for k, v in page.items() if k != "text"}},
                            obligation_ids=ev_obl_ids,
                            conditions=ev.get("conditions") if isinstance(ev.get("conditions"), dict) else
                                {"context": ev["conditions"]} if isinstance(ev.get("conditions"), str) and ev["conditions"] else {},
                        )
                        
                        # Preserve source metadata on evidence
                        evidence["sourceKind"] = source_kind
                        evidence["sourceId"] = source_id
                        evidence["sourceTitle"] = source_title
                        evidence["sourceUrl"] = source_url
                        if read_result.get('publicationIdentity'):
                            evidence['sourcePublicationIdentity'] = read_result['publicationIdentity']
                        
                        # Merge: skip duplicates by evidence ID
                        if evidence["evidenceId"] not in existing_by_id:
                            all_evidence.append(evidence)
                            existing_by_id[evidence["evidenceId"]] = evidence
                            if content_hash:
                                extracted_hashes.add((source_id, content_hash))
                    except ValueError:
                        pass
        
        repo_update(
            run_id,
            lambda r: {**r, "state": {**(r.get("state") or {}), "evidence": all_evidence}},
            expected_revision=None,
        )
        
        return {"evidence_ids": [e["evidenceId"] for e in all_evidence]}
    
    return node


def make_assess_node(
    coverage_gaps_fn: Callable[[list, list, list], list],
    repo_update: Callable[[str, Callable, dict | None], dict],
    llm_invoke: Callable[..., dict] | None = None,
) -> Callable[[GraphState], dict]:
    """Assess coverage and decide next action.
    
    Uses a batched budgeted LLM call per assess round to judge obligation/evidence
    binding and conditions. Literal=='passed' plus obligation ID alone is NOT sufficient
    for relevance — the LLM must confirm the evidence actually addresses the obligation.
    Unsupported/unchecked evidence never closes a gap.
    
    Changed queries target specific missing source/obligation pairs with meaningful
    gap-focused content (not just a round marker). Stops on no new evidence.
    Bounded maximum 2 requery rounds.
    """
    
    def node(state: GraphState) -> dict:
        run_id = state.get("run_id", "")
        requery_count = state.get("requery_count", 0)
        prev_source_count = state.get("prev_source_count", 0)
        
        record = repo_update(run_id, lambda r: {**r, "stage": "assess"}, expected_revision=None)
        from services.deep_research.joint_assessment import enabled as joint_enabled,assess as joint_assess
        if joint_enabled(record):
            return joint_assess(state,record,repo_update,llm_invoke,coverage_gaps_fn)
        from services.deep_research.adaptive_assessment import enabled, assess
        if enabled(record):
            return assess(state, record, repo_update, llm_invoke, coverage_gaps_fn)
        plan = record.get("state", {}).get("plan", [])
        evidence = record.get("state", {}).get("evidence", [])
        materials = record.get("materials", [])
        current_source_count = len(record.get("state", {}).get("sources", []))
        
        # Build obligation lookup
        obligation_map = {}
        for plan_item in plan:
            for obl in plan_item.get("obligations", []):
                obl_id = obl.get("obligationId", "")
                if obl_id:
                    obligation_map[obl_id] = obl.get("question", "")
        
        # Batch relevance judgment via LLM if available
        from services.deep_research.selection import balanced_sample
        relevance_verdicts: dict[str, bool] = {}
        if llm_invoke is not None and evidence:
            relevance_pairs = []
            for ev in evidence:
                for obl_id in ev.get("obligationIds", []):
                    if obl_id in obligation_map:
                        relevance_pairs.append({
                            "evidenceId": ev["evidenceId"],
                            "obligationId": obl_id,
                            "quote": ev.get("quote", ""),
                            "conditions": ev.get("conditions", {}),
                            "obligationQuestion": obligation_map[obl_id],
                            "sourceWorkId": ev.get("sourceWorkId", ""),
                        })
            
            if relevance_pairs:
                selected_pairs = balanced_sample(relevance_pairs,
                    lambda pair: (pair["sourceWorkId"], pair["obligationId"]), 20)
                batch_prompt = f"""For each evidence-obligation pair below, judge whether the evidence ACTUALLY addresses the obligation question. A literal quote match is NOT sufficient — the content must be topically relevant and the conditions must be compatible.

Pairs:
{json.dumps(selected_pairs, ensure_ascii=False, indent=2)}

Return a COMPACT JSON array of {{evidenceId, obligationId, relevant: true/false}}.
Do not include reasons or extra prose; include one verdict for EVERY supplied pair.
Only mark relevant=true if the evidence directly bears on the obligation question."""
                
                try:
                    result = llm_invoke(run_id, "assess_relevance", batch_prompt,
                                        {"max_tokens": 4000, "temperature": 0.0})
                    if hasattr(result, "content"):
                        resp_content = result.content
                    elif isinstance(result, dict):
                        resp_content = result.get("content", "[]")
                    else:
                        resp_content = str(result)
                    
                    verdicts = _safe_parse_json(resp_content)
                    if isinstance(verdicts, list):
                        for v in verdicts:
                            if isinstance(v, dict):
                                key = f"{v.get('evidenceId', '')}:{v.get('obligationId', '')}"
                                relevance_verdicts[key] = v.get("relevant") is True
                except Exception:
                    pass
        
        # Build coverage records — only supported if LLM confirmed relevance
        coverage = []
        for ev in evidence:
            ev_obl_ids = ev.get("obligationIds", [])
            if not ev_obl_ids:
                continue
            literal_passed = ev.get("verification", {}).get("literal") == "passed"
            if not literal_passed:
                continue
            for obl_id in ev_obl_ids:
                if obl_id not in obligation_map:
                    continue
                rel_key = f"{ev['evidenceId']}:{obl_id}"
                is_relevant = relevance_verdicts.get(rel_key, False)
                coverage.append({
                    "obligationId": obl_id,
                    "sourceWorkId": ev.get("sourceWorkId", ""),
                    "state": "supported" if is_relevant else "unchecked",
                    "checked": True,
                })
        
        required_sources = [m.get("materialId", "") for m in materials]
        if not required_sources:
            required_sources = list(dict.fromkeys(s.get("workId") for s in record.get("state", {}).get("sources", []) if s.get("workId")))
        # Keep a positive result when another passage for the same pair was insufficient.
        merged_coverage = {}
        for row in coverage:
            key = (row["obligationId"], row["sourceWorkId"])
            if key not in merged_coverage or row["state"] == "supported":
                merged_coverage[key] = row
        coverage = list(merged_coverage.values())
        gaps = coverage_gaps_fn(plan, coverage, required_sources)
        if not required_sources:
            gaps = [{"obligationId": obl_id, "question": question, "missingEvidence": "尚未取得可用文献", "checked": True}
                    for obl_id, question in obligation_map.items()]
        
        # Decide next action - bounded maximum 2 requery rounds
        stop_reason = ""
        requery_queries = []
        
        # Stop on no new evidence since last round
        if requery_count > 0 and current_source_count <= prev_source_count:
            stop_reason = "no_new_evidence"
        elif not gaps:
            stop_reason = "covered"
        elif requery_count >= (4 if record.get("budget", {}).get("profile") == "extended" else 2):
            stop_reason = "max_requery"
        elif len(gaps) > len(plan) * 2:
            stop_reason = "too_many_gaps"
        else:
            # Generate meaningful gap-focused queries targeting missing source/obligation pairs
            seen_queries = set()
            for gap in gaps:
                obl_id = gap.get("obligationId", "")
                question = gap.get("question", "")
                missing_source = gap.get("sourceWorkId", "")
                if not obl_id or not question:
                    continue
                # Meaningful changed query: include the gap context and missing source
                strategy = "对照实验 消融结果 评测设置 固定条件" if requery_count == 0 else "反对证据 局限性 失败案例 泛化边界"
                parts = [question, gap.get("missingEvidence", ""), strategy]
                changed_query = "；".join(parts)
                key = (obl_id, missing_source)
                if key not in seen_queries:
                    seen_queries.add(key)
                    requery_queries.append({
                        "obligationId": obl_id,
                        "query": changed_query,
                        "missingSource": missing_source,
                    })
        
        missing = {gap.get("obligationId") for gap in gaps}
        progress_plan = [{**item, "status": "gap" if any(obl["obligationId"] in missing for obl in item.get("obligations", [])) else "completed"}
                         for item in plan]
        repo_update(
            run_id,
            lambda r: {**r, "state": {**(r.get("state") or {}), "plan": progress_plan, "gaps": gaps, "stopReason": stop_reason}},
            expected_revision=None,
        )
        
        new_requery_count = requery_count
        if gaps and not stop_reason and requery_queries:
            new_requery_count = requery_count + 1
        
        return {
            "gaps": gaps,
            "stop_reason": stop_reason,
            "requery_count": new_requery_count,
            "requery_queries": requery_queries,
            "prev_source_count": current_source_count,
        }
    
    return node


def make_synthesize_node(
    llm_invoke: Callable[..., dict],
    repo_update: Callable[[str, Callable, dict | None], dict],
) -> Callable[[GraphState], dict]:
    """Synthesize total answer from verified evidence. Uses reserve pool.
    
    Generates ONE synthesis for the total question. Sections organized by output kind
    using claim IDs mapped to sections. No unchecked model prose in report body.
    """
    
    def node(state: GraphState) -> dict:
        run_id = state.get("run_id", "")
        
        record = repo_update(run_id, lambda r: {**r, "stage": "synthesize"}, expected_revision=None)
        question = effective_question(record)
        evidence = record.get("state", {}).get("evidence", [])
        gaps = record.get("state", {}).get("gaps", [])
        brief_state = record.get("state", {})
        output_kind = brief_state.get("outputKind", "direction_survey")
        strict_budget = type(record.get('budgetContractVersion')) is int and record['budgetContractVersion'] == 1
        strict_hypothesis = type(record.get('hypothesisContractVersion')) is int and record['hypothesisContractVersion'] == 1
        from services.deep_research.experiment_protocol import protocol_version
        strict_protocol = protocol_version(record.get('protocolContractVersion'))
        from services.deep_research.experiment_workflow import workflow_version, workflow_contract
        strict_workflow = workflow_version(record.get('workflowContractVersion'))
        from services.deep_research.answer_constraints import requested_character_limit
        requested_limit = requested_character_limit(question)
        from services.deep_research.synthesis import OUTPUT_KIND_SECTIONS
        section_templates = OUTPUT_KIND_SECTIONS.get(output_kind, OUTPUT_KIND_SECTIONS["direction_survey"])
        claim_limit = (12 if output_kind == 'experiment_design' else 5 if output_kind == 'paper_comparison'
                       else 2 if requested_limit and requested_limit <= 300 else 3 if requested_limit else 12)
        from services.deep_research.answer_format import enabled as format_enabled, requested_points, guidance as format_guidance
        point_constraint = requested_points(question) if format_enabled(record) else None
        if point_constraint and output_kind != 'experiment_design':
            claim_limit = point_constraint['count']
        paper_titles = {m.get('materialId'): m.get('title', '') for m in record.get('materials', [])}
        
        # Format evidence summaries with obligation binding
        from services.deep_research.selection import (
            balanced_sample, surrounding_context, comparison_evidence_order, distinct_evidence_candidates)
        evidence_summaries = []
        evidence_aliases = {}
        source_aliases = {}
        source_registry = {}
        from services.deep_research.synthesis_evidence import enabled as premise_enabled,order_premises,result_role,fit_premises
        premise_mode=premise_enabled(record)
        premise_bundles=[];table_registry={};table_keys={}
        candidates = distinct_evidence_candidates(evidence)
        if premise_mode:
            from services.deep_research.experiment_envelope import enabled as compact_experiment_envelope
            if output_kind=='experiment_design' and compact_experiment_envelope(record):
                from services.deep_research.selection import proposal_evidence_order
                candidates=proposal_evidence_order(candidates,question)
            candidates,premise_bundles=order_premises(candidates,brief_state.get('plan',[]),
                **({'membership_intents':True} if record['synthesisEvidenceContractVersion'] in (2,3,4,5,6) else {}),
                **({'module_intents':True} if record['synthesisEvidenceContractVersion'] in (3,4,5,6) else {}),
                **({'condition_intents':True} if record['synthesisEvidenceContractVersion'] in (4,5,6) else {}),
                **({'definition_context':True,'read_sources':brief_state.get('readResults',[])}
                   if record['synthesisEvidenceContractVersion'] in (5,6) else {}),
                **({'operational_context':True}
                   if record['synthesisEvidenceContractVersion']==6 and output_kind=='experiment_design' else {}))
        elif output_kind == 'paper_comparison':
            candidates = comparison_evidence_order(candidates, paper_titles)
        elif output_kind == 'experiment_design':
            from services.deep_research.selection import proposal_evidence_order
            candidates = proposal_evidence_order(candidates, question)
        from services.deep_research.claim_check import enabled as claim_check_enabled,prioritize_results
        if premise_mode and claim_check_enabled(record) and record['claimCheckContractVersion']==2:
            candidates,premise_bundles=prioritize_results(candidates,premise_bundles,question)
        selected_candidates=candidates if premise_mode else balanced_sample(candidates,
            lambda item:(item.get('sourceWorkId',''),tuple(item.get('obligationIds',[]))),20)
        for ev in selected_candidates:
            alias = f"E{len(evidence_aliases) + 1}"
            evidence_aliases[alias] = ev['evidenceId']
            source_id = ev.get('sourceWorkId', '')
            if source_id not in source_aliases:
                source_aliases[source_id] = f'P{len(source_aliases) + 1}'
                from services.deep_research.source_labels import source_display_title
                source_registry[source_aliases[source_id]] = {
                    'workId': source_id,
                    'title': source_display_title(ev.get('sourceTitle'), paper_titles.get(source_id))}
                if ev.get('sourcePublicationIdentity'):
                    source_registry[source_aliases[source_id]]['publicationIdentity'] = ev['sourcePublicationIdentity']
            table_fields={}
            if ev.get('tableData') is not None:
                if premise_mode:
                    table_key=digest({'work':ev.get('sourceWorkId'),'version':ev.get('sourceVersionId'),
                                      'hash':ev.get('contentHash'),'table':ev['tableData']})
                    if table_key not in table_keys:
                        tid=f'T{len(table_keys)+1}';table_keys[table_key]=tid
                        table_registry[tid]={'source':source_aliases[source_id],'tableData':ev['tableData']}
                    table_fields={'tableDataRef':table_keys[table_key]}
                else:
                    table_fields={'tableData':ev['tableData']}
            evidence_summaries.append({
                "evidenceId": alias,
                "quote": ev.get("quote", ""),
                "source": source_aliases[source_id],
                "sourceContext": surrounding_context(ev),
                **table_fields,
                **({'resultRoleHintOnly':result_role(ev)} if premise_mode else {}),
                'location': {key: value for key, value in ev.get('location', {}).items()
                             if key not in {'chunk', 'pageResolution'}},
                **({'conditions': ev['conditions']} if ev.get('conditions') else {}),
                "obligations": ev.get("obligationIds", []),
                "accessLevel": ev.get("accessLevel", "fulltext"),
            })
        
        from uuid import uuid4
        from services.deep_research.prompt_budget import fit_evidence_prompt
        evidence_marker = uuid4().hex
        claim_fields = 'claimId, text, kind, evidenceRefs, conditions, obligationIds, detailLevel, tableBindings (required for table measurements)'
        from services.deep_research.factual_scope import drafting_schema_enabled,DRAFTING_SCHEMA
        if drafting_schema_enabled(record) and output_kind in {'claim_verification','paper_comparison'}:
            claim_fields += ', draftingBasis (required object; fill before text using schema below)'
        if output_kind == 'experiment_design':
            claim_fields += ', designRole (required on every proposal/hypothesis), executionSpec (required for groups, data and analysis roles)'
            if strict_budget:
                claim_fields += ', executionSpec also required for the budget role'
            if strict_hypothesis:
                claim_fields += ', executionSpec also required for the hypothesis role'
            if strict_protocol:
                claim_fields += ', executionSpec also required for the controls role'
        from services.deep_research.design_drafting import synthesis_obligations
        draft_obligations = synthesis_obligations(brief_state.get('plan', []))
        prompt = f"""Synthesize a complete answer to the research question.
Question: {question}
Output kind: {output_kind}
Strict total character limit: {requested_limit or 'concise, no explicit maximum'}
Answer directly and omit secondary quantitative examples. Conditions count toward the same limit.
Claim count is independent of display length: shorten each statement rather than merging unrelated facts.
Evidence count: {len(evidence)}
User clarification: {separate_clarification(record)}
Gaps: {json.dumps([g.get('question') for g in gaps[:5]], ensure_ascii=False)}
Research questions (answer_requirement is a requested deliverable; supporting_research informs it): {json.dumps(draft_obligations, ensure_ascii=False, separators=(',', ':'))}
Source registry (P keys identify papers, not evidenceRefs): {json.dumps(source_registry, ensure_ascii=False, separators=(',', ':'))}

Evidence summaries:
{evidence_marker}

Return ONLY compact JSON with:
- sections: array of {{title, claimIds: [claim_id_strings]}}
- claims: array of {{{claim_fields}}}
Table measurements require tableBindings: [{{evidenceId,rowNumber,groupIndex,metric,value}}].
Copy exact tableData row, zero-based group, metric and string value. Name dataset, method variant,
metric and value together; no anonymous numeric series. Without tableData use qualitative evidence;
never bypass table checks by relabeling a reported measurement as inference.
Bind only the cells whose values you actually state, not every metric on that row.
For a short answer select the minimum sufficient numerical example and preserve space
for requested conditions/limitations; do not reproduce entire rows or add storage/speed
figures unless needed for the user's question. A bibliography suffix is not a method variant.
Every numeric table claim must explicitly name its method/row label even when the user
already named it. Preserve every hierarchical group level, including the aggregate column.
When checking a named table, stay with that table's cells and requested metric distinction;
an equal number in another experiment is not a substitute or a required digression.
Use ONLY supplied E IDs in evidenceRefs. Evidence IDs are routing keys only: keep E1/E2/... and raw IDs OUT of text and conditions.
P keys are also internal: use source titles in prose, never P1/P2/....
Use source names in prose; UI supplies links. Missing selected evidence does not prove authors omitted a test.
Limitations are evidence-bounded inference claims. Never invent results or present unchecked claims as verified.
State the bounds of the evidence actually read; avoid paper-wide absence assertions
unless an explicit source establishes that exact absence. Finite experiments do not
establish a guarantee for untested conditions.
For example use the neutral structure "当前取得的证据支持…，不足以证明…在其他条件仍成立";
fill it only with actual supported scope. Do not replace this with "论文没有测试…".
Every factual condition, including hardware, needs its supporting source in THAT claim's
own evidenceRefs. A condition cited only by another claim cannot support this one.
Section titles MUST be selected from {json.dumps(section_templates, ensure_ascii=False)}.
Sections reference actual claimIds. All facts, proposals and hypotheses require claims and sections;
no extra unchecked prose. At most {claim_limit} claims, each independently checkable; never merge
unrelated papers, benchmarks or protocols to shorten the answer. For two requested points use at most two claims.
Write concise understandable Chinese, explaining technical components, conditioning inputs and activation rules;
Meet the frozen completionCriteria at their responseType: an explanation must say how/why
the requested input changes or constrains the operation/output. Listing names is insufficient.
For novices, explain each essential unfamiliar concept through what actually happens;
do not assume the reader knows optimization, derivatives or technical method labels.
Explain the problem, signal, adjustment and later consequence in ordinary words first.
Include a technical name/formula only after its meaning, if it helps the requested answer.
When asked how training works, connect the error/signal, the quantity it updates,
and how the update affects later predictions. Naming a differentiability trick
or saying "gradients can flow" alone does not explain that path. State conditional effects
(if the signal pushes a parameter up/down, what changes next), not guaranteed convergence.
Use only supplied evidence, without inventing causal examples.
Planning criteria describe requested deliverables, never establish scientific facts.
Do not repeat the same proposition in text and conditions; use the limited space for the mechanism.
not English placeholders or generic 'depends on the input/view'. Answer each requested aspect or state its
specific evidence limitation. Respect scope and total text+conditions length; put conflicting conditions beside conclusions.
Kinds: reported, inference, hypothesis, proposal. Copy reported numbers exactly; derived ratios/differences are inferences.
Explanations derived from reported equations/parameter links are inferences: cite
their exact premises and state the conditional update, not guaranteed convergence.
Proposals are unexecuted choices, not existing facts. Preserve method labels and variant markers;
distinguish reproduced baselines from original-paper measurements and separate results from controlled trajectories.
With contextOmitted, never invent antecedents or attribute baseline findings to the proposed method.
Abstract-only claims use detailLevel="abstract" and explicitly limit their scope; otherwise "fulltext".
Experiment designs must cover hypothesis, groups, controls, data, metrics, steps, confounders and decisions.
Orient losses before formulas, distinguish conditional/averaged effects and paper distillation from proposed truncation."""

        if output_kind=='experiment_design' and strict_protocol:
            from services.deep_research.design_drafting import prospective_draft_prompt
            prompt=prospective_draft_prompt(question=question,limit=requested_limit,
                clarification=separate_clarification(record),gaps=[g.get('question') for g in gaps[:5]],
                obligations=draft_obligations,sources=source_registry,evidence_marker=evidence_marker,
                claim_fields=claim_fields,claim_limit=claim_limit,section_templates=section_templates,
                **({'concise':True} if type(record.get('experimentIntentContractVersion')) is int
                   and record['experimentIntentContractVersion'] in (1,2,3) else {}))
        prompt += format_guidance(point_constraint)
        from services.deep_research.synthesis import SCIENTIFIC_TERMINOLOGY
        prompt += '\n' + SCIENTIFIC_TERMINOLOGY
        if any(row.get('publicationIdentity') for row in source_registry.values()):
            from services.deep_research.publication_identity import GUIDANCE as publication_guidance
            prompt += '\n' + publication_guidance
        if output_kind == 'paper_comparison':
            prompt += "\nFor a comparison, separate each paper's reported evidence from the cross-paper judgment. " \
                      "Where evidence exists, provide one short reported claim per paper, followed by a separate " \
                      "inference about comparability. A baseline reproduced in paper A is a result of paper A, " \
                      "not a measurement from paper B. Keep each numerical tuple with its own dataset and protocol. " \
                      "Do not transfer an abstract's resolution or speed claim onto a main-table row without evidence. " \
                      "Prefer a supported qualitative tradeoff over a long list of numbers whose conditions cannot " \
                      "fit the requested length. If one paper lacks evidence, record that gap instead of inventing its claim. " \
                      "A cross-paper judgment must cite the supplied evidence from both papers that supports it. " \
                      "Distinguish documented conflicting conditions from conditions not established by the selected evidence. " \
                      "Unknown hardware or resolution is not proof that hardware or resolution differs. " \
                      "Discuss every requested tradeoff (including quality) before adding secondary ablation examples."
        
        if output_kind == "experiment_design":
            from services.deep_research.experiment_intent import enabled as intent_enabled, guidance as experiment_guidance
            if intent_enabled(record):
                prompt += '\n'+experiment_guidance(question,draft=True,
                    policy_version=record['experimentIntentContractVersion'])
            from services.deep_research.design_drafting import design_drafting_requirements
            from services.deep_research.execution_spec import EXECUTION_SPEC_CONTRACT
            prompt += '\n' + EXECUTION_SPEC_CONTRACT
            if strict_protocol:
                from services.deep_research.experiment_protocol import protocol_contract
                prompt += '\n' + protocol_contract(strict_protocol)
            if strict_workflow:
                prompt += '\n' + workflow_contract(strict_workflow)
            if strict_budget:
                from services.deep_research.budget_spec import BUDGET_SPEC_CONTRACT
                prompt += '\n' + BUDGET_SPEC_CONTRACT
            if strict_hypothesis:
                from services.deep_research.hypothesis_spec import HYPOTHESIS_SPEC_CONTRACT
                prompt += '\n' + HYPOTHESIS_SPEC_CONTRACT
            from services.deep_research.experiment_intent import single_toggle_request
            prompt += '\n' + design_drafting_requirements(brief_state.get('metricDomains'),compact=strict_protocol,
                **({'concise_policy':True,'factorial_reference':not single_toggle_request(question)}
                   if intent_enabled(record) else {}))
            from services.deep_research.experimental_reasoning import design_output_outline
            prompt += ('\nREQUIRED OUTPUT OUTLINE (one claim for EACH role, even when several share a section):\n'
                       + json.dumps(design_output_outline(strict_budget=strict_budget,
                           strict_hypothesis=strict_hypothesis, strict_protocol=strict_protocol,
                           strict_workflow=strict_workflow), ensure_ascii=False, separators=(',', ':'))
                       + '\nA section title is not a designRole. Include all roles with their own complete specs. '
                       'Budget owns the canonical preparation/per-group amounts. Link hypothesis to analysis '
                       'and exact effect keys; fulfill the requested statistical purpose, never downgrade it.')
        from services.deep_research.comparison_reasoning import enabled as comparison_enabled,GUIDANCE as comparison_guidance
        if comparison_enabled(record) and output_kind in {'paper_comparison','claim_verification'}:
            prompt+='\n'+comparison_guidance
        from services.deep_research.factual_scope import enabled as scope_enabled,DRAFT_GUIDANCE
        if scope_enabled(record) and output_kind in {'paper_comparison','claim_verification'}:
            prompt+='\n'+DRAFT_GUIDANCE
            if drafting_schema_enabled(record):
                prompt+='\nRequired draftingBasis object on EACH output claim (metadata, not evidence):\n'+json.dumps(DRAFTING_SCHEMA,ensure_ascii=False,separators=(',',':'))
        from services.deep_research.table_bindings import declared_references_enabled,REFERENCE_GUIDANCE
        if declared_references_enabled(record):
            prompt+='\n'+REFERENCE_GUIDANCE
        if (type(record.get('comparisonReasoningContractVersion')) is int
                and record['comparisonReasoningContractVersion']==3
                and output_kind in {'paper_comparison','claim_verification'}):
            from services.deep_research.comparison_methodology import REFERENCE
            prompt+='\n'+REFERENCE
        table_marker=uuid4().hex
        if premise_mode:
            prompt+='\nShared table packets (tableDataRef resolves ONLY for its own source/evidence row):\n'+table_marker
            prompt+='''
For tableBindings keep the E evidenceId, never a T or P ID. Its tableDataRef
resolves the unchanged tableData above; a reference in another row/source grants
no permission. Role hints are acquisition hints only, not provenance approval.
When tableDataOmitted=true, only the unchanged quote/context is supplied. Do not
invent tableBindings or numerical rows from an omitted packet; preserve the
qualitative premise without adding optional numerical examples.
Address each paper in its own factual claim before cross-paper inference. Do not
append assertions about another paper's absence to a paper-specific claim.
For training describe the actual initial/joint stages when supplied. A generic
joint optimizer alone does not establish whole-sequence offline fitting.
For a main-table request, distinguish the main quantitative comparison from
operator profiling/ablation; do not relabel a profiling FPS as a main-table result.
The supplied rows are a selection, not the entire acquired pool. Missing a row
from this prompt cannot establish that a paper or the acquired pool lacks a fact.
Keep uncertainty positive and bounded: state which supplied premises support
which conclusion and which stronger inference is not established. Never fill
space with unsupported global absence or incidental iteration/performance values.
'''
        if premise_mode and output_kind in {'paper_comparison','claim_verification'}:
            from services.deep_research.factual_template import build as factual_template
            prompt=factual_template(record,question,output_kind,requested_limit,claim_limit,section_templates,
                draft_obligations,source_registry,evidence_marker,table_marker,
                drafting_schema=drafting_schema_enabled(record),point_guidance=format_guidance(point_constraint))
        from services.deep_research.experiment_template import enabled as compact_experiment_enabled,build as experiment_template
        from services.deep_research.answer_point_intent import enabled as point_intent_enabled, GUIDANCE as point_intent_guidance
        if point_intent_enabled(record) and output_kind != 'experiment_design':
            prompt += '\n' + point_intent_guidance
        from services.deep_research.scope_expression import enabled as scope_expression_enabled, guidance as scope_expression_guidance
        if scope_expression_enabled(record) and output_kind != 'experiment_design':
            prompt += '\n' + scope_expression_guidance(record['scopeExpressionContractVersion'])
        from services.deep_research.experiment_planning import enabled as staged_experiment,basis_limit
        staged_mode=premise_mode and output_kind=='experiment_design' and staged_experiment(record)
        from services.deep_research.experiment_capacity import input_limit as experiment_input_limit,reserved_basis_bytes,enabled as experiment_capacity_enabled
        basis_slot=(uuid4().hex+' '*(reserved_basis_bytes(record)-32)) if staged_mode else None
        if premise_mode and output_kind=='experiment_design' and compact_experiment_enabled(record):
            prompt=experiment_template(record,question=question,limit=requested_limit,
                clarification=separate_clarification(record),gaps=[g.get('question') for g in gaps[:5]],
                obligations=draft_obligations,sources=source_registry,evidence_marker=evidence_marker,
                table_marker=table_marker,claim_fields=claim_fields,claim_limit=claim_limit,
                section_templates=section_templates,**({'basis_slot':basis_slot} if staged_mode else {}))
        compact_evidence_wire=(premise_mode and output_kind=='experiment_design'
            and record.get('synthesisEvidenceContractVersion')==6)
        if compact_evidence_wire:
            from services.deep_research.evidence_wire import LEGEND,SHORT_LEGEND
            from services.deep_research.experiment_plan_encoding import flexible as flexible_plan
            evidence_wire_legend=SHORT_LEGEND if flexible_plan(record) else LEGEND
            prompt+='\n'+evidence_wire_legend
        template = prompt
        if premise_mode:
            reverse_aliases={eid:alias for alias,eid in evidence_aliases.items()}
            wire_bundles=[{**bundle,'evidenceIds':[reverse_aliases.get(eid,eid) for eid in bundle['evidenceIds']],
                          **({'requiredContextByEvidenceId':{reverse_aliases.get(eid,eid):context
                              for eid,context in bundle['requiredContextByEvidenceId'].items()}}
                             if bundle.get('requiredContextByEvidenceId') else {})}
                          for bundle in premise_bundles]
            def render_premises(rows):
                tids={row['tableDataRef'] for row in rows if row.get('tableDataRef')}
                packet=rows
                if compact_evidence_wire:
                    from services.deep_research.evidence_wire import encode,decode
                    packet=encode(rows)
                    if decode(packet)!=rows:raise ValueError('evidence_wire_mismatch')
                return template.replace(evidence_marker,json.dumps(packet,ensure_ascii=False,separators=(',',':')),1).replace(
                    table_marker,json.dumps({key:table_registry[key] for key in table_registry if key in tids},
                        ensure_ascii=False,separators=(',',':')),1)
            numerical_request=bool(re.search(r'数值|具体值|是多少|多少|核(?:查|对)|\b(?:values?|numbers?|how many|how much|verify)\b',question,re.I))
            qualitative_comparison=bool(re.search(r'为何|为什么|可比|同条件|\b(?:why|comparab\w*|alignment)\b',question,re.I))
            from services.deep_research.experiment_outline_encoding import allocation_enabled,encode as encode_outline
            encoded_allocation=staged_mode and allocation_enabled(record)
            def wire_size(value):
                return len(encode_outline(record,value)[0].encode('utf8'))
            prompt,evidence_summaries,missing_bundles=fit_premises(evidence_summaries,render_premises,wire_bundles,
                **({'max_bytes':experiment_input_limit(record)} if staged_mode else {}),
                omit_optional_table_data=output_kind=='paper_comparison' and qualitative_comparison and not numerical_request,
                **({'prompt_byte_size':wire_size} if encoded_allocation else {}),
                **({'required_contexts':{eid:context for b in wire_bundles
                       for eid,context in b.get('requiredContextByEvidenceId',{}).items()}}
                   if record['synthesisEvidenceContractVersion'] in (5,6) else {}))
            repo_update(run_id,lambda r:{**r,'state':{**r.get('state',{}),'synthesisPremiseAllocation':{
                'version':1,'candidateEvidenceIds':[e['evidenceId'] for e in selected_candidates],
                'suppliedEvidenceIds':[evidence_aliases[row['evidenceId']] for row in evidence_summaries],
                'missingPremiseBundles':missing_bundles,'inputBytes':len(prompt.encode('utf8')),
                'fixedInputBytes':len(render_premises([]).encode('utf8')),
                **({'sizingContractVersion':2,'encodedInputBytes':wire_size(prompt),
                    'fixedEncodedInputBytes':wire_size(render_premises([])),
                    'planningSlotReservedBytes':reserved_basis_bytes(record)} if encoded_allocation else {}),
                **({'inputContractVersion':1,'maxInputBytes':experiment_input_limit(record)}
                   if staged_mode and experiment_capacity_enabled(record) else {}),
                'tableDataOmittedEvidenceIds':[evidence_aliases[row['evidenceId']] for row in evidence_summaries if row.get('tableDataOmitted')],
                'sharedTablePackets':len({row['tableDataRef'] for row in evidence_summaries if row.get('tableDataRef')})}}},expected_revision=None)
        else:
            prompt, evidence_summaries = fit_evidence_prompt(evidence_summaries,
                lambda rows: template.replace(evidence_marker, json.dumps(rows, ensure_ascii=False, separators=(',', ':')), 1))
        if output_kind=='experiment_design' and intent_enabled(record) and evidence and not evidence_summaries:
            return {'error_code':'synthesis_evidence_capacity'}
        if (premise_mode and output_kind=='experiment_design' and compact_experiment_enabled(record)
                and missing_bundles):
            return {'error_code':'synthesis_evidence_capacity'}
        evidence_aliases = {row['evidenceId']: evidence_aliases[row['evidenceId']] for row in evidence_summaries}
        workflow_plan = None
        workflow_instruction = ''
        if staged_mode:
            from services.deep_research.experiment_planning import planning_prompt,prepare_plan,prepare_draft
            from services.deep_research.experiment_plan_encoding import enabled as plan_encoding,wire_text
            from services.deep_research.scientific_outline import enabled as decision_outline
            if decision_outline(record):
                from services.deep_research.scientific_outline import prompt_for as planning_prompt,prepare_plan
            def checkpoint_planning(value):
                repo_update(run_id,lambda r:{**r,'state':{**r.get('state',{}),
                    'experimentPlanning':value}},expected_revision=None)
            tables_used={row['tableDataRef'] for row in evidence_summaries if row.get('tableDataRef')}
            current=repo_update(run_id,lambda r:r,expected_revision=None)
            plan=prepare_plan(current,prompt=planning_prompt(question=question,obligations=draft_obligations,
                sources=source_registry,evidence=evidence_summaries,
                tables={key:table_registry[key] for key in table_registry if key in tables_used},
                metric_domains=brief_state.get('metricDomains'),
                **({'compact':True} if record['experimentDraftContractVersion'] in (4,5,6) else {}),
                **({'lean':True} if record['experimentDraftContractVersion'] in (5,6) else {}),
                **({'positional':True} if plan_encoding(record) else {}),
                **({'blueprint':True} if plan_encoding(record) and record['experimentPlanEncodingContractVersion'] in (3,4,5,6,7) else {}),
                **({'blueprint_rows':True} if plan_encoding(record) and record['experimentPlanEncodingContractVersion'] in (4,5,6,7) else {}),
                **({'state_lists':True} if plan_encoding(record) and record['experimentPlanEncodingContractVersion'] in (5,6,7) else {}),
                **({'shared_blueprint':True} if plan_encoding(record) and record['experimentPlanEncodingContractVersion'] in (6,7) else {}),
                request_sized_blueprint=plan_encoding(record) and record['experimentPlanEncodingContractVersion']==7,
                configuration_consistency_version=record.get('configurationConsistencyContractVersion',0),
                execution_guidance_version=record.get('experimentExecutionGuidanceContractVersion',0),
                **({'input_contract_version':1} if experiment_capacity_enabled(record) else {})),aliases=evidence_aliases,
                invoke=lambda node,prompt,options:llm_invoke(run_id,node,prompt,options,use_reserve=True),
                parse=_safe_parse_json,checkpoint=checkpoint_planning)
            if plan is None:
                return {'error_code':'budget_exhausted'}
            current=repo_update(run_id,lambda r:r,expected_revision=None)
            from services.deep_research.execution_workflow_blueprint import enabled as typed_workflow, prepare as prepare_workflow, prompt_for as workflow_prompt, instruction as workflow_directive
            if typed_workflow(record):
                def checkpoint_workflow(value):
                    repo_update(run_id, lambda r: {**r, 'state': {**r.get('state', {}),
                        'executionWorkflowBlueprint': value}}, expected_revision=None)
                workflow_plan = prepare_workflow(current,
                    prompt=workflow_prompt(question=question, basis=plan['basis'], sources=source_registry,
                        evidence=evidence_summaries,
                        tables={key:table_registry[key] for key in table_registry if key in tables_used},
                        obligations=draft_obligations, version=record['executionWorkflowContractVersion']), aliases=evidence_aliases,
                    invoke=lambda node,prompt,options:llm_invoke(run_id,node,prompt,options,use_reserve=True),
                    parse=_safe_parse_json, checkpoint=checkpoint_workflow)
                if workflow_plan is None:
                    return {'error_code': 'budget_exhausted'}
                workflow_instruction = workflow_directive(workflow_plan)
                current=repo_update(run_id,lambda r:r,expected_revision=None)
            actual_basis=(wire_text(plan['basis'],version=record['experimentPlanEncodingContractVersion'])
                if plan_encoding(record) and not decision_outline(record)
                else json.dumps(plan['basis'],ensure_ascii=False,separators=(',',':')))
            from services.deep_research.experiment_generation_envelope import enabled as generation_envelope,refit
            if generation_envelope(record):
                planning_rows=deepcopy(evidence_summaries)
                prompt,evidence_summaries,generation_audit=refit(record,planning_rows,
                    lambda rows:render_premises(rows).replace(basis_slot,actual_basis,1)+workflow_instruction,wire_bundles,plan,
                    **({'extra_required':workflow_plan['value']['sourceRefs']} if workflow_plan else {}),
                    required_contexts={eid:context for b in wire_bundles
                        for eid,context in b.get('requiredContextByEvidenceId',{}).items()})
                generation_audit.update(
                    planningEvidenceIds=[evidence_aliases[r['evidenceId']] for r in planning_rows],
                    suppliedEvidenceIds=[evidence_aliases[r['evidenceId']] for r in evidence_summaries])
                repo_update(run_id,lambda r:{**r,'state':{**r.get('state',{}),
                    'generationPremiseAllocation':generation_audit}},expected_revision=None)
                evidence_aliases={row['evidenceId']:evidence_aliases[row['evidenceId']] for row in evidence_summaries}
            else:
                prompt=prompt.replace(basis_slot,actual_basis,1)+workflow_instruction
            from services.deep_research.experiment_outline_encoding import encode as encode_outline
            prompt,outline_audit=encode_outline(record,prompt)
            if prepare_draft(current,plan,prompt=prompt,checkpoint=checkpoint_planning,
                    **({'outline_encoding_audit':outline_audit} if outline_audit is not None else {})) is None:
                return {'error_code':'budget_exhausted'}
        from services.deep_research.factual_reasoning import request_options as factual_options
        from services.deep_research.experiment_template import request_options as experiment_options,reasoning_enabled as experiment_reasoning
        result = llm_invoke(run_id, "synthesize", prompt,
            {"max_tokens": 4000, "temperature": 0.2, **factual_options(record,question,output_kind),
             **experiment_options(record,output_kind)}, use_reserve=True)
        finish = (result.get('finishReason', result.get('finish_reason')) if isinstance(result, dict)
                  else getattr(result, 'finish_reason', None))
        if finish == 'length':
            return {'error_code': 'invalid_synthesis_response'}
        
        if hasattr(result, "content"):
            content = result.content
        elif isinstance(result, dict):
            content = result.get("content", "{}")
        else:
            content = str(result)
        
        parsed = _safe_parse_json(content)
        from services.deep_research.synthesis_container import normalize_synthesis_container
        parsed, container_kind = normalize_synthesis_container(parsed)
        if not isinstance(parsed, dict) or not isinstance(parsed.get("claims"), list):
            return {"error_code": "invalid_synthesis_response"}
        experiment_drafting_audit=None
        experiment_representation_audit=[]
        if output_kind=='experiment_design' and experiment_reasoning(record):
            experiment_drafting_audit={'version':2,'basis':parsed.pop('designBasis',None),
                'evidenceAliases':dict(evidence_aliases),'verification':'unchecked'}
        elif staged_mode:
            experiment_drafting_audit={'version':record['experimentDraftContractVersion'],'basis':deepcopy(plan['basis']),
                'evidenceAliases':dict(evidence_aliases),'verification':'unchecked',
                'unexpectedEcho':parsed.pop('designBasis',None)}
        from services.deep_research.answer_constraints import compact_answer, resolve_evidence_aliases
        parsed = resolve_evidence_aliases(parsed, evidence_aliases)
        scope_expression_audit = []
        if scope_expression_enabled(record) and output_kind != 'experiment_design':
            from services.deep_research.scope_expression import materialize as materialize_scope
            try:
                for index, claim in enumerate(parsed['claims']):
                    if not isinstance(claim,dict): continue
                    parsed['claims'][index], audit = materialize_scope(claim, record['scopeExpressionContractVersion'])
                    if audit: scope_expression_audit.append(audit)
            except ValueError:
                return {'error_code':'invalid_synthesis_response'}
        drafting_audit={}
        synthesis_presentation_audit={}
        if scope_enabled(record):
            from services.deep_research.citation_presentation import normalize as normalize_markers
            quotation_by_alias={row['evidenceId']:row.get('quote','')+'\n'+
                json.dumps(row.get('sourceContext',{}),ensure_ascii=False) for row in evidence_summaries}
            for index,claim in enumerate(parsed['claims']):
                if isinstance(claim,dict) and 'draftingBasis' in claim:
                    drafting_audit[claim.get('claimId','')]=claim.pop('draftingBasis')
                if isinstance(claim,dict):
                    normalized,audit=normalize_markers(claim,evidence_aliases,quotation_by_alias,
                        **({'version':record['citationPresentationContractVersion']} if type(record.get('citationPresentationContractVersion')) is int
                           and record['citationPresentationContractVersion'] in (2,3,4) else {}))
                    parsed['claims'][index]=normalized
                    if audit:
                        synthesis_presentation_audit[claim.get('claimId','')]=audit
        if output_kind == "experiment_design":
            from services.deep_research.execution_materialization import materialize_execution_claim
            from services.deep_research.budget_contract import stamp_budget_contract
            parsed = stamp_budget_contract(parsed, enabled=strict_budget)
            from services.deep_research.hypothesis_contract import stamp_hypothesis_contract
            parsed = stamp_hypothesis_contract(parsed, enabled=strict_hypothesis)
            from services.deep_research.experiment_protocol import stamp_protocol_contract
            parsed = stamp_protocol_contract(parsed, enabled=strict_protocol)
            from services.deep_research.experiment_workflow import stamp_workflow_contract
            parsed = stamp_workflow_contract(parsed, enabled=strict_workflow)
            if compact_experiment_enabled(record) and record['experimentDraftContractVersion']==6:
                from services.deep_research.experiment_representation import normalize_claims
                parsed['claims'],changes=normalize_claims([{**c,'designContractVersion':2}
                    if isinstance(c,dict) else c for c in parsed['claims']])
                experiment_representation_audit.extend({'phase':'synthesis',**change} for change in changes)
            if workflow_plan is not None:
                from services.deep_research.execution_workflow_blueprint import bind as bind_workflow
                parsed, workflow_binding = bind_workflow(parsed, workflow_plan)
                repo_update(run_id, lambda r: {**r, 'state': {**r.get('state', {}),
                    'executionWorkflowBinding': workflow_binding}}, expected_revision=None)
            parsed['claims'] = [materialize_execution_claim({**claim, 'designContractVersion': 2})
                                if isinstance(claim, dict) else claim for claim in parsed['claims']]
        from services.deep_research.scope_compaction import enabled as scope_compaction_enabled, compact as compact_scope
        compact_invoke = lambda prompt: llm_invoke(run_id, "synthesize_compact", prompt,
                {"max_tokens": 2000, "temperature": 0.0})
        if scope_expression_audit and scope_compaction_enabled(record):
            parsed, scope_expression_audit = compact_scope(parsed, scope_expression_audit, question,
                compact_invoke, _safe_parse_json, output_kind=output_kind, evidence=evidence,
                presentation_version=record.get('reportPresentationContractVersion',0))
        else:
            parsed = compact_answer(parsed, question, compact_invoke, _safe_parse_json,
                output_kind=output_kind, evidence=evidence,
                preserve_claims=bool(point_constraint and point_constraint['mode'] == 'exact'),
                presentation_version=record.get('reportPresentationContractVersion',0),
                **({'fixed_claim_ids':[a['claimId'] for a in scope_expression_audit]} if scope_expression_audit else {}))
        if parsed is None:
            return {"error_code": "invalid_synthesis_response"}

        from services.deep_research.audience_rewrite import eligible, rewrite_for_beginner, has_time_for_rewrite
        if eligible(record, parsed, output_kind):
            current = repo_update(run_id, lambda r: r, expected_revision=None)
            def checkpoint_audience(value):
                repo_update(run_id, lambda r: {**r, 'state': {**r.get('state', {}),
                    'audienceRewrite': value}}, expected_revision=None)
            parsed = rewrite_for_beginner(parsed, evidence, question,
                lambda prompt, output: llm_invoke(run_id, 'synthesize_audience', prompt,
                    {'max_tokens': output, 'temperature': 0.0}), _safe_parse_json,
                saved_state=current.get('state', {}).get('audienceRewrite'), checkpoint=checkpoint_audience,
                can_start=has_time_for_rewrite(current),
                **({'verification_policy':{
                    'absence_scope_version':current.get('absenceScopeContractVersion',0),
                    'quantity_spelling_version':current.get('quantitySpellingContractVersion',0),
                    'feedback_version':current.get('verificationFeedbackContractVersion',0),
                    'table_references_version':current.get('tableReferencesContractVersion',0)}}
                   if current.get('audienceRewriteContractVersion') in (7,8) else {}),
                **({'contract_version':current['audienceRewriteContractVersion'],'requirement_context':[
                    {key:o[key] for key in ('obligationId','question','completionCriteria','requiredSources') if key in o}
                    for item in current.get('state',{}).get('plan',[]) for o in item.get('obligations',[])]}
                   if current.get('audienceRewriteContractVersion') in (2,3,4,5,6,7,8) else {}))
        
        if output_kind == "experiment_design":
            # Compaction must not hide required settings back in metadata.
            parsed = stamp_budget_contract(parsed, enabled=strict_budget)
            parsed = stamp_hypothesis_contract(parsed, enabled=strict_hypothesis)
            parsed = stamp_protocol_contract(parsed, enabled=strict_protocol)
            parsed = stamp_workflow_contract(parsed, enabled=strict_workflow)
            if compact_experiment_enabled(record) and record['experimentDraftContractVersion']==6:
                from services.deep_research.experiment_representation import normalize_claims
                parsed['claims'],changes=normalize_claims([{**c,'designContractVersion':2}
                    if isinstance(c,dict) else c for c in parsed['claims']])
                experiment_representation_audit.extend({'phase':'post_compaction',**change} for change in changes)
            parsed['claims'] = [materialize_execution_claim({**claim, 'designContractVersion': 2})
                                if isinstance(claim, dict) else claim for claim in parsed['claims']]
            from services.deep_research.answer_constraints import answer_character_count
            if requested_limit and answer_character_count(parsed) > requested_limit:
                return {"error_code": "invalid_synthesis_response"}

        from services.deep_research.plan_resume import enabled as editable_plan
        version = int(brief_state.get('planRevision', 0)) + 1 if editable_plan(record) else 1
        report_version_id = f"report_{run_id}_v{version}"
        
        repo_update(
            run_id,
            lambda r: {
                **r,
                "state": {
                    **(r.get("state") or {}),
                    "reportVersionId": report_version_id,
                    "reportBody": parsed,
                    "synthesisContainer": container_kind,
                    **({'experimentDraftingAudit':experiment_drafting_audit} if experiment_drafting_audit is not None else {}),
                    **({'experimentRepresentationAudit':experiment_representation_audit} if experiment_representation_audit else {}),
                    **({'synthesisScopeExpressionAudit':scope_expression_audit} if scope_expression_enabled(record) and output_kind!='experiment_design' else {}),
                    **({'factualDraftingAudit':drafting_audit,
                        'synthesisPresentationAudit':synthesis_presentation_audit} if scope_enabled(record) else {}),
                },
            },
            expected_revision=None,
        )
        
        return {"report_version_id": report_version_id}
    
    return node


def make_verify_node(
    verify_claims_fn: Callable[[list, list, Callable | None], dict],
    semantic_check_fn: Callable[[list, list], list] | None,
    repo_update: Callable[[str, Callable, dict | None], dict],
    llm_invoke: Callable[..., dict] | None = None,
) -> Callable[[GraphState], dict]:
    """Verify claims against evidence with literal and semantic checks. Semantic uses reserve."""
    
    def node(state: GraphState) -> dict:
        run_id = state.get("run_id", "")
        
        if state.get("error_code"):
            return {}
        record = repo_update(run_id, lambda r: {**r, "stage": "verify"}, expected_revision=None)
        report_body = record.get("state", {}).get("reportBody", {})
        evidence = record.get("state", {}).get("evidence", [])
        
        claims = report_body.get("claims", [])
        
        # Semantic check uses reserve pool (wrapped to pass use_reserve flag)
        def budgeted_semantic(claims_to_check: list, evidence_list: list, *, proposal_context=()) -> list:
            if semantic_check_fn is None:
                return []
            return semantic_check_fn(claims_to_check,evidence_list,
                **({'proposal_context':proposal_context} if proposal_context else {}))
        
        from services.deep_research.final_coverage import audit_final_answer
        from services.deep_research.request_coverage import enabled as request_coverage_enabled
        from services.deep_research.claim_check import enabled as claim_check_enabled
        from services.deep_research.request_dimensions import enabled as dimensions_enabled
        from services.deep_research.comparison_reasoning import enabled as comparison_enabled
        from services.deep_research.factual_scope import enabled as scope_enabled
        from services.deep_research.table_bindings import declared_references_enabled
        from services.deep_research.evidence_priority import priority_enabled
        from services.deep_research.coverage_repair import prepare_coverage_repair, merge_verified_revisions
        from services.deep_research.design_consistency import enforce_design_consistency
        saved = record.get('state', {})
        repair_report = saved.get('repairReport', report_body)
        if saved.get('repairAttempted') and 'initialAnswerCoverage' in saved and 'repairTargets' in saved:
            verification_result = saved['initialVerification']
            answer_coverage = saved['initialAnswerCoverage']
            repair_targets = saved['repairTargets']
        else:
            verification_result = enforce_design_consistency(
                verify_claims_fn(claims, evidence, budgeted_semantic), evidence,
                protocol_required=record.get('protocolContractVersion', 0),
                workflow_required=record.get('workflowContractVersion', 0))
            current = repo_update(run_id, lambda r: r, expected_revision=None)
            answer_coverage = audit_final_answer(run_id, effective_question(record),
                saved.get('plan', []), verification_result.get('accepted', []),
                evidence, llm_invoke, _safe_parse_json, budget=current.get('budget'),
                **({'request_contract':record['requestCoverageContractVersion']} if request_coverage_enabled(record) else {}),
                **({'claim_check':True} if claim_check_enabled(record) else {}),
                **({'diagnostics':True} if type(record.get('coverageDiagnosticsContractVersion')) is int and record['coverageDiagnosticsContractVersion']==1 else {}),
                **({'literal_dimensions':True} if dimensions_enabled(record) else {}))
            if saved.get('outputKind') == 'experiment_design':
                from services.deep_research.design_completion import prepare_design_completion
                repair_report, verification_result = prepare_design_completion(
                    report_body, verification_result, evidence, saved.get('plan', []))
            repair_targets = prepare_coverage_repair(repair_report, verification_result,
                answer_coverage if answer_coverage.get('status') == 'checked' else {'gaps': []})
        if saved.get('repairCompleted') and saved.get('verifiedReport'):
            return {'claim_ids': [c['claimId'] for c in saved['verifiedReport'].get('verifiedClaims', [])]}

        # One bounded repair round may use up to three preflighted batches from
        # the normal pool. Final verification reserve stays protected, and all
        # revised wording passes the same checks again.
        if repair_targets.get("rejected") and llm_invoke and not saved.get('repairVerificationError'):
            repo_update(run_id, lambda r: {**r, "state": {**r.get("state", {}), "repairAttempted": True,
                "initialVerification": verification_result, 'initialAnswerCoverage': answer_coverage,
                'repairTargets': repair_targets, 'repairReport': repair_report}}, expected_revision=None)
            from services.deep_research.repair import repair_rejected
            from services.deep_research.answer_point_intent import enabled as point_intent_enabled, from_drafting_audit
            from services.deep_research.scope_expression import enabled as scope_expression_enabled
            from services.deep_research.table_identity_context import enabled as table_identity_enabled
            from services.deep_research.repair_compaction import enabled as repair_compaction_enabled, compact_repairs
            from services.deep_research.contracts import BudgetExhaustedError, DeepResearchError
            def invoke_repair(prompt, output_limit=None):
                # Admit the rewrite and its independent verification as a pair.
                # Do not spend the final seconds on wording that cannot be checked.
                from datetime import datetime, UTC
                maximum = float(record.get('budget', {}).get('maxWallClockSeconds') or 0)
                started = record.get('startedAt')
                if maximum and started:
                    elapsed = (datetime.now(UTC) - datetime.fromisoformat(started.replace('Z', '+00:00'))).total_seconds()
                    from services.deep_research.factual_repair import protected_seconds
                    repair_ids={r['claimId'] for r in repair_targets.get('rejected',[])}
                    time_targets=[c for c in repair_report.get('claims',[]) if c.get('claimId') in repair_ids]
                    minimum = protected_seconds(record,time_targets)
                    if maximum - elapsed < minimum:
                        repo_update(run_id, lambda r: {**r, 'state': {**r.get('state', {}),
                            'repairStatus': 'skipped_time', 'repairTimeRequiredSeconds': minimum}}, expected_revision=None)
                        raise BudgetExhaustedError('repairTimeSeconds', maximum - minimum, elapsed)
                try:
                    options = {"max_tokens": 3000, "temperature": 0.0}
                    if output_limit is not None:
                        options['_repair_output_limit'] = output_limit
                    from services.deep_research.factual_reasoning import request_options as factual_options
                    options.update(factual_options(record,effective_question(record),
                        record.get('state',{}).get('outputKind')))
                    response = llm_invoke(run_id, "repair_claims", prompt, options)
                except BudgetExhaustedError as exc:
                    repo_update(run_id, lambda r: {**r, "state": {**r.get("state", {}),
                        "repairStatus": "skipped_budget", "repairLimit": exc.details}}, expected_revision=None)
                    raise
                finish = (response.get('finishReason', response.get('finish_reason'))
                          if isinstance(response, dict) else getattr(response, 'finish_reason', None))
                repo_update(run_id, lambda r: {**r, "state": {**r.get("state", {}),
                    "repairStatus": "output_truncated" if finish == 'length' else "response_received"}},
                    expected_revision=None)
                return response
            try:
                revised = saved.get('repairDraft')
                if revised is None:
                    from services.deep_research.repair_budget import repair_prompt_byte_limit
                    current = repo_update(run_id, lambda r: r, expected_revision=None)
                    def checkpoint_repair_batches(batch_state):
                        repo_update(run_id, lambda r: {**r, 'state': {**r.get('state', {}),
                            'repairBatchState': batch_state,
                            **({'repairStatus':'response_invalid','repairResponseError':batch_state['responseError']}
                               if batch_state.get('responseError') else {}),
                            **({'repairBatchStop': batch_state['stop']} if batch_state.get('stop') else {})}}, expected_revision=None)
                    from services.deep_research.factual_repair import enabled as compact_repair_enabled
                    from services.deep_research.repair import factual_redraft_eligible
                    compact_repair=compact_repair_enabled(record) and factual_redraft_eligible(repair_report)
                    from services.deep_research.experiment_repair import enabled as shared_experiment_repair
                    from services.deep_research.experiment_edits import can_edit,OUTPUT_TOKENS as EDIT_OUTPUT_TOKENS
                    edit_repair=(shared_experiment_repair(record)
                        and record['experimentRepairContractVersion'] in (2,3,4,5,6) and can_edit(repair_report))
                    repair_input_options={}
                    if compact_repair:
                        from services.deep_research.repair_budget import repair_batch_output_limit
                        target_count=sum(c.get('claimId') in {r['claimId'] for r in repair_targets.get('rejected',[])}
                                         for c in repair_report.get('claims',[]))
                        repair_input_options['output_tokens']=repair_batch_output_limit(target_count)
                    if edit_repair:
                        repair_input_options['output_tokens']=EDIT_OUTPUT_TOKENS
                        from services.deep_research.repair_budget import experiment_repair_window
                        if experiment_repair_window(record):
                            repair_input_options['input_bytes']=32000
                    from services.deep_research.experiment_evidence import build_context as experiment_evidence_context
                    candidate_context=experiment_evidence_context(record)
                    revised = repair_rejected(repair_report, repair_targets, evidence, effective_question(record),
                        invoke_repair, _safe_parse_json,
                        max_prompt_bytes=repair_prompt_byte_limit(current.get('budget', {}),**repair_input_options),
                        metric_domains=record.get('state', {}).get('metricDomains'),
                        batch_state=saved.get('repairBatchState'), checkpoint=checkpoint_repair_batches,
                        current_budget=lambda: repo_update(run_id, lambda r: r, expected_revision=None).get('budget', {}),
                        invoke_request=invoke_repair,
                        **({'defer_length_filter':True} if repair_compaction_enabled(record) else {}),
                        **({'table_identity_context':True} if table_identity_enabled(record) else {}),
                        **({'claim_check':True} if claim_check_enabled(record) else {}),
                        **({'compact_source_repair':True} if compact_repair else {}),
                        **({'shared_experiment_schema':True} if shared_experiment_repair(record) else {}),
                        **({'experimental_edits':True} if edit_repair else {}),
                        **({'experimental_diagnostics':True} if edit_repair and record['experimentRepairContractVersion'] in (3,4,5,6) else {}),
                        **({'experimental_nested_tables':True} if edit_repair and record['experimentRepairContractVersion'] in (4,5,6) else {}),
                        **({'experimental_representation':True} if edit_repair and record['experimentRepairContractVersion'] in (5,6) else {}),
                        **({'experimental_coverage':True} if edit_repair and record['experimentRepairContractVersion']==6 else {}),
                        **({'scheduling_version':record['experimentRepairPriorityContractVersion']} if edit_repair
                           and type(record.get('experimentRepairPriorityContractVersion')) is int
                           and record['experimentRepairPriorityContractVersion'] in (1,2) else {}),
                        **({'repair_evidence_packet_version':record['experimentRepairInputContractVersion']} if edit_repair
                           and type(record.get('experimentRepairInputContractVersion')) is int
                           and record['experimentRepairInputContractVersion'] in (1,2,3,4,5)
                           and type(record.get('structuredOutputContractVersion')) is int
                           and record['structuredOutputContractVersion'] in (8,9,10,11,12,13,14,15) else {}),
                        **({'configuration_consistency_version':2} if type(record.get('configurationConsistencyContractVersion')) is int
                           and record['configurationConsistencyContractVersion']==2 else {}),
                        **({'citation_presentation_version':record['citationPresentationContractVersion']} if type(record.get('citationPresentationContractVersion')) is int
                           and record['citationPresentationContractVersion'] in (2,3,4) else {}),
                        **({'experiment_evidence_context':candidate_context} if candidate_context is not None else {}),
                        **({'strict_response':True} if type(record.get('repairProgressContractVersion')) is int
                           and record['repairProgressContractVersion']==2 else {}),
                        **({'comparison_reasoning':True} if comparison_enabled(record) else {}),
                        **({'comparison_methodology':True} if type(record.get('comparisonReasoningContractVersion')) is int
                           and record['comparisonReasoningContractVersion']==3 else {}),
                        **({'experimental_intent':record['experimentIntentContractVersion']}
                           if type(record.get('experimentIntentContractVersion')) is int
                           and record['experimentIntentContractVersion'] in (1,2,3) else {}),
                        **({'factual_scope':record['factualScopeContractVersion']} if scope_enabled(record) else {}),
                        **({'answer_intents':from_drafting_audit(
                            record.get('state',{}).get('factualDraftingAudit',{}),repair_report.get('claims',[]))}
                           if point_intent_enabled(record)
                           and saved.get('outputKind')!='experiment_design' else {}),
                        **({'scope_expression':record['scopeExpressionContractVersion']} if scope_expression_enabled(record)
                           and saved.get('outputKind')!='experiment_design' else {}),
                        **({'declared_table_refs':True} if declared_references_enabled(record) else {}),
                        **({'question_priority':True} if priority_enabled(record) else {}),
                        **({'fact_redraft':True,'source_aware_redraft':record['factRedraftContractVersion'] in (2,3),
                            **({'concise_factual':True} if record['factRedraftContractVersion']==3 else {}),
                            'requirement_context':[
                            {key:o[key] for key in (('obligationId','question','completionCriteria','requiredSources')
                                if record['factRedraftContractVersion'] in (2,3) else ('obligationId','question','completionCriteria')) if key in o}
                            for item in record.get('state',{}).get('plan',[]) for o in item.get('obligations',[])]}
                           if type(record.get('factRedraftContractVersion')) is int
                           and record['factRedraftContractVersion'] in (1,2,3) else {}))
                    if repair_compaction_enabled(record):
                        current = repo_update(run_id, lambda r: r, expected_revision=None)
                        def checkpoint_compaction(value):
                            repo_update(run_id, lambda r: {**r, 'state': {**r.get('state', {}),
                                'repairCompaction': value}}, expected_revision=None)
                        def invoke_compaction(prompt):
                            # Same normal pool, tracked request identity and absolute
                            # deadline. Reserve enough time to check the new wording.
                            from datetime import datetime, UTC
                            from services.deep_research.factual_repair import protected_seconds
                            maximum = float(record.get('budget',{}).get('maxWallClockSeconds') or 0)
                            if maximum and record.get('startedAt'):
                                elapsed = (datetime.now(UTC)-datetime.fromisoformat(record['startedAt'].replace('Z','+00:00'))).total_seconds()
                                minimum = protected_seconds(record,revised)
                                if maximum-elapsed < minimum:
                                    raise BudgetExhaustedError('repairTimeSeconds',maximum-minimum,elapsed)
                            if len(prompt.encode('utf8')) > 32000:
                                raise BudgetExhaustedError('repairCompactionPromptBytes',32000,len(prompt.encode('utf8')))
                            return llm_invoke(run_id,'synthesize_compact',prompt,{'max_tokens':2000,'temperature':0.0})
                        revised = compact_repairs(repair_report,revised,repair_targets.get('accepted',[]),
                            current.get('state',{}).get('repairBatchState'),effective_question(record),
                            invoke_compaction,_safe_parse_json,evidence=evidence,output_kind=saved.get('outputKind',''),
                            presentation_version=record.get('reportPresentationContractVersion',0),
                            saved=current.get('state',{}).get('repairCompaction'),checkpoint=checkpoint_compaction)
                    repo_update(run_id, lambda r: {**r, 'state': {**r.get('state', {}),
                        'repairDraft': revised}}, expected_revision=None)
                if revised:
                    def revised_semantic(targets, sources, *, proposal_context=()):
                        from services.deep_research.rejected_design_context import enabled, rejected_context
                        context=list(proposal_context)
                        if enabled(record.get('experimentReviewEnvelopeContractVersion')):
                            # New revisions replace old drafts by identity. Unchanged failed
                            # siblings remain visible but retain their rejection checks.
                            context+=rejected_context(repair_report.get('claims',[]),
                                verification_result.get('rejected',[]),
                                exclude=[c['claimId'] for c in revised],phase='initial_verification')
                        check = getattr(semantic_check_fn, 'check_revisions', None)
                        if check:
                            return check(targets,sources,repair_targets.get('accepted',[]),
                                **({'proposal_context':context} if context else {}))
                        return budgeted_semantic(targets,sources,proposal_context=context)
                    merged = saved.get('repairVerification')
                    if merged is None:
                        from services.deep_research.repair_progress import enabled as progress_required, partition_revisions
                        candidates, unchanged = (partition_revisions(repair_report, verification_result, revised)
                                                 if progress_required(record) else (revised, []))
                        checked = (verify_claims_fn(candidates, evidence, revised_semantic) if candidates
                                   else {'accepted': [], 'rejected': []})
                        checked = {**checked, 'rejected': [*checked.get('rejected', []), *unchanged]}
                        merged = enforce_design_consistency(merge_verified_revisions(verification_result, checked), evidence,
                            protocol_required=record.get('protocolContractVersion', 0),
                            workflow_required=record.get('workflowContractVersion', 0))
                        repo_update(run_id, lambda r: {**r, 'state': {**r.get('state', {}),
                            'repairVerificationChecks': checked,
                            'repairUnchangedRejections': unchanged,
                            'repairVerification': merged}}, expected_revision=None)
                    if merged.get('accepted') != verification_result.get('accepted'):
                        current = repo_update(run_id, lambda r: r, expected_revision=None)
                        answer_coverage = audit_final_answer(run_id, effective_question(record),
                            record.get('state', {}).get('plan', []), merged.get('accepted', []),
                            evidence, llm_invoke, _safe_parse_json, budget=current.get('budget'),
                            **({'request_contract':record['requestCoverageContractVersion']} if request_coverage_enabled(record) else {}),
                            **({'claim_check':True} if claim_check_enabled(record) else {}),
                            **({'diagnostics':True} if type(record.get('coverageDiagnosticsContractVersion')) is int and record['coverageDiagnosticsContractVersion']==1 else {}),
                            **({'literal_dimensions':True} if dimensions_enabled(record) else {}))
                    verification_result = merged
            except BudgetExhaustedError as exc:
                repo_update(run_id, lambda r: {**r, 'state': {**r.get('state', {}),
                    'repairStatus': r.get('state', {}).get('repairStatus') or 'skipped_budget',
                    'repairLimit': exc.details}},
                    expected_revision=None)
            except DeepResearchError as exc:
                # Only a confirmed, received-but-invalid verification response
                # may preserve the previous independently checked answer. A
                # transport/unknown call, revoked scope or programming error
                # must still propagate through normal pause/failure handling.
                if (exc.code != 'invalid_verification_response'
                        or exc.details.get('responseState') != 'received_invalid'):
                    raise
                repo_update(run_id, lambda r: {**r, 'state': {**r.get('state', {}),
                    'repairStatus': 'verification_invalid_response',
                    'repairVerificationError': {'code': exc.code, 'responseState': 'received_invalid'}}},
                    expected_revision=None)
        
        accepted = verification_result.get("accepted", [])
        rejected = verification_result.get("rejected", [])

        # Update report with only verified claims
        verified_report = {
            **report_body,
            "verifiedClaims": accepted,
            "rejectedClaims": rejected,
            "answerCoverage": answer_coverage,
            "verificationSummary": {
                "accepted": len(accepted),
                "rejected": len(rejected),
            },
        }
        
        repo_update(
            run_id,
            lambda r: {
                **r,
                "state": {**(r.get("state") or {}), "verifiedReport": verified_report,
                          'repairCompleted': bool(r.get('state', {}).get('repairAttempted'))},
            },
            expected_revision=None,
        )
        
        return {"claim_ids": [c.get("claimId") for c in accepted]}
    
    return node


def make_publish_node(
    repo_publish: Callable[..., tuple],
    repo_update: Callable[[str, Callable, dict | None], dict],
) -> Callable[[GraphState], dict]:
    """Publish verified report atomically to outbox.
    
    Renders ONLY verified claims or clearly labeled proposals/hypotheses.
    Sections organized by output kind using claim IDs to sections.
    No unchecked model prose in report body. No repeated synthesis model call.
    """
    
    def node(state: GraphState) -> dict:
        run_id = state.get("run_id", "")
        if state.get("error_code"):
            return {}
        report_version_id = state.get("report_version_id") or f"report_{run_id}_v1"
        execution_epoch = state.get("execution_epoch", 0)
        
        record = repo_update(run_id, lambda r: {**r, "stage": "publish"}, expected_revision=None)
        verified_report = record.get("state", {}).get("verifiedReport", {})
        brief_state = record.get("state", {})
        output_kind = brief_state.get("outputKind", "direction_survey")
        
        from services.deep_research.design_consistency import enforce_design_consistency
        checked = enforce_design_consistency({'accepted': verified_report.get('verifiedClaims', []),
                                             'rejected': verified_report.get('rejectedClaims', [])},
                                             brief_state.get('evidence', []),
                                             protocol_required=record.get('protocolContractVersion', 0),
                                             workflow_required=record.get('workflowContractVersion', 0))
        if checked['accepted'] != verified_report.get('verifiedClaims', []):
            # A resumed publish must not trust inconsistent marked definitions
            # or retain a coverage verdict for an answer that has been changed.
            verified_report = {**verified_report, 'verifiedClaims': checked['accepted'],
                'rejectedClaims': checked['rejected'],
                'verificationSummary': {'accepted': len(checked['accepted']), 'rejected': len(checked['rejected'])},
                'answerCoverage': {**verified_report.get('answerCoverage', {}), 'status': 'invalidated_design_contract'}}
            repo_update(run_id, lambda r: {**r, 'state': {**r.get('state', {}),
                        'verifiedReport': verified_report}}, expected_revision=None)
        accepted_claims = verified_report.get("verifiedClaims", [])
        rejected_count = len(verified_report.get("rejectedClaims", []))
        from services.deep_research.final_coverage import remaining_retrieval_gaps
        audit = verified_report.get('answerCoverage', {})
        from services.deep_research.completion_criteria import revalidate_completion_audit
        audit = revalidate_completion_audit(brief_state.get('plan', []), accepted_claims, audit)
        from services.deep_research.display_metadata import revalidate_display_metadata
        audit = revalidate_display_metadata(audit, accepted_claims, brief_state.get('evidence', []))
        if audit != verified_report.get('answerCoverage', {}):
            verified_report = {**verified_report, 'answerCoverage': audit}
            repo_update(run_id, lambda r: {**r, 'state': {**r.get('state', {}),
                        'verifiedReport': verified_report}}, expected_revision=None)
        from services.deep_research.obligation_purpose import nonblocking_research_obligations
        research_notes = nonblocking_research_obligations(brief_state.get('plan', []),
            effective_question(record), accepted_claims, audit.get('verdicts'),
            audit.get('wholeQuestionId'), audit.get('invalidAspectObligations', [])) \
            if audit.get('status') == 'checked' else []
        research_questions = {o.get('obligationId'): o.get('question', '')
                              for item in brief_state.get('plan', []) for o in item.get('obligations', [])}
        research_notes = [{**note, 'question': research_questions.get(note['obligationId'], '')}
                          for note in research_notes]
        gaps = [*remaining_retrieval_gaps(record.get('state', {}).get('gaps', []), audit,
                    accepted_claims, record.get('state', {}).get('evidence', []),
                    plan=brief_state.get('plan', []), question=effective_question(record)),
                *audit.get('gaps', [])]
        
        factual_claims = [claim for claim in accepted_claims if claim.get("kind") in {"reported", "inference"}]
        from services.deep_research.reporting import build_sections, conversation_summary, publication_notices
        presentation_version = record.get('reportPresentationContractVersion',0)
        sections = build_sections(accepted_claims, output_kind, verified_report.get("sections"),
            presentation_version=presentation_version)
        visible_notice, folded_notice = publication_notices(accepted_claims, presentation_version=presentation_version)
        repair_notice = ('补充核验未完成；已保留此前核实的内容。'
                         if brief_state.get('repairStatus') == 'verification_invalid_response' else
                         '修订结果未能解析；已保留此前核实的内容。'
                         if brief_state.get('repairStatus') == 'response_invalid' else '')
        display_fields = {}
        if type(presentation_version) is int and presentation_version == 2:
            from services.deep_research.answer_constraints import requested_character_limit
            display_fields = {'presentationVersion':2, 'characterLimit':requested_character_limit(effective_question(record)),
                              'verificationNotice':folded_notice}
        display_payload = {**display_fields, 'outputKind':output_kind, 'claims':accepted_claims, 'sections':sections,
                           'evidence':record.get('state',{}).get('evidence',[]), 'limitations':visible_notice+repair_notice}
        from services.deep_research.answer_format import publication_format_gaps
        gaps.extend(publication_format_gaps(record, accepted_claims, sections, display_payload=display_payload))
        if output_kind == "experiment_design":
            from services.deep_research.synthesis import OUTPUT_KIND_SECTIONS
            from services.deep_research.experimental_reasoning import DESIGN_ROLE_LABELS, missing_design_roles
            present = {section["title"] for section in sections}
            gaps = [*gaps, *[{"question": f"补齐实验方案：{title}", "missingEvidence": "尚未形成经过检查的方案内容"}
                            for title in OUTPUT_KIND_SECTIONS["experiment_design"] if title not in present]]
            gaps.extend({'question': f'补齐实验方案：{DESIGN_ROLE_LABELS[role]}',
                         'missingEvidence': '这项方案要求尚未通过完整性和逻辑核验', 'designRole': role}
                        for role in missing_design_roles(accepted_claims))
        complete_proposal = output_kind in {"experiment_design", "research_entry"} and bool(evidence := record.get("state", {}).get("evidence", []))
        if not accepted_claims:
            outcome = OUTCOME_INCONCLUSIVE
        elif gaps or (rejected_count and audit.get('status') != 'checked') or (not factual_claims and not complete_proposal):
            outcome = OUTCOME_PARTIAL
        elif accepted_claims:
            outcome = OUTCOME_COMPLETE
        else:
            outcome = OUTCOME_INCONCLUSIVE
        
        # Build sections from verified claims only, organized by output kind
        
        # Build safe summary from accepted claims only
        safe_summary = conversation_summary(accepted_claims, outcome,
            evidence=record.get('state', {}).get('evidence', []), output_kind=output_kind,
            presentation_version=presentation_version)
        
        publication_payload = {
            **display_fields,
            "reportVersionId": report_version_id,
            "outputKind": output_kind,
            "summary": safe_summary,
            "sections": sections,
            "claims": accepted_claims,
            "evidence": evidence if (evidence := record.get("state", {}).get("evidence", [])) else [],
            "limitations": visible_notice + repair_notice,
            "gaps": gaps,
            "researchNotes": research_notes,
            "outcome": outcome,
        }
        
        dedup_key = f"{run_id}:{report_version_id}"
        missing_ids = {gap.get('obligationId') for gap in gaps if isinstance(gap, dict)}
        broad_gap = any(not isinstance(gap, dict) or gap.get('wholeQuestion') for gap in gaps)
        final_plan = [{**item, 'status': 'gap' if broad_gap or any(
            o.get('obligationId') in missing_ids for o in item.get('obligations', [])) else 'completed'}
            for item in brief_state.get('plan', [])]
        
        pub_record, created = repo_publish(
            run_id=run_id,
            dedup_key=dedup_key,
            payload=publication_payload,
            outcome=outcome,
            expected_epoch=execution_epoch,
            report_text=_render_report_markdown(publication_payload),
        )
        
        repo_update(
            run_id,
            lambda r: {
                **r,
                "state": {
                    **(r.get("state") or {}),
                    "publicationId": pub_record.get("publicationId", ""),
                    "reportText": _render_report_markdown(publication_payload),
                    "plan": final_plan,
                },
            },
            expected_revision=None,
        )
        
        return {
            "publication_id": pub_record.get("publicationId", ""),
            "outcome": outcome,
        }
    
    return node


def _build_verified_sections(accepted_claims: list[dict], output_kind: str) -> list[dict]:
    from services.deep_research.reporting import build_sections
    return build_sections(accepted_claims, output_kind)


def _render_report_markdown(payload: dict) -> str:
    from services.deep_research.reporting import render_report
    return render_report(payload)


# ── Conditional Edges ──────────────────────────────────────────────────────────

def route_after_resolve_brief(state: GraphState) -> str:
    if state.get("budget_exhausted"):
        return "publish"
    if state.get("clarification_needed"):
        return "wait_clarification"  # Route to clarification node which calls interrupt()
    if state.get("error_code"):
        return "fail"
    return "plan"


def route_after_extract(state: GraphState) -> str:
    return 'synthesize' if state.get('budget_exhausted') and not state.get('assess_after_extraction_stop') else 'assess'


def route_after_assess(state: GraphState) -> str:
    if state.get('dependency_transition'):
        return 'advance_frontier'
    if state.get('extraction_pending') and state.get('gaps') and not state.get('budget_exhausted'):
        return 'extract'
    stop_reason = state.get("stop_reason", "")
    gaps = state.get("gaps", [])
    requery_count = state.get("requery_count", 0)
    budget_exhausted = state.get("budget_exhausted", False)
    requery_queries = state.get("requery_queries", [])
    
    if state.get("error_code"):
        return "fail"
    if budget_exhausted:
        return "synthesize"
    if stop_reason == "covered" or not gaps:
        return "synthesize"
    if stop_reason in ("max_requery", "too_many_gaps", "no_new_evidence"):
        return "synthesize"
    # Only requery if we have changed queries and haven't exceeded bound
    if requery_count <= state.get("max_requery_rounds", 2) and requery_queries:
        return "acquire"
    return "synthesize"


def route_after_publish(state: GraphState) -> str:
    if state.get("error_code"):
        return "fail"
    return "end"


# ── Graph Builder ──────────────────────────────────────────────────────────────

def build_deep_research_graph(
    *,
    llm_invoke: Callable[..., dict],
    retrieve_fn: Callable[[str, str, int], list],
    read_fn: Callable[[str, str], dict],
    scope_validator: Callable[[str, str], bool],
    make_evidence_fn: Callable[..., dict],
    coverage_gaps_fn: Callable[[list, list, list], list],
    verify_claims_fn: Callable[[list, list, Callable | None], dict],
    semantic_check_fn: Callable[[list, list], list] | None = None,
    repo_update: Callable[[str, Callable, dict | None], dict],
    repo_publish: Callable[[str, str, dict], tuple],
    validate_plan_fn: Callable[[list], list],
    checkpoint_conn: sqlite3.Connection | None = None,
    external_acquire: Callable[[str, list[dict[str, Any]]], list[dict[str, Any]]] | None = None,
    extract_batch_size: int = 1,
) -> Any:
    """Build the compiled LangGraph with persistent checkpoints.
    
    Args:
        llm_invoke: Function(run_id, node_name, prompt, extra_body, use_reserve=False) -> {content, usage}
        retrieve_fn: Tracked retriever function
        read_fn: Tracked reader function  
        scope_validator: Authoritative validator (injected, fail-closed)
        make_evidence_fn: From verification module
        coverage_gaps_fn: From coverage module
        verify_claims_fn: From verification module
        semantic_check_fn: Optional semantic checker (uses reserve pool)
        repo_update: Repository update_run function
        repo_publish: Repository publish_report function
        validate_plan_fn: From coverage module
        checkpoint_conn: Long-lived SQLite connection for checkpoints (required for production)
        external_acquire: Optional AcademicAcquisition callback for external sources
    
    Returns:
        Compiled LangGraph ready for invoke/stream
    """
    if StateGraph is None:
        raise RuntimeError("LangGraph not available - install langgraph package")
    
    workflow = StateGraph(GraphState)
    from services.deep_research.dependencies import scoped_updater, finish_assessment, advance_frontier
    frontier_update = scoped_updater(repo_update)
    def bounded(function):
        def execute(state):
            from services.deep_research.contracts import BudgetExhaustedError
            try:
                return function(state)
            except BudgetExhaustedError:
                return {"budget_exhausted": True, "stop_reason": "budget_exhausted"}
        return execute
    
    # Add nodes
    workflow.add_node("resolve_brief", bounded(make_resolve_brief_node(llm_invoke, repo_update)))
    workflow.add_node("wait_clarification", make_wait_for_clarification_node(repo_update))
    workflow.add_node("plan", bounded(make_plan_node(llm_invoke, repo_update, validate_plan_fn)))
    workflow.add_node("acquire", make_acquire_node(retrieve_fn, scope_validator, frontier_update, external_acquire=external_acquire))
    workflow.add_node("read", make_read_node(read_fn, scope_validator, frontier_update))
    if extract_batch_size > 1:
        from services.deep_research.extraction import make_batched_extract_node
        extractor = make_batched_extract_node(llm_invoke, make_evidence_fn, scope_validator, frontier_update,
                                               batch_size=min(extract_batch_size, 3))
    else:
        extractor = make_extract_node(llm_invoke, make_evidence_fn, scope_validator, frontier_update)
    def bounded_extract(state):
        from services.deep_research.contracts import BudgetExhaustedError
        from services.deep_research.adaptive_assessment import enabled
        try:
            return extractor(state)
        except BudgetExhaustedError:
            record = repo_update(state['run_id'], lambda r: r, expected_revision=None)
            return {'budget_exhausted': True, 'stop_reason': 'budget_exhausted',
                    'assess_after_extraction_stop': enabled(record)}
    workflow.add_node("extract", bounded_extract)
    assessment = make_assess_node(coverage_gaps_fn, frontier_update, llm_invoke=llm_invoke)
    def assess_frontier(state):
        from services.deep_research.extraction_schedule import defer_assessment
        record=frontier_update(state['run_id'],lambda r:r,expected_revision=None)
        output=defer_assessment(state,record,frontier_update)
        if output is None:
            output = assessment(state)
        if state.get('extraction_pending') and output.get('gaps') and not state.get('budget_exhausted'):
            # Examine already-read, unreviewed passages before spending a
            # targeted requery round. No settled passage is dispatched twice.
            output = {**output, 'stop_reason': '', 'requery_queries': [],
                      'requery_count': state.get('requery_count', 0), 'extraction_pending': True}
        return finish_assessment(state, output, repo_update)
    workflow.add_node("assess", assess_frontier)
    workflow.add_node('advance_frontier', lambda state: advance_frontier(state, repo_update))
    workflow.add_edge('advance_frontier', 'acquire')
    workflow.add_node("synthesize", bounded(make_synthesize_node(llm_invoke, repo_update)))
    workflow.add_node("verify", make_verify_node(verify_claims_fn, semantic_check_fn, repo_update, llm_invoke=llm_invoke))
    workflow.add_node("publish", make_publish_node(repo_publish, repo_update))
    
    # Set entry point
    workflow.set_entry_point("resolve_brief")
    
    # Add edges - clarification node calls interrupt() internally
    workflow.add_conditional_edges("resolve_brief", route_after_resolve_brief, {
        "plan": "plan",
        "wait_clarification": "wait_clarification",  # Routes to node that calls interrupt()
        "publish": "publish",
        "fail": END,
    })
    
    # New clarified goals refresh assumptions, metric scope and constraints
    # before planning; old unmarked checkpoints keep their original route.
    workflow.add_conditional_edges("wait_clarification",
        lambda state: 'resolve_brief' if state.get('refresh_brief') else 'plan',
        {'resolve_brief': 'resolve_brief', 'plan': 'plan'})
    
    workflow.add_conditional_edges("plan", lambda state: "fail" if state.get("error_code") else "publish" if state.get("budget_exhausted") else "assess" if state.get('assess_inherited') else "acquire",
                                   {"fail": END, "acquire": "acquire", "assess": "assess", "publish": "publish"})
    workflow.add_edge("acquire", "read")
    workflow.add_edge("read", "extract")
    workflow.add_conditional_edges("extract", route_after_extract,
                                   {"synthesize": "synthesize", "assess": "assess"})
    
    workflow.add_conditional_edges("assess", route_after_assess, {
        'advance_frontier': 'advance_frontier',
        'extract': 'extract',
        "acquire": "acquire",
        "synthesize": "synthesize",
        "fail": END,
    })
    
    workflow.add_edge("synthesize", "verify")
    workflow.add_edge("verify", "publish")
    
    workflow.add_conditional_edges("publish", route_after_publish, {
        "end": END,
        "fail": END,
    })
    
    # Compile with checkpointer - REQUIRED for production
    if checkpoint_conn is not None:
        if SqliteSaver is None:
            raise RuntimeError("SqliteSaver not available")
        checkpointer = SqliteSaver(checkpoint_conn)
        return workflow.compile(checkpointer=checkpointer)
    
    # For testing without persistence
    return workflow.compile()


# ── Helpers ────────────────────────────────────────────────────────────────────

def _safe_parse_json(text: str) -> Any:
    """Parse a complete JSON root, preserving arrays inside Markdown fences."""
    if not text:
        return {}
    
    cleaned = text.strip()
    if cleaned.startswith("```"):
        wrapper = re.fullmatch(r'```(?:json)?\s*([\s\S]*?)\s*```', cleaned, re.I)
        if wrapper is None:
            # A missing Markdown terminator does not truncate a complete JSON
            # value. Parse the ENTIRE remaining body, without legacy substring
            # salvage, punctuation repair, or accepting trailing prose/roots.
            body = re.sub(r'^```(?:json)?\s*', '', cleaned, count=1, flags=re.I)
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return {}
        cleaned = wrapper.group(1).strip()
    
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # Legacy prose wrappers may surround a complete value. The earliest
        # container is the root: never salvage an inner object from a broken
        # array, or return the first verdict instead of the whole array.
        root = re.search(r'[\[{]', cleaned)
        if root:
            end_char = ']' if root.group() == '[' else '}'
            end = cleaned.rfind(end_char)
            if end > root.start():
                try:
                    return json.loads(cleaned[root.start():end+1])
                except json.JSONDecodeError:
                    pass
        
        logger.warning("Failed to parse structured model response (%s bytes)", len(text.encode("utf-8")))
        return {}


def estimate_prompt_tokens(prompt: str) -> int:
    """Conservative token estimation for UTF-8 text.
    
    Chinese characters typically require more tokens than ASCII.
    Uses byte length / 3 as conservative estimate (NOT upper bound).
    This is the actual byte-based calculation, not capped at any maximum.
    """
    byte_length = len(prompt.encode("utf-8"))
    return max(1, byte_length // 3)


def check_deadline(started_at: float, deadline_seconds: float) -> bool:
    """Check if deadline has been exceeded. Returns True if still within deadline."""
    if deadline_seconds <= 0:
        return True
    elapsed = time.monotonic() - started_at
    return elapsed < deadline_seconds


def remaining_seconds(started_at: float, deadline_seconds: float) -> float:
    """Get remaining seconds until deadline. Returns 0 if exceeded."""
    if deadline_seconds <= 0:
        return float("inf")
    elapsed = time.monotonic() - started_at
    remaining = deadline_seconds - elapsed
    return max(0.0, remaining)
