"""Versioned proposed controls and split prechecks; no experiment is executed."""
from copy import deepcopy
import json

from services.deep_research.group_spec import validate_operation

CONTROL_FIELDS = {'initialization':'初始化与配对', 'rendering':'渲染或评估设置',
                  'optimizer':'优化器与更新规则', 'otherInterventions':'其他干预'}
PROTOCOL_ROLES = {'controls','data'}
PROTOCOL_CONTRACT = '''Protocol contract 1 (server assigned) applies to controls and data.
controls executionSpec has EXACTLY initialization, rendering, optimizer, otherInterventions.
Each is an operation {action:nonblank,parameters:list}; parameters use the groups schema
{name:unique nonblank,type:number|choice,value:finite nonbool number|nonblank choice}.
initialization specifies actual creation, seed/parameters and paired copying of states;
rendering specifies evaluator/renderer and numeric resolution or resizing choices;
optimizer specifies actual optimizer and rates/schedule for every trainable group.
These three operations need nonempty parameters. "same"/unknown defaults are not choices.
otherInterventions explicitly disables or defines all relevant shared policies; genuinely
parameter-free disabling permits []. Choices are proposed, not paper settings.
For data, keep the existing exact schema. Execution prechecks enumerate real items,
reject duplicates/missing explicit IDs, construct the split, and stop if either side is
empty or overlaps. Unknown original view counts are not asserted or invented. A precheck
is an instruction, not evidence of actual capacity; dataset/subset membership still needs evidence.
seeded_fraction sorts item identifiers, shuffles with the specified seed, uses
min(N-1,max(1,floor(N*f))) evaluation items, and requires N>=2; record manifest and RNG version.
For every_nth use its stated order/zero-based offset; stop on an empty side.
Write rationale/limits in text, not a duplicate of executionSpec; the app renders it.'''

DATA_PRECHECK = ('执行前预检（尚未执行）：枚举实际样本并保存清单，拒绝重复标识；'
    '显式划分的标识必须存在。按上述规则划分后，训练集与评估集必须都非空且互不重叠；'
    '否则停止实验并记录原因，不自动换数据。记录实际数量、排序、种子及随机数实现版本。'
    '这些是预检要求，不表示论文已报告或系统已确认样本数量。')


def protocol_errors(role, spec):
    if role == 'data':
        from services.deep_research.execution_spec import execution_spec_errors
        errors = execution_spec_errors(role,spec)
        if errors:
            return errors
        split=spec['split']
        expected={'every_nth':{'mode','order','stride','offset'},
                  'seeded_fraction':{'mode','evaluationFraction','seed'},
                  'explicit':{'mode','train','evaluation'}}[split['mode']]
        if set(split)!=expected:
            errors.append('split.unrecognized_fields')
        return errors
    if role != 'controls' or not isinstance(spec,dict):
        return ['controls.spec']
    if set(spec)!=set(CONTROL_FIELDS):
        return ['controls.fields']
    errors=[]
    for key in CONTROL_FIELDS:
        errors.extend(validate_operation(spec[key],key))
        if key!='otherInterventions' and isinstance(spec[key],dict) and spec[key].get('parameters')==[]:
            errors.append(key+'.parameters_required')
    return errors


def stamp_protocol_contract(report, enabled=True):
    result=deepcopy(report)
    result.pop('protocolContractVersion',None)
    if enabled:result['protocolContractVersion']=1
    for claim in result.get('claims',[]):
        if isinstance(claim,dict):
            claim.pop('protocolContractVersion',None)
            if enabled and claim.get('designRole') in PROTOCOL_ROLES:
                claim['protocolContractVersion']=1
    return result


def claim_protocol_text(claim):
    from services.deep_research.protocol_text import render_execution_spec
    role,spec=claim.get('designRole'),claim.get('executionSpec')
    if claim.get('protocolContractVersion')!=1:
        return render_execution_spec(role,spec)
    if protocol_errors(role,spec):
        return ''
    if role=='controls':
        lines=['拟议固定条件（尚未执行）：']
        for key,label in CONTROL_FIELDS.items():
            operation=spec[key]
            lines.append('- '+label+'：'+operation['action'])
            for param in operation['parameters']:
                lines.append('  - '+param['name']+'：'+json.dumps(param['value'],ensure_ascii=False,allow_nan=False))
        return '\n'.join(lines)
    text=render_execution_spec(role,spec)
    if spec['split']['mode']=='seeded_fraction':
        text+='\n\n随机划分操作：先按样本标识排序，再用指定种子打乱；N≥2时取min(N−1,max(1,floor(N×评估比例)))项作评估，其余作训练。'
    return text+'\n\n'+DATA_PRECHECK


def enforce_protocol_consistency(verification, required=False):
    result=deepcopy(verification)
    keep=[]
    for claim in result.get('accepted',[]):
        marked='protocolContractVersion' in claim
        expected=required and claim.get('designRole') in PROTOCOL_ROLES and claim.get('designContractVersion')==2
        if not marked and not expected:
            keep.append(claim);continue
        valid=(type(claim.get('protocolContractVersion')) is int and claim['protocolContractVersion']==1
               and claim.get('designRole') in PROTOCOL_ROLES
               and claim.get('kind') in {'proposal','suggestion','hypothesis'})
        errors=protocol_errors(claim.get('designRole'),claim.get('executionSpec')) if valid else ['invalid_protocol_contract']
        if errors:
            result.setdefault('rejected',[]).append({'claimId':claim['claimId'],
                'reason':'incomplete_experiment_protocol','detail':', '.join(errors)})
        else:keep.append(claim)
    result['accepted']=keep
    return result
