"""Audit published baseline-asset references, without fetching or running them."""
from copy import deepcopy
import re


_ASSET = r'(?:\b(?:checkpoints?|pre[- ]?trained (?:models?|weights)|model weights|trained models?)\b|预训练模型|预训练权重|模型检查点)'
_RELEASE = r'(?:\b(?:available|released?|downloadable|provided|published|accessible)\b|可下载|已发布|已公开|公开提供)'
_PUBLIC_CLAUSE = re.compile(
    _ASSET + r'[^.;!?\n]{0,100}' + _RELEASE + '|' + _RELEASE + r'[^.;!?\n]{0,100}' + _ASSET,
    re.I)
_QUALIFIED = re.compile(
    r'\b(?:no|not|never|without|unavailable|will|plan(?:ned)?|intend|would|could|may|might|request|upon|if|whether)\b'
    r'|\bgoing to\b|尚未|未(?:公开|发布|提供)|不(?:公开|发布|提供)|计划|[将会](?:公开|发布|提供)|申请', re.I)


def requires_existing_asset(claim):
    return (isinstance(claim, dict) and claim.get('kind') in {'proposal', 'suggestion', 'hypothesis'}
            and claim.get('designRole') == 'budget'
            and type(claim.get('budgetContractVersion')) is int and claim['budgetContractVersion'] == 1
            and isinstance(claim.get('executionSpec'), dict)
            and isinstance(claim['executionSpec'].get('baseline'), dict)
            and claim['executionSpec']['baseline'].get('mode') == 'existing')


def validate_asset_availability(claim, audit, evidence):
    """A paper training a model is not evidence of a released checkpoint.

    This structural audit binds an explicit release clause and published HTTPS
    locator to the target's own fulltext citation. Independent semantics still
    checks the asset/dataset/selection identity. It does not prove that a remote
    download works now, nor does it authorize following the locator.
    """
    if not requires_existing_asset(claim):
        return []
    if not isinstance(audit, dict):
        return ['AA_MISSING']
    keys = {'evidenceId', 'quote', 'assetQuote', 'availabilityQuote', 'locator'}
    if set(audit) != keys or any(not isinstance(audit[k], str) or not audit[k].strip() for k in keys):
        return ['AA_MALFORMED']
    matches = [e for e in evidence if e.get('evidenceId') == audit['evidenceId']]
    if len(matches) != 1 or audit['evidenceId'] not in claim.get('evidenceRefs', []):
        return ['AA_UNOWNED_EVIDENCE']
    source = matches[0]
    if source.get('accessLevel') != 'fulltext' or source.get('verification', {}).get('literal') != 'passed':
        return ['AA_UNVERIFIED_FULLTEXT']
    quote = audit['quote']
    if quote not in source.get('quote', ''):
        return ['AA_QUOTE_NOT_IN_SOURCE']
    clause = audit['availabilityQuote']
    if clause not in quote or audit['assetQuote'] not in clause:
        return ['AA_RELEASE_NOT_BOUND']
    lexical_clause = re.sub(r'\s+', ' ', clause)
    if _QUALIFIED.search(lexical_clause) or not _PUBLIC_CLAUSE.search(lexical_clause):
        return ['AA_NO_EXPLICIT_RELEASE']
    locator = audit['locator']
    published = {token.rstrip('.,;!?)]）】') for token in re.findall(r'https://[^\s<>"\x00-\x1f]+', quote)}
    if not re.fullmatch(r'https://[^\s<>"\x00-\x1f]+', locator) or locator not in published:
        return ['AA_NO_PUBLISHED_LOCATOR']
    return []


def enforce_asset_prerequisites(verification, evidence=()):
    """Keep incomplete shared-baseline protocols out of accepted results.

    Run again after revision merging and before publication, so repairing only
    a dependent paragraph cannot bypass a failed asset prerequisite.
    """
    result = deepcopy(verification)
    accepted = result.get('accepted', [])
    rejected = result.setdefault('rejected', [])
    accepted_ids = {c.get('claimId') for c in accepted}
    failed = {c['claimId'] for c in rejected if c.get('assetPrerequisite') is True
              and c.get('claimId') not in accepted_ids}
    for claim in accepted:
        errors = validate_asset_availability(claim, claim.get('assetAvailability'), evidence)
        if errors:
            failed.add(claim['claimId'])
            rejected.append({'claimId': claim['claimId'], 'reason': 'unverified_baseline_asset',
                             'detail': ', '.join(errors), 'assetPrerequisite': True})
    if not failed:
        return result
    keep = []
    for claim in accepted:
        if claim['claimId'] in failed:
            continue
        if (claim.get('designContractVersion') == 2 and claim.get('kind') in {'proposal', 'suggestion', 'hypothesis'}
                and claim.get('designRole') in {'controls', 'steps'}):
            rejected.append({'claimId': claim['claimId'], 'reason': 'baseline_asset_dependency',
                             'detail': 'Existing baseline asset is not established: ' + ', '.join(sorted(failed)),
                             'dependsOn': sorted(failed)})
        else:
            keep.append(claim)
    result['accepted'] = keep
    return result
