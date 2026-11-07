"""Typed prospective workflow; validates plans, never executes experiments."""
from copy import deepcopy
import json

from services.deep_research.group_spec import validate_operation

STAGES = ('prepare_data', 'acquire_baseline', 'initialize_components', 'pair_groups',
          'apply_interventions', 'recover', 'evaluate', 'record')
RECORDS = {'baseline_identity', 'split_manifest', 'seed_manifest', 'component_states',
           'group_configs', 'recovery_budgets', 'evaluation_outputs', 'raw_measurements'}
WORKFLOW_VERSIONS = (1, 2, 3, 4, 5)
RECORD_LABELS = {'baseline_identity': '基线身份', 'split_manifest': '数据划分清单',
    'seed_manifest': '随机种子清单', 'component_states': '新组件初始状态',
    'group_configs': '各组配置', 'recovery_budgets': '各组训练预算',
    'evaluation_outputs': '评估输出', 'raw_measurements': '原始测量',
    'group_checkpoints': '各组最终检查点'}
WORKFLOW_CONTRACT = '''Workflow contract 1 (server assigned): steps executionSpec exactly
{refs:{data:claimId,budget:claimId,controls:claimId,groups:claimId},
order:[prepare_data,acquire_baseline,initialize_components,pair_groups,apply_interventions,recover,evaluate,record],
baselineMode:train|existing,replicationMode:retrained_per_seed|fixed_checkpoint,
componentInitializations:[{componentId:unique nonblank,creation:{action,parameters},appliesTo:[group IDs]}],
checkpointSelection:{mode:fixed_budget} OR {mode:train_loss,rule:operation}
OR {mode:validation_split,split:data split schema,rule:operation},
records:[baseline_identity,split_manifest,seed_manifest,component_states,group_configs,
recovery_budgets,evaluation_outputs,raw_measurements]}.
refs select exact sibling claim IDs; modes match the referenced budget and data.
Define creation parameters for EVERY introduced component; [] only if no new component.
Create each listed component once per repetition, then copy the same state to appliesTo groups.
For retrained_per_seed execute fitting separately for EACH data seed: train-mode
baselines are rebuilt per seed; existing assets are identical warm starts, not
independent baseline retraining. All fitting uses training data only.
Prepare/lock all splits BEFORE fitting or component creation. Validation is split only
from the training portion, before fitting; never use the held-out evaluation portion
for initialization, tuning, stopping or checkpoint selection. fixed_budget selects
the final budget step. Keep prose/controls consistent; typed fields cannot override a conflict.
All choices are unexecuted proposals. The app renders the workflow, so do not repeat it.'''

WORKFLOW_CONTRACT_V2 = '''Workflow contract 2 (server assigned): steps executionSpec exactly
{refs:{data:claimId,budget:claimId,controls:claimId,groups:claimId},
order:[prepare_data,acquire_baseline,initialize_components,pair_groups,apply_interventions,recover,evaluate,record],
baselineMode:train|existing,replicationMode:retrained_per_seed|fixed_checkpoint,
componentInitializations:[{componentId,initializationMode:derive|fresh,
inputs:[{state:baseline|training_data|EARLIER_componentId,selector:concrete existing state/selection}],
creation:{action,parameters},appliesTo:[actual group IDs]}],
checkpointSelection:{mode:fixed_budget} OR {mode:train_loss,rule:operation}
OR {mode:validation_split,split:data split schema,rule:operation},
records:[baseline_identity,split_manifest,seed_manifest,component_states,group_configs,
recovery_budgets,evaluation_outputs,raw_measurements,group_checkpoints]}.
refs match accepted sibling IDs; baseline/replication modes match them. Component IDs
are unique and cannot be baseline/training_data. derive needs at least one EXISTING
input; fresh needs inputs:[] and actual shape/value/RNG settings. Components are created
in list order, once per repetition, then identical copies go to appliesTo. Creation
parameters are nonempty and define the NEW state, not an instruction to copy a missing
enhancement. Never assume a new component already exists inside the baseline.
All splits are locked BEFORE fitting, including creation from training_data. An inner
validation split uses only training data; stop if either inner side is empty/overlaps.
Final evaluation cannot initialize, tune, stop or select. fixed_budget selects the last
budget step. Train-mode retrained_per_seed rebuilds per seed; existing assets are shared
warm starts, not independently trained baselines. Save resulting group checkpoints.
Operations use {action,parameters:[{name,type:number|choice,value}]}.
These are unexecuted proposals; text adds rationale, not a duplicate field listing.'''

WORKFLOW_CONTRACT_V3 = WORKFLOW_CONTRACT_V2.replace('Workflow contract 2', 'Workflow contract 3').replace(
    'All splits are locked BEFORE fitting',
    'For fresh creation include a choice parameter named state_layout describing actual '
    'state variables, dimensions/counts and their initial values/distributions. A seed '
    'and one opacity value alone do not initialize positions, scale, orientation or appearance. '
    'Use exact input-dependent count rules when needed.\nAll splits are locked BEFORE fitting')

from services.deep_research.state_initialization import STATE_CONTRACT
WORKFLOW_CONTRACT_V4 = '''Workflow contract 4 (server assigned): steps executionSpec exactly
{refs:{data:ID,budget:ID,controls:ID,groups:ID},
order:[prepare_data,acquire_baseline,initialize_components,pair_groups,apply_interventions,recover,evaluate,record],
baselineMode:train|existing,replicationMode:retrained_per_seed|fixed_checkpoint,
baselineInitialization:null OR {initializationMode:fresh|derive,inputs,creation,stateDefinitions},
componentInitializations:[{componentId,initializationMode:fresh|derive,inputs,creation,stateDefinitions,appliesTo:[group IDs]}],
checkpointSelection:{mode:fixed_budget} OR {mode:train_loss,rule:operation}
OR {mode:validation_split,split:data split schema,rule:operation},
records:[baseline_identity,split_manifest,seed_manifest,component_states,group_configs,
recovery_budgets,evaluation_outputs,raw_measurements,group_checkpoints]}.
Train requires an explicit baselineInitialization BEFORE baseline fitting; existing
requires null and grounded budget asset selection. Baseline inputs use training_data
only. Component inputs use baseline/training_data/EARLIER component IDs; each entry is
{state,selector:actual existing state}. fresh has inputs:[]; derive has inputs.
creation is {action,parameters}; [] is allowed when stateDefinitions fully specify creation.
Define actual initial values for EVERY required state, not an opaque state_layout string.
Create once per repetition, then copy identical complete states to appliesTo groups.
refs match accepted siblings and modes. Lock all data splits before any fitting/creation.
Inner validation uses training data only, with nonempty/disjoint prechecks. Final
evaluation never initializes, tunes, stops or selects. fixed_budget uses the last step.
retrained_per_seed rebuilds train baselines per data seed; existing assets are shared
warm starts. Controls initialization references this steps ID, never another checkpoint
source. Keep original prose consistent. All values are prospective, not measured results.
''' + STATE_CONTRACT

WORKFLOW_CONTRACT_V5 = '''Workflow5 is an UNEXECUTED phase/lifetime proposal, not approval.
Keep Workflow4 refs/order/modes/baselineInitialization/checkpointSelection and nine records.
Add frameIterations (positive integer if per-frame phases exist, otherwise zero), phases.
Each component keeps its complete Workflow4 initialization and adds
lifecycle:{scope:per_repeat|per_frame,createAfter:[phaseId],disposeAfter:phaseId|null}.
The initialization is a recipe; allocate its instance at this declared boundary, not all upfront.
Each phase exactly {phaseId,scope,kind:fit|setup|evaluate|record,groups:[actual IDs],
sharing:shared|per_group,after:[earlier phaseId],reads:[input],updates:[baseline|componentId],
outputs:[unique outputId],action:operation,budget:null|{unit,perExecution}}.
An input is {state:baseline|training_data|earlier componentId,selector} OR
{phaseId,outputId,selector}. Phase-output inputs are allowed only after their production;
baseline initialization precedes this timeline and uses training_data only.
Per-frame phases are contiguous. Per-repeat resources are prepared before entering the
frame loop; same-boundary recipes within a scope follow component order. Per-frame
components must be disposed in that frame after all direct uses, including recording
when recording consumes that state. Preserved outputs may outlive the component.
Never read a future instance/output, use a disposed state, leak a treatment-only state
to control, or update training_data. Final evaluation/record phases cannot update models.
shared runs once and supplies identical outputs to its declared groups; per_group runs
separately. All final evaluations follow fitting for their group; records consume actual
evaluation outputs (possibly through explicit copies), not merely occur later.
Only fit phases have budgets; units optimizer_steps|epochs require nonbool integer caps,
wall_seconds allows finite numbers; caps are nonnegative. Whole recovery group budget
per repeat equals the sum of each applicable fit cap times frameIterations for per_frame
or 1 for per_repeat. Shared work is attributed to each comparison group, not falsely
counted as separate physical execution. Preserve unmatched-budget interpretation.
Baseline training/acquisition is completed before this timeline and uses its own budget.
All source facts/assets still need evidence; initial values need scientific compatibility.
''' + STATE_CONTRACT


def workflow_version(value):
    return value if type(value) is int and value in WORKFLOW_VERSIONS else 0


def workflow_contract(version):
    return {1: WORKFLOW_CONTRACT, 2: WORKFLOW_CONTRACT_V2, 3: WORKFLOW_CONTRACT_V3,
            4: WORKFLOW_CONTRACT_V4, 5: WORKFLOW_CONTRACT_V5}[version]


def _strings(value):
    return (isinstance(value, list) and bool(value)
            and all(isinstance(item, str) and item.strip() for item in value)
            and len(value) == len(set(value)))


def _operation_errors(operation, path):
    try:
        return validate_operation(operation, path)
    except (TypeError, ValueError):
        return [path + '.invalid_types']


def workflow_errors(spec, version=1):
    if not workflow_version(version):
        return ['workflow.version']
    if not isinstance(spec, dict):
        return ['workflow.spec']
    errors = []
    expected_fields = {'refs', 'order', 'baselineMode', 'replicationMode', 'componentInitializations',
                       'checkpointSelection', 'records'} | ({'baselineInitialization'} if version >= 4 else set())
    if version == 5:
        expected_fields |= {'frameIterations', 'phases'}
    if set(spec) != expected_fields:
        errors.append('workflow.fields')
    refs = spec.get('refs')
    if (not isinstance(refs, dict) or set(refs) != {'data', 'budget', 'controls', 'groups'}
            or not all(isinstance(v, str) and v.strip() for v in refs.values())
            or len(set(refs.values())) != 4):
        errors.append('workflow.refs')
    if spec.get('order') != list(STAGES):
        errors.append('workflow.order')
    if spec.get('baselineMode') not in ('train', 'existing'):
        errors.append('workflow.baselineMode')
    if spec.get('replicationMode') not in ('retrained_per_seed', 'fixed_checkpoint'):
        errors.append('workflow.replicationMode')
    if version >= 4:
        baseline = spec.get('baselineInitialization')
        if spec.get('baselineMode') == 'existing':
            if baseline is not None:
                errors.append('workflow.baseline_existing_creation')
        elif not isinstance(baseline, dict) or set(baseline) != {'initializationMode', 'inputs', 'creation', 'stateDefinitions'}:
            errors.append('workflow.baseline_initialization')
        else:
            errors.extend(_creation_input_errors(baseline, set(), version, baseline=True))
            errors.extend(_operation_errors(baseline['creation'], 'workflow.baseline_creation'))
    components = spec.get('componentInitializations')
    if not isinstance(components, list):
        errors.append('workflow.componentInitializations')
    else:
        ids = set()
        for component in components:
            fields = {'componentId', 'creation', 'appliesTo'}
            if version >= 2:
                fields |= {'inputs', 'initializationMode'}
            if version >= 4:
                fields.add('stateDefinitions')
            if version == 5:
                fields.add('lifecycle')
            if (not isinstance(component, dict) or set(component) != fields
                    or not isinstance(component.get('componentId'), str) or not component['componentId'].strip()
                    or component['componentId'] in ids
                    or (version >= 2 and component['componentId'] in {'baseline', 'training_data'})):
                errors.append('workflow.component')
                continue
            if version >= 2:
                errors.extend(_creation_input_errors(component, ids, version))
            ids.add(component['componentId'])
            errors.extend(_operation_errors(component['creation'], 'workflow.creation'))
            if version < 4 and isinstance(component['creation'], dict) and component['creation'].get('parameters') == []:
                errors.append('workflow.creation.parameters_required')
            if not _strings(component['appliesTo']):
                errors.append('workflow.component.appliesTo')
    selection = spec.get('checkpointSelection')
    if not isinstance(selection, dict):
        errors.append('workflow.checkpointSelection')
    else:
        mode = selection.get('mode')
        fields = {'fixed_budget': {'mode'}, 'train_loss': {'mode', 'rule'},
                  'validation_split': {'mode', 'split', 'rule'}}
        if not isinstance(mode, str) or mode not in fields or set(selection) != fields.get(mode):
            errors.append('workflow.checkpointSelection.fields')
        else:
            if mode != 'fixed_budget':
                errors.extend(_operation_errors(selection['rule'], 'workflow.checkpointSelection.rule'))
                if isinstance(selection['rule'], dict) and selection['rule'].get('parameters') == []:
                    errors.append('workflow.checkpointSelection.rule.parameters_required')
            if mode == 'validation_split':
                from services.deep_research.execution_spec import _validate_split
                split = selection['split']
                if not isinstance(split, dict):
                    errors.append('workflow.validationSplit')
                else:
                    _validate_split(split, errors.append)
                    expected = {'every_nth': {'mode', 'order', 'stride', 'offset'},
                        'seeded_fraction': {'mode', 'evaluationFraction', 'seed'},
                        'explicit': {'mode', 'train', 'evaluation'}}
                    split_mode = split.get('mode')
                    if not isinstance(split_mode, str) or set(split) != expected.get(split_mode):
                        errors.append('workflow.validationSplit.fields')
    records = spec.get('records')
    required_records = RECORDS | ({'group_checkpoints'} if version >= 2 else set())
    if not _strings(records) or not required_records <= set(records):
        errors.append('workflow.records')
    elif version == 5 and len(records) != len(required_records):
        errors.append('workflow.records')
    if version == 5:
        from services.deep_research.workflow_lifecycle import lifecycle_errors
        errors.extend(lifecycle_errors(spec))
    return list(dict.fromkeys(errors))


def _creation_input_errors(component, earlier, version, *, baseline=False):
    inputs, mode = component['inputs'], component['initializationMode']
    if not isinstance(mode, str) or mode not in {'derive', 'fresh'} or not isinstance(inputs, list):
        return ['workflow.creation.inputs']
    if (mode == 'derive' and not inputs) or (mode == 'fresh' and inputs):
        return ['workflow.creation.input_mode_conflict']
    errors, seen = [], set()
    operation = component.get('creation')
    parameters = operation.get('parameters') if isinstance(operation, dict) else None
    if version == 3 and mode == 'fresh' and (not isinstance(parameters, list) or not any(
            isinstance(p, dict) and p.get('name') == 'state_layout' and p.get('type') == 'choice'
            and isinstance(p.get('value'), str) and p['value'].strip() for p in parameters)):
        errors.append('workflow.creation.fresh_layout_required')
    for item in inputs:
        if (version == 5 and not baseline and isinstance(item, dict)
                and set(item) == {'phaseId', 'outputId', 'selector'}
                and all(isinstance(v, str) and v.strip() for v in item.values())):
            identity = ('phase', item['phaseId'], item['outputId'], item['selector'])
            if identity in seen: errors.append('workflow.creation.duplicate_input')
            seen.add(identity)
            continue  # Full phase/output/group/lifetime checks run in lifecycle_errors.
        if (not isinstance(item, dict) or set(item) != {'state', 'selector'}
                or not all(isinstance(v, str) and v.strip() for v in item.values())):
            errors.append('workflow.creation.input')
            continue
        if item['state'] not in (earlier | {'training_data'} | (set() if baseline else {'baseline'})):
            errors.append('workflow.creation.unavailable_input')
        identity = (item['state'], item['selector'])
        if identity in seen:
            errors.append('workflow.creation.duplicate_input')
        seen.add(identity)
    if version >= 4:
        from services.deep_research.state_initialization import state_definition_errors
        errors.extend('workflow.' + error for error in state_definition_errors(component.get('stateDefinitions'), inputs))
    return errors


def stamp_workflow_contract(report, enabled=True):
    version = 1 if enabled is True else workflow_version(enabled)
    result = deepcopy(report)
    result.pop('workflowContractVersion', None)
    if version:
        result['workflowContractVersion'] = version
    for claim in result.get('claims', []):
        if isinstance(claim, dict):
            claim.pop('workflowContractVersion', None)
            if version and claim.get('designRole') == 'steps':
                claim['workflowContractVersion'] = version
    return result


def workflow_text(claim):
    version = workflow_version(claim.get('workflowContractVersion'))
    if not version or workflow_errors(claim.get('executionSpec'), version):
        return ''
    spec = claim['executionSpec']
    if version == 5:
        from services.deep_research.workflow_lifecycle_text import lifecycle_text
        return lifecycle_text(spec)
    lines = ['拟议执行流程（尚未执行）：',
        '1. 先枚举数据、完成预检并锁定训练与最终评估划分；最终评估集不参与任何拟合。']
    if spec['checkpointSelection']['mode'] == 'validation_split':
        from services.deep_research.protocol_text import render_split
        lines.append('   验证集仅从训练部分再次划出，在拟合前固定；规则：' +
                     (render_split(spec['checkpointSelection']['split'], training='拟合', evaluation='验证')
                      if version >= 2 else json.dumps(spec['checkpointSelection']['split'], ensure_ascii=False, sort_keys=True)))
        if version >= 2:
            lines.append('   内层拟合与验证部分必须都非空且互不重叠；否则停止。')
    mode = spec['replicationMode']
    if mode == 'retrained_per_seed':
        lines.append('2. 对数据项的每个种子分别执行拟合；每次重复内配对各组。')
        lines.append('   ' + ('每个种子分别重训基线。' if spec['baselineMode'] == 'train' else
                             '每次从相同既有资产复制起点；不能宣称独立重训了基线。'))
    else:
        lines.append('2. 复用一个固定基线；多个后续种子不代表独立重训了基线。')
    lines.append('   ' + ('基线按预算项训练，仅使用训练部分。' if spec['baselineMode'] == 'train'
                         else '基线按预算项的既有资产规则获取并核对身份。'))
    if version >= 4 and spec['baselineInitialization'] is not None:
        lines.extend(_initialization_details(spec['baselineInitialization'], '基线初始状态'))
    lines.append('3. 每次重复先创建所需新组件，再配对复制到各组：')
    for component in spec['componentInitializations']:
        from services.deep_research.operation_text import operation_text
        if version >= 2:
            for source in component['inputs']:
                name = {'baseline': '已有基线', 'training_data': '训练数据'}.get(source['state'], source['state'])
                if version < 4:
                    lines.append('   - ' + component['componentId'] + '的输入：' + name + '；选取规则：' + source['selector'])
            if component['initializationMode'] == 'fresh':
                lines.append('   - ' + component['componentId'] + '：从显式初值新建，不复制已有组件。')
        lines.append('   - ' + component['componentId'] + '：' + component['creation']['action'] +
            (operation_text(component['creation'], include_action=False) if version >= 2
             else '；参数=' + json.dumps(component['creation']['parameters'], ensure_ascii=False)) +
            '；相同初始状态复制到组 ' + '、'.join(component['appliesTo']))
        if version >= 4:
            lines.extend(_initialization_details(component, component['componentId'] + '的初始状态'))
    if not spec['componentInitializations']:
        lines.append('   本方案声明没有新建组件；是否与实际干预一致仍需科学核查。')
    lines.extend(['4. 复制配对状态，按分组项实施干预，再按预算项执行各组恢复；固定条件保持一致。',
                  '5. 按所选检查点规则完成训练与选择，最终评估只在全部选择结束后进行。'])
    selection = spec['checkpointSelection']
    if selection['mode'] == 'fixed_budget':
        lines.append('   使用预算结束时的检查点，不根据最终评估表现挑选。')
    else:
        from services.deep_research.operation_text import operation_text
        lines.append('   选择依据仅为' + ('训练损失' if selection['mode'] == 'train_loss' else '独立验证部分') +
            '：' + (operation_text(selection['rule']) if version >= 2 else selection['rule']['action'] +
                   '；参数=' + json.dumps(selection['rule']['parameters'], ensure_ascii=False)))
    lines.extend(['   最终评估集不得用于初始化、调参、早停或检查点选择。',
                  ('6. 保存：' + '、'.join(RECORD_LABELS.get(key, key) for key in spec['records']) + '。'
                   if version >= 2 else '6. 保存基线身份、划分与种子清单、组件初态、各组配置及恢复预算、评估输出和原始测量。')])
    return '\n'.join(lines)


def _initialization_details(initialization, title):
    from services.deep_research.state_initialization import state_definitions_text
    from services.deep_research.operation_text import operation_text
    lines = ['', '<details>', '<summary>' + title + '</summary>', '']
    lines.append('初值来源：' + ('从显式初值新建。' if initialization['initializationMode'] == 'fresh'
                            else '按下面列出的已有输入派生。'))
    for i, source in enumerate(initialization['inputs']):
        lines.append(f"输入{i}：{source['state']}；选取规则：{source['selector']}")
    lines.extend([operation_text(initialization['creation']), '',
        state_definitions_text(initialization['stateDefinitions']), '',
        '执行前按实际输入核对形状、轴和初值广播规则；维度不符或引用越界时停止，不自动替换。',
        '', '</details>', ''])
    return lines


def enforce_workflow_consistency(verification, required=False):
    required_version = 1 if required is True else workflow_version(required)
    result = deepcopy(verification)
    accepted = result.get('accepted', [])
    indexed = {}
    for claim in accepted:
        key = claim.get('claimId')
        if isinstance(key, str):
            indexed[key] = claim if key not in indexed else None
    rejected = set()
    for claim in accepted:
        expected = required and claim.get('designRole') == 'steps' and claim.get('designContractVersion') == 2
        if 'workflowContractVersion' not in claim and not expected:
            continue
        version = workflow_version(claim.get('workflowContractVersion'))
        valid = (version and (not expected or version == required_version)
            and claim.get('designRole') == 'steps' and claim.get('kind') in {'proposal', 'suggestion', 'hypothesis'})
        errors = workflow_errors(claim.get('executionSpec'), version) if valid else ['invalid_workflow_contract']
        if not errors:
            spec = claim['executionSpec']
            siblings = {role: indexed.get(key) for role, key in spec['refs'].items()}
            for role, sibling in siblings.items():
                if (not isinstance(sibling, dict) or sibling.get('designRole') != role
                        or sibling.get('kind') not in {'proposal', 'suggestion', 'hypothesis'}
                        or not isinstance(sibling.get('executionSpec'), dict)):
                    errors.append('workflow.unverified_reference.' + role)
            if not errors:
                budget = siblings['budget'].get('executionSpec', {})
                data = siblings['data'].get('executionSpec', {})
                if spec['baselineMode'] != budget.get('baseline', {}).get('mode'):
                    errors.append('workflow.baseline_mode_conflict')
                if spec['replicationMode'] != data.get('replication', {}).get('mode'):
                    errors.append('workflow.replication_mode_conflict')
                if version == 5:
                    from services.deep_research.workflow_lifecycle import lifecycle_budget_errors
                    errors.extend(lifecycle_budget_errors(spec, budget))
                groups = budget.get('recovery', {}).get('groups', {})
                if any(group not in groups for c in spec['componentInitializations'] for group in c['appliesTo']):
                    errors.append('workflow.unknown_initialization_group')
                if version >= 4:
                    controls = siblings['controls']
                    if (type(controls.get('protocolContractVersion')) is not int or controls['protocolContractVersion'] != 2
                            or controls['executionSpec'].get('initialization') != {'workflowClaimId': claim['claimId']}):
                        errors.append('workflow.initialization_reference_conflict')
        if errors:
            rejected.add(claim['claimId'])
            result.setdefault('rejected', []).append({'claimId': claim['claimId'],
                'reason': 'inconsistent_experiment_workflow', 'detail': ', '.join(errors)})
    result['accepted'] = [c for c in accepted if c.get('claimId') not in rejected]
    return result
