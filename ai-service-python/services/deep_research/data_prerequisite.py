"""Attach one bounded data-feasibility investigation to an experiment plan."""
from copy import deepcopy

QUESTION = ('拟议实验可使用哪些现有数据集或论文子集？核对实际场景/样本名称或数量、'
            '训练与评估划分；沿用其他论文子集时回查该来源，不以整个数据集替代子集。')
QUERY = 'datasets evaluation benchmark subset scenes sample names number train test split'
PROPOSED_QUESTION = ('核对拟选数据集及准确子集的身份和实际成员依据；命名选择核对场景/样本名，'
    '按数量或全量选择核对该子集数量，不以整个父数据集替代子集。拟议划分、分辨率和训练预算由方案明确选择；'
    '仅在用户要求复现或核对原设置时追查作者的这些设置。')
PROPOSED_QUERY = 'dataset benchmark subset scene sample membership names available count'
PROPOSED_PLANNING_GUIDANCE = '''For a proposed experiment, investigate factual prerequisites:
the intervention's actual mechanism and the selected dataset/subset's identity and membership.
Named selection needs evidence for the named units; counted/all selection needs the exact
subset count. Do not substitute the parent dataset. A NEW proposed split, resolution,
optimizer or finite training budget is a design choice, not an author-setting lookup.
Ask for original view counts, splits or iterations only if the user requests those facts
or reproduction, or a specific claim depends on them. Preserve explicit original-fact
requests; proposed choices cannot replace them. Keep auxiliary queries narrowly relevant.'''


def ensure_data_prerequisite(plan, source_ids, question, *, proposed_protocol=False):
    """Keep user sub-question count; route acquisition through existing tracked tools.

    This auxiliary investigation is not itself an extra requested answer section.
    Its unresolved gaps still need the ordinary final coverage decision, and any
    chosen data claim separately requires the source-bound availability audit.
    """
    result = deepcopy(plan)
    if not result:
        return result
    sources = list(dict.fromkeys(source_ids))
    excerpt = question[:160]
    expected = {'question': PROPOSED_QUESTION if proposed_protocol else QUESTION,
                'searchQuery': PROPOSED_QUERY if proposed_protocol else QUERY, 'requiredSources': sources,
                'purpose': 'supporting_research' if len(excerpt) >= 8 else 'answer_requirement',
                'requestExcerpt': excerpt}
    if proposed_protocol:
        expected['dataPrerequisiteContractVersion'] = 1
    if any('completionCriteria' in o for item in result for o in item['obligations']):
        expected['completionCriteria'] = [{'criterionId': 'available_data',
            'requirement': '核对拟议数据选择的现有场景或样本依据，以及已取得证据的范围。',
            'responseType': 'identification'}]
    obligations = [o for item in result for o in item['obligations']]
    if any(all(o.get(k) == v for k, v in expected.items()) for o in obligations):
        return result
    used = {o['obligationId'] for o in obligations} | {item['itemId'] for item in result}
    identity, suffix = 'data_availability', 0
    while identity in used:
        suffix += 1
        identity = f'data_availability_{suffix}'
    result[0]['obligations'].insert(0, {'obligationId': identity, **expected})
    return result
