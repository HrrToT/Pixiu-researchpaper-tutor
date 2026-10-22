"""Explicit repair dispositions; coverage is never scientific acceptance."""
from collections import Counter
import json
import re


def add_contract(prompt,originals,*,version=1):
    ids=list(originals)
    def replacement(match):
        # Keep the complete original edit grammar, writable paths and value
        # rule. Coverage must not erase the schema it asks the model to follow.
        item=match[1][1:-1]
        if type(version) is int and version==2:
            return ('Return ONLY exactly one item per writable ID '+json.dumps(ids,separators=(',',':'))+
                ' (no omitted/duplicate/extra IDs): '+item+
                ' OR {"claimId":"ID","unresolved":"specific reason, at most600characters"}. '
                'Feedback is partial syntax, not the target list. Edits must fix ALL checks; otherwise '
                'explain unresolved, which is not a revision or approval.')
        return ('Return ONLY one JSON array item for EACH writable ID '+json.dumps(ids,separators=(',',':'))+
            '. Schema-feedback targets are additional syntax hints, NOT the full target list. '
            'Each item is exactly '+item+' OR {"claimId":"ID","unresolved":"specific reason, at most600characters"}. '
            'Nonempty edits must address ALL checks on that target. If a safe complete repair is not possible, '
            'explain the remaining gap; unresolved is not a revision or approval. No omitted/duplicate/extra IDs.')
    result,count=re.subn(r'^Return ONLY (\[\{.*\}\])\.$',replacement,prompt,count=1,flags=re.M)
    if count!=1:raise ValueError('Missing experimental edit response contract')
    return result


def partition(originals,response):
    expected=list(originals);known=set(expected)
    counts=Counter(r.get('claimId') for r in response if isinstance(r,dict) and isinstance(r.get('claimId'),str))
    edits=[];unresolved=[];invalid=set();unexpected=set();malformed=0
    for row in response:
        if not isinstance(row,dict) or not isinstance(row.get('claimId'),str):malformed+=1;continue
        cid=row['claimId']
        if cid not in known:unexpected.add(cid);continue
        if counts[cid]!=1:invalid.add(cid);continue
        if set(row)=={'claimId','edits'} and isinstance(row['edits'],list) and 1<=len(row['edits'])<=64:
            edits.append(row)
        elif (set(row)=={'claimId','unresolved'} and isinstance(row['unresolved'],str)
                and row['unresolved'].strip() and len(row['unresolved'])<=600):
            unresolved.append({'claimId':cid,'reason':row['unresolved']})
        else:invalid.add(cid)
    submitted=[r['claimId'] for r in edits];accounted=set(submitted)|{r['claimId'] for r in unresolved}
    missing=[cid for cid in expected if cid not in accounted]
    audit={'version':1,'expectedTargetIds':expected,'submittedEditIds':submitted,'unresolvedTargets':unresolved,
        'missingTargetIds':missing,'invalidTargetIds':[cid for cid in expected if cid in invalid],
        'unexpectedTargetIds':sorted(unexpected),'malformedEntries':malformed,
        'responseCoverageComplete':not(missing or unexpected or malformed),
        'scientificApproval':False}
    return edits,audit
