"""Typed prospective workflow; validates plans, never executes experiments."""
from copy import deepcopy
import json

from services.deep_research.group_spec import validate_operation

STAGES = ('prepare_data', 'acquire_baseline', 'initialize_components', 'pair_groups',
          'apply_interventions', 'recover', 'evaluate', 'record')
RECORDS = {'baseline_identity', 'split_manifest', 'seed_manifest', 'component_states',
           'group_configs', 'recovery_budgets', 'evaluation_outputs', 'raw_measurements'}
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


def _strings(value):
    return (isinstance(value, list) and bool(value)
            and all(isinstance(item, str) and item.strip() for item in value)
            and len(value) == len(set(value)))


def _operation_errors(operation, path):
    try:
        return validate_operation(operation, path)
    except (TypeError, ValueError):
        return [path + '.invalid_types']


def workflow_errors(spec):
    if not isinstance(spec, dict):
        return ['workflow.spec']
    errors = []
    if set(spec) != {'refs', 'order', 'baselineMode', 'replicationMode', 'componentInitializations',
                     'checkpointSelection', 'records'}:
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
    components = spec.get('componentInitializations')
    if not isinstance(components, list):
        errors.append('workflow.componentInitializations')
    else:
        ids = set()
        for component in components:
            if (not isinstance(component, dict) or set(component) != {'componentId', 'creation', 'appliesTo'}
                    or not isinstance(component.get('componentId'), str) or not component['componentId'].strip()
                    or component['componentId'] in ids):
                errors.append('workflow.component')
                continue
            ids.add(component['componentId'])
            errors.extend(_operation_errors(component['creation'], 'workflow.creation'))
            if isinstance(component['creation'], dict) and component['creation'].get('parameters') == []:
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
    if not _strings(records) or not RECORDS <= set(records):
        errors.append('workflow.records')
    return list(dict.fromkeys(errors))


def stamp_workflow_contract(report, enabled=True):
    result = deepcopy(report)
    result.pop('workflowContractVersion', None)
    if enabled:
        result['workflowContractVersion'] = 1
    for claim in result.get('claims', []):
        if isinstance(claim, dict):
            claim.pop('workflowContractVersion', None)
            if enabled and claim.get('designRole') == 'steps':
                claim['workflowContractVersion'] = 1
    return result


def workflow_text(claim):
    if claim.get('workflowContractVersion') != 1 or workflow_errors(claim.get('executionSpec')):
        return ''
    spec = claim['executionSpec']
    lines = ['拟议执行流程（尚未执行）：',
        '1. 先枚举数据、完成预检并锁定训练与最终评估划分；最终评估集不参与任何拟合。']
    if spec['checkpointSelection']['mode'] == 'validation_split':
        lines.append('   验证集仅从训练部分再次划出，在拟合前固定；规则：' +
                     json.dumps(spec['checkpointSelection']['split'], ensure_ascii=False, sort_keys=True))
    mode = spec['replicationMode']
    if mode == 'retrained_per_seed':
        lines.append('2. 对数据项的每个种子分别执行拟合；每次重复内配对各组。')
        lines.append('   ' + ('每个种子分别重训基线。' if spec['baselineMode'] == 'train' else
                             '每次从相同既有资产复制起点；不能宣称独立重训了基线。'))
    else:
        lines.append('2. 复用一个固定基线；多个后续种子不代表独立重训了基线。')
    lines.append('   ' + ('基线按预算项训练，仅使用训练部分。' if spec['baselineMode'] == 'train'
                         else '基线按预算项的既有资产规则获取并核对身份。'))
    lines.append('3. 每次重复先创建所需新组件，再配对复制到各组：')
    for component in spec['componentInitializations']:
        lines.append('   - ' + component['componentId'] + '：' + component['creation']['action'] +
            '；参数=' + json.dumps(component['creation']['parameters'], ensure_ascii=False) +
            '；相同初始状态复制到组 ' + '、'.join(component['appliesTo']))
    if not spec['componentInitializations']:
        lines.append('   本方案声明没有新建组件；是否与实际干预一致仍需科学核查。')
    lines.extend(['4. 复制配对状态，按分组项实施干预，再按预算项执行各组恢复；固定条件保持一致。',
                  '5. 按所选检查点规则完成训练与选择，最终评估只在全部选择结束后进行。'])
    selection = spec['checkpointSelection']
    if selection['mode'] == 'fixed_budget':
        lines.append('   使用预算结束时的检查点，不根据最终评估表现挑选。')
    else:
        lines.append('   选择依据仅为' + ('训练损失' if selection['mode'] == 'train_loss' else '独立验证部分') +
            '：' + selection['rule']['action'] + '；参数=' + json.dumps(selection['rule']['parameters'], ensure_ascii=False))
    lines.extend(['   最终评估集不得用于初始化、调参、早停或检查点选择。',
                  '6. 保存基线身份、划分与种子清单、组件初态、各组配置及恢复预算、评估输出和原始测量。'])
    return '\n'.join(lines)


def enforce_workflow_consistency(verification, required=False):
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
        valid = (type(claim.get('workflowContractVersion')) is int and claim['workflowContractVersion'] == 1
            and claim.get('designRole') == 'steps' and claim.get('kind') in {'proposal', 'suggestion', 'hypothesis'})
        errors = workflow_errors(claim.get('executionSpec')) if valid else ['invalid_workflow_contract']
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
                groups = budget.get('recovery', {}).get('groups', {})
                if any(group not in groups for c in spec['componentInitializations'] for group in c['appliesTo']):
                    errors.append('workflow.unknown_initialization_group')
        if errors:
            rejected.add(claim['claimId'])
            result.setdefault('rejected', []).append({'claimId': claim['claimId'],
                'reason': 'inconsistent_experiment_workflow', 'detail': ', '.join(errors)})
    result['accepted'] = [c for c in accepted if c.get('claimId') not in rejected]
    return result
