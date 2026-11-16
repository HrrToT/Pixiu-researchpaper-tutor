"""Allow source-reported joint contrasts without relabeling them as inference."""


def enabled(record):
    from services.deep_research.comparison_intent import operations_enabled
    return (operations_enabled(record) and type(record.get('comparisonJointReportsContractVersion')) is int
            and record['comparisonJointReportsContractVersion']==1)


PLANNING = '''Use joint for a shared source-reported contrast or numerical example as well as
comparability, tradeoffs and conditional choice. A requested SINGLE baseline example
is one joint deliverable, not a separate numerical inventory for every paper.
One permitted publication may report both baseline and compared method. The required
material scope is not a demand for every number to appear in every paper.
Keep all independently requested per-paper mechanisms/costs and joint limitations.
Do not invent facts, simplify away dimensions or demand extra examples.'''

GENERATION = '''Joint targets may use kind=reported for a contrast directly reported by
their own permitted original sources; never relabel a reported measurement as inference
to fit the protocol. One publication can report both baseline and compared method.
Preserve baseline identity/variant, measured group, metric, unit and protocol in the
same point, with exact own tableBindings where applicable. Ordinary Ours outside a
paper-column cell needs its explicit source method identity, not a borrowed heading.
Respect the human's requested number of examples ACROSS the whole answer: do not
repeat the same numerical inventory in paper cells and the joint point. Select the
minimum sufficient matched example; retain necessary contrary results and all
mechanism/cost/comparability/choice goals. No source or format grants approval.'''
