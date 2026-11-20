"""Source-local representation guidance; no evidence or reviewer relaxation."""
GUIDANCE = '''Only actual source-local tableData/tableDataRef defines typed cells. Plain-text tables
are quotations, not cell packets: use own evidenceRefs and tableBindings=[] when that
field exists; never invent row/group indices. For supplied typed cells bind exact
own evidenceId, original source rowNumber (not selected position), zero-based groupIndex,
packet metric key including its arrows, and unchanged value. Omitted geometry grants no
cells; ambiguous fragments cannot justify guessed numerical facts.
Every raw number still needs its exact method/variant, dataset, subgroup/aggregate,
metric direction, unit and own literal quotation. Another paper's comparator is not
an author's self-report; do not invent all-scene aggregates from indoor/outdoor values.
Derived quantities are inferences bound to source inputs, not reported cells.
Model knowledge and rejected annotations are not sources. Omit unsupported optional
parameters while preserving requested mechanisms and scope. Independent checks remain.
'''
