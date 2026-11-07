"""Auditable, value-preserving JSON normalization for new initial plans only."""
import hashlib
import json


def enabled(record,node='plan'):
    from services.deep_research.initial_plan_instructions import enabled as instructions_enabled
    return (node=='plan' and isinstance(record,dict)
        and type(record.get('initialPlanResponseContractVersion')) is int
        and record['initialPlanResponseContractVersion']==1
        and instructions_enabled(record))


class _Pairs(list):
    pass


def _canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def parse(text):
    """Collapse equal decoded JSON values; conflicting duplicates never win."""
    if not isinstance(text,str) or len(text.encode('utf8'))>131072:
        raise ValueError('Invalid planning JSON size')
    def reject_constant(value):raise ValueError('Non-JSON constant')
    # This exact plan schema has only integer priority; every scientific number
    # or expression belongs in text. Refuse float tokens before binary rounding
    # could make distinct high-precision duplicates appear identical.
    def reject_float(value):raise ValueError('Non-integer planning JSON number')
    tree=json.loads(text,object_pairs_hook=_Pairs,parse_constant=reject_constant,parse_float=reject_float)
    duplicates=[]
    def visit(value,path,occurrence,depth):
        if depth>64:raise ValueError('Planning JSON depth exceeded')
        if isinstance(value,_Pairs):
            result={};first={}
            for index,(key,child) in enumerate(value):
                child=visit(child,[*path,key],[*occurrence,'pair',index,'value'],depth+1)
                if key in result:
                    if _canonical(result[key])!=_canonical(child):
                        raise ValueError('Conflicting duplicate planning key')
                    duplicates.append({'objectPath':path,'objectPairsPath':occurrence,'key':key,
                        'firstPairIndex':first[key],'duplicatePairIndex':index,
                        'valueSha256':hashlib.sha256(_canonical(child).encode('utf8')).hexdigest()})
                else:result[key]=child;first[key]=index
            return result
        if isinstance(value,list):
            return [visit(v,[*path,i],[*occurrence,'item',i],depth+1) for i,v in enumerate(value)]
        # Reject non-finite overflow as well as explicit NaN/Infinity tokens.
        _canonical(value)
        return value
    parsed=visit(tree,[],[],0);canonical=_canonical(parsed)
    return parsed,{'version':1,'mode':'identical_duplicate_keys_only',
        'inputSha256':hashlib.sha256(text.encode('utf8')).hexdigest(),
        'canonicalRootSha256':hashlib.sha256(canonical.encode('utf8')).hexdigest(),
        'duplicates':duplicates,'scientificApproval':False}


def validate_shape(plan,question):
    """Require the new requested shape before existing semantic/scope checks."""
    def exact(value,keys):
        if not isinstance(value,dict) or set(value)!=set(keys.split()):
            raise ValueError('Invalid initial plan fields')
    def text(value):
        if not isinstance(value,str) or not value.strip():raise ValueError('Invalid initial plan text')
    if not isinstance(plan,list) or not 1<=len(plan)<=4:raise ValueError('Initial plan needs1-4 items')
    for item in plan:
        exact(item,'itemId question obligations searchQuery dependencies priority')
        for key in ('itemId','question','searchQuery'):text(item[key])
        if type(item['priority']) is not int or item['priority'] not in (1,2,3):raise ValueError('Invalid initial plan priority')
        if not isinstance(item['dependencies'],list) or any(not isinstance(i,str) or not i.strip() for i in item['dependencies']):
            raise ValueError('Invalid initial plan dependencies')
        if not isinstance(item['obligations'],list) or not 1<=len(item['obligations'])<=2:
            raise ValueError('Initial plan needs1-2 obligations per item')
        for o in item['obligations']:
            exact(o,'obligationId question requiredSources searchQuery purpose requestExcerpt completionCriteria')
            for key in ('obligationId','question','searchQuery','requestExcerpt'):text(o[key])
            if o['purpose'] not in ('answer_requirement','supporting_research'):
                raise ValueError('Invalid initial plan purpose')
            minimum=8 if o['purpose']=='supporting_research' else min(8,len(question.strip()))
            if len(o['requestExcerpt'].strip())<minimum or o['requestExcerpt'] not in question:
                raise ValueError('Initial plan request excerpt is not literal')
            if not isinstance(o['requiredSources'],list) or any(not isinstance(s,str) or not s.strip() for s in o['requiredSources']):
                raise ValueError('Invalid initial plan sources')
            if not isinstance(o['completionCriteria'],list) or not 1<=len(o['completionCriteria'])<=4:
                raise ValueError('Invalid initial plan criteria')
            for c in o['completionCriteria']:
                exact(c,'criterionId requirement responseType')
                for key in ('criterionId','requirement'):text(c[key])
                if c['responseType'] not in ('identification','explanation','procedure','limitation'):
                    raise ValueError('Invalid initial plan response type')


def verify_saved(response):
    from services.deep_research.structured_output import normalize
    from services.deep_research.contracts import DeepResearchError
    if not isinstance(response,dict) or not isinstance(response.get('rawContent'),str):
        raise DeepResearchError('invalid_plan_response_audit','规划原始响应记录缺失，不能重新发送。')
    rebuilt=normalize('plan',{**response,'content':response['rawContent']},initial_plan_response=True)
    if (rebuilt['content']!=response.get('content')
            or rebuilt['structuredOutput']!=response.get('structuredOutput')):
        raise DeepResearchError('invalid_plan_response_audit','规划响应审计不匹配，不能重新发送。')
