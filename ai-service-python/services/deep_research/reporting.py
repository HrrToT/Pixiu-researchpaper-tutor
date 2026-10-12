"""Organize accepted claims; never render unverified model section prose."""
from services.deep_research.synthesis import OUTPUT_KIND_SECTIONS, resolve_output_kind


def build_sections(claims, output_kind, proposed_sections=None):
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
    return sections


def _display_gaps(gaps):
    """Keep the full audit in storage, show each unfinished obligation once."""
    specific = [g for g in gaps if not isinstance(g, dict) or not g.get('wholeQuestion')]
    selected = {}
    for gap in specific or gaps:
        key = (gap.get('obligationId') or gap.get('question')) if isinstance(gap, dict) else gap
        if key and (key not in selected or isinstance(gap, dict) and gap.get('stage') == 'answer'):
            selected[key] = gap
    return list(selected.values())


def render_report(payload):
    claims = {claim["claimId"]: claim for claim in payload.get("claims", []) if claim.get("claimId")}
    refs = list(dict.fromkeys(ref for claim in claims.values() for ref in claim.get("evidenceRefs", [])))
    ref_numbers = {ref: index + 1 for index, ref in enumerate(refs)}
    sources = {e["evidenceId"]: e for e in payload.get("evidence", []) if e.get("evidenceId")}
    lines, rendered = [], set()
    sections = payload.get("sections") or build_sections(list(claims.values()), payload.get("outputKind", "direction_survey"))
    labels = {"inference": "有依据的推断：", "hypothesis": "待验证假设：", "suggestion": "实验建议：", "proposal": "实验建议："}
    for section in sections:
        content = []
        for key in section.get("claimIds", []):
            claim = claims.get(key)
            if not claim or key in rendered:
                continue
            rendered.add(key)
            citations = " ".join(f"[{ref_numbers[ref]}](#research-evidence-{ref})" for ref in claim.get("evidenceRefs", []) if ref in ref_numbers)
            content.append(f"- {labels.get(claim.get('kind'), '')}{claim['text']} {citations}".rstrip())
            conditions = claim.get("conditions")
            if isinstance(conditions, dict) and conditions:
                content.append("  适用条件：" + "；".join(f"{name}：{value}" for name, value in conditions.items()))
        if content:
            lines.extend([f"## {section['title']}", "", *content, ""])
    if not claims:
        lines.extend(["当前取得的证据不足以回答这个问题。", ""])
    gaps = _display_gaps(payload.get("gaps", []))
    if gaps:
        lines.extend(["<details>", f"<summary>还有 {len(gaps)} 项未完成</summary>", ""])
        for gap in gaps[:8]:
            question = gap if isinstance(gap, str) else gap.get("question", "")
            if question:
                reason = gap.get("missingEvidence", "") if isinstance(gap, dict) else ""
                lines.append(f"- {question}" + (f"：{reason}" if reason else ""))
        lines.extend(["", "</details>", ""])
    if payload.get("limitations"):
        lines.extend([payload["limitations"], ""])
    if refs:
        lines.extend(["<details>", "<summary>原文依据</summary>", ""])
        for ref in refs:
            evidence = sources.get(ref, {})
            title = evidence.get("sourceTitle") or evidence.get("sourceWorkId") or "论文来源"
            page = evidence.get("location", {}).get("page")
            access = " · 仅摘要" if evidence.get("accessLevel") == "abstract" else ""
            lines.append(f"**[{ref_numbers[ref]}] {title}**" + (f" · 第 {page} 页" if page else "") + access)
            if evidence.get("quote"):
                lines.extend(["", "> " + evidence["quote"].replace("\n", "\n> "), ""])
        lines.extend(["</details>", ""])
    return "\n".join(lines).strip()


def conversation_summary(claims, outcome, *, max_chars=500):
    """Keep whole claims and their epistemic labels; never cut a number or condition."""
    labels = {"inference": "有依据的推断：", "hypothesis": "待验证假设：",
              "suggestion": "实验建议：", "proposal": "实验建议："}
    boundary = {"partial": "当前结果尚不完整，已核实的内容已保存。",
                "inconclusive": "当前取得的证据不足以形成可靠结论。"}.get(outcome, "")
    parts = []
    length = len(boundary)
    for claim in claims:
        text = str(claim.get("text", "")).strip()
        if not text:
            continue
        item = labels.get(claim.get("kind"), "") + text
        conditions = claim.get("conditions")
        if isinstance(conditions, dict) and conditions:
            item += "（" + "；".join(f"{key}：{value}" for key, value in conditions.items()) + "）"
        if length + len(item) + 2 > max_chars:
            continue
        parts.append(item)
        length += len(item) + 2
    if boundary:
        parts.append(boundary)
    return "\n\n".join(parts) or "研究结果已保存，可打开报告查看。"
