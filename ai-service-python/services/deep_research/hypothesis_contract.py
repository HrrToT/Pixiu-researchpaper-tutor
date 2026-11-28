"""Versioned links between a proposed hypothesis and its accepted analysis."""
from copy import deepcopy


def stamp_hypothesis_contract(report, enabled=True):
    result = deepcopy(report)
    result.pop('hypothesisContractVersion', None)
    if enabled:
        result['hypothesisContractVersion'] = 1
    for claim in result.get('claims', []):
        if isinstance(claim, dict):
            claim.pop('hypothesisContractVersion', None)
            if enabled and claim.get('designRole') == 'hypothesis':
                claim['hypothesisContractVersion'] = 1
    return result


def enforce_hypothesis_consistency(verification):
    from services.deep_research.hypothesis_spec import (
        hypothesis_analysis_errors, validate_hypothesis_spec, PURPOSE_DECISIONS)
    from services.deep_research.execution_spec import execution_spec_errors

    result = deepcopy(verification)
    accepted = result.get('accepted', [])
    targets = [c for c in accepted if c.get('designRole') == 'hypothesis'
               and type(c.get('hypothesisContractVersion')) is int and c['hypothesisContractVersion'] == 1]
    rejected = {}
    withheld_analyses = set()
    for hypothesis in targets:
        spec = hypothesis.get('executionSpec')
        reference = spec.get('analysisClaimId') if isinstance(spec, dict) else None
        candidates = [c for c in accepted if c.get('claimId') == reference]
        analysis = candidates[0] if len(candidates) == 1 else None
        errors = (hypothesis_analysis_errors(spec, analysis)
                  if hypothesis.get('kind') in {'proposal', 'suggestion', 'hypothesis'}
                  else ['hypothesis_kind_is_not_prospective'])
        if not errors:
            continue
        rejected[hypothesis['claimId']] = ', '.join(errors)
        # The program cannot choose which intended decision is correct. Allow
        # the one bounded repair to revise BOTH sides rather than silently
        # downgrading a requested test to a descriptive answer.
        if (not validate_hypothesis_spec(spec) and analysis is not None
                and analysis.get('designRole') == 'analysis'
                and analysis.get('kind') in {'proposal', 'suggestion', 'hypothesis'}
                and not execution_spec_errors('analysis', analysis.get('executionSpec'))
                and PURPOSE_DECISIONS[spec['purpose']] != analysis['executionSpec']['decision']['mode']):
            withheld_analyses.add(analysis['claimId'])
            rejected[analysis['claimId']] = 'hypothesis_purpose_and_analysis_decision_conflict'
    for hypothesis in targets:
        spec = hypothesis.get('executionSpec')
        reference = spec.get('analysisClaimId') if isinstance(spec, dict) else None
        if isinstance(reference, str) and reference in withheld_analyses:
            rejected.setdefault(hypothesis['claimId'], 'referenced_analysis_withheld_for_consistency')
    if rejected:
        result['accepted'] = [c for c in accepted if c.get('claimId') not in rejected]
        result.setdefault('rejected', []).extend({'claimId': identity,
            'reason': 'inconsistent_hypothesis_analysis', 'detail': detail}
            for identity, detail in rejected.items())
    return result
