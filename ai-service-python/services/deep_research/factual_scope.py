"""Distinguish observed scope from necessary or universal scientific conditions."""
import json
import re


def enabled(record):
    return (type(record.get('factualScopeContractVersion')) is int
            and record['factualScopeContractVersion'] in (1,2))


def drafting_schema_enabled(record):
    return (type(record.get('factualScopeContractVersion')) is int
            and record['factualScopeContractVersion']==2)


DRAFTING_SCHEMA={'premiseStatus':'choose established, contradicted or not_established',
    'observations':[{'evidenceId':'own supplied E ID','quote':'exact original excerpt'}],
    'scopeDecision':'choose reported_case, bounded_inference, exclusive or universal',
    'unresolved':'specific evidence boundary; empty only when none remains'}


DRAFT_GUIDANCE = '''Before writing each factual claim's text, fill draftingBasis FIRST:
{"premiseStatus":"established|contradicted|not_established",
 "observations":[{"evidenceId":"own E ID","quote":"exact short original excerpt"}],
 "scopeDecision":"reported_case|bounded_inference|exclusive|universal",
 "unresolved":"specific boundary, or empty"}.
This is private, UNVERIFIED drafting metadata; never put it in prose or treat it as proof.
Check the user's premise rather than obeying a why-question's assumed conclusion.
Do not write a stronger conclusion than the observations establish. In particular:
- 'observed at a setting' does NOT mean 'works ONLY at that setting'; failure at one
  other setting does not establish an exhaustive boundary, threshold or necessary condition.
- Unknown alignment does NOT mean conditions differ. State what has and has not been
  established. A raw ratio can be calculated but is not a controlled method speedup.
- A supplemental/ablation baseline is NOT automatically the requested original method.
  Bind the actual compared subjects and protocol before making even a qualitative claim.
- Evidence-bounded unknown scope is NOT an assertion that authors omitted experiments.
Write the qualified verdict, its minimum source premises and the remaining scope limit.
If the user's premise is too strong, correct it directly. Do not fill the gap with a list
of numbers or categorical impossibility. Preserve requested conditions/unknowns in the
short answer; omit secondary examples. Do not repeat conditions already in text.
'''


def audit_prompt(targets):
    return '\nScope-strength audit for factual targets: '+json.dumps(targets,separators=(',',':'))+'''
A passed verdict also MUST include:
"scopeAudit":{"claimStrength":"bounded|exclusive|universal",
 "evidenceStrength":"bounded|exclusive|universal","supported":true,
 "statementExcerpt":"exact words from target text/condition identifying its scope",
 "premises":[{"evidenceId":"own E ID","quote":"exact original quote/context excerpt"}]}
Assess the strength of the ACTUAL assertion, not a charitable weaker paraphrase.
'Only applies/only works/only at ... holds' asserts an exclusive necessary condition.
'The selected evidence only supports ...' describes bounded knowledge instead.
An observation at a setting, and failures at some other settings, are bounded premises;
they do not prove that no other setting can work. Reject any stronger exclusive/universal
conclusion unless original evidence explicitly establishes that full strength for the
same method, result and scope. Do not infer such strength from the model's explanation.
Also reject an ablation comparison relabelled as the original baseline, and unknown
alignment presented as a known difference. Quote the ACTUAL asserted scope and its own
support. Different citation counts or numeric matches do not establish logical support.
For unsupported scope return failed with the precise overreach; never rewrite the target
and pass the weaker version. This audit is internal and grants no factual approval.
'''


def validate_audit(claim,verdict,evidence):
    if claim.get('kind') not in {'reported','inference'}:
        return []
    audit=verdict.get('scopeAudit')
    strengths={'bounded','exclusive','universal'}
    if (not isinstance(audit,dict) or not isinstance(audit.get('claimStrength'),str)
            or not isinstance(audit.get('evidenceStrength'),str)
            or audit['claimStrength'] not in strengths or audit['evidenceStrength'] not in strengths
            or audit.get('supported') is not True):
        return ['scope_strength_not_established']
    # Bounded observations cannot establish an exclusive or universal law.
    # Exclusive and universal assertions are different strengths, not substitutes.
    if audit['claimStrength']!='bounded' and audit['claimStrength']!=audit['evidenceStrength']:
        return ['scope_stronger_than_evidence']
    excerpt=audit.get('statementExcerpt')
    conditions=claim.get('conditions') or {}
    fields=[claim.get('text',''),*(str(v) for v in conditions.values())] if isinstance(conditions,dict) else [claim.get('text','')]
    if not isinstance(excerpt,str) or not excerpt.strip() or not any(excerpt in field for field in fields):
        return ['scope_statement_not_bound']
    own={e['evidenceId']:e for e in evidence if e.get('evidenceId') in claim.get('evidenceRefs',[])}
    rows=audit.get('premises')
    if not isinstance(rows,list) or not 1 <= len(rows) <= 20:
        return ['scope_premises_not_bound']
    normalize=lambda value:re.sub(r'\s+',' ',value).strip()
    for row in rows:
        ev=own.get(row.get('evidenceId')) if isinstance(row,dict) else None
        quote=row.get('quote') if isinstance(row,dict) else None
        if not ev or not isinstance(quote,str) or not quote.strip():
            return ['scope_premises_not_bound']
        context=ev.get('sourceContext','')
        context=json.dumps(context,ensure_ascii=False) if isinstance(context,dict) else str(context)
        if not any(normalize(quote) in normalize(text) for text in (ev.get('quote',''),context)):
            return ['scope_premises_not_bound']
    return []
