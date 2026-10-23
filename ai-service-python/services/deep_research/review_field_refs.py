"""Exact declaration references for negative review feedback, never approval."""
from copy import deepcopy

from services.deep_research.contracts import digest
from services.deep_research.rejection_audit import ROOTS, bind
from services.deep_research.review_field_index import field_index

POLICY = '''Failed verdicts need 1..6 findings, each EXACTLY
{kind:incomplete|incompatible|unsupported|missing_field,claimId,field,reason}.
field is a literal code: text, conditions, executionSpec, or executionSpec/KEY.
Select an ACTUAL field in the supplied field index: present or specKeys for existing
values, missingSpecKeys for absent allowed keys. No dotted paths, nested indices or value.
The server resolves that exact original field; state a specific defect INSIDE it.
missing_field is ONLY for an actually absent text/executionSpec/allowed spec key.
Present null/empty/invalid fields need another kind. Metrics/limits use text/conditions.
One precise Chinese defect per finding, target or supplied context claimId only.
Passed verdicts use findings:[] AND all positive audits. Binding is not scientific approval.'''


def catalogue(context):
    result = {}
    index = field_index(context)
    rows = {c['claimId']: c for c in context if isinstance(c, dict)
        and any(i['claimId'] == c.get('claimId') for i in index)}
    for item in index:
        cid = item['claimId']; claim = rows[cid]; role = item['role']
        refs = {key: {'path': [key], 'present': key in claim}
            for key in ('text', 'conditions') if key in claim or key == 'text'}
        if role in ROOTS:
            refs['executionSpec'] = {'path': ['executionSpec'], 'present': 'executionSpec' in claim}
            spec = claim.get('executionSpec')
            if isinstance(spec, dict):
                for key in sorted(set(spec) | ROOTS[role]):
                    code = 'executionSpec/' + key.replace('~', '~0').replace('/', '~1')
                    refs[code] = {'path': ['executionSpec', key], 'present': key in spec}
        result[cid] = refs
    return result


def bind_refs(verdict, context):
    """Resolve only declared field codes; do not infer a path or fix a verdict."""
    refs = catalogue(context)
    original = deepcopy(verdict.get('findings'))
    expanded = []; errors = []
    if verdict.get('status') == 'failed' and isinstance(original, list) and 1 <= len(original) <= 6:
        for i, finding in enumerate(original):
            if (not isinstance(finding, dict) or set(finding) != {'kind','claimId','field','reason'}
                    or not isinstance(finding['claimId'], str) or finding['claimId'] not in refs
                    or not isinstance(finding['field'], str) or finding['field'] not in refs[finding['claimId']]):
                errors.append(f'finding.{i}.field_reference'); continue
            ref = refs[finding['claimId']][finding['field']]
            missing = finding['kind'] == 'missing_field'
            if missing == ref['present']:
                errors.append(f'finding.{i}.presence'); continue
            item = {k: deepcopy(finding[k]) for k in ('kind','claimId','reason')}
            item['path'] = ref['path']
            if not missing:
                claim = next(c for c in context if isinstance(c, dict) and c.get('claimId') == finding['claimId'])
                value = claim
                for key in ref['path']: value = value[key]
                item['value'] = deepcopy(value)
            expanded.append(item)
    elif verdict.get('status') != 'passed' or original != []:
        errors.append('missing_field_references')
    result = bind({**deepcopy(verdict), **({'status': 'failed'} if errors else {}),
        'findings': expanded if not errors else []}, context)
    if errors:
        result['rejectionAudit']['errors'] = errors
        result['rejectionAudit']['originalFindings'] = original
    if verdict.get('status') == 'failed' or errors:
        result.setdefault('rejectionAudit', {})['referenceBinding'] = {
            'version': 1, 'catalogueDigest': digest(refs), 'requestContextDigest': digest(context),
            'originalFindings': original, 'originalStatus': verdict.get('status'),
            'expandedFindingsDigest': digest(expanded),
            'scientificRejectionVerified': False}
    return result
