"""Whole original source rows for each actual workflow-unit request.

Required premises and every prior proposal reference remain atomic. Selection
never edits a quote, protocol choice, table, permission or scientific verdict.
"""
from copy import deepcopy
import json

from services.deep_research.contracts import DeepResearchError, digest


def enabled(record):
    from services.deep_research.experiment_stage_allocation import enabled as staged
    return (isinstance(record, dict)
            and type(record.get('workflowPremiseAllocationContractVersion')) is int
            and record['workflowPremiseAllocationContractVersion'] == 1 and staged(record))


def _refs(value):
    if (not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value)
            or len(set(value)) != len(value)):
        raise DeepResearchError('invalid_workflow_premise_state', '工作流证据依赖无效，不能发送。')
    return set(value)


def required(record):
    return _refs(record.get('state', {}).get('synthesisPremiseAllocation', {}).get('requiredPremiseEvidenceAliases'))


def allocate(record, *, source_data, context, aliases, prior_values, node, render, transport_options=None):
    from services.deep_research import workflow_representation_stage as representation
    if node == 'plan_workflow_init' and representation.enabled(record) and record[representation.MARKER] in (2, 3):
        from services.deep_research.workflow_representation_dependencies import allocate as dependencies
        return dependencies(record,source_data=source_data,context=context,aliases=aliases,prior_values=prior_values,
                            node=node,render=render,transport_options=transport_options)
    from services.deep_research.planning_transport import overhead_bytes
    from services.deep_research.workflow_metadata_window import input_limit
    if not enabled(record):raise ValueError('Workflow premise allocation is not enabled')
    max_input=input_limit(record,node)
    data=json.loads(source_data)
    rows=data.get('evidence')
    if not isinstance(rows,list) or any(not isinstance(r,dict) or not isinstance(r.get('evidenceId'),str) for r in rows):
        raise DeepResearchError('invalid_workflow_premise_state', '工作流原始证据缺失，不能发送。')
    ids=[r['evidenceId'] for r in rows]
    if len(set(ids))!=len(ids) or not set(ids)<=aliases.keys():
        raise DeepResearchError('invalid_workflow_premise_state', '工作流证据身份不一致，不能发送。')
    needed=required(record)|_refs(data['unverifiedScientificPlan']['sourceRefs'])
    for value in prior_values:needed|=_refs(value['sourceRefs'])
    if not needed<=set(ids):
        raise DeepResearchError('invalid_workflow_premise_state', '工作流依赖的原文未提供，不能发送。')
    pack=lambda v:json.dumps(v,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    overhead=overhead_bytes(record,node,transport_options)
    def request(selected):
        chosen=[r for r in rows if r['evidenceId'] in selected]
        scoped=deepcopy(data);scoped['evidence']=chosen
        ctx=deepcopy(context)
        if 'allowedSourceRefs' in ctx:
            # Narrow permission to the original objects actually transmitted.
            if _refs(ctx['allowedSourceRefs'])!=set(aliases):
                raise DeepResearchError('invalid_workflow_premise_state', '工作流引用权限与原始输入不一致。')
            ctx['allowedSourceRefs']=sorted(selected)
        text=pack(scoped)
        return render(text,ctx),text,ctx
    selected=set(ids);body,text,ctx=request(selected)
    if len(body.encode('utf8'))+overhead>max_input:
        selected=set(needed);body,text,ctx=request(selected)
        # Keep every required row even if the complete dependency set cannot fit.
        if len(body.encode('utf8'))+overhead<=max_input:
            for eid in ids:
                if eid in selected:continue
                trial=request(selected|{eid})
                if len(trial[0].encode('utf8'))+overhead<=max_input:
                    selected.add(eid);body,text,ctx=trial
    audit={'version':1,'node':node,'parentDataDigest':digest(data),'originalContextDigest':digest(context),
        'requiredAliases':[i for i in ids if i in needed],'suppliedAliases':[i for i in ids if i in selected],
        'priorProposalDigests':[digest(v) for v in prior_values],
        'inputBytes':len(body.encode('utf8'))+overhead,'transportOverheadBytes':overhead,'maxInputBytes':max_input,
        'sourceSelectionIsScientificApproval':False}
    return body,text,ctx,{i:aliases[i] for i in aliases if i in selected},audit
