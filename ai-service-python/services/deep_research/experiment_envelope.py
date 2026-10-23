"""Version4 experimental input compaction; no scientific permission changes."""
from copy import deepcopy
import re

BASIS_BYTES=2500
DIRECT_PLAN_OPTION='_direct_experiment_plan'
REFERENCE_RULE=('Frozen question/requestExcerpt values with humanQuestionPrefixChars=N mean the exact first N '
    'Unicode characters of the Human question above, not a new requirement. A requiredSources value '
    '{sourceRef:P} means the exact registry[P].workId. Expand these references when interpreting the '
    'unchanged requirements; they grant no source or factual support.')
GAP_REFERENCE_RULE=('Gap {humanQuestionPrefixChars:N} means Question[:N] in Unicode characters. '
    '{requirementQuestionRef:ID} means that unique frozen obligation question after prefix expansion. '
    'Reconstruct exact gaps; references are not evidence.')


def compact_gap_references(gaps,question,obligations):
    result=[]
    for gap in gaps:
        if isinstance(gap,str) and len(gap)>=64 and isinstance(question,str) and question.startswith(gap):
            result.append({'humanQuestionPrefixChars':len(gap)});continue
        matches=[r.get('obligationId') for r in obligations if isinstance(r,dict)
            and isinstance(gap,str) and r.get('question')==gap and isinstance(r.get('obligationId'),str)]
        if len(matches)==1 and len(gap.encode('utf8'))>len(matches[0].encode('utf8'))+45:
            result.append({'requirementQuestionRef':matches[0]})
        else:result.append(deepcopy(gap))
    return result


def enabled(record):
    from services.deep_research.experiment_template import enabled as template_enabled
    return template_enabled(record) and record['experimentDraftContractVersion'] in (4,5,6)


def compact_obligations(obligations,question,sources,*,short_prefixes=False):
    result=deepcopy(obligations)
    for row in result:
        for key in ('question','requestExcerpt'):
            value=row.get(key)
            if (isinstance(value,str) and str(question).startswith(value)
                    and (len(value)>=64 or short_prefixes and len(value.encode('utf8'))>40)):
                row[key]={'humanQuestionPrefixChars':len(value)}
        if isinstance(row.get('requiredSources'),list):
            refs=[]
            for value in row['requiredSources']:
                matches=[alias for alias,source in sources.items() if source.get('workId')==value]
                refs.append({'sourceRef':matches[0]} if len(matches)==1 else value)
            row['requiredSources']=refs
    return result


def two_arm_request(question):
    from services.deep_research.experiment_intent import single_toggle_request
    if not isinstance(question,str):return False
    if re.search(r'四组|两(?:个)?因素|two[- ]factors?|four groups|2\s*[x×]\s*2',question,re.I):return False
    return single_toggle_request(question) or bool(
        re.search(r'两组|two groups',question,re.I) and re.search(
            r'跳过或执行|跳过.{0,20}(?:执行|启用)|skip.{0,25}(?:execute|enable)|with and without',question,re.I))
