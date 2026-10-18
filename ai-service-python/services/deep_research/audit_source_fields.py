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
            and record['auditSourceFieldsContractVersion']==1)


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
