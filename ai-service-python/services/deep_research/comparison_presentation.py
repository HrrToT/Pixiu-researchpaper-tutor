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
    if value['version'] == 3:
        import hashlib
        # Full accepted text and conditions are already in the audit's claims.
        # Keep the exact table bound without duplicating all scientific prose.
        table = {'format':'markdown_table', 'present':bool(table),
                 'cellsFromAcceptedClaimIds':True,
                 'renderedTextSha256':hashlib.sha256(table.encode('utf-8')).hexdigest()}
    joint_binding={}
    if value.get('jointReports') is True:
        import hashlib,json
        cell_ids={cid for row in layout for cid in row['claimIds']}
        fields=('claimId','kind','text','conditions','evidenceRefs','tableBindings','obligationIds','scopeExpression','executionSpec')
        joint=[{k:c[k] for k in fields if k in c} for c in claims
               if c['claimId'] not in cell_ids and c.get('kind')=='reported']
        if joint:
            joint_binding={'jointReportedClaimsSha256':hashlib.sha256(json.dumps(joint,ensure_ascii=False,
                sort_keys=True,separators=(',',':')).encode()).hexdigest()}
    return {'version': value['version'], 'sources': deepcopy(value['sources']), 'layout': layout,
            'sections': sections(value, claims), 'table': table,
            **({'jointGoals':deepcopy(value['jointGoals'])} if value['version']==3 else {}),
            **({'jointReports':True} if value.get('jointReports') is True else {}),**joint_binding}


def audit_digest(value, claims):
    import hashlib
    import json
    return hashlib.sha256(json.dumps(audit_view(value, claims), ensure_ascii=False,
                                    sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def revalidate_audit(audit, value, claims):
    if value is not None and audit.get('comparisonPresentationDigest') == audit_digest(value, claims):
        return audit
    gap = {'obligationId': audit.get('wholeQuestionId') or 'answer_comparison_layout',
           'stage': 'answer', 'wholeQuestion': True,
           'missingEvidence': '比较表格或条目归属尚未通过当前答案审核'}
    return {**audit, 'status': 'invalidated_comparison_presentation',
            'gaps': [*audit.get('gaps', []), gap]}


def metadata(draft):
    version = draft.get('layoutVersion',1)
    shared = type(version) is int and version in (2,3)
    fields = ('obligationId', 'question', 'source', 'claimIds')
    if shared: fields += ('axisId', 'axisTitle')
    return {'version': version if shared else 1,
            **({'checkOutputShapeVersion':1} if version==3
               and type(draft.get('answerWireAudit',{}).get('version')) is int
               and draft['answerWireAudit']['version']==2 else {}),
            **({'jointReports':True} if version==3 and draft.get('jointReports') is True else {}),
            **({'jointGoals':deepcopy(draft['jointGoals'])} if version==3 else {}), 'sources': deepcopy(draft['sources']),
            'layout': [{k: deepcopy(row[k]) for k in
                        (*fields, *(['obligationIds'] if 'obligationIds' in row else []))}
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
        shared = value['version'] in (2,3)
        key = row['axisId'] if shared else row['obligationId']
        if key not in groups:
            groups[key] = {'question': row['axisTitle'] if shared else row['question'], 'cells': {}}
        if not shared:
            groups[key]['cells'][row['source']] = row
            continue
        cell = groups[key]['cells'].setdefault(row['source'], {'claimIds': []})
        # Several obligations can share a display axis, but remain distinct
        # claims with their original source permissions and coverage identities.
        cell['claimIds'].extend(cid for cid in row['claimIds'] if cid not in cell['claimIds'])
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
