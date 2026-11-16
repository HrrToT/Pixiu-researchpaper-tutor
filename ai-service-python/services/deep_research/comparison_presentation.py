"""Present comparison layout using only the claims supplied by publication.

Callers supply verified claims for publication and draft claims only for sizing.
Layout and bibliography are not an alternative scientific approval channel.
"""
from copy import deepcopy
from html import escape

from services.deep_research.source_labels import source_display_title


def audit_view(value, claims):
    """The exact table and routing for accepted claims, never draft contents."""
    known = {c['claimId'] for c in claims}
    layout = [{**row, 'claimIds': [cid for cid in row['claimIds'] if cid in known]}
              for row in value['layout']]
    refs = list(dict.fromkeys(ref for claim in claims for ref in claim.get('evidenceRefs', [])))
    table, _ = render_table(value, claims, {ref: i+1 for i, ref in enumerate(refs)}, counting=True)
    return {'version': 1, 'sources': deepcopy(value['sources']), 'layout': layout,
            'sections': sections(value, claims), 'table': table}


def audit_digest(value, claims):
    import hashlib
    import json
    return hashlib.sha256(json.dumps(audit_view(value, claims), ensure_ascii=False,
                                    sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def revalidate_audit(audit, value, claims):
    if audit.get('comparisonPresentationDigest') == audit_digest(value, claims):
        return audit
    gap = {'obligationId': audit.get('wholeQuestionId') or 'answer_comparison_layout',
           'stage': 'answer', 'wholeQuestion': True,
           'missingEvidence': '比较表格或条目归属尚未通过当前答案审核'}
    return {**audit, 'status': 'invalidated_comparison_presentation',
            'gaps': [*audit.get('gaps', []), gap]}


def metadata(draft):
    return {'version': 1, 'sources': deepcopy(draft['sources']),
            'layout': [{k: deepcopy(row[k]) for k in
                        ('obligationId', 'question', 'source', 'claimIds')}
                       for row in draft['layout']]}


def sections(value, claims):
    cell_ids = {cid for row in value['layout'] for cid in row['claimIds']}
    ordinary = [c for c in claims if c['claimId'] not in cell_ids]
    return [
        {'title': '比较结论', 'claimIds': [c['claimId'] for c in ordinary
                                       if c.get('kind') not in {'proposal', 'suggestion', 'hypothesis'}]},
        {'title': '逐项比较', 'claimIds': [c['claimId'] for c in claims if c['claimId'] in cell_ids],
         'comparisonTable': True},
        {'title': '选择建议', 'claimIds': [c['claimId'] for c in ordinary
                                       if c.get('kind') in {'proposal', 'suggestion', 'hypothesis'}]},
    ]


def _safe(value):
    # Entities keep pipe/backslash mathematics intact inside a GFM table cell.
    return escape(str(value), quote=False).replace('|', '&#124;').replace('\r\n', '\n').replace('\n', '<br>')


def render_table(value, claims, numbers, *, counting=False):
    from services.deep_research.reporting import display_conditions
    indexed = {c['claimId']: c for c in claims}
    columns = list(dict.fromkeys(row['source'] for row in value['layout']))
    groups = {}
    for row in value['layout']:
        key = row['obligationId']
        if key not in groups: groups[key] = {'question': row['question'], 'cells': {}}
        groups[key]['cells'][row['source']] = row
    active = [group for group in groups.values()
              if any(cid in indexed for cell in group['cells'].values() for cid in cell['claimIds'])]
    if not active: return '', set()
    labels, plain_labels = [], []
    for index, source in enumerate(columns):
        full = source_display_title(value['sources'][source].get('title'), f'论文{index+1}')
        from services.deep_research.publication_identity import validated
        source_info = value['sources'][source]
        identity = validated(source_info.get('publicationIdentity'), source_info.get('versionId'))
        suffix = ' (' + identity['revision'] + ')' if identity else ''
        short = full + suffix if len(full + suffix) <= 36 else full[:35-len(suffix)] + '…' + suffix
        full += suffix
        if short in plain_labels: short += f' · {index+1}'
        plain_labels.append(short)
        if counting:
            labels.append(short)
        else:
            own_ids = [cid for row in value['layout'] if row['source']==source for cid in row['claimIds']]
            first_ref = next((e for cid in own_ids if cid in indexed
                              for e in indexed[cid].get('evidenceRefs', []) if e in numbers), None)
            label = _safe(short)
            if first_ref:
                tooltip = escape(full.replace('\\','\\\\').replace('\n',' '), quote=True)
                label = f'[{label}](#research-evidence-{first_ref} "{tooltip}")'
            labels.append(label)
    lines = [' | '.join(['比较维度', *labels])] if counting else [
        '| ' + ' | '.join(['比较维度', *labels]) + ' |',
        '| ' + ' | '.join(['---'] * (len(columns) + 1)) + ' |']
    rendered = set()
    for group in active:
        cells = []
        for source in columns:
            slot = group['cells'].get(source)
            points = [indexed[cid] for cid in slot['claimIds'] if cid in indexed] if slot else []
            parts = []
            for point in points:
                rendered.add(point['claimId'])
                label = '推断：' if point.get('kind') == 'inference' else ''
                text = label + point['text']
                conditions = point.get('conditions')
                if isinstance(conditions, dict) and conditions:
                    text += ' 适用条件：' + display_conditions(conditions)
                if counting:
                    cites = ' '.join(str(numbers[e]) for e in point.get('evidenceRefs', []) if e in numbers)
                    parts.append((text + ' ' + cites).rstrip())
                else:
                    cites = ' '.join(f'[{numbers[e]}](#research-evidence-{e})'
                                     for e in point.get('evidenceRefs', []) if e in numbers)
                    parts.append((_safe(text) + ' ' + cites).rstrip())
            if not parts: parts = ['尚未形成可核验结论' if slot else '—']
            cells.append(('\n' if counting else '<br><br>').join(parts))
        heading = group['question'] if counting else _safe(group['question'])
        line = ' | '.join([heading, *cells])
        lines.append(line if counting else '| ' + line + ' |')
    return '\n'.join(lines), rendered
