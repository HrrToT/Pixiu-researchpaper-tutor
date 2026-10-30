"""Fixed request-owned completion checks, never source-invented requirements."""
from copy import deepcopy
import json


def enabled(record):
    return (type(record.get('requestCoverageContractVersion')) is int
            and record['requestCoverageContractVersion'] in (1,2,3)
            and record.get('state',{}).get('outputKind') in
            ('claim_verification','paper_comparison','direction_survey','research_entry'))


def contract(plan,question,*,whole_question_id=None,literal_request_dimensions=False):
    result=[]
    for item in plan:
        for o in item.get('obligations',[]):
            checks=[{'checkId':'criterion:'+c['criterionId'],'requirement':c['requirement'],
                     'criterionId':c['criterionId'],'responseType':c['responseType']}
                    for c in o.get('completionCriteria',[])]
            if not checks:checks=[{'checkId':'request','requirement':o.get('question') or question}]
            if literal_request_dimensions and o['obligationId']==whole_question_id:
                from services.deep_research.evidence_requirements import _request_parts
                from services.deep_research.request_dimensions import split_dimensions
                from services.deep_research.request_context import ResearchQuestion
                layers=(getattr(question,'point_instruction_layers',question.instruction_layers)
                        if isinstance(question,ResearchQuestion) else (question,))
                # Only the latest explicit human wording can add literal checks;
                # model clarification questions and parent artifact prose cannot.
                literal=layers[0] if layers else ''
                dimensions=[d for part in _request_parts(literal) for d in (split_dimensions(part) or [])]
                # Keep the full original question regardless of whether literal
                # dimensions can be safely separated. Never replace its scope.
                if 0<len(dimensions)<=4:
                    checks.extend({'checkId':'literal_dimension_'+str(i+1),**d} for i,d in enumerate(dimensions))
            result.append({'obligationId':o['obligationId'],'question':o.get('question') or question,
                           'purpose':o.get('purpose','answer_requirement'),'checks':checks})
    return result


def prompt(question,requirements,claims,metadata,evidence_marker,policy):
    # Preserve substantive quality standards but replace the open-ended
    # aspect-generation task and its redundant status/schema instructions.
    quality=policy.split('Before marking covered, enumerate',1)[0]
    return f'''Audit the FINAL ACCEPTED ANSWER against the FIXED REQUEST CHECKLIST.
Question: {question}
Fixed checks (requirements, never paper facts): {json.dumps(requirements,ensure_ascii=False,separators=(',',':'))}
Accepted final claims: {json.dumps(claims,ensure_ascii=False,separators=(',',':'))}
Server-rendered answer metadata: {json.dumps(metadata,ensure_ascii=False,separators=(',',':'))}
Available evidence for detecting omissions, NOT inventing requirements: {evidence_marker}
{quality}
Only the fixed checks define this audit's requirements. Read EACH complete accepted
claim and conditions; several claims may jointly satisfy one check. Bind all relevant
claims, not just the first. Your own missing binding is not missing answer content.
Do not replace a request for evidence limits with 'the paper did not test other X'.
Do not turn a bounded reported result into an exclusive domain or add a demand to
prove author-wide absence. Source facts can reveal a genuinely omitted condition
needed to answer a fixed check, but cannot become extra required check IDs or text.
Do not rewrite, approve or reject scientific claims here: factual checks are separate.
For each listed obligation return exactly one object, with exactly obligationId and
checks. Each check has exactly checkId,status,bindings,reason. Copy every fixed ID
once; no requirement text, aspects, criteria, gapDetail or overall status in output.
status is covered|partial|missing. reason is a concise explanation (1-800 characters)
of actual answer coverage, not a paper-absence assertion or a command to the repairer.
Bindings are actual accepted claim field references: {{"claimId":"ID","field":"text"}}
or field="conditions". Covered/partial have bindings when content is relevant;
missing uses []. Covered needs sufficient content, never only citation/ID presence.
Return ONLY a JSON array, e.g. [{{"obligationId":"fixed ID","checks":[
{{"checkId":"fixed ID","status":"partial","bindings":[],"reason":"what part of the fixed request remains unanswered"}}]}}].
Only supporting_research obligations may instead return exactly obligationId and
notRequired: {{"reason":"specific reason >=12 chars","requestExcerpt":"exact original question excerpt >=8 chars",
"bindings":[{{"claimId":"ID","field":"text"}}]}}. This never exempts the original
question or an answer_requirement and still undergoes the existing exemption checks.
'''


def normalize(value,requirements):
    """Project one decision per fixed check; do not infer semantic coverage."""
    if not isinstance(value,list):return None
    ids=[r.get('obligationId') if isinstance(r,dict) else None for r in value]
    expected=[r['obligationId'] for r in requirements]
    if any(not isinstance(k,str) for k in ids) or len(set(ids))!=len(ids) or set(ids)!=set(expected):return None
    by_id={r['obligationId']:r for r in value};out=[]
    for required in requirements:
        row=by_id[required['obligationId']]
        if set(row)=={'obligationId','notRequired'}:
            n=row['notRequired']
            if (required['purpose']!='supporting_research' or not isinstance(n,dict)
                    or set(n)!={'reason','requestExcerpt','bindings'}):return None
            out.append({'obligationId':row['obligationId'],'status':'not_required',**deepcopy(n)})
            continue
        if set(row)!={'obligationId','checks'} or not isinstance(row['checks'],list):return None
        checks=row['checks'];keys=[c.get('checkId') if isinstance(c,dict) else None for c in checks]
        wanted=[c['checkId'] for c in required['checks']]
        if any(not isinstance(k,str) for k in keys) or len(set(keys))!=len(keys) or set(keys)!=set(wanted):return None
        actual={c['checkId']:c for c in checks};aspects=[];criteria=[];bindings=[];reasons=[]
        for fixed in required['checks']:
            c=actual[fixed['checkId']]
            if (set(c)!={'checkId','status','bindings','reason'}
                    or c['status'] not in ('covered','partial','missing') or not isinstance(c['bindings'],list)
                    or not isinstance(c['reason'],str) or not 1<=len(c['reason'].strip())<=800
                    or c['status']=='missing' and c['bindings']):return None
            binding=deepcopy(c['bindings'])
            for b in binding:
                if b not in bindings:bindings.append(deepcopy(b))
            aspects.append({'aspectId':fixed['checkId'],'requirement':fixed['requirement'],
                'basis':{'kind':'request','excerpt':required['question']},'status':c['status'],'bindings':binding})
            if 'criterionId' in fixed:
                criteria.append({'criterionId':fixed['criterionId'],'responseType':fixed['responseType'],
                                 'status':c['status'],'bindings':deepcopy(binding)})
            reasons.append({'checkId':fixed['checkId'],'reason':c['reason']})
        status=('covered' if all(a['status']=='covered' for a in aspects) else
                'missing' if all(a['status']=='missing' for a in aspects) else 'partial')
        result={'obligationId':row['obligationId'],'status':status,'bindings':bindings,
                'aspects':aspects,'criteria':criteria,'requestCheckReasons':reasons}
        if status!='covered':
            result['gapDetail']={'criterionIds':[c['criterionId'] for c in criteria if c['status']!='covered'],
                'aspectIds':[a['aspectId'] for a in aspects if a['status']!='covered'],
                'missingContent':'请补全本条固定要求中标为未满足的部分，具体要求见 missingAspects。',
                'reason':'此缺口由固定检查项的未满足状态汇总；模型说明不作为新增要求或论文事实。'}
        out.append(result)
    return out


DECISION_FOCUS = """
Decide coverage from the actual accepted answer below, read jointly across its points.
An explicit supported/partly supported/not supported/cannot establish assessment is a
judgement; do not demand an additional synonymous verdict label after it. Its reasoning
and relevant conditions still have to answer the fixed check. Words like 'supports' alone
are not sufficient if the assessed proposition or evidence-bounded explanation is absent.
For an unverified-scope request, identify which stronger inference the answer bounds and
whether that limit is relevant; do not require an exhaustive inventory of possible settings.
Partial/missing needs a concrete unanswered part of THAT fixed requirement. Do not contradict
an explicit answer sentence by saying it is absent, or add an experiment, threshold or
extra detail just because it occurs in the source. Brevity does not waive necessary content.
These rules grant no factual approval and no automatic coverage from keywords or IDs.
"""


def focus_answer(prompt_text, question, requirements, claims, metadata):
    """Move exact decision inputs after evidence and policies, without truncation."""
    heading = 'Audit the FINAL ACCEPTED ANSWER against the FIXED REQUEST CHECKLIST.\n'
    payload = (f'Question: {question}\n'
        + 'Fixed checks (requirements, never paper facts): '+json.dumps(requirements,ensure_ascii=False,separators=(',',':'))+'\n'
        + 'Accepted final claims: '+json.dumps(claims,ensure_ascii=False,separators=(',',':'))+'\n'
        + 'Server-rendered answer metadata: '+json.dumps(metadata,ensure_ascii=False,separators=(',',':'))+'\n')
    prefix=heading+payload
    if not prompt_text.startswith(prefix):
        raise ValueError('Coverage decision inputs do not match their serialized prefix')
    return heading+prompt_text[len(prefix):]+DECISION_FOCUS+'\nDecision inputs (fixed request and complete accepted answer):\n'+payload
