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


def validate_basis(value,allowed,*,max_bytes=MAX_BASIS_BYTES,lean=False,blueprint=False):
    """Structure/citation permissions only; never a scientific approval."""
    expected={'sourceRefs','protocol','unresolved'} if lean else {'sourceFacts','protocol','unresolved'}
    if not isinstance(value,dict) or set(value)!=expected:
        return False
    facts,protocol,unresolved=value.get('sourceFacts',[]),value['protocol'],value['unresolved']
    if not isinstance(facts,list) or len(facts)>12 or not isinstance(protocol,dict) or set(protocol)!=PROTOCOL_KEYS:
        return False
    if blueprint is True:
        from services.deep_research.experiment_blueprint import valid_state,valid_budget
        if (not lean or any(not isinstance(protocol[k],str) or not protocol[k].strip()
                for k in PROTOCOL_KEYS-{'state','pairingBudget'})
                or not valid_state(protocol['state']) or not valid_budget(protocol['pairingBudget'])):
            return False
    elif any(not isinstance(v,str) or not v.strip() for v in protocol.values()):
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
        size=len(json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode())
        return max_bytes is None or size<=max_bytes
    except (ValueError,TypeError):
        return False


def planning_prompt(*,question,obligations,sources,evidence,tables,metric_domains,compact=False,lean=False,positional=False,configuration_consistency_version=0,input_contract_version=0,execution_guidance_version=0,blueprint=False):
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
    if positional is True and lean:
        prompt=prompt.replace('The ENTIRE compact JSON must fit2500UTF-8 bytes. Use concise English and approximately200bytes',
            'Aim below2500UTF-8 bytes for the complete object. Use concise English and approximately200bytes')
        prompt+='\nAll values are sent losslessly in a2500-byte tuple; stay concise. Do not omit any decision or gap.\n'
        if type(input_contract_version) is int and input_contract_version==1:
            prompt=prompt.replace('All values are sent losslessly in a2500-byte tuple;',
                'The complete raw JSON and its lossless tuple must each fit4000 UTF-8 bytes;')
    if blueprint is True:
        if not (compact is True and lean is True and positional is True):
            raise ValueError('Execution blueprint requires staged compact planning')
        from services.deep_research.experiment_blueprint import PLANNING
        prompt=PLANNING+SPLIT_GUIDANCE+'\n'+REFERENCE_RULE+'\n'
    prompt+='\nHuman question:\n'+question+'\nFrozen requirements:\n'+packed(obligations)
    prompt+='\nSource registry (metadata only):\n'+packed(sources)
    prompt+='\nExact original evidence with unchanged permissions:\n'+packed(evidence)
    prompt+='\nShared table packets (own tableDataRef only):\n'+packed(tables)
    prompt+='\n'+_DRAFT_POLICY+'\n'+guidance(question,draft=True,policy_version=3)
    prompt+='\nMetric protocols:\n'+packed(metric_protocol_requirements(metric_domains))
    if not (two_arm_request(question) if compact else single_toggle_request(question)):
        prompt+='\n'+_DRAFT_STATISTICS
    from services.deep_research.configuration_consistency import modern,PLANNING2
    if modern(configuration_consistency_version):prompt+='\n'+PLANNING2
    from services.deep_research.experiment_execution_guidance import enabled as execution_guidance,PLANNING
    if execution_guidance({'experimentExecutionGuidanceContractVersion':execution_guidance_version}):
        prompt+='\n'+PLANNING
    return prompt


def request_identity(record,node,prompt,options):
    """Freeze the same role options/framing that the tracked invoker reserves."""
    from services.deep_research.runtime import research_model_options
    from services.deep_research.structured_output import enabled as native_json,messages_for_record
    options=research_model_options(node,options)
    identity={'prompt':prompt,'extra':options}
    if native_json(record):
        options={**options,'response_format':{'type':'json_object'}};identity['extra']=options
        identity['messages']=messages_for_record(record,node,prompt)
    return identity


def valid_plan_basis(record,value,aliases):
    from services.deep_research.experiment_plan_encoding import enabled as plan_encoding,wire_text,flexible
    if plan_encoding(record):
        from services.deep_research.experiment_blueprint import enabled as blueprint_enabled
        if not validate_basis(value,aliases,max_bytes=MAX_BASIS_BYTES,lean=True,blueprint=blueprint_enabled(record)):return False
        try:return len(wire_text(value,version=record['experimentPlanEncodingContractVersion']).encode('utf8'))<=(MAX_BASIS_BYTES if flexible(record) else basis_limit(record))
        except (TypeError,ValueError,OverflowError):return False
    return validate_basis(value,aliases,max_bytes=basis_limit(record),lean=record.get('experimentDraftContractVersion') in (5,6))


def basis_encoding_audit(record,basis):
    from services.deep_research.experiment_plan_encoding import wire_text,flexible
    raw=len(json.dumps(basis,ensure_ascii=False,separators=(',',':')).encode('utf8'))
    wire=len(wire_text(basis,version=record['experimentPlanEncodingContractVersion']).encode('utf8'))
    if flexible(record):
        return {'rawBytes':raw,'wireBytes':wire,'preferredSlotBytes':basis_limit(record),
            'rawLimitBytes':MAX_BASIS_BYTES,'fitsPreferredSlot':wire<=basis_limit(record),'scientificApproval':False}
    return {'rawBytes':raw,'wireBytes':wire,'slotLimit':basis_limit(record),'scientificApproval':False}


def prepare_plan(record,*,prompt,aliases,invoke,parse,checkpoint):
    """Return a received plan or None for known pre-send budget refusal."""
    from services.deep_research.experiment_capacity import input_limit,enabled as capacity_enabled
    if len(prompt.encode())>input_limit(record):
        raise DeepResearchError('experiment_planning_input_capacity','实验科学规划输入超过原有容量，尚未发送。')
    from services.deep_research.experiment_envelope import enabled as compact_enabled,DIRECT_PLAN_OPTION
    request=request_identity(record,'plan_experiment',prompt,{'max_tokens':PLANNING_OUTPUT_TOKENS,'temperature':0.0,
        **({DIRECT_PLAN_OPTION:True} if compact_enabled(record) else {})})
    from services.deep_research.experiment_plan_encoding import enabled as plan_encoding,encode,wire_text,flexible
    encoding=plan_encoding(record)
    encoding_version=record['experimentPlanEncodingContractVersion'] if encoding else 0
    from services.deep_research.experiment_blueprint import enabled as blueprint_enabled
    blueprint=blueprint_enabled(record)
    from services.deep_research.experiment_outline_encoding import enabled as outline_encoding
    outlined=outline_encoding(record)
    from services.deep_research.experiment_generation_envelope import enabled as generation_envelope
    identity=digest({'version':1,'request':request,'evidenceAliases':aliases,
        **({'basisEncodingVersion':encoding_version} if encoding else {}),
        **({'outlineEncodingVersion':record['experimentOutlineEncodingContractVersion']} if outlined else {}),
        **({'generationEnvelopeVersion':1} if generation_envelope(record) else {}),
        **({'experimentInputVersion':1} if capacity_enabled(record) else {})})
    saved=deepcopy(record.get('state',{}).get('experimentPlanning'))
    if saved is not None:
        if (not isinstance(saved,dict) or type(saved.get('version')) is not int or saved['version']!=1
                or saved.get('inputDigest')!=identity or saved.get('request')!=request
                or saved.get('evidenceAliases')!=aliases
                or encoding and (type(saved.get('basisEncodingVersion')) is not int or saved['basisEncodingVersion']!=encoding_version)):
            raise DeepResearchError('invalid_experiment_planning_state','保存的实验规划与原输入不一致，不能重新发送。')
        if saved.get('status')=='ready':
            if (not valid_plan_basis(record,saved.get('basis'),aliases)
                    or digest(saved.get('response'))!=saved.get('responseDigest')
                    or not isinstance(saved.get('response'),dict)
                    or parsed_basis(saved['response'],parse)!=saved['basis']):
                raise DeepResearchError('invalid_experiment_planning_state','保存的实验规划记录无效，不能重新发送。')
            if encoding and (type(saved.get('basisEncodingVersion')) is not int or saved['basisEncodingVersion']!=encoding_version
                    or saved.get('encodedBasis')!=encode(saved['basis'],version=encoding_version)
                    or saved.get('encodedBasisDigest')!=digest(saved['encodedBasis'])
                    or digest(saved.get('basisEncodingAudit'))!=digest(basis_encoding_audit(record,saved['basis']))):
                raise DeepResearchError('invalid_experiment_planning_state','保存的规划编码已改变，不能重新发送。')
            return saved
        if saved.get('status')=='invalid_response':
            raise DeepResearchError('invalid_experiment_planning_response','实验规划已返回但未形成完整结构，原响应已保留。')
        if saved.get('status')=='output_capacity':
            if (not flexible(record) or digest(saved.get('response'))!=saved.get('responseDigest')
                    or parsed_basis(saved.get('response'),parse)!=saved.get('basis')
                    or not validate_basis(saved.get('basis'),aliases,max_bytes=None,lean=True,blueprint=blueprint)
                    or valid_plan_basis(record,saved.get('basis'),aliases)
                    or digest(saved.get('basisEncodingAudit'))!=digest(basis_encoding_audit(record,saved['basis']))):
                raise DeepResearchError('invalid_experiment_planning_state','保存的规划容量记录已改变，不能重新发送。')
            raise DeepResearchError('experiment_planning_output_capacity','规划草稿超出当前容量，原稿已保留，尚未生成完整方案。')
        if saved.get('status')=='not_started_budget':
            return None
        if saved.get('status') not in {'pending','response_received'}:
            raise DeepResearchError('invalid_experiment_planning_state','保存的实验规划状态无效，不能重新发送。')
    else:
        saved={'version':1,'inputDigest':identity,'request':request,'evidenceAliases':deepcopy(aliases),
               'verification':'unchecked','status':'pending',**({'basisEncodingVersion':encoding_version} if encoding else {}),
               **({'experimentInputVersion':1} if capacity_enabled(record) else {})}
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
    if (flexible(record) and isinstance(response,dict)
            and response.get('finishReason',response.get('finish_reason'))!='length'
            and validate_basis(basis,aliases,max_bytes=None,lean=True,blueprint=blueprint)
            and not valid_plan_basis(record,basis,aliases)):
        saved.update(status='output_capacity',basis=basis,basisEncodingAudit=basis_encoding_audit(record,basis))
        checkpoint(saved)
        raise DeepResearchError('experiment_planning_output_capacity','规划草稿超出当前容量，原稿已保留，尚未生成完整方案。')
    if (not isinstance(response,dict) or response.get('finishReason',response.get('finish_reason'))=='length'
            or not valid_plan_basis(record,basis,aliases)):
        saved['status']='invalid_response';checkpoint(saved)
        raise DeepResearchError('invalid_experiment_planning_response','实验科学规划未完整返回或引用无效，原响应已保留。')
    if encoding:
        saved.update(encodedBasis=encode(basis,version=encoding_version),encodedBasisDigest=digest(encode(basis,version=encoding_version)),
            basisEncodingAudit=basis_encoding_audit(record,basis))
    saved.update(status='ready',basis=basis);checkpoint(saved)
    return saved


def parsed_basis(response,parse):
    try:
        return parse(response.get('content','')) if isinstance(response,dict) else None
    except (ValueError,TypeError,RecursionError):
        return None


def prepare_draft(record,plan,*,prompt,checkpoint,outline_encoding_audit=None):
    """Freeze the direct body request; resume through the ordinary ledger guard.

    Admission applies only to a new request. An already prepared request must
    reach the ledger even when late, to reuse a settled result or reject unknown.
    """
    from services.deep_research.experiment_plan_encoding import enabled as plan_encoding,flexible
    from services.deep_research.experiment_outline_encoding import enabled as outline_encoding,validate
    from services.deep_research.experiment_capacity import input_limit,enabled as capacity_enabled
    if ((capacity_enabled(record) and type(plan.get('experimentInputVersion')) is not int)
            or plan.get('experimentInputVersion',0)!=(1 if capacity_enabled(record) else 0)):
        raise DeepResearchError('invalid_experiment_planning_state','保存的实验输入窗口已改变，不能重新发送。')
    validate(record,prompt,outline_encoding_audit)
    if outline_encoding(record):
        if (plan.get('outlineEncodingAudit') is not None
                and plan['outlineEncodingAudit']!=outline_encoding_audit):
            raise DeepResearchError('invalid_experiment_outline_state','保存的实验输出目录已经改变，不能重新发送。')
        plan={**plan,'outlineEncodingAudit':deepcopy(outline_encoding_audit)}
    capacity_request=request_identity(record,'synthesize',prompt,{'max_tokens':4000,'temperature':0.2}) if flexible(record) else None
    if flexible(record) and plan.get('draftStatus')=='not_started_capacity':
        if plan.get('draftCapacity',{}).get('requestDigest')!=digest(capacity_request):
            raise DeepResearchError('invalid_experiment_planning_state','保存的配置容量请求已改变，不能重新发送。')
        raise DeepResearchError('experiment_drafting_input_capacity','实验配置输入超过原有容量，尚未发送。')
    if plan_encoding(record) and len(prompt.encode('utf8'))>input_limit(record):
        if flexible(record):
            checkpoint({**plan,'draftStatus':'not_started_capacity','draftCapacity':{
                'inputBytes':len(prompt.encode('utf8')),'maxInputBytes':input_limit(record),
                'requestDigest':digest(capacity_request),'scientificApproval':False}})
        raise DeepResearchError('experiment_drafting_input_capacity','实验配置输入超过原有容量，尚未发送。')
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
