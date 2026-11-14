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
Every newly introduced component needs its own creation rule; copying an existing
baseline alone does not define a new component's initial state.
rendering specifies the actual evaluation/rendering operation or implementation,
not just a framework name, and numeric resolution or resizing choices;
optimizer specifies actual optimizer and rates/schedule for every trainable group.
These three operations need nonempty parameters. "same"/unknown defaults are not choices.
otherInterventions explicitly disables or defines all relevant shared policies; genuinely
parameter-free disabling permits []. Choices are proposed, not paper settings.
For example, otherInterventions={"action":"Disable other shared interventions","parameters":[]}.
Do not substitute a list or a disabledPolicies object for this operation.
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

PROTOCOL_REVIEW_POLICY = '''Protocol contract 1 is structurally checked before this request.
Judge each control operation's actual scientific meaning, parameters, pairing and consistency;
nonempty fields do not establish executable initialization, resolution or optimizer rates.
Check creation of EACH new component; copying the baseline is not its creation rule.
For controls audit fields bind initialization/rendering/optimizer/otherInterventions respectively
to paired_initialization/render_settings/optimizer_settings/other_interventions.
Data prechecks enumerate real items, reject duplicate/missing IDs, and stop on empty or
overlapping splits. seeded_fraction sorts IDs, shuffles with its seed and uses
min(N-1,max(1,floor(N*f))) evaluation items for N>=2. These instructions assert no original
view count. Ground dataset/subset membership independently; unknown availability still fails.'''

PROTOCOL_CONTRACT_V2 = '''Protocol contract 2 (server assigned): controls executionSpec exactly
{initialization:{workflowClaimId:exact steps ID},rendering:operation,optimizer:operation,
otherInterventions:operation}. Initialization is defined ONLY in that workflow's
baselineInitialization and componentInitializations; do not repeat checkpoint paths
or invent another starting state. Rendering names an actual compatible operation and
numeric image-size/resize settings; optimizer defines actual rates/schedules for all
trainable groups. An operation is {action,parameters:[{name,type:number|choice,value}]}.
Rendering/optimizer need parameters; otherInterventions explicitly defines/disables
shared policies and may use []. Proposed choices are not original-paper settings.
Data keeps its exact existing schema: reproducible split/seeds/independent units and
nonempty/disjoint prechecks. Lock splits before fitting, enumerate real items and
record IDs/seeds/RNG version; final evaluation cannot initialize/tune/select. Existing
dataset/subset membership still needs evidence; these prechecks assert no author counts.
Text gives rationale, not duplicate configuration. Structural validity is not science.'''

PROTOCOL_REVIEW_POLICY_V2 = '''Protocol contract 2 is structurally checked before this request.
controls.initialization.workflowClaimId resolves the ONLY initialization definition in
that exact workflow 4 target/context. Review its baseline acquisition, every component
state/initial value, pairing and original prose with actual optimizer/render compatibility.
Reject competing checkpoint sources, omitted states or inconsistent copying; an exact
reference and valid schema are not scientific approval. The paired_initialization slot
can bind that pointer only when its full referenced protocol fulfills the requirement.
Data prechecks enumerate actual items, reject duplicates/missing IDs, and stop on empty
or overlapping splits. seeded_fraction sorts IDs, shuffles with its seed and takes
min(N-1,max(1,floor(N*f))) evaluation items for N>=2. Ground dataset/subset membership
independently; these proposed rules assert no original count or available author asset.
Rendering and optimizer still need actual operations and numeric settings for all
trainable groups. A general framework name or shared-default promise is insufficient.'''


def protocol_version(value):
    return value if type(value) is int and value in (1, 2) else 0


def protocol_contract(version):
    return {1: PROTOCOL_CONTRACT, 2: PROTOCOL_CONTRACT_V2}[version]


def protocol_errors(role, spec, version=1):
    if not protocol_version(version):
        return ['protocol.version']
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
        if version == 2 and key == 'initialization':
            value = spec[key]
            if (not isinstance(value, dict) or set(value) != {'workflowClaimId'}
                    or not isinstance(value.get('workflowClaimId'), str) or not value['workflowClaimId'].strip()):
                errors.append('initialization.workflow_reference')
            continue
        errors.extend(validate_operation(spec[key],key))
        if key!='otherInterventions' and isinstance(spec[key],dict) and spec[key].get('parameters')==[]:
            errors.append(key+'.parameters_required')
    return errors


def stamp_protocol_contract(report, enabled=True):
    version = 1 if enabled is True else protocol_version(enabled)
    result=deepcopy(report)
    result.pop('protocolContractVersion',None)
    if version:result['protocolContractVersion']=version
    for claim in result.get('claims',[]):
        if isinstance(claim,dict):
            claim.pop('protocolContractVersion',None)
            if version and claim.get('designRole') in PROTOCOL_ROLES:
                claim['protocolContractVersion']=version
    return result


def claim_protocol_text(claim):
    from services.deep_research.protocol_text import render_execution_spec
    role,spec=claim.get('designRole'),claim.get('executionSpec')
    version = protocol_version(claim.get('protocolContractVersion'))
    if not version:
        return render_execution_spec(role,spec)
    if protocol_errors(role,spec,version):
        return ''
    if role=='controls':
        lines=['拟议固定条件（尚未执行）：']
        for key,label in CONTROL_FIELDS.items():
            operation=spec[key]
            if version == 2 and key == 'initialization':
                lines.append('- '+label+'：使用执行流程中统一定义的基线与新组件初值，并在每次重复内配对复制到各组。')
                continue
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
    required_version = 1 if required is True else protocol_version(required)
    indexed = {}
    for c in result.get('accepted', []):
        identity = c.get('claimId')
        if isinstance(identity, str):
            indexed[identity] = c if identity not in indexed else None
    keep=[]
    for claim in result.get('accepted',[]):
        marked='protocolContractVersion' in claim
        expected=required and claim.get('designRole') in PROTOCOL_ROLES and claim.get('designContractVersion')==2
        if not marked and not expected:
            keep.append(claim);continue
        version = protocol_version(claim.get('protocolContractVersion'))
        valid=(version and (not expected or version == required_version)
               and claim.get('designRole') in PROTOCOL_ROLES
               and claim.get('kind') in {'proposal','suggestion','hypothesis'})
        errors=protocol_errors(claim.get('designRole'),claim.get('executionSpec'),version) if valid else ['invalid_protocol_contract']
        if not errors and version == 2 and claim.get('designRole') == 'controls':
            from services.deep_research.experiment_workflow import workflow_errors
            target = indexed.get(claim['executionSpec']['initialization']['workflowClaimId'])
            if (not isinstance(target, dict) or target.get('designRole') != 'steps'
                    or type(target.get('workflowContractVersion')) is not int or target['workflowContractVersion'] not in (4, 5)
                    or workflow_errors(target.get('executionSpec'), target['workflowContractVersion'])
                    or target['executionSpec']['refs']['controls'] != claim['claimId']):
                errors.append('initialization.unverified_workflow')
        if errors:
            result.setdefault('rejected',[]).append({'claimId':claim['claimId'],
                'reason':'incomplete_experiment_protocol','detail':', '.join(errors)})
        else:keep.append(claim)
    result['accepted']=keep
    return result
