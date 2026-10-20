"""Persist a small, unverified scientific plan before full configuration drafting.

Both requests use the ordinary tracked invoker and the same run budget. A
received-invalid or unknown response never creates a hidden retry/fallback.
"""
from copy import deepcopy
from datetime import datetime, UTC
import json

from services.deep_research.contracts import DeepResearchError, digest

MAX_BASIS_BYTES=4000
PLANNING_OUTPUT_TOKENS=6144
PROTOCOL_KEYS={'intervention','data','state','poseError','measurement','pairingBudget'}
SPLIT_GUIDANCE=('For multiview temporal data, frame indices choose a time window; camera/view IDs choose '
    'training vs held-out evaluation views. Holding out every fifth FRAME does not create a held-out CAMERA. '
    'Declare these axes separately and validate nonempty/disjoint camera sets. Choose a window with the '
    'requested phenomenon using training observations only, before fitting or comparison; a scene name '
    'does not prove that every chosen frame contains the phenomenon. Predeclare the training-only selection '
    'rule and reject/record an ineligible window without using final evaluation views or scores. '
    'Within-frame optimization iterations/epochs are not video-frame intervals; preserve the actual '
    'method schedule and shared-state transfer. Proposed changes must be explicit and retain the requested technique.')


def enabled(record):
    from services.deep_research.experiment_template import enabled as template_enabled
    return template_enabled(record) and record['experimentDraftContractVersion'] in (3,4,5,6)


def basis_limit(record):
    from services.deep_research.experiment_envelope import enabled as compact_enabled,BASIS_BYTES
    return BASIS_BYTES if compact_enabled(record) else MAX_BASIS_BYTES


def remaining_seconds(record,now=None):
    budget=record.get('budget',{})
    elapsed=float(budget.get('elapsedSeconds') or 0)
    if record.get('startedAt'):
        elapsed=max(elapsed,((now or datetime.now(UTC))-datetime.fromisoformat(
            record['startedAt'].replace('Z','+00:00'))).total_seconds())
    return max(0,float(budget.get('maxWallClockSeconds',360))-max(0,elapsed))


def validate_basis(value,allowed,*,max_bytes=MAX_BASIS_BYTES,lean=False):
    """Structure/citation permissions only; never a scientific approval."""
    expected={'sourceRefs','protocol','unresolved'} if lean else {'sourceFacts','protocol','unresolved'}
    if not isinstance(value,dict) or set(value)!=expected:
        return False
    facts,protocol,unresolved=value.get('sourceFacts',[]),value['protocol'],value['unresolved']
    if not isinstance(facts,list) or len(facts)>12 or not isinstance(protocol,dict) or set(protocol)!=PROTOCOL_KEYS:
        return False
    if any(not isinstance(v,str) or not v.strip() for v in protocol.values()):
        return False
    if (not isinstance(unresolved,list) or len(unresolved)>8
            or any(not isinstance(v,str) or not v.strip() for v in unresolved)):
        return False
    if lean:
        refs=value['sourceRefs']
        if (not isinstance(refs,list) or len(refs)>20 or any(not isinstance(ref,str) or ref not in allowed for ref in refs)
                or len(refs)!=len(set(refs))):
            return False
    for fact in facts:
        if (not isinstance(fact,dict) or set(fact)!={'topic','evidenceRefs','scope'}
                or any(not isinstance(fact[k],str) or not fact[k].strip() for k in ('topic','scope'))):
            return False
        refs=fact['evidenceRefs']
        if (not isinstance(refs,list) or not refs or any(not isinstance(ref,str) or ref not in allowed for ref in refs)
                or len(refs)!=len(set(refs))):
            return False
    try:
        return len(json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode())<=max_bytes
    except (ValueError,TypeError):
        return False


def planning_prompt(*,question,obligations,sources,evidence,tables,metric_domains,compact=False,lean=False):
    from services.deep_research.design_drafting import _DRAFT_POLICY,_DRAFT_STATISTICS
    from services.deep_research.experiment_intent import guidance,single_toggle_request
    from services.deep_research.metric_scope import metric_protocol_requirements
    packed=lambda value:json.dumps(value,ensure_ascii=False,separators=(',',':'))
    from services.deep_research.experiment_envelope import compact_obligations,REFERENCE_RULE,two_arm_request,BASIS_BYTES
    if compact:obligations=compact_obligations(obligations,question,sources)
    prompt='''Plan the scientific logic of an UNEXECUTED experiment, before typing its full configuration.
Do not emit executionSpec arrays or a final report. Return exactly:
{"sourceFacts":[{"topic":"actual source fact","evidenceRefs":["own supplied E ID"],"scope":"bounded fact"}],
"protocol":{"intervention":"actual equation/insertion point; control vs treatment",
"data":"exact evidenced dataset/member and proposed split",
"state":"complete representation/network layout and reproducible common initialization",
"poseError":"concrete requested perturbation or explicitly not applicable",
"measurement":"executable observation/reference, aggregation, real-motion handling and quality guard",
"pairingBudget":"paired units, finite preparation and whole-group budgets, decision scope"},
"unresolved":["specific evidence gap, only when present"]}.
The ENTIRE compact JSON must fit4000UTF-8 bytes. Prefer concise English for this private plan;
the final report will be Chinese. Choose concrete proposed values now. No opaque weights blob,
unnamed renderer, raw-motion-magnitude jitter proxy or imagined GT at unseen times.
List paper facts only with supplied E refs; preserve actual operations/versions. A proposed
parameter need not match an author's choice, but do not relabel a source fact as a proposal.
No fact/source permission is granted by this plan; every final attributed claim still needs
its OWN original evidenceRefs. Questions/metadata/other model plans are not source evidence.
Do not claim results, novelty, validation or that authors omitted unselected facts.
'''
    if lean:
        prompt='''Plan the scientific logic of an UNEXECUTED experiment before its full configuration.
Return exactly {"sourceRefs":["own supplied E IDs used for these decisions"],
"protocol":{"intervention":"actual operation and control/treatment difference",
"data":"evidenced member, temporal window and separate held-out units, training-only eligibility rule",
"state":"actual shared module/representation and reproducible common-state initialization",
"poseError":"requested perturbation or explicitly not applicable",
"measurement":"paired observables, references and aggregation",
"pairingBudget":"finite shared preparation, honest whole-group cost and bounded decision"},
"unresolved":["specific remaining evidence gap"]}.
The ENTIRE compact JSON must fit2500UTF-8 bytes. Use concise English and approximately200bytes
per protocol field. State decisions once. Do NOT repeat source quotations or paper-fact summaries:
the NEXT full-configuration request receives the SAME original evidence and source permissions.
sourceRefs is only an index into supplied evidence, not a factual claim or verification.
Keep all six protocol decisions concrete and mutually consistent; detailed state arrays and complete
executionSpec definitions belong in the next request. Mark proposed values as unexecuted choices.
Preserve the actual required learned modules and operations; do not substitute a convenient rigid
transform or guess a dataset member. Put exact remaining gaps in unresolved. A whole-stage/package
comparison may add optimization: record finite unmatched cost, not an isolated parameter effect.
No fact/source permission is granted by this plan. Every final attributed claim still requires
its OWN original E refs. Do not claim results, novelty, validation or global absence of source facts.
'''+SPLIT_GUIDANCE+'\n'+REFERENCE_RULE+'\n'
    elif compact:
        prompt=prompt.replace('fit4000UTF-8',f'fit{BASIS_BYTES}UTF-8')
        prompt+='''
Keep this a short scientific blueprint: at most6source facts, short protocol choices;
detailed state arrays and complete configurations belong in the NEXT request. Preserve
the actual required learned modules and operations. Never substitute a convenient rigid
transform, different loss or guessed member for an unsupported method/data fact; record
that exact gap in unresolved instead. A compound stage/package can add optimization:
record its finite unmatched cost honestly, without claiming an isolated parameter effect.
'''+REFERENCE_RULE+'\n'
    prompt+='\nHuman question:\n'+question+'\nFrozen requirements:\n'+packed(obligations)
    prompt+='\nSource registry (metadata only):\n'+packed(sources)
    prompt+='\nExact original evidence with unchanged permissions:\n'+packed(evidence)
    prompt+='\nShared table packets (own tableDataRef only):\n'+packed(tables)
    prompt+='\n'+_DRAFT_POLICY+'\n'+guidance(question,draft=True,policy_version=3)
    prompt+='\nMetric protocols:\n'+packed(metric_protocol_requirements(metric_domains))
    if not (two_arm_request(question) if compact else single_toggle_request(question)):
        prompt+='\n'+_DRAFT_STATISTICS
    return prompt


def request_identity(record,node,prompt,options):
    """Freeze the same role options/framing that the tracked invoker reserves."""
    from services.deep_research.runtime import research_model_options
    from services.deep_research.structured_output import enabled as native_json,messages
    options=research_model_options(node,options)
    identity={'prompt':prompt,'extra':options}
    if native_json(record):
        options={**options,'response_format':{'type':'json_object'}};identity['extra']=options
        identity['messages']=messages(node,prompt,record['structuredOutputContractVersion'])
    return identity


def prepare_plan(record,*,prompt,aliases,invoke,parse,checkpoint):
    """Return a received plan or None for known pre-send budget refusal."""
    if len(prompt.encode())>24000:
        raise DeepResearchError('experiment_planning_input_capacity','实验科学规划输入超过原有容量，尚未发送。')
    from services.deep_research.experiment_envelope import enabled as compact_enabled,DIRECT_PLAN_OPTION
    request=request_identity(record,'plan_experiment',prompt,{'max_tokens':PLANNING_OUTPUT_TOKENS,'temperature':0.0,
        **({DIRECT_PLAN_OPTION:True} if compact_enabled(record) else {})})
    identity=digest({'version':1,'request':request,'evidenceAliases':aliases})
    saved=deepcopy(record.get('state',{}).get('experimentPlanning'))
    if saved is not None:
        if (not isinstance(saved,dict) or type(saved.get('version')) is not int or saved['version']!=1
                or saved.get('inputDigest')!=identity or saved.get('request')!=request
                or saved.get('evidenceAliases')!=aliases):
            raise DeepResearchError('invalid_experiment_planning_state','保存的实验规划与原输入不一致，不能重新发送。')
        if saved.get('status')=='ready':
            if (not validate_basis(saved.get('basis'),aliases,max_bytes=basis_limit(record),lean=record.get('experimentDraftContractVersion') in (5,6))
                    or digest(saved.get('response'))!=saved.get('responseDigest')
                    or not isinstance(saved.get('response'),dict)
                    or parsed_basis(saved['response'],parse)!=saved['basis']):
                raise DeepResearchError('invalid_experiment_planning_state','保存的实验规划记录无效，不能重新发送。')
            return saved
        if saved.get('status')=='invalid_response':
            raise DeepResearchError('invalid_experiment_planning_response','实验规划已返回但未形成完整结构，原响应已保留。')
        if saved.get('status')=='not_started_budget':
            return None
        if saved.get('status') not in {'pending','response_received'}:
            raise DeepResearchError('invalid_experiment_planning_state','保存的实验规划状态无效，不能重新发送。')
    else:
        saved={'version':1,'inputDigest':identity,'request':request,'evidenceAliases':deepcopy(aliases),
               'verification':'unchecked','status':'pending'}
        if remaining_seconds(record)<150:
            saved['status']='not_started_budget';checkpoint(saved);return None
        checkpoint(saved)
    if saved['status']=='pending':
        response=invoke('plan_experiment',request['prompt'],request['extra'])
        # Exceptions/unknowns propagate with the prepared request still pending;
        # the ordinary ledger blocks another physical send for that identity.
        saved.update(status='response_received',response=deepcopy(response),responseDigest=digest(response));checkpoint(saved)
    response=saved.get('response')
    if digest(response)!=saved.get('responseDigest'):
        raise DeepResearchError('invalid_experiment_planning_state','保存的实验规划响应已改变，不能重新发送。')
    basis=parsed_basis(response,parse)
    if (not isinstance(response,dict) or response.get('finishReason',response.get('finish_reason'))=='length'
            or not validate_basis(basis,aliases,max_bytes=basis_limit(record),lean=record.get('experimentDraftContractVersion') in (5,6))):
        saved['status']='invalid_response';checkpoint(saved)
        raise DeepResearchError('invalid_experiment_planning_response','实验科学规划未完整返回或引用无效，原响应已保留。')
    saved.update(status='ready',basis=basis);checkpoint(saved)
    return saved


def parsed_basis(response,parse):
    try:
        return parse(response.get('content','')) if isinstance(response,dict) else None
    except (ValueError,TypeError,RecursionError):
        return None


def prepare_draft(record,plan,*,prompt,checkpoint):
    """Freeze the direct body request; resume through the ordinary ledger guard.

    Admission applies only to a new request. An already prepared request must
    reach the ledger even when late, to reuse a settled result or reject unknown.
    """
    request=request_identity(record,'synthesize',prompt,{'max_tokens':4000,'temperature':0.2})
    if plan.get('draftRequest') is not None:
        if plan['draftRequest']!=request:
            raise DeepResearchError('invalid_experiment_planning_state','保存的实验配置请求与原输入不一致，不能重新发送。')
        return request
    if plan.get('draftStatus')=='not_started_budget' or remaining_seconds(record)<90:
        checkpoint({**plan,'draftStatus':'not_started_budget'})
        return None
    checkpoint({**plan,'draftStatus':'prepared','draftRequest':request})
    return request
