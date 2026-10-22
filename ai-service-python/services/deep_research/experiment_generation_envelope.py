"""Compact framing and actual-plan evidence allocation, without lost requirements."""
from copy import deepcopy
import json

from services.deep_research.contracts import DeepResearchError,digest
from services.deep_research.experiment_outline_encoding import encode
from services.deep_research.synthesis_evidence import fit_premises


def enabled(record):
    return all(type(record.get(key)) is int and record[key]==version for key,version in (
        ('experimentGenerationEnvelopeContractVersion',1),('experimentDraftContractVersion',6),
        ('configurationConsistencyContractVersion',2),('experimentOutlineEncodingContractVersion',2)))


def draft_prompt(*,question,limit,clarification,gaps,obligations,sources,evidence_marker,
                 claim_fields,claim_limit,section_templates,concise=True):
    packed=lambda value:json.dumps(value,ensure_ascii=False,separators=(',',':'))
    return f'''Design an executable UNEXECUTED experiment; preserve the complete requested scope.
Question: {question}
Total text/conditions character limit: {limit or 'concise; no explicit maximum'}
User clarification: {clarification}
Gaps: {packed(gaps)}
Frozen requirements (goals, not evidence): {packed(obligations)}
Source registry (identity metadata, not evidence): {packed(sources)}
Evidence summaries:
{evidence_marker}
Return ONLY {{"sections":[],"claims":[]}}. Sections use title/claimIds from {packed(section_templates)}.
Maximum {claim_limit} claims; include EVERY required role and complete executionSpec.
Each claim uses {claim_fields}.
Requested paper facts need separate supported reported/inference claims. EACH paper-method,
dataset/member/count/asset fact needs its OWN supplied E evidence; choices need no author
attribution. Abstract facts stay abstract-level; table measurements need exact tableBindings.
No invented facts/results/novelty, relabeled facts, global absence or E/P IDs/hashes in prose.
Write concise Chinese rationale/conditions once; typed settings are rendered. Keep all roles
consistent and explicit evidence gaps bounded. Full role grammar and scientific rules follow.'''


def refit(record,rows,render,bundles,plan,*,required_contexts=None,max_bytes=None):
    """Reallocate only within evidence actually supplied to the planning request.

    Required source bundles AND every unverified-plan reference remain atomic.
    They are input dependencies, not factual approval or citation permission.
    On overflow return the complete required request for the unchanged final
    capacity guard, never the conveniently smaller incomplete selection.
    """
    if not enabled(record):raise DeepResearchError('invalid_experiment_generation_state','实验生成契约不匹配。')
    from services.deep_research.experiment_capacity import input_limit
    max_bytes=input_limit(record) if max_bytes is None else min(max_bytes,input_limit(record))
    by_id={r['evidenceId']:r for r in rows}
    refs=plan['basis']['sourceRefs']
    needed={eid for bundle in bundles for eid in bundle['evidenceIds']}|set(refs)
    if len(by_id)!=len(rows) or not needed<=by_id.keys():
        raise DeepResearchError('invalid_experiment_generation_state','生成所需原文不在原规划材料中，不能发送。')
    required=[row['evidenceId'] for row in rows if row['evidenceId'] in needed]
    atomic=[{'obligationId':'complete_unverified_generation_inputs','evidenceIds':required}]
    measure=lambda value:len(encode(record,value)[0].encode('utf8'))
    prompt,selected,missing=fit_premises(rows,render,atomic,max_bytes=max_bytes,
        required_contexts=required_contexts,prompt_byte_size=measure)
    if missing:
        # Preserve the full failed input and let prepare_draft freeze/refuse it.
        selected=[deepcopy(row) for row in rows if row['evidenceId'] in needed]
        prompt=render(selected)
        if measure(prompt)<=max_bytes:
            raise DeepResearchError('invalid_experiment_generation_state','必需前提分配不一致，不能发送。')
    if not needed<={row['evidenceId'] for row in selected}:
        raise DeepResearchError('invalid_experiment_generation_state','生成输入遗漏必需前提，不能发送。')
    audit={'version':1,'planningEvidenceAliases':[r['evidenceId'] for r in rows],
        'suppliedEvidenceAliases':[r['evidenceId'] for r in selected],
        'requiredEvidenceAliases':required,'unverifiedPlanReferences':list(refs),
        'missingPremiseBundles':missing,'rawInputBytes':len(prompt.encode('utf8')),
        'encodedInputBytes':measure(prompt),'maxInputBytes':max_bytes,
        'planBasisDigest':digest(plan['basis']),'planReferencesAreEvidenceApproval':False}
    return prompt,selected,audit
