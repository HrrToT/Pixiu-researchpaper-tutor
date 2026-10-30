"""Literal shared-module hints; ranking is never scientific verification."""
import re

_METRICS = {'PSNR', 'SSIM', 'LPIPS', 'FPS', 'GPU', 'CPU', 'RAM', 'VRAM', 'RGB', 'PDF'}


def named_modules(question):
    """Use at most two explicitly named acronyms in a shared/fixed clause.

    Do not infer modules from paper titles, model output or background knowledge.
    A missing definition stays a gap; a matched name grants no factual approval.
    """
    names = []
    for clause in re.split(r'[。；;\n.!?]', question or ''):
        if not re.search(r'固定|共同|相同|共享|\b(?:fixed|same|shared|common)\b', clause, re.I):
            continue
        for match in re.finditer(r'(?<![A-Za-z0-9])[A-Z][A-Z0-9-]{1,11}(?![A-Za-z0-9])', clause):
            name = match.group()
            if name not in _METRICS and name not in names:
                names.append(name)
    return names[:2]


def definition_score(text, name):
    # Ignore repeated Paper/Section wrappers. Matching a title is not a definition.
    body = re.split(r'\bContent:\s*', text or '', maxsplit=1)[-1]
    if not re.search(r'(?<![A-Za-z0-9])'+re.escape(name)+r'(?![A-Za-z0-9])', body):
        return 0
    return len({m.group().lower() for m in re.finditer(
        r'\b(?:inputs?|outputs?|predict\w*|encod\w*|maps?|MLP|network|hash|'
        r'translations?|rotations?|quaternions?|dimensions?)\b|输入|输出|编码|预测|网络|维度', body, re.I)})


def definition_premise(row,name,read_sources):
    """Return a rank and mandatory literal antecedent, never support approval.

    Context for a pronoun must equal a text actually read under the SAME unique
    source/work/version/hash. Titles, tables, unrelated passages and ambiguous
    occurrences cannot supply an antecedent. Keep the original evidence intact.
    """
    if (row.get('verification',{}).get('literal')!='passed' or row.get('accessLevel')!='fulltext'
            or row.get('tableData') or row.get('location',{}).get('table')):
        return 0,None
    if re.search(r'table\s*\d|profil\w*|overhead|related work|references',row.get('location',{}).get('section',''),re.I):
        return 0,None
    quote=row.get('quote','')
    action=r'\b(?:maps?|outputs?|predict\w*|encod\w*|MLP|network)\b|映射|输出|预测|编码|网络'
    if not isinstance(quote,str) or not re.search(action,quote,re.I):
        return 0,None
    direct=definition_score(quote,name)
    if direct:
        return direct,None
    if not re.match(r'\s*(?:This|It|These|The (?:encoder|encoding|network|module))\b|\s*(?:该|这)',quote,re.I):
        return 0,None
    keys=(('sourceId','sourceId'),('sourceWorkId','workId'),('sourceVersionId','versionId'),('contentHash','contentHash'))
    if any(not isinstance(row.get(a),str) or not row[a] for a,_ in keys):
        return 0,None
    matches=[s for s in read_sources if all(s.get(b)==row[a] for a,b in keys) and s.get('accessLevel')=='fulltext']
    if len(matches)!=1:
        return 0,None
    source=row.get('sourceContext')
    if not isinstance(source,str) or source not in [matches[0].get('text'),*[p.get('text') for p in matches[0].get('pages',[])]]:
        return 0,None
    body=re.split(r'\bContent:\s*',source,maxsplit=1)[-1]
    if body.count(quote)!=1:
        return 0,None
    start=body.index(quote)
    from services.deep_research.quote_context import _sentence_cuts
    bounds=[0,*[cut for cut in _sentence_cuts(body[:start]) if cut<start],start]
    for index in range(len(bounds)-2,max(-1,len(bounds)-5),-1):
        prefix=body[bounds[index]:start]
        if len(prefix)>600:
            break
        if definition_score(prefix,name) and re.search(action,prefix,re.I):
            return definition_score(prefix+quote,name),{'before':prefix,'after':'','truncated':bool(bounds[index] or start+len(quote)<len(body))}
    return 0,None
