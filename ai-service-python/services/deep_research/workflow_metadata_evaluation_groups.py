"""Authored per-arm versus shared evaluations; never splits an old proposal."""
from copy import deepcopy
import json

from services.deep_research import workflow_metadata_fit_budget as typed

NAME='typed_evaluation_groups_steps_v1'
POLICY=typed.scoped.POLICY+(
    'evaluate uses scalar group and sharing:per_group. evaluate_shared uses groups '
    'and sharing:shared, only when every input exists in every consuming arm. '
    'Declare separate evaluations for different arm inputs; preserve every arm measurement. '
    'Every declared arm needs an evaluate/evaluate_shared/observe measurement. '
    'These are authored choices, not implicit filtering of unavailable states.\n'
)


def expanded(value):
    result=deepcopy(value)
    if not isinstance(result,dict) or not isinstance(result.get('steps'),list):
        raise ValueError('Incomplete evaluation ownership metadata')
    issues=[]
    for i,step in enumerate(result['steps']):
        if not isinstance(step,dict):raise ValueError('Invalid authored step')
        kind=step.get('kind')
        if kind=='evaluate':
            if 'group' not in step or 'groups' in step:
                raise ValueError('Evaluation requires one explicit group field')
            step['groups']=[step.pop('group')]
            expected='per_group'
        elif kind=='evaluate_shared':
            if 'groups' not in step or 'group' in step:
                raise ValueError('Shared evaluation requires explicit groups')
            step['kind']='evaluate';expected='shared'
        else:continue
        if step.get('sharing')!=expected:
            issues.append({'code':'evaluation.sharing','path':f'/steps/{i}/sharing',
                'actual':deepcopy(step.get('sharing')),'expected':expected})
    return result,issues


def coverage_issues(value):
    arms=set();observed=set()
    def groups(items):
        if not isinstance(items,list):return set()
        return {g for g in items if isinstance(g,str) and g and not set(g)-{'0','1'}}
    for component in value.get('components',[]):
        if isinstance(component,dict):arms.update(groups(component.get('appliesTo')))
    for step in value['steps']:
        current=groups(step.get('groups'))
        if step.get('kind') in ('observe','record'):
            current=groups([step.get('group')])
        arms.update(current)
        if step.get('kind') in ('evaluate','observe'):observed.update(current)
    missing=sorted(arms-observed)
    return ([{'code':'evaluation.coverage','path':'/steps','requiredGroups':sorted(arms),
        'observedGroups':sorted(observed),'missingGroups':missing,
        'expected':'explicit evaluate/evaluate_shared/observe for every declared arm; no dropped control'}]
        if missing else [])


def complete_scaffolding(value):
    try:return typed.complete_scaffolding(expanded(value)[0])
    except (ValueError,TypeError,RecursionError):return False


def decode(value):
    lowered,issues=expanded(value)
    if issues or coverage_issues(lowered):raise ValueError('Invalid evaluation ownership or coverage')
    return typed.decode(lowered)


def field_feedback(value,aliases):
    lowered,issues=expanded(value)
    result=typed.field_feedback(lowered,aliases)
    result['issues']+=issues+coverage_issues(lowered)
    for issue in result['issues']:
        parts=issue['path'].split('/')
        if len(parts)>=4 and parts[1]=='steps' and parts[3]=='groups':
            step=value['steps'][int(parts[2])]
            if step['kind']=='evaluate':
                issue.update(path='/steps/'+parts[2]+'/group',actual=deepcopy(step['group']))
                issue.pop('actualInInvalidMetadata',None)
    return result


def generation_prompt(source_data,context):
    from services.deep_research.workflow_metadata_input import input_text
    return POLICY+typed.COUNT_POLICY+input_text({'authoritativeInput':json.loads(source_data),'unitContext':context})


def revision_prompt(source_data,value,feedback):
    from services.deep_research.workflow_metadata_input import input_text
    return POLICY+typed.COUNT_POLICY+'Revise invalidMetadata using ALL authoritative input and fieldFeedback.\n'+input_text({
        'authoritativeInput':json.loads(source_data),'invalidMetadata':value,'fieldFeedback':feedback})


def descriptor():
    result=typed.descriptor();result['name']=NAME
    branches=[]
    for branch in result['schema']['$defs']['step']['anyOf']:
        props=branch['properties']
        if 'evaluate' in props['kind'].get('enum',[]):
            single=deepcopy(branch);shared=deepcopy(branch)
            for evaluation in (single,shared):
                evaluation.pop('allOf',None)
                evaluation['properties']['updates']={'const':[]}
            single['properties'].update(kind={'const':'evaluate'},sharing={'const':'per_group'})
            single['properties']['group']=single['properties'].pop('groups')['items']
            single['required']=[('group' if k=='groups' else k) for k in single['required']]
            shared['properties'].update(kind={'const':'evaluate_shared'},sharing={'const':'shared'})
            branches.extend((single,shared))
            props['kind']={'const':'setup'};branch.pop('allOf',None)
        branches.append(branch)
    result['schema']['$defs']['step']['anyOf']=branches
    return result
