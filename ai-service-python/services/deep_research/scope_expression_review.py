"""Review observed facts and evidence entailment separately, with own bindings."""
from copy import deepcopy
import json
import re

from services.deep_research.scope_expression import materialize


def enabled(record):
    return (type(record.get('scopeExpressionReviewContractVersion')) is int
            and record['scopeExpressionReviewContractVersion'] in (1,2))


def context_for_record(record, claims):
    if not enabled(record): return {}
    state = record.get('state', {})
    if not isinstance(state,dict): return {}
    initial = state.get('synthesisScopeExpressionAudit')
    entries = list(initial) if isinstance(initial,list) else []
    repair = state.get('repairBatchState')
    batches = repair.get('scopeExpressionAudit', {}) if isinstance(repair,dict) else {}
    if isinstance(batches,dict):
        for rows in batches.values():
            if isinstance(rows,list): entries.extend(rows)
    result = {}
    for claim in claims:
        candidates = {}
        for entry in entries:
            if (not isinstance(entry,dict) or entry.get('claimId') != claim.get('claimId')
                    or entry.get('renderedText') != claim.get('text') or 'expression' not in entry): continue
            try:
                rebuilt, _ = materialize({**claim,'text':'','scopeExpression':entry['expression']})
            except (TypeError,ValueError): continue
            if rebuilt['text'] != claim.get('text'): continue
            key = json.dumps(entry['expression'],ensure_ascii=False,sort_keys=True)
            candidates[key] = entry['expression']
        if len(candidates)==1:
            result[claim['claimId']] = deepcopy(next(iter(candidates.values())))
    return result


def guidance(context):
    return '''
Structured scope-expression review. These expressions are UNVERIFIED declarations
equivalent to the actual target text, never evidence, approval or private reasoning.
Review every observed setting as a factual assertion: its exact subject/attribute/value
needs its OWN supplied quotation/context. Tested points do not establish threshold
intervals (e.g. an observation at 66% does not establish <=70%).
Review each notEstablished proposition as an entailment question about THESE cited
passages and their supplied context, not a claim that the paper omitted experiments:
- If the exact quantified proposition follows from the source (including a universal
  theorem or broader reported result), relation=entailed: the boundary must FAIL.
- If only specific observations are supplied and no valid inference establishes the
  explicit broader proposition, relation=not_entailed. This requires explaining the
  scope gap; it does NOT require an author-written disclaimer. It does not assert
  that the proposition is false or that authors never tested it.
- Ambiguous quantification, unspecified comparison domain or unresolved reasoning
  is relation=undetermined, never a passed boundary. Do not silently insert 'all'.
A passed overall verdict still needs the existing factual/scope/result audits PLUS
scopeExpressionAudit={"observedSettings":[{"index":0,"setting":exact setting object,
"status":"supported","premises":[{"evidenceId":"own E ID","path":["quote"]}]}],
"notEstablished":[{"index":0,"proposition":"exact proposition",
"relation":"not_entailed","quantification":"explicit","isNegation":false,
"authorOmission":false,"reason":"why the actual cited premises do not entail it",
"premises":[{"evidenceId":"own E ID","path":["quote"]}]}]}.
Arrays follow expression order with exact counts, including empty arrays. Each item
needs nonempty own source premises. An unchanged supplied sourceContext path is also
allowed; or use evidenceId+quote with an exact original excerpt, never both forms.
Judge the full available source field, not just a cherry-picked phrase. A valid path
does not prove support. If any fact fails, boundary is entailed/ambiguous, or one
clause is unsupported, return failed with the precise reason. Never upgrade a failed
verdict merely because this structure is present.
Unverified scope expressions by actual target claimId:
''' + json.dumps(context,ensure_ascii=False,separators=(',',':')) + '\n'


def _bound(premises, own):
    if not isinstance(premises,list) or not 1 <= len(premises) <= 20: return False
    from services.deep_research.audit_source_fields import resolve
    normalize=lambda s:re.sub(r'\s+',' ',s).strip()
    for row in premises:
        if not isinstance(row,dict): return False
        if 'path' in row:
            if resolve(row,own) is None: return False
        else:
            if set(row)!={'evidenceId','quote'}: return False
            item=own.get(row.get('evidenceId')) if isinstance(row.get('evidenceId'),str) else None
            quote=row.get('quote')
            if not item or not isinstance(quote,str) or not quote.strip(): return False
            context=item.get('sourceContext','')
            if isinstance(context,dict): context=json.dumps(context,ensure_ascii=False)
            if not any(normalize(quote) in normalize(s) for s in (item.get('quote',''),str(context))): return False
    return True


def validate(claim, expression, verdict, evidence):
    audit=verdict.get('scopeExpressionAudit')
    if not isinstance(audit,dict) or set(audit)!={'observedSettings','notEstablished'}:
        return ['scope_expression_audit_missing']
    own={e['evidenceId']:e for e in evidence if e.get('evidenceId') in claim.get('evidenceRefs',[])}
    for name in ('observedSettings','notEstablished'):
        rows=audit[name]; expected=expression[name]
        if not isinstance(rows,list) or len(rows)!=len(expected): return ['scope_expression_items_missing']
        for index,(row,target) in enumerate(zip(rows,expected)):
            if not isinstance(row,dict) or type(row.get('index')) is not int or row['index']!=index:
                return ['scope_expression_item_not_bound']
            if name=='observedSettings':
                if row.get('setting')!=target or row.get('status')!='supported':
                    return ['scope_observed_setting_not_supported']
            else:
                if (row.get('proposition')!=target or row.get('relation')!='not_entailed'
                        or row.get('quantification')!='explicit' or row.get('isNegation') is not False
                        or row.get('authorOmission') is not False or not isinstance(row.get('reason'),str)
                        or not row['reason'].strip()):
                    return ['scope_boundary_entailment_unresolved']
            if not _bound(row.get('premises'),own): return ['scope_expression_premises_not_bound']
    return []
