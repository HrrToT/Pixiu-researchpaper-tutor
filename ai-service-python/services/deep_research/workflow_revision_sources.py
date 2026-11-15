"""Preserve valid authored source identities during unrelated metadata repair."""
from copy import deepcopy
import json

OPTION = '_workflow_revision_source_refs'
NAME = 'metadata_symbolic_results_bound_refs_v1'


def enabled(record):
    from services.deep_research.workflow_revision_context import enabled as context
    return context(record) and record['workflowRevisionContextContractVersion'] == 3


def valid(refs):
    return (isinstance(refs, list) and len(refs) <= 20
            and all(isinstance(x, str) and 0 < len(x) <= 128 for x in refs)
            and len(set(refs)) == len(refs))


def bound_refs(record, wire, feedback, aliases):
    refs = wire.get('sourceRefs')
    if (not enabled(record) or not valid(refs) or not set(refs) <= aliases.keys()
            or any(str(x).startswith('unit.sourceRefs') for x in feedback.get('codes', []))
            or any(str(x.get('path', '')).startswith('/sourceRefs') for x in feedback.get('issues', []))):
        return None
    return deepcopy(refs)


def bind_descriptor(descriptor, refs):
    if not valid(refs): raise ValueError('Invalid bound metadata source identities')
    result = deepcopy(descriptor)
    result['name'] = NAME
    result['schema']['properties']['sourceRefs']['const'] = deepcopy(refs)
    return result


def policy(refs):
    return ('This revision has no source-identity error. Echo the exact sourceRefs array bound by the '
            'schema, including every E prefix and order. This preserves authored identities, not '
            'scientific approval or permission to invent support. Do not decode aliases as dictionary '
            'indices or replace them with paper IDs. Exact sourceRefs JSON data: '
            + json.dumps(refs, ensure_ascii=False, separators=(',', ':')) + '\n')
