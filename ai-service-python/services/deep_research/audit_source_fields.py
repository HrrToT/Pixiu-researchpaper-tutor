"""Bind internal audits to unchanged fields actually shown to the verifier.

This avoids retyping PDF typography. It does not normalize source words, grant
new citations, expose hidden context or decide whether a premise implies a claim.
"""

GUIDANCE='''Internal source bindings for scopeAudit/comparisonAudit ONLY:
Use an unchanged field reference instead of retyping long quotations:
{"evidenceId":"own E ID","path":["quote"]}.
For actually supplied context use ["sourceContext"] when it is a string, or
["sourceContext","before"] / ["sourceContext","after"] when that field exists.
The server resolves the exact field from the SAME visible source; no field is generated.
Use only one representation per premise: evidenceId+path OR evidenceId+quote, never both.
For comparisonAudit.differences.left/right the same path form also includes the literal
value string, which must actually occur in the resolved field. Empty/missing fields,
foreign sources, arbitrary paths, source metadata and full documents are not allowed.
Choose only fields supporting the asserted subject and scope; a valid reference alone
is not logical support. Judge the unchanged claim independently before returning passed.
Do not apply this alternative to dataAvailability, designAudit or tableBindings; their
own schemas remain unchanged. The paper quotations themselves must remain unchanged.'''


def enabled(record):
    return (type(record.get('auditSourceFieldsContractVersion')) is int
            and record['auditSourceFieldsContractVersion'] in (1,2,3))


TARGET_GUIDANCE='''For scopeAudit's target binding, prefer "statementPath":["text"] instead
of retyping statementExcerpt. A specific existing string condition may use
["conditions","its exact key"]. Use exactly one of statementPath and statementExcerpt.
This resolves the unchanged target assertion, NOT paper evidence. Judge the full actual
text AND conditions, including their scope strength; source premises remain mandatory.
No sourceContext, metadata, foreign target, missing field or computed path is permitted.'''


def resolve_target(audit, claim):
    if 'statementExcerpt' in audit:
        return None
    path=audit.get('statementPath')
    if path==['text']:
        value=claim.get('text')
    elif (isinstance(path,list) and len(path)==2 and path[0]=='conditions'
          and isinstance(path[1],str) and isinstance(claim.get('conditions'),dict)):
        value=claim['conditions'].get(path[1])
    else:
        return None
    return value if isinstance(value,str) and value.strip() else None


def resolve(row, own, *, with_value=False):
    keys={'evidenceId','path','value'} if with_value else {'evidenceId','path'}
    if not isinstance(row,dict) or set(row)!=keys or not isinstance(row.get('evidenceId'),str):
        return None
    item=own.get(row['evidenceId'])
    path=row.get('path')
    if (not item or not isinstance(path,list)
            or path not in [['quote'],['sourceContext'],['sourceContext','before'],['sourceContext','after']]):
        return None
    value=item
    for key in path:
        if not isinstance(value,dict) or key not in value:
            return None
        value=value[key]
    if not isinstance(value,str) or not value.strip():
        return None
    return item,value
