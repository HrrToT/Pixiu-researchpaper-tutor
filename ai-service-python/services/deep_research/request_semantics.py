"""Keep source-access requirements owned by human instructions before freezing."""
from copy import deepcopy
import re


def enabled(record):
    return (type(record.get('requestSemanticsContractVersion')) is int
        and record['requestSemanticsContractVersion'] in (1,2))


def normalize_access_requirements(plan,question,*,version=1):
    if type(version) is not int or version not in (1,2,3):raise ValueError('Invalid request semantics policy')
    from services.deep_research.access_disclosure import access_only
    from services.deep_research.evidence_requirements import _outside_examples
    layers=getattr(question,'instruction_layers',(str(question),))
    result=deepcopy(plan);changes=[]
    for item in result:
        for obligation in item.get('obligations',[]):
            excerpt=obligation.get('requestExcerpt')
            criteria=obligation.get('completionCriteria',[])
            if (obligation.get('purpose')!='answer_requirement' or not isinstance(excerpt,str)
                    or len(excerpt.strip())<8 or not access_only(excerpt)
                    or len(criteria)!=1 or criteria[0].get('responseType')!='identification'):
                continue
            # Only a standalone access criterion can be projected. Never erase
            # scientific or mixed criteria under a generic access excerpt.
            description=criteria[0].get('requirement','')
            if not isinstance(description,str):continue
            access_description=re.sub(r'用户|助手|模型|系统|\bAI\b','',description).replace('标注','标明')
            if version==2:
                access_description=re.sub(r'[，,；;]?(?:并|且)?(?:指出|说明)(?:该|此)?信息在(?:材料|原文|文中)中?的(?:体现|位置|依据)[。.]?$','',access_description)
            if version==3:
                # Provenance-only wording is not a request for mechanisms,
                # results, numbers or comparisons. Unknown/scientific tokens
                # remain and keep the conservative access-only guard closed.
                access_description=re.sub(r'给出|指出|信息|该|此|其中|原文|中|在|体现|位置|文本|证明|标识|理由','',access_description)
            if not access_only(access_description):continue
            grounded=False
            for layer in layers:
                visible=_outside_examples(layer)
                for match in re.finditer(re.escape(excerpt),visible):
                    prefix=re.split(r'[。！？；，,\n]',visible[:match.start()])[-1]
                    if not re.search(r'不用|无需|不要|不必|取消|别',prefix):
                        grounded=True
            if not grounded:continue
            original={'question':obligation.get('question'),'completionCriteria':deepcopy(criteria)}
            obligation['question']=excerpt
            criteria[0]['requirement']=excerpt
            if original!={'question':excerpt,'completionCriteria':criteria}:
                changes.append({'obligationId':obligation['obligationId'],'requestExcerpt':excerpt,
                    'before':original,'after':{'question':excerpt,'completionCriteria':deepcopy(criteria)}})
    return result,changes


PLAN_GUIDANCE='''An access-disclosure request asks what THIS ASSISTANT obtained/cites,
not what the human personally read. Preserve the literal human access request in
requestExcerpt and as an identification criterion; do not invent the user's reading
history or convert access metadata into a scientific research question.'''


DRAFT_GUIDANCE='''Distinguish YOUR reading/learning recommendations from author facts.
Use kind proposal (or suggestion) for a recommended reading order or learning route.
Such ordinary advice is unexecuted guidance, not an experiment. Use reported for an
author-prescribed order ONLY if this claim's own quotation explicitly prescribes it;
the paper's section order alone does not prove an author recommendation. Never claim
the user read a paper. Server acquisition labels describe only actual cited excerpts.
Translate minimal/small accuracy loss as 精度损失较小 or 尽量减少精度损失 when supported,
not 最小/最低/所有方法中最优 without an actual comparative minimum in own evidence.'''

PLAN_GUIDANCE_V2='Access identification needs the actual acquisition label, not an invented requirement to find a statement about the application reading the paper inside that paper. Do not add a proof-location criterion unless the human explicitly requested it.'
