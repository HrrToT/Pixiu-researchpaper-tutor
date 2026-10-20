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
