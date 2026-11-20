"""Rank experiment data prerequisites from explicit question conditions.

Text co-occurrence selects a candidate, never proves a scene/condition relation.
"""
import re

_CONDITIONS = {
    'emergence': (r'新出现|新出现内容|初始帧[^。；;]{0,12}(?:没有|不存在)|'
                  r'\bemerging\b|\bnewly[ -]appear\w*|\bnew objects?\b',
                  r'\bemerg\w*\b|\bnot present in (?:the )?(?:initial|first) frame\b'),
    'occlusion': (r'遮挡|\bocclu\w*\b',r'\bocclu\w*\b|遮挡'),
}


def requested_conditions(question):
    return [name for name,(ask,_) in _CONDITIONS.items() if re.search(ask,question or '',re.I)]


def condition_score(text,section,name):
    if name not in _CONDITIONS or re.search(r'related work|references|background',section or '',re.I):
        return 0
    body=re.split(r'\bContent:\s*',text or '',maxsplit=1)[-1]
    condition=list(re.finditer(_CONDITIONS[name][1],body,re.I))
    scenes=list(re.finditer(r'\b(?:scenes?|sequences?|samples?|subjects?|cohorts?)\b|场景|样本',body,re.I))
    evaluation=list(re.finditer(r'\b(?:ablation|evaluat\w*|experiments?|results?|stud(?:y|ies))\b|消融|实验|评估',body,re.I))
    # A dataset list or generic method motivation is not a data prerequisite.
    for anchor in condition:
        if any(abs(anchor.start()-s.start())<=900 for s in scenes) and any(
                abs(anchor.start()-e.start())<=900 for e in evaluation):
            return 10+min(3,len(condition))+bool(re.search(r'\bwithout\b|\bfail\w*\b|缺少|不能',body,re.I))
    return 0
