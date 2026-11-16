"""Readable field names with two lossless layers and equivalent schema sharing."""
from copy import deepcopy
import json

MARKER = 'workflowInitializationReadableInputContractVersion'
LEGEND = ('Input encoding only. First restore {"$":i} to strings[i], {"~":o} to literal object o. '
          'Then {"@":[columns,rows]} to object rows and {"!":o} to literal object o. '
          'Preserve all values. Output ordinary schema values, never references.')
TEXT = {'type':'string','minLength':1}
REF = {'$ref':'#/$defs/t'}


def enabled(record):
    from services.deep_research.workflow_initialization_reasoning import enabled as reasoning
    return (isinstance(record,dict) and type(record.get(MARKER)) is int
            and record[MARKER]==1 and reasoning(record))


def _json(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def input_text(value):
    from services.deep_research import shared_strings,nested_tables
    from services.deep_research.contracts import digest
    wire=shared_strings.pack(nested_tables.pack(value))
    if digest(nested_tables.unpack(shared_strings.unpack(wire)))!=digest(value):
        raise ValueError('Readable initializer input changed original values')
    encoded=_json(wire)+'\n'+LEGEND;literal=_json(value)
    return literal if len(literal.encode())<=len(encoded.encode()) else encoded


def expand_schema(schema):
    """Proof decoder for this one schema alias; no model output is interpreted."""
    value=deepcopy(schema)
    if not isinstance(value.get('$defs'),dict) or value['$defs'].pop('t',None)!=TEXT:
        raise ValueError('Invalid nonblank text alias')
    def visit(item):
        if isinstance(item,dict):
            if item==REF:return deepcopy(TEXT)
            return {key:visit(child) for key,child in item.items()}
        if isinstance(item,list):return [visit(child) for child in item]
        return deepcopy(item)
    return visit(value)


def descriptor(target):
    from services.deep_research.workflow_initialization_semantics import descriptor as original
    from services.deep_research.contracts import digest
    result=original(target);before=deepcopy(result['schema'])
    if 't' in before['$defs']:raise ValueError('Schema alias already owned')
    def visit(value):
        if isinstance(value,dict):
            if value==TEXT:return deepcopy(REF)
            return {key:visit(child) for key,child in value.items()}
        if isinstance(value,list):return [visit(child) for child in value]
        return deepcopy(value)
    result['schema']=visit(before);result['schema']['$defs']['t']=deepcopy(TEXT)
    if digest(expand_schema(result['schema']))!=digest(before):
        raise ValueError('Initializer schema sharing changed constraints')
    return result
