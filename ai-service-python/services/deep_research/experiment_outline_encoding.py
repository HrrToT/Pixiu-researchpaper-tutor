"""Lossless encoding of the system outline AFTER evidence/plan allocation.

No source, plan, choice or requirement is removed. Old requests are unchanged.
"""
import json

from services.deep_research.contracts import DeepResearchError,digest
from services.deep_research.configuration_consistency import generation
from services.deep_research.experimental_reasoning import design_output_outline
from services.deep_research.experiment_edits import columnar,restore_columns

MARKER='REQUIRED OUTPUT OUTLINE (one claim per role):\n'
LEGEND='Outline table: columns name row values; merge each final extra-fields object. Output ordinary claims, not a table.\n'


def enabled(record):
    return (type(record.get('experimentOutlineEncodingContractVersion')) is int
        and record['experimentOutlineEncodingContractVersion'] in (1,2)
        and type(record.get('experimentDraftContractVersion')) is int
        and record['experimentDraftContractVersion']==6
        and type(record.get('configurationConsistencyContractVersion')) is int
        and record['configurationConsistencyContractVersion']==2)


def allocation_enabled(record):
    return enabled(record) and record['experimentOutlineEncodingContractVersion']==2


def _packed(value):
    return json.dumps(value,ensure_ascii=False,separators=(',',':'),allow_nan=False)


def _outline():
    return design_output_outline(strict_budget=True,strict_hypothesis=True,strict_protocol=2,strict_workflow=4)


def _error():
    return DeepResearchError('invalid_experiment_outline_state','实验输出目录与原始系统结构不一致，不能发送。')


def _suffix(record):
    from services.deep_research.experiment_generation_envelope import enabled as generation_enabled
    if (generation_enabled(record) and type(record.get('experimentGenerationEnvelopeContractVersion')) is int
            and record['experimentGenerationEnvelopeContractVersion'] in (2,3)):
        from services.deep_research.compact_generation_rules import CONFIGURATION
        return '\n'+CONFIGURATION
    return '\n'+generation(record['configurationConsistencyContractVersion'])


def encode(record,prompt):
    if not enabled(record):return prompt,None
    outline=_outline();packet=columnar(outline)
    if restore_columns(packet)!=outline:raise _error()
    suffix=_suffix(record)
    needle=MARKER+_packed(outline)+suffix
    # The actual system paragraph follows the human question. Source/plan data
    # are JSON strings; their escaped line breaks cannot replace this boundary.
    head,found,tail=prompt.rpartition(needle)
    if not found:raise _error()
    encoded=head+MARKER+LEGEND+_packed(packet)+suffix+tail
    audit={'version':record['experimentOutlineEncodingContractVersion'],'originalOutline':outline,'encodedOutline':packet,
        'originalInputBytes':len(prompt.encode('utf8')),'encodedInputBytes':len(encoded.encode('utf8')),
        'originalPromptDigest':digest(prompt),'encodedPromptDigest':digest(encoded),'scientificApproval':False}
    validate(record,encoded,audit)
    return encoded,audit


def validate(record,prompt,audit):
    """Reconstruct the exact original prompt; this is not content approval."""
    if not enabled(record):
        if audit is not None:raise _error()
        return
    if (not isinstance(audit,dict) or set(audit)!={'version','originalOutline','encodedOutline',
            'originalInputBytes','encodedInputBytes','originalPromptDigest','encodedPromptDigest','scientificApproval'}
            or type(audit['version']) is not int or audit['version']!=record['experimentOutlineEncodingContractVersion']
            or audit['scientificApproval'] is not False
            or type(audit['originalInputBytes']) is not int or type(audit['encodedInputBytes']) is not int):
        raise _error()
    expected=_outline();packet=columnar(expected)
    try:
        canonical=_packed(audit['originalOutline'])==_packed(expected) and _packed(audit['encodedOutline'])==_packed(packet)
    except (ValueError,TypeError,OverflowError):
        raise _error()
    if not canonical:raise _error()
    if restore_columns(audit['encodedOutline'])!=expected:raise _error()
    suffix=_suffix(record)
    head,found,tail=prompt.rpartition(MARKER+LEGEND+_packed(packet)+suffix)
    if not found:raise _error()
    original=head+MARKER+_packed(expected)+suffix+tail
    if (audit['encodedPromptDigest']!=digest(prompt) or audit['originalPromptDigest']!=digest(original)
            or audit['originalInputBytes']!=len(original.encode('utf8'))
            or audit['encodedInputBytes']!=len(prompt.encode('utf8'))):
        raise _error()
