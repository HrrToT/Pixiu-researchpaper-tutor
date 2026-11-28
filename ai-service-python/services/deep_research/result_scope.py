"""Reject unsupported primary-result attribution, never approve a table role."""
import re
from services.deep_research.synthesis_evidence import result_role


def purpose_not_established(claim,support):
    if claim.get('kind') not in {'reported','inference'}:
        return False
    text=claim.get('text','')
    if not re.search(r'主表|主要结果表|\bmain (?:results? )?table\b',text,re.I):
        return False
    if re.search(r'(?:并非|不是|而非|不属于|不代表)\s*主表|\bnot (?:the )?main (?:results? )?table\b',text,re.I):
        return False
    if not re.search(r'(?:FPS|帧率|速度)[^。；;!?！？\n]{0,32}(?:来自|取自|出自|\bfrom\b)',text,re.I):
        return False
    for work in {e.get('sourceWorkId') for e in support if result_role(e)=='profiling'}:
        own=[e for e in support if e.get('sourceWorkId')==work]
        if not any(result_role(e)=='quantitative_comparison'
                   or re.search(r'\bmain results?\b|主要结果|主表',e.get('quote',''),re.I) for e in own):
            return True
    return False
