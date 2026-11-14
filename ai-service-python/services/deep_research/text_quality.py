"""Keep undecodable source glyphs visible while refusing scientific approval."""
from copy import deepcopy


def control_count(text):
    if isinstance(text,dict):return sum(control_count(v) for v in text.values())
    if isinstance(text,(list,tuple)):return sum(control_count(v) for v in text)
    if not isinstance(text,str):return 0
    return sum((ord(c)<32 and c not in "\n\r\t") or ord(c)==127 or c=="\ufffd" for c in text)


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
    return create
