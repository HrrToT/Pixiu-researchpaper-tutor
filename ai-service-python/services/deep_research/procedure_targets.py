"""Rank passages about the requested operation's object, never approve content."""
import re

_OBJECTS=(
    (r'网格|\bmesh(?:es)?\b',r'网格|\bmesh(?:es)?\b'),
    (r'点云|\bpoint[ -]clouds?\b',r'点云|\bpoint[ -]clouds?\b'),
    (r'深度图|\bdepth[ -]maps?\b',r'深度图|\bdepth[ -]maps?\b'),
    (r'法线图|\bnormal[ -]maps?\b',r'法线图|\bnormal[ -]maps?\b'),
    (r'特征|\bfeatures?\b',r'特征|\bfeatures?\b'),
)
_ACTION=r'\b(?:extract\w*|fus\w*|construct\w*|generat\w*|convert\w*|render\w*|reconstruct\w*)\b|提取|融合|构建|生成|转换|渲染|重建'
_REQUEST=r'提取|生成|融合|转换|流程|路径|步骤|\b(?:extract\w*|generat\w*|fus\w*|convert\w*|pipeline|procedur\w*|steps?|path)\b'


def score(text,request):
    if request.get('role')!='procedure' or not re.search(_REQUEST,request.get('query',''),re.I):return 0
    patterns=[body for query,body in _OBJECTS if re.search(query,request['query'],re.I)]
    best=0
    for pattern in patterns:
        for hit in re.finditer(pattern,text,re.I):
            # Only this literal quote participates. Adjacent unrelated paragraphs,
            # source titles or another paper's text cannot supply the operation.
            left=re.split(r'[.!?。！？]',text[max(0,hit.start()-100):hit.start()])[-1]
            right=re.split(r'[.!?。！？]',text[hit.end():hit.end()+100])[0]
            part=left+hit.group()+right
            action=bool(re.search(_ACTION,part,re.I))
            own=bool(re.search(r'\b(?:we|our)\b|本文|我们',part,re.I))
            best=max(best,1+3*action+2*(action and own))
    return best
