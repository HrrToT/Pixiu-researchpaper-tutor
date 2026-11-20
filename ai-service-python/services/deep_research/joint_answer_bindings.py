"""Joint answer bindings preserve scientific prose and acquisition metadata roles."""
import re


def enabled(metadata):
    return (isinstance(metadata,dict) and type(metadata.get('requestSemanticsContractVersion')) is int
        and metadata['requestSemanticsContractVersion']==2)


def access_instruction(question, *, citation_access=False):
    from services.deep_research.access_disclosure import access_only
    from services.deep_research.evidence_requirements import _outside_examples
    layers=getattr(question,'instruction_layers',(str(question),))
    for layer in layers:
        for part in re.split(r'[。！？；，,\n]',_outside_examples(layer)):
            canonical=part.strip().replace('引用','依据') if citation_access else part.strip()
            if len(part.strip())>=8 and access_only(canonical):return canonical
    return None


def bindings_supported(bindings,known,metadata,requirement):
    from services.deep_research.answer_coverage import _bindings_supported
    from services.deep_research.access_disclosure import access_bindings_supported
    if _bindings_supported(bindings,known):return True
    if access_bindings_supported(bindings,known,metadata,requirement):return True
    access=access_instruction(requirement,citation_access=type(metadata.get('answerBindingCatalogVersion')) is int and metadata['answerBindingCatalogVersion']==1) if enabled(metadata) else None
    if not access or not isinstance(bindings,list):return False
    labels=[b for b in bindings if isinstance(b,dict) and b.get('field')=='sourceAccessSummary']
    prose=[b for b in bindings if b not in labels]
    # Metadata alone cannot answer a mixed scientific question. Every other
    # binding still needs actual accepted text/conditions, not source quotes.
    return (bool(prose) and _bindings_supported(prose,known)
        and access_bindings_supported(labels,known,metadata,access))


def without_character_limits(text):
    """Remove only explicit response-length directives from object matching."""
    return re.sub(
        r'(?:用(?:不超过|最多|至多)?|控制在|总共最多|不超过|最多|至多)\s*\d{2,5}\s*'
        r'(?:个字符|字(?!节)|characters\b)|'
        r'\b(?:within|at most|no more than|in)\s+\d{2,5}\s+characters\b',
        '',text,flags=re.I)


GUIDANCE='''For an original question containing BOTH scientific content and an explicit
access-disclosure command, the aggregate bindings may jointly cite accepted text/
conditions AND sourceAccessSummary. Scientific criteria still bind scientific prose;
access-only identification criteria may bind the server label. Neither role replaces
the other. A 300-character response limit is a format constraint, not a number the
answer must repeat; requested measurements, table/equation IDs and object counts
remain content requirements. Do not infer completeness from these binding permissions.'''
