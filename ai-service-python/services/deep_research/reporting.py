"""Organize accepted claims; never render unverified model section prose."""
import json
import re
from services.deep_research.synthesis import OUTPUT_KIND_SECTIONS, resolve_output_kind


def build_sections(claims, output_kind, proposed_sections=None, *, presentation_version=0):
    templates = OUTPUT_KIND_SECTIONS.get(resolve_output_kind(output_kind), OUTPUT_KIND_SECTIONS["direction_survey"])
    indexed = {claim["claimId"]: claim for claim in claims if claim.get("claimId")}
    used, sections = set(), []
    if output_kind == 'experiment_design':
        from services.deep_research.experimental_reasoning import DESIGN_ROLES
        for title in templates:
            ids = [key for key, claim in indexed.items()
                   if isinstance(claim.get('designRole'), str)
                   and DESIGN_ROLES.get(claim['designRole'], (None,))[0] == title]
            if ids:
                used.update(ids)
                sections.append({'title': title, 'claimIds': ids})
    for section in proposed_sections or []:
        if not isinstance(section, dict) or section.get("title") not in templates:
            continue
        refs = section.get("claimIds", [])
        if not isinstance(refs, list):
            continue
        ids = [key for key in refs if isinstance(key, str) and key in indexed and key not in used]
        if ids:
            used.update(ids)
            sections.append({"title": section["title"], "claimIds": ids})
    # Keep every accepted claim even if the model supplied a malformed section map.
    remaining = [key for key in indexed if key not in used]
    if remaining:
        sections.append({"title": templates[0], "claimIds": remaining})
    sections.sort(key=lambda section: templates.index(section["title"]))
    if (type(presentation_version) is int and presentation_version in (1, 2, 3)
            and resolve_output_kind(output_kind)=='claim_verification'):
        # These IDs contain independently accepted claims, including revisions
        # whose content changed after the model's original section assignment.
        # Actual unfinished obligations are rendered separately from payload.gaps.
        sections=[{**section,'title':'依据与范围'} if section['title']=='未解决事项' else section
                  for section in sections]
    if type(presentation_version) is int and presentation_version in (2,3):
        # Revisions can return claims to the fallback section. Keep all claims
        # under a single heading without rewriting their words or old reports.
        merged = {}
        for section in sections:
            group = merged.setdefault(section['title'], {'title':section['title'], 'claimIds':[]})
            group['claimIds'].extend(key for key in section['claimIds'] if key not in group['claimIds'])
        sections = list(merged.values())
    return sections


def _display_gaps(gaps, *, presentation_version=0):
    """Keep the full audit in storage, show each unfinished obligation once."""
    specific = [g for g in gaps if not isinstance(g, dict) or not g.get('wholeQuestion')]
    selected = {}
    for gap in specific or gaps:
        key = (gap.get('obligationId') or gap.get('question')) if isinstance(gap, dict) else gap
        if key and (key not in selected or isinstance(gap, dict) and gap.get('stage') == 'answer'):
            selected[key] = gap
    rows = list(selected.values())
    if type(presentation_version) is not int or presentation_version not in (2,3):
        return rows
    merged = {}
    for index, gap in enumerate(rows):
        if not isinstance(gap, dict) or not isinstance(gap.get('question'), str) or not gap['question'].strip():
            merged[('unmerged', index)] = gap
            continue
        # Repeated retrieval obligations can refer to the same human question.
        # Coalesce only equal displayed questions/reasons, retaining distinct
        # reasons and the union of missing aspects; the full audit stays stored.
        key = (gap['question'], gap.get('missingEvidence', ''))
        if key not in merged:
            merged[key] = {**gap, 'missingAspects':list(gap.get('missingAspects') or [])}
        else:
            aspects = merged[key]['missingAspects']
            aspects.extend(a for a in gap.get('missingAspects', []) if a not in aspects)
    return list(merged.values())


def source_access_summary(claims, evidence):
    """Describe cited external evidence, never imply the entire paper was read."""
    refs = {ref for claim in claims for ref in claim.get('evidenceRefs', [])}
    cited = [item for item in evidence if item.get('evidenceId') in refs]
    if not any(item.get('sourceKind') == 'arxiv' for item in cited):
        return ''
    levels = {item.get('accessLevel') for item in cited}
    labels = [label for level, label in [('fulltext', '全文片段'), ('abstract', '摘要'),
                                         ('user_note', '笔记')] if level in levels]
    if levels - {'fulltext', 'abstract', 'user_note'} or refs - {item.get('evidenceId') for item in cited}:
        labels.append('访问范围未标明的材料')
    return '本回答引用：' + '、'.join(labels) + '。'


def display_conditions(conditions):
    """The generic context wrapper is metadata; retain every condition value."""
    if not isinstance(conditions, dict):
        return ''
    return '；'.join(str(value) if name == 'context' else f'{name}：{value}'
                    for name,value in conditions.items())


def _claim_label(claim,labels,version,output_kind):
    if type(version) is int and version==3 and output_kind!='experiment_design':
        from services.deep_research.general_advice import eligible
        if eligible(claim):
            return '' if re.match(r'^(?:建议|推荐)',str(claim.get('text',''))) else '建议：'
    return labels.get(claim.get('kind'),'')


def render_report(payload, *, _counting=False):
    claims = {claim["claimId"]: claim for claim in payload.get("claims", []) if claim.get("claimId")}
    refs = list(dict.fromkeys(ref for claim in claims.values() for ref in claim.get("evidenceRefs", [])))
    ref_numbers = {ref: index + 1 for index, ref in enumerate(refs)}
    sources = {e["evidenceId"]: e for e in payload.get("evidence", []) if e.get("evidenceId")}
    access_summary = source_access_summary(list(claims.values()), list(sources.values()))
    lines, rendered = ([access_summary, ''] if access_summary else []), set()
    sections = payload.get("sections") or build_sections(list(claims.values()), payload.get("outputKind", "direction_survey"))
    compact = (type(payload.get('presentationVersion')) is int and payload['presentationVersion'] in (2,3))
    limited = compact and type(payload.get('characterLimit')) is int and payload['characterLimit'] > 0
    labels = {"inference": "有依据的推断：", "hypothesis": "待验证假设：", "suggestion": "实验建议：", "proposal": "实验建议："}
    if compact:
        labels['inference'] = '推断：'
    for section in sections:
        content = []
        analysis_protocols = set()
        for key in section.get("claimIds", []):
            claim = claims.get(key)
            if not claim or key in rendered:
                continue
            rendered.add(key)
            citations = " ".join(f"[{ref_numbers[ref]}](#research-evidence-{ref})" for ref in claim.get("evidenceRefs", []) if ref in ref_numbers)
            if _counting:
                citations = ' '.join(str(ref_numbers[ref]) for ref in claim.get('evidenceRefs', []) if ref in ref_numbers)
            text = claim['text']
            if claim.get('designRole') == 'analysis':
                from services.deep_research.execution_materialization import verification_claim_view
                prose = verification_claim_view(claim).get('text')
                if isinstance(prose, str) and prose != text:
                    suffix = text[len(prose):]
                    protocol_key = (json.dumps(claim.get('executionSpec'), sort_keys=True, ensure_ascii=False), suffix)
                    if protocol_key in analysis_protocols:
                        text = prose
                    else:
                        analysis_protocols.add(protocol_key)
            # Only repeated deterministic protocol suffixes are hidden. Keep
            # every original sentence, condition and source on its own claim.
            label=_claim_label(claim,labels,payload.get('presentationVersion'),payload.get('outputKind'))
            content.append(f"{'' if _counting else '- '}{label}{text} {citations}".rstrip())
            conditions = claim.get("conditions")
            if isinstance(conditions, dict) and conditions:
                content.append("  适用条件：" + display_conditions(conditions))
        if content:
            redundant_heading = (limited and len(sections) == 1
                                 and section['title'] in ('判断', '核心判断', '比较结论'))
            if not redundant_heading:
                lines.extend([f"{'' if _counting else '## '}{section['title']}", ''])
            lines.extend([*content, ''])
    if not claims:
        empty = ("尚未形成通过核验的实验方案。" if payload.get('outputKind') == 'experiment_design'
                 else "本次尚未形成通过核验的结论。")
        lines.extend([empty, ""])
    gaps = _display_gaps(payload.get("gaps", []), presentation_version=payload.get('presentationVersion',0))
    if gaps and not _counting:
        lines.extend(["<details>", f"<summary>还有 {len(gaps)} 项未完成</summary>", ""])
        for gap in gaps:
            question = gap if isinstance(gap, str) else gap.get("question", "")
            if question:
                reason = gap.get("missingEvidence", "") if isinstance(gap, dict) else ""
                if compact and isinstance(gap, dict):
                    aspects = [a for a in gap.get('missingAspects', []) if isinstance(a,str) and a.strip()]
                    if aspects:
                        reason += ('；' if reason else '') + '缺少：' + '、'.join(dict.fromkeys(aspects))
                lines.append(f"- {question}" + (f"：{reason}" if reason else ""))
        lines.extend(["", "</details>", ""])
    notes = payload.get('researchNotes')
    if isinstance(notes, list) and notes and not _counting:
        lines.extend(['<details>', '<summary>查证范围说明</summary>', ''])
        for note in notes:
            if isinstance(note, dict) and isinstance(note.get('question'), str) and note['question']:
                lines.append('- 辅助问题「' + note['question'] + '」未纳入本次回答范围。')
        lines.extend(['', '</details>', ''])
    if payload.get("limitations"):
        lines.extend([payload["limitations"], ""])
    if refs and not _counting:
        lines.extend(["<details>", "<summary>原文依据</summary>", ""])
        for ref in refs:
            evidence = sources.get(ref, {})
            title = evidence.get("sourceTitle") or evidence.get("sourceWorkId") or "论文来源"
            page = evidence.get("location", {}).get("page")
            access = {'abstract': ' · 仅摘要', 'fulltext': ' · 全文片段',
                      'user_note': ' · 笔记'}.get(evidence.get('accessLevel'), '')
            lines.append(f"**[{ref_numbers[ref]}] {title}**" + (f" · 第 {page} 页" if page else "") + access)
            if evidence.get("quote"):
                lines.extend(["", "> " + evidence["quote"].replace("\n", "\n> "), ""])
        if compact and payload.get('verificationNotice'):
            lines.extend([payload['verificationNotice'], ''])
        lines.extend(["</details>", ""])
    elif compact and payload.get('verificationNotice') and not _counting:
        lines.extend(['<details>', '<summary>核查说明</summary>', '', payload['verificationNotice'], '', '</details>'])
    return "\n".join(lines).strip()


def visible_answer_character_count(payload):
    """Count direct answer text, excluding server disclosures and decoration.

    Claim-authored Markdown/LaTeX is counted conservatively as written; it
    cannot introduce fake disclosure markup to evade the budget.
    """
    return len(re.sub(r'\s+', '', render_report(payload, _counting=True)))


def publication_notices(claims, *, presentation_version=0,output_kind=None):
    if type(presentation_version) is not int or presentation_version not in (2,3):
        return verification_notice(claims), ''
    from services.deep_research.general_advice import eligible
    visible = verification_notice([c for c in claims if c.get('kind') in {'hypothesis','proposal','suggestion'}
        and not (presentation_version==3 and output_kind!='experiment_design' and eligible(c))])
    folded = verification_notice([c for c in claims if c.get('kind') in {'reported','inference'}])
    return visible, folded


def verification_notice(claims):
    """Describe only the kinds actually retained in the published answer."""
    kinds = {claim.get('kind') for claim in claims}
    parts = []
    if 'reported' in kinds:
        parts.append('论文事实已按所列原文核对。')
    if 'inference' in kinds:
        parts.append('推断限于所列证据和适用条件。')
    if kinds & {'hypothesis', 'proposal', 'suggestion'}:
        parts.append('假设与实验建议尚未经过实验验证。')
    return ''.join(parts)


def conversation_summary(claims, outcome, *, max_chars=500, evidence=None, output_kind=None, presentation_version=0):
    """Keep whole claims and their epistemic labels; never cut a number or condition."""
    labels = {"inference": "有依据的推断：", "hypothesis": "待验证假设：",
              "suggestion": "实验建议：", "proposal": "实验建议："}
    if type(presentation_version) is int and presentation_version in (2,3):
        labels['inference'] = '推断：'
    boundary = {"partial": "当前结果尚不完整，已核实的内容已保存。",
                "inconclusive": "本次尚未形成通过核验的结论。"}.get(outcome, "")
    if outcome == 'inconclusive' and output_kind == 'experiment_design':
        boundary = '尚未形成通过核验的实验方案。'
    access = source_access_summary(claims, evidence or [])
    parts = [access] if access else []
    length = len(boundary) + len(access) + (2 if access else 0)
    for claim in claims:
        text = str(claim.get("text", "")).strip()
        if not text:
            continue
        item = _claim_label(claim,labels,presentation_version,output_kind) + text
        conditions = claim.get("conditions")
        if isinstance(conditions, dict) and conditions:
            item += "（" + display_conditions(conditions) + "）"
        if length + len(item) + 2 > max_chars:
            continue
        parts.append(item)
        length += len(item) + 2
    if boundary:
        parts.append(boundary)
    return "\n\n".join(parts) or "研究结果已保存，可打开报告查看。"
