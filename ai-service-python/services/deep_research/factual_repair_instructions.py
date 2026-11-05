"""Single copies of factual-repair rules; no source or scientific approval."""


def guidance(feature, legacy, version):
    if version != 1:
        return legacy
    return {
        'table_identity': 'Keep exact dataset/group, literal method/variant label beside metric/value; readable names may precede it. '
            'Drop only bibliography suffixes. Code/configuration is not published measurements. Marker meaning is paper-specific: '
            'resolve unverified same-version note candidates from own quotes. Provenance needs BOTH note and table cited in that claim; '
            'other-point notes prove no cells. Empty/missing citations prove no paper omission. Inferences need own premises, not matching author conclusions. '
            'Permissions unchanged; navigation/IDs stay private.',
        'comparison': 'Distinguish arithmetic, whole-system comparison, and isolated method effects. Nonzero-denominator ratios are calculable, '
            'but interpretation needs commensurate measured operations and question-relevant conditions; equal units alone are insufficient. '
            'System comparisons may vary hardware. Method-effect attribution needs actual controls/alignment; unknown alignment proves no difference, '
            'paper omission or arithmetic impossibility. Correct unsupported impossibility premises before the verdict. '
            'Own citations must support empirical operations/platforms/protocols/settings/numbers/causes; check logical implication for the stated comparison type. '
            'Possible confounders are not established causes; unrelated baseline captions prove no own timing protocol. These logic definitions grant no factual approval.',
        'advice': 'Ordinary advice retains proposal/suggestion kind, IDs, permissions, scope and shared length limit. '
            'Rebuild the actual reading/navigation goal, not an experiment; no seeds/splits/interventions/training budgets or experimental guarantees. '
            'Every embedded paper fact needs own permitted originals. Reading order is your advice unless explicitly author-prescribed. '
            'Check section/access identity against actual metadata/context: reading an abstract first does not mean abstract-only acquisition; method text is not an abstract. '
            'Old feedback aliases are not current evidence. Rebuild whole targets, not merely labels. Internal IDs stay private; factual, advice-purpose, scope and coverage reviews remain.',
        'preservation': 'Preserve every requested deliverable including advice, mechanisms, conditions and every point ID/kind/own refs. No repeated overview or bibliography/routing labels in public prose. '
            'Brevity removes repetition/irrelevant examples, never requested content or qualifications. Do not substitute a safe author-summary '
            'or generic uncertainty for the requested evidence-bounded answer. Unsupported parts stay unresolved; no invented facts or stronger conclusions.',
        'assessment': 'Assess the precise requested claim from underlying own evidence, not author repetition or a universal disclaimer. '
            'Give a bounded verdict and minimum informative observation with method/baseline variant, dataset/group, metric and actual conditions. '
            'Similar is not identical. Invent no tolerance, experimental difference, or demand for all metrics. '
            'Derived judgement is inference; bind reported input cells, never computed differences. '
            'Summary-only acquisition cannot independently check a claim. Scope limits concern acquired citations, '
            'never paper-wide missing experiments without explicit own evidence. Use scopeExpression for its boundary; '
            'no stronger absence in text/conditions, no negative finding from uncertainty. Obey point/length limits and independent review.',
        'access': 'The server labels accepted task/arXiv citations from actual accessLevel: fulltext means excerpts, abstract means abstract. '
            'Access is metadata, not scientific support or proof of reading the whole paper/user reading. '
            'Keep access declarations out of prose/conditions; do not change access or add irrelevant citations for a label. '
            'Without accepted citations, access disclosure remains unfinished.',
        'semantics': 'Your reading/learning route is proposal/suggestion, unexecuted ordinary advice. '
            'Author-prescribed order is reported only with an own explicit quote; section order is insufficient. '
            'Never claim the user read papers. Minimal/small loss means 精度损失较小/尽量减少精度损失, '
            'not comparative minimum/best without own evidence.',
        'conditions': 'Condition index copies visible table group/method labels for navigation only; mappings remain unverified. '
            'Check original headers, full quote/context and actual method in the relevant group, with own permitted E citation. '
            'Nearby related-work dataset names prove no evaluated setting. Labels prove no causation, comparable protocol, '
            'quality, universal scope or absence. Empty index means no indexed table, not no paper/pool evidence. '
            'No aliases, extra permissions, geometry/factual approval or public navigation text.',
    }[feature]


def scope_guidance(version):
    from services.deep_research.factual_prompt import scope_guidance as render
    return render(version)
