"""Separate bounded wire/storage/expansion for complete symbolic metadata.

No choice is filled, merged or renamed. Old records keep all original caps.
The expanded value remains inside the existing 32000-byte workflow bound.
"""

GUIDANCE = (
    'Operation parameters are uniquely named settings, not repeated invocations. '
    'For multiple metrics use distinct parameter names or one explicit metric-set choice; '
    'never repeat one parameter name with different values. Keep every requested metric, '
    'observable, reference and unit. Each arm reads only reserved inputs or components '
    'whose appliesTo includes that arm. An intervention-off arm uses its unquantized model '
    'state, not a nonexistent codebook or indices. Do not broaden appliesTo, remove arms, '
    'measurements or fitting to cure a missing read or save space.\n'
)


def enabled(record):
    from services.deep_research.workflow_metadata_output import enabled as output_enabled
    return (isinstance(record,dict)
            and type(record.get('workflowMetadataEnvelopeContractVersion')) is int
            and record['workflowMetadataEnvelopeContractVersion']==1 and output_enabled(record))


def limits(record):
    return {'raw':32768,'wire':16384,'expanded':32000} if enabled(record) else {
        'raw':16384,'wire':8192,'expanded':8192}


def over_capacity(record,raw,wire,value=None):
    from services.deep_research.execution_workflow_blueprint import packed
    cap=limits(record)
    return (len(raw.encode('utf8'))>cap['raw'] or len(packed(wire).encode('utf8'))>cap['wire']
            or value is not None and len(packed(value).encode('utf8'))>cap['expanded'])
