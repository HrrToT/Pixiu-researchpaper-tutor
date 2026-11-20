import json

from services.deep_research.design_audit import required_design_slots, validate_design_audit
from services.deep_research.experimental_reasoning import design_requirements
from services.deep_research.tools import BudgetedSemanticChecker


def test_vague_shared_controls_cannot_pass_without_concrete_audit_bindings():
    claim = {'claimId': 'control', 'kind': 'proposal', 'designRole': 'controls',
             'text': 'Use the same initialization, renderer and optimizer.'}
    missing = validate_design_audit(claim, {'status': 'passed', 'designAudit': {}}, [])
    assert set(missing) == {'paired_initialization', 'render_settings', 'optimizer_settings', 'other_interventions'}
    concrete = {**claim, 'text': ('Copy the same saved baseline and enhancement initialization to A/B. '
        'Render both at 640x480 with the same renderer configuration. '
        'Use Adam with learning rate 0.001 for trainable parameters in both arms. '
        'Disable occupancy removal and compaction in both arms.')}
    choices = concrete['text'].split('. ')
    audit = {key: {'claimId': 'control', 'quote': choice}
             for key, choice in zip(required_design_slots()['controls'], choices)}
    assert validate_design_audit(concrete, {'designAudit': audit}, []) == []
    audit['render_settings']['quote'] = 'Render at an invented resolution.'
    assert validate_design_audit(concrete, {'designAudit': audit}, []) == ['render_settings']


def test_descriptive_contract_does_not_require_inferential_procedures_but_preserves_pairing():
    claim = {'claimId': 'analysis', 'kind': 'proposal', 'designRole': 'analysis',
             'designContractVersion': 2, 'text': 'Report the mean paired PSNR difference on the same held-out views.',
             'evidenceRefs': [], 'executionSpec': {
                 'effects': {'difference': 'mean over identical held-out views of B PSNR minus A PSNR'},
                 'uncertainty': {'mode': 'descriptive', 'boundary': 'Single fixed checkpoint, no population inference.'},
                 'decision': {'mode': 'descriptive', 'boundary': 'Report observed direction without a significance claim.'}}}
    prompts = []
    def invoke(**kwargs):
        prompts.append(kwargs['prompt'])
        return {'content': json.dumps([{'claimId': 'analysis', 'status': 'passed', 'designAudit': {
            slot: {'fields': [{'claimId': 'analysis', 'path': ['executionSpec', field], 'value': claim['executionSpec'][field]}]}
            for slot, field in [('effects', 'effects'), ('uncertainty', 'uncertainty'), ('decision_rule', 'decision')]}}])}
    checker = BudgetedSemanticChecker(invoke, 'r', metric_domains=['quality'],
        research_question='One-scene descriptive paired comparison, not a statistical test.')
    verdicts = checker([claim], [])
    assert verdicts[0]['status'] == 'passed'
    assert validate_design_audit(claim, verdicts[0], []) == []
    assert 'purely descriptive comparison with explicit scope' in prompts[0]
    assert 'needs no confidence interval, bootstrap' in prompts[0]
    assert 'Require paired groups within units' in prompts[0]
    assert 'If resampling is proposed' in prompts[0]
    assert 'descriptive single-scene comparison' in design_requirements(['quality'], roles={'analysis'})
