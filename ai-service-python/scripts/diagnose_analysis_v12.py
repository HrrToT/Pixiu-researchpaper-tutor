"""Replay original v12 responses and collect exact rejections, no Provider."""
import json
import sys
from unittest.mock import patch

from llm.client import DeepSeekLLM
from schemas.conversation import ConversationCapabilityRequest
from services.conversation_capability_service import _compare, _critique
from services import grounded_comparison, grounded_critique

data = json.load(sys.stdin)
papers = [item['pdfId'] for item in data['plan']['materials']]
replayed = {}
for case in data['plan']['cases']:
    kind = case['capability']
    marker = 'findings' if kind == 'critique' else 'dimensions'
    raw = next(row['response'] for row in data['cache']['cacheRows'] if marker in row['response'])
    raw_before = json.dumps(raw, sort_keys=True)
    module = grounded_critique if kind == 'critique' else grounded_comparison
    original = module.check_numeric_claim
    original_resolve = module.resolve_references
    rejected = []

    def inspect(claim, sources):
        try:
            return original(claim, sources)
        except ValueError as error:
            rejected.append({'summary': claim.get('summary'), 'reason': str(error)})
            raise

    def inspect_selection(claim, *args, **kwargs):
        try:
            return original_resolve(claim, *args, **kwargs)
        except ValueError as error:
            rejected.append({'summary': claim.get('summary'), 'reason': str(error), 'stage': 'excerpt_selection'})
            raise

    request = ConversationCapabilityRequest(taskId='offline-v12-diagnosis-no-publish', capability=kind,
        message=case['prompt'], allowedPaperIds=[papers[1]] if kind == 'critique' else papers,
        primaryPaperId=papers[1] if kind == 'critique' else papers[0], strictScope=kind == 'critique')
    with (patch.object(DeepSeekLLM, 'invoke', side_effect=AssertionError('Provider forbidden')),
          patch('services.socratic_service._call_guarded_llm', return_value=json.dumps(raw)) as substitute,
          patch.object(module, 'check_numeric_claim', side_effect=inspect),
          patch.object(module, 'resolve_references', side_effect=inspect_selection)):
        result = _critique(request, papers[1]) if kind == 'critique' else _compare(request, [])
    assert substitute.call_count == 1 and result['partial'] is True
    assert raw_before == json.dumps(raw, sort_keys=True)
    replayed[kind] = {'partial': result['partial'], 'rejections': rejected,
                      'claims': result.get('groundedClaims'), 'message': result['message']}
print(json.dumps({'providerCalls': 0, 'taskWrites': 0, 'rawResponsesUnchanged': True,
                  'results': replayed}, ensure_ascii=False))
