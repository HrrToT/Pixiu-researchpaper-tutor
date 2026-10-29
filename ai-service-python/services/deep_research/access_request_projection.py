"""Freeze acquisition identification from human intent, not generated prose style."""
from copy import deepcopy
import re

_SCIENCE=re.compile(r'实验|机制|结果|性能|对比|比较|指标|数值|算法|质量|速度|精度|损失|训练|推导|公式|方程|参数|假设|PSNR|SSIM|FPS|\bdB\b|[%±=<>]',re.I)


def enabled(record):
    return (type(record.get('accessRequestProjectionContractVersion')) is int
        and record['accessRequestProjectionContractVersion']==1)


def project(plan,question):
    from services.deep_research.access_disclosure import access_only
    from services.deep_research.evidence_requirements import _outside_examples
    layers=getattr(question,'instruction_layers',(str(question),))
    result=deepcopy(plan);changes=[]
    for item in result:
        for o in item.get('obligations',[]):
            excerpt=o.get('requestExcerpt');criteria=o.get('completionCriteria',[])
            if (o.get('purpose')!='answer_requirement' or not isinstance(excerpt,str)
                    or len(excerpt.strip())<8 or not access_only(excerpt)
                    or len(criteria)!=1 or criteria[0].get('responseType')!='identification'):
                continue
            q=o.get('question','');description=criteria[0].get('requirement','')
            if not isinstance(q,str) or not isinstance(description,str):continue
            # A generated metadata question may include a paper name/PDF
            # parenthesis. Neither grants a scientific requirement an exemption.
            if _SCIENCE.search(q) or _SCIENCE.search(description):continue
            if not (access_only(q) or re.search(r'实际.{0,8}(?:读到|阅读|获取|取得|获得|引用|依据)',q)):
                continue
            if not ('全文' in q and '摘要' in q):continue
            grounded=False
            for layer in layers:
                visible=_outside_examples(layer)
                for match in re.finditer(re.escape(excerpt),visible):
                    prefix=re.split(r'[。！？；，,\n]',visible[:match.start()])[-1]
                    if not re.search(r'不用|无需|不要|不必|取消|别',prefix):grounded=True
                # Explicit additional human requests cannot be erased under a
                # shorter generated excerpt, including provenance requests.
                parts=re.split(r'[。！？；，,\n]|(?:并且?|同时|以及|然后)(?=给出|说明|指出|解释|比较|对比|分析|计算|设计)',visible)
                if any(len(p.strip())>=4 and not access_only(p.strip()) and p.strip() in description
                       for p in parts):grounded=False;break
            if not grounded:continue
            before={'question':q,'completionCriteria':deepcopy(criteria)}
            o['question']=excerpt;criteria[0]['requirement']=excerpt
            after={'question':excerpt,'completionCriteria':deepcopy(criteria)}
            if before!=after:changes.append({'obligationId':o['obligationId'],'requestExcerpt':excerpt,
                'before':before,'after':after,'basis':'human_access_instruction'})
    return result,changes
