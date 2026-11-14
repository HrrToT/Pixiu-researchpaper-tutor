"""Measure the actual shared publication allowance without rewriting content."""
from copy import deepcopy
import json


def guidance(report, scope_ids, count, limit):
    blank={**deepcopy(report),'claims':[{**deepcopy(c),'text':'','conditions':{}} for c in report['claims']]}
    base=count(blank)
    reserved=count({**blank,'claims':[deepcopy(c) if c['claimId'] in scope_ids else empty
        for c,empty in zip(report['claims'],blank['claims'])]})
    rows=[]
    for index,claim in enumerate(report['claims']):
        single=deepcopy(blank);single['claims'][index]=deepcopy(claim)
        rows.append({'claimId':claim['claimId'],'kind':'scope' if claim['claimId'] in scope_ids else 'prose',
                     'currentCharactersAboveFixed':count(single)-base})
    budget={'totalCharacters':limit,'currentCompleteCharacters':count(report),
        'fixedDisplayAndAcceptedCharacters':base,'currentScopeReserveCharacters':reserved-base,
        'ordinaryProseSharedCharactersIfScopeUnchanged':max(0,limit-reserved),
        'pointMeasurements':rows}
    return '''\nServer-measured publication budget (capacity metadata, NOT paper facts):
'''+json.dumps(budget,ensure_ascii=False,separators=(',',':'))+'''
The shared ordinary-prose allowance applies to ALL prose text AND conditions together,
after retaining the CURRENT scope wording, fixed accepted points and display overhead.
Shorten prose enough to fit that allowance; a small edit cannot solve a large overrun.
If you shorten editable scope wording, its measured savings can be redistributed;
the final compiled answer must still fit the same total limit. Scope text is compiled
by the service, so its labels and every field string consume space too. Preserve all
original points, scientific distinctions, necessary conditions and frozen comparison
fields. Do not drop a point or weaken a judgement to fit. Return only the requested
response schema; never copy these budget numbers into the scientific answer.
These measurements are guidance only. The unchanged final rendered-length guard and
independent source/scientific/coverage checks still decide acceptance.
'''
