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
        try:
            if (not isinstance(response,dict)
                    or response.get('finishReason',response.get('finish_reason')) != 'stop'
                    or not isinstance(response.get('content'),str)
                    or len(response['content'].encode('utf-8')) > 100000):
                raise ValueError('Invalid or truncated response')
            payload = json.loads(response['content'])
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
        admitted, isolated = [], []
        for row in payload['answers']:
            point = row.get('point')
            reason = None
            if isinstance(point,dict):
                evidence = point.get('evidenceRefs')
                cells = point.get('cellRefs')
                if (not isinstance(evidence,list) or any(not isinstance(ref,str)
                        or ref not in stage['allowedEvidenceByTarget'][row['targetId']] for ref in evidence)):
                    reason = 'stage_evidence_permission'
                elif (not isinstance(cells,list) or any(not isinstance(ref,str)
                        or ref not in stage['allowedCellsByTarget'][row['targetId']] for ref in cells)):
                    reason = 'stage_table_permission'
            if reason:
                isolated.append({'targetId':row['targetId'],'reason':reason})
                admitted.append({'targetId':row['targetId'],'goalRefs':[],'point':None})
            else:
                admitted.append(deepcopy(row))
        # Negative isolation mirrors the ordinary wire compiler. The exact raw
        # response stays journaled; no guessed citation or positive fact is added.
        entry['isolatedTargets'] = isolated
        checkpoint(deepcopy(saved))
        answers.extend(admitted)
    return {'content':json.dumps({'answers':answers},ensure_ascii=False),'finishReason':'stop'}
