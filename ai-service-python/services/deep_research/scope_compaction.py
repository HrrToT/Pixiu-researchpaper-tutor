"""One joint wording edit; recompile authored scope and retain no old approval."""
from copy import deepcopy
import json

from services.deep_research.answer_constraints import requested_character_limit, visible_count, normalize_conditions
from services.deep_research.scope_expression import materialize, guidance


def enabled(record):
    return (type(record.get('scopeCompactionContractVersion')) is int
            and record['scopeCompactionContractVersion'] == 1
            and type(record.get('scopeExpressionContractVersion')) is int
            and record['scopeExpressionContractVersion'] == 2)


def compact(report, audits, question, invoke, parse, *, output_kind='', evidence=(), presentation_version=0):
    """Return revised report and matching unchecked ASTs, or reject atomically.

    All existing points, kinds, citations, obligations and table bindings remain.
    Wording of ordinary facts and scope fields shares one rendered-length budget.
    Semantics are not certified here: the normal verifier checks the new wording.
    """
    if (not isinstance(report,dict) or not isinstance(report.get('claims'),list)
            or not isinstance(audits,list)
            or any(not isinstance(c,dict) or not isinstance(c.get('claimId'),str)
                   or not c['claimId'].strip() or not isinstance(c.get('text'),str)
                   for c in report['claims'])
            or any(not isinstance(a,dict) for a in audits)):
        return None, audits
    source = normalize_conditions(deepcopy(report))
    if any(not isinstance(c.get('conditions',{}),dict) for c in source['claims']):
        return None, audits
    original = {c['claimId']:c for c in source['claims']}
    if len(original) != len(source['claims']): return None, audits
    expressions = {}
    for audit in audits:
        key = audit.get('claimId')
        if key not in original or key in expressions: return None, audits
        try:
            rebuilt, _ = materialize({**original[key], 'text':'',
                                      'scopeExpression':audit.get('expression')}, 2)
        except (ValueError, TypeError): return None, audits
        if rebuilt != original[key] or audit.get('renderedText') != rebuilt['text']:
            return None, audits
        expressions[key] = deepcopy(audit['expression'])
    limit = requested_character_limit(question)
    def count(value):
        return visible_count(value,limit,output_kind,evidence,presentation_version)
    if not limit or count(source) <= limit: return source, deepcopy(audits)
    overhead = count({**source,'claims':[{**c,'text':'','conditions':{}} for c in source['claims']]})
    available = limit - overhead
    if available <= 0: return None, audits
    from services.deep_research.table_bindings import bound_table_context
    inputs = [{
        'claimId':key,'text':'' if key in expressions else c['text'],
        'conditions':{} if key in expressions else c.get('conditions',{}),
        'scopeExpression':expressions.get(key),
        'requiredTableContext':bound_table_context(c,evidence),
    } for key,c in original.items()]
    prompt = f'''Compress ALL answer points together in Chinese. Human question: {question}
The complete rendered answer must fit {limit} characters; headings/notices use
{overhead}, leaving {available} for text, conditions and compiled scope statements.
Share that allowance across ordinary facts AND scope statements. Do not preserve
a long scope statement at the expense of the answer. Do not add facts or delete,
merge or add points. Preserve every input claimId exactly once in input order.
Return ONLY {{"claims":[{{"claimId":"original ID","text":"...","conditions":{{}},
"scopeExpression":null}}]}}. These are the only four fields per row.
Ordinary points keep scopeExpression=null. Retain necessary labels, conditions,
method/group/metric/value identity from requiredTableContext when retaining numbers.
Scope points keep text="", conditions={{}} and a scopeExpression object. Shorten
its authored field wording, keeping the same observation and boundary counts,
quantifiers, actual domains, subjects, comparators and predicates. Do not replace
the question's criterion with a stronger and easier-to-reject guarantee. Do not
convert an epistemic boundary into a negative result or missing-experiment claim.
The service compiles each observation as subject，attribute=value under
所引来源报告的评估设置包括： and each boundary as
这些引用不足以证明：在范围「domain」内的所有情形中/至少一种情形中，subject相对于comparator，predicate。
These prefixes, punctuation and all field strings consume the shared allowance.
No old evidence verdict is retained: all new wording will be independently checked.
''' + guidance(2) + '\nInput:\n' + json.dumps(inputs,ensure_ascii=False,separators=(',',':'))
    response = invoke(prompt)
    if response.get('finishReason',response.get('finish_reason')) == 'length': return None, audits
    value = parse(response.get('content',''))
    if not isinstance(value,dict) or set(value) != {'claims'} or not isinstance(value['claims'],list):
        return None, audits
    rows = value['claims']
    if (any(not isinstance(c,dict) or set(c) != {'claimId','text','conditions','scopeExpression'} for c in rows)
            or [c['claimId'] for c in rows] != list(original)): return None, audits
    revised, new_audits = [], []
    for row in rows:
        key = row['claimId']; old = expressions.get(key); expr = row['scopeExpression']
        if old is None and expr is not None: return None, audits
        if old is not None:
            if not isinstance(expr,dict) or set(expr) != set(old): return None, audits
            if any(not isinstance(expr[name],list) or len(expr[name]) != len(old[name]) for name in old):
                return None, audits
            if any(not isinstance(new,dict) or new.get('quantifier') != before['quantifier']
                   for new,before in zip(expr['notEstablished'],old['notEstablished'])):
                return None, audits
        if not isinstance(row['text'],str) or not isinstance(row['conditions'],dict): return None, audits
        try:
            claim,audit = materialize({**original[key],**row},2)
        except (ValueError,TypeError): return None, audits
        if not claim['text'].strip(): return None, audits
        revised.append(claim)
        if audit: new_audits.append(audit)
    result = {**source,'claims':revised}
    return (result,new_audits) if count(result) <= limit else (None,audits)
