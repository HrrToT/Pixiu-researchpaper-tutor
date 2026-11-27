"""Checkpoint source-local drafts without publishing or approving them.

New comparison planning version6 selects this module. The tracked invoker remains
the authority for request identity, material permission and atomic budget usage.
"""
from copy import deepcopy
import json

from services.deep_research.contracts import BudgetExhaustedError, DeepResearchError, digest
from services.deep_research.experiment_planning import remaining_seconds
from services.deep_research.factual_reasoning import request_options
from services.deep_research.request_context import effective_question
from services.deep_research.comparison_measurement_display import explicit_stage_schema
from services.deep_research.comparison_wire import COMPARISON_POINT_KINDS, TABLE_EXAMPLE_BODY
from services.deep_research.comparison_cross_paper_boundary import compile_point as compile_paper_boundary


def bind_stage_point(point, pairs, *, setting_references=False, protocol_settings_only=False):
    """Compile explicit choices without changing the journaled provider response."""
    body = point.get('body')
    if pairs:
        pair_id = body.get('tableExample') if isinstance(body, dict) and set(body) == {'tableExample'} else None
        if (point.get('kind') != 'reported' or not isinstance(pair_id, str) or pair_id not in pairs
                or point.get('evidenceRefs') != [] or point.get('cellRefs') != []):
            raise ValueError('stage_matched_example_pair')
        selected = pairs[pair_id]
        return {**point, 'body': TABLE_EXAMPLE_BODY, 'evidenceRefs': selected['evidenceRefs'],
                'cellRefs': selected['cellRefs']}
    if not setting_references or not isinstance(body, dict) or set(body) != {'boundary'}:
        return point
    boundary = body['boundary']
    settings = boundary.get('observedSettings') if isinstance(boundary, dict) else None
    if not isinstance(settings, list):
        return point
    if protocol_settings_only:
        from services.deep_research.measurement_table_navigation import benchmark_metric
        literal_headers = {'帧率', '渲染速度', '渲染耗时', '模型体积', '存储大小', '峰值显存', '压缩比'}
        for setting in settings:
            attribute = setting.get('attribute') if isinstance(setting, dict) else None
            if isinstance(attribute, str) and (benchmark_metric(attribute) or attribute.strip() in literal_headers):
                raise ValueError('stage_boundary_repeats_benchmark')
    if not any(isinstance(s, dict) and 'evidenceRefs' in s for s in settings):
        return point
    refs = point.get('evidenceRefs')
    if not isinstance(refs, list):
        raise ValueError('stage_boundary_setting_evidence')
    for setting in settings:
        if not isinstance(setting, dict):
            raise ValueError('stage_boundary_setting_evidence')
        if 'evidenceRefs' not in setting:
            continue
        setting_refs = setting['evidenceRefs']
        if (not isinstance(setting_refs, list) or not setting_refs
                or any(not isinstance(ref, str) or ref not in refs for ref in setting_refs)
                or len(set(setting_refs)) != len(setting_refs)):
            raise ValueError('stage_boundary_setting_evidence')
    return {**point, 'body': {'boundary': {**boundary,
            'observedSettings': [{k: v for k, v in setting.items() if k != 'evidenceRefs'} for setting in settings]}}}


def recorded_response(record, prompt, options, calls):
    """Read an exact succeeded ledger entry; never reserve or dispatch a call."""
    from services.deep_research.runtime import research_model_options
    from services.deep_research.structured_output import messages_for_record, enabled
    from services.deep_research.planning_transport import options_for_record
    extra = research_model_options('synthesize', options)
    identity = {'prompt':prompt,'extra':extra}
    if enabled(record):
        identity['extra'] = options_for_record(record,'synthesize',extra)
        identity['messages'] = messages_for_record(record,'synthesize',prompt)
    key = digest(identity)
    found = [c for c in calls if c.get('runId') == record['runId'] and c.get('node') == 'synthesize'
             and c.get('tool') == 'llm_invoke' and c.get('argsDigest') == key]
    if len(found) != 1 or found[0].get('status') != 'succeeded' or not isinstance(found[0].get('result'),dict):
        return None
    return deepcopy(found[0]['result'])


def generate(snapshot, *, current, checkpoint, invoke, recover=None, before_dispatch=None):
    """Return the combined unverified envelope; never retry an uncertain stage.

    Received responses are checkpointed before parsing. Malformed responses and
    unknown calls retain their original identity and refuse automatic replay.
    """
    binding = digest({k:v for k,v in snapshot.items() if k not in {'admission','inputDigest'}})
    if snapshot.get('inputDigest') != binding or snapshot.get('scientificApproval') is not False:
        raise DeepResearchError('invalid_comparison_stage_input', '比较输入身份不一致。')
    record = current()
    check_kind = explicit_stage_schema(record)
    abstention_version = record.get('comparisonStageAbstentionContractVersion')
    allow_stage_abstention = type(abstention_version) is int and abstention_version == 1
    setting_references = record.get('comparisonJointReportsContractVersion') in (15, 16)
    saved = deepcopy(record.get('state',{}).get('comparisonStageGeneration'))
    expected = [s['stageId'] for s in snapshot['stages']]
    if len(set(expected)) != len(expected):
        raise ValueError('Duplicate comparison stages')
    if saved is None:
        saved = {'version':1,'inputDigest':binding,'stages':{},'scientificApproval':False}
        checkpoint(deepcopy(saved))
    if (not isinstance(saved,dict) or type(saved.get('version')) is not int or saved['version'] != 1
            or saved.get('inputDigest') != binding or saved.get('scientificApproval') is not False
            or not isinstance(saved.get('stages'),dict) or set(saved['stages']) - set(expected)):
        raise DeepResearchError('invalid_comparison_stage_state', '比较阶段状态或输入身份已改变。')
    answers = []
    evidence_owners = {row['evidenceId']: row['source'] for row in snapshot.get('rows', [])}
    for stage in snapshot['stages']:
        if digest({k:v for k,v in stage.items() if k != 'inputDigest'}) != stage.get('inputDigest'):
            raise DeepResearchError('invalid_comparison_stage_input', '比较阶段输入已改变。')
        sid = stage['stageId']
        entry = saved['stages'].get(sid)
        record = current()
        options = {'max_tokens':4000,'temperature':0.2,
                   **request_options(record,effective_question(record),'paper_comparison')}
        if (isinstance(entry,dict) and entry.get('inputDigest') == stage['inputDigest']
                and entry.get('status') in {'invoking','invocation_stopped'} and recover is not None):
            known = recover(stage['prompt'],options)
            if isinstance(known,dict):
                entry.update(status='response_received',response=deepcopy(known),responseDigest=digest(known))
                checkpoint(deepcopy(saved))
        if entry is None:
            if record.get('status') != 'running':
                raise DeepResearchError('comparison_stage_stopped', '研究已停止，不能继续发送比较请求。')
            budget = record.get('budget',{})
            if any(type(budget.get(k)) is not int or budget[k] < 0
                   for k in ('maxModelCalls','modelCalls','reservedModelCalls')):
                raise ValueError('Invalid comparison stage dispatch budget')
            remaining = budget['maxModelCalls'] - budget['modelCalls'] - budget['reservedModelCalls']
            if remaining <= 0:
                raise BudgetExhaustedError('comparisonStageCalls',max(0,remaining),1)
            if remaining_seconds(record) <= 0:
                raise BudgetExhaustedError('comparisonStageWallClock',0,1)
            if before_dispatch is not None:
                before_dispatch()
            entry = {'inputDigest':stage['inputDigest'],'status':'invoking'}
            saved['stages'][sid] = entry
            checkpoint(deepcopy(saved))
            try:
                response = invoke('synthesize',stage['prompt'],options)
            except Exception:
                entry['status'] = 'invocation_stopped'
                checkpoint(deepcopy(saved))
                raise
            entry.update(status='response_received',response=deepcopy(response),responseDigest=digest(response))
            checkpoint(deepcopy(saved))
        if (not isinstance(entry,dict) or entry.get('inputDigest') != stage['inputDigest']
                or entry.get('status') not in {'response_received','compiled_unverified','invalid_response'}
                or digest(entry.get('response')) != entry.get('responseDigest')):
            raise DeepResearchError('comparison_stage_invocation_stopped', '比较阶段调用未确认或保存身份改变，不能自动重发。')
        response = entry['response']
        if entry['status'] == 'invalid_response':
            raise DeepResearchError('invalid_comparison_stage_response', '比较阶段响应无效，原结果已保留。')
        isolated = []
        try:
            if (not isinstance(response,dict)
                    or response.get('finishReason',response.get('finish_reason')) != 'stop'
                    or not isinstance(response.get('content'),str)
                    or len(response['content'].encode('utf-8')) > 100000):
                raise ValueError('Invalid or truncated response')
            payload = json.loads(response['content'])
            if payload is None and allow_stage_abstention:
                # A settled null response contains no claims. Preserve every
                # frozen target as unresolved without changing the raw reply.
                isolated = [{'targetId': target, 'reason': 'stage_returned_null'} for target in stage['targetIds']]
                payload = {'answers': [{'targetId': target, 'goalRefs': [], 'point': None} for target in stage['targetIds']]}
            if not isinstance(payload,dict) or set(payload) != {'answers'} or not isinstance(payload['answers'],list):
                raise ValueError('Invalid comparison stage envelope')
            ids = [a.get('targetId') if isinstance(a,dict) else None for a in payload['answers']]
            if (any(not isinstance(i,str) or i not in stage['targetIds'] for i in ids)
                    or len(set(ids)) != len(ids)):
                raise ValueError('Invalid comparison stage target identity')
        except (ValueError,TypeError,RecursionError):
            entry['status'] = 'invalid_response'
            checkpoint(deepcopy(saved))
            raise DeepResearchError('invalid_comparison_stage_response', '比较阶段响应无效，原结果已保留。') from None
        entry['status'] = 'compiled_unverified'
        admitted = []
        for row in payload['answers']:
            point = row.get('point')
            reason = None
            if isinstance(point,dict):
                pairs = stage.get('examplePairsByTarget', {}).get(row['targetId'])
                try:
                    papers = stage.get('paperSubjectsByTarget', {}).get(row['targetId'])
                    if stage.get('speedExplanationProse') is True:
                        body = point.get('body')
                        if (point.get('kind') != 'inference' or point.get('cellRefs') != []
                                or not isinstance(body, dict) or set(body) != {'prose'}):
                            raise ValueError('stage_speed_explanation_requires_prose')
                    if papers:
                        point = compile_paper_boundary(
                            point, papers, snapshot['sources'], evidence_owners,
                            setting_statements=stage.get('paperSettingStatements') is True,
                            cited_dataset_scope=record.get('comparisonCrossPaperBoundaryContractVersion') == 7)
                    point = bind_stage_point(point, pairs,
                                             setting_references=setting_references and (stage['stageId'] == 'joint' or bool(papers)),
                                             protocol_settings_only=(record.get('comparisonJointReportsContractVersion') == 16
                                                                     and bool(stage.get('examplePairsByTarget'))))
                except ValueError as exc:
                    isolated.append({'targetId':row['targetId'],'reason':str(exc)})
                    admitted.append({'targetId':row['targetId'],'goalRefs':[],'point':None})
                    continue
                evidence = point.get('evidenceRefs')
                cells = point.get('cellRefs')
                if (not isinstance(evidence,list) or any(not isinstance(ref,str)
                        or ref not in stage['allowedEvidenceByTarget'][row['targetId']] for ref in evidence)):
                    reason = 'stage_evidence_permission'
                elif (not isinstance(cells,list) or any(not isinstance(ref,str)
                        or ref not in stage['allowedCellsByTarget'][row['targetId']] for ref in cells)):
                    reason = 'stage_table_permission'
                elif check_kind and (not isinstance(point.get('kind'), str)
                                     or point['kind'] not in COMPARISON_POINT_KINDS):
                    reason = 'stage_claim_kind'
            if reason:
                isolated.append({'targetId':row['targetId'],'reason':reason})
                admitted.append({'targetId':row['targetId'],'goalRefs':[],'point':None})
            else:
                admitted.append(deepcopy({**row, 'point':point} if isinstance(point,dict) else row))
        # Negative isolation mirrors the ordinary wire compiler. The exact raw
        # response stays journaled; no guessed citation or positive fact is added.
        entry['isolatedTargets'] = isolated
        checkpoint(deepcopy(saved))
        answers.extend(admitted)
    return {'content':json.dumps({'answers':answers},ensure_ascii=False),'finishReason':'stop'}
