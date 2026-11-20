"""Keep undecodable source glyphs visible while refusing scientific approval."""
from copy import deepcopy


def control_count(text):
    if isinstance(text,dict):return sum(control_count(v) for v in text.values())
    if isinstance(text,(list,tuple)):return sum(control_count(v) for v in text)
    if not isinstance(text,str):return 0
    return sum((ord(c)<32 and c not in "\n\r\t") or ord(c)==127 or c=="\ufffd" for c in text)


def literal_state_valid(evidence):
    """Validate a persisted guard decision without granting literal support."""
    literal=evidence.get('verification',{}).get('literal')
    if literal not in ('passed','failed'):return False
    count=control_count(evidence.get('quote'))+control_count(evidence.get('sourceContext'))
    if count:
        return literal=='failed' and evidence.get('textQualityAudit')=={
            'version':1,'status':'unreadable_glyphs','controlCount':count}
    return 'textQualityAudit' not in evidence


def guard(factory,record):
    if type(record.get('sourceGlyphContractVersion')) is not int or record['sourceGlyphContractVersion']!=1:
        return factory
    def create(source,quote,original,**kwargs):
        evidence=factory(source,quote,original,**kwargs)
        count=control_count(quote)+control_count(original)
        if count:
            evidence=deepcopy(evidence)
            evidence['verification']={**evidence.get('verification',{}),'literal':'failed'}
            evidence['textQualityAudit']={'version':1,'status':'unreadable_glyphs','controlCount':count}
        return evidence
    page_batch = getattr(factory, '__dict__', {}).get('physical_page_batch')
    if callable(page_batch):
        create.physical_page_batch = page_batch
    page_diagnostics = getattr(factory, '__dict__', {}).get('physical_page_diagnostics')
    if callable(page_diagnostics):create.physical_page_diagnostics = page_diagnostics
    return create
