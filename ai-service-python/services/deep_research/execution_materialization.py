"""Expose generated execution choices before any semantic verification."""
from copy import deepcopy

from services.deep_research.protocol_text import render_execution_spec


def materialize_execution_claim(claim):
    result = deepcopy(claim)
    if (not isinstance(result, dict) or result.get('designContractVersion') != 2
            or result.get('kind') not in {'proposal', 'suggestion', 'hypothesis'}
            or not isinstance(result.get('text'), str)):
        return result
    text = render_execution_spec(result.get('designRole'), result.get('executionSpec'))
    if text:
        suffix = '\n\n' + text
        if not result['text'].endswith(suffix):
            # Preserve original prose. A contradictory narrative is still
            # visible to the verifier, never silently replaced by metadata.
            result['text'] += suffix
    return result
