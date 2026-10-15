"""Separate the requested proposal from the investigations that inform it."""
from copy import deepcopy


def ensure_experiment_deliverable(plan, question, source_ids):
    """Keep the complete user request mandatory; do not rewrite research as answered.

    This is a new-run contract. Original questions/queries/source requirements
    remain supporting investigations. The original request becomes a mandatory
    deliverable, including any explicitly requested original facts or explanation.
    Final scope review may exempt support only AFTER that deliverable and the
    whole original request are independently covered by the accepted answer.
    """
    result=deepcopy(plan)
    if not result or not isinstance(question,str) or not question.strip():
        return result
    excerpt=question[:160]
    expected={'question':question,'requiredSources':list(dict.fromkeys(source_ids)),
              'purpose':'answer_requirement','requestExcerpt':excerpt,
              'deliverableContractVersion':1,
              'completionCriteria':[
                  {'criterionId':'requested_scope','responseType':'explanation',
                   'requirement':'回应原问题明确要求的解释、比较和原论文事实；拟议设置不能替代用户要求的原始数据。给出有边界的假设与明确分组。'},
                  {'criterionId':'configuration','responseType':'procedure',
                   'requirement':'给出可执行的初始化、固定条件、数据选择与划分预检、训练或恢复预算；不以未知默认值代替具体选择。'},
                  {'criterionId':'execution_analysis','responseType':'procedure',
                   'requirement':'给出操作步骤、测量口径和与用户目标一致的结果判断规则。'},
                  {'criterionId':'limits','responseType':'limitation',
                   'requirement':'明确方案尚未执行，区分原文依据、拟议选择及结论适用边界，不承诺已有结果或保证新颖。'}]}
    obligations=[o for item in result for o in item.get('obligations',[])]
    existing=next((o for o in obligations if all(o.get(k)==v for k,v in expected.items())),None)
    for obligation in obligations:
        if obligation is existing:
            continue
        # Short requests cannot support an exemption trail; retain the stricter
        # existing purpose instead of inventing an excerpt.
        if len(excerpt.strip())>=8:
            obligation['purpose']='supporting_research'
            obligation['requestExcerpt']=excerpt
    if existing is not None:
        return result
    used={o['obligationId'] for o in obligations}|{item['itemId'] for item in result}
    identity='experiment_deliverable'
    while identity in used:identity+='_new'
    query=next((o.get('searchQuery') for o in obligations if o.get('searchQuery')),
               result[0].get('searchQuery') or question)
    result[0]['obligations'].insert(0,{'obligationId':identity,'searchQuery':query,**expected})
    return result
