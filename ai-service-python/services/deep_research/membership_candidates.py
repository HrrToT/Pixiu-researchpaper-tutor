"""Own literal name-bearing quotations; candidates are never membership proof."""
import re
from services.deep_research.data_availability import _name_in_quote_with_boundary


def _source_label(quote, selected):
    if re.fullmatch(r'[A-Za-z][A-Za-z0-9 _-]*',selected):
        match=re.search(r'(?<!\w)'+re.escape(selected)+r'(?!\w)',quote,re.I)
        if match and re.fullmatch(r'[A-Za-z][A-Za-z0-9 _-]*',match[0]):
            return match[0]
        return None
    return selected if _name_in_quote_with_boundary(quote,selected) else None


def named_membership_candidates(claims,evidence):
    """Narrow audit choices without adding permission or changing a verdict.

    Callers pass only the actually visible evidence rows. A quoted name may be
    excluded/negated or belong to a different subset; the reviewer must still
    establish the SAME dataset/member relation and preserve exact quotations.
    """
    result={}
    for claim in claims:
        if claim.get('designRole')!='data' or claim.get('designContractVersion')!=2:
            continue
        scenes=claim.get('executionSpec',{}).get('scenes',{})
        names=scenes.get('names')
        if scenes.get('mode')!='named' or not isinstance(names,list) or not names or any(
                not isinstance(name,str) or not name.strip() for name in names):
            continue
        refs=claim.get('evidenceRefs',[]);rows=[]
        for evidence_row in evidence:
            if (evidence_row.get('evidenceId') not in refs or evidence_row.get('accessLevel')!='fulltext'
                    or evidence_row.get('verification',{}).get('literal')!='passed'):
                continue
            quote=evidence_row.get('quote','')
            if not isinstance(quote,str):
                continue
            labels=[_source_label(quote,name) for name in names]
            if all(label is not None for label in labels):
                rows.append({'evidenceId':evidence_row['evidenceId'],'nameBindings':[
                    {'selectedName':name,'sourceLabel':label} for name,label in zip(names,labels)]})
        result[claim['claimId']]=rows
    return result
