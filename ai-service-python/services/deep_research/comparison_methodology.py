"""Logical comparison definitions, never extra empirical paper evidence.

Engineering rationale was checked against the official Google Benchmark timing
guide and MLPerf Inference submission guide on 2026-10-18. They distinguish
measurement modes/scenarios and system comparisons. No benchmark observation is
injected into a user's task; no dependency or runtime network call is introduced.
"""

REFERENCES=(
    'https://google.github.io/benchmark/user_guide.html#manual-timing',
    'https://docs.mlcommons.org/inference/submission/',
)

REFERENCE='''Comparison reasoning definitions (trusted logic, NOT empirical paper evidence):
First distinguish arithmetic on reported numbers, a comparison of whole measured systems,
and an isolated effect attributed to one method. A numeric quotient with a nonzero
denominator is calculable; its scientific interpretation also needs commensurate quantities
and the conditions relevant to the particular question. Equal unit labels alone do not
establish the same measured operation. A raw quotient alone cannot identify a method effect.
System comparisons may intentionally vary hardware; do not demand identical hardware for
every useful comparison. For an isolated method effect, explain what is actually controlled
or what relevant alignment the selected evidence has not established. Unknown alignment is
not a demonstrated difference, an author-wide omission, or arithmetic impossibility.
If the question assumes an unsupported impossibility, correct that premise explicitly before
giving the evidence-bounded interpretation. Do not repeat the assumed conclusion in the opening.
These definitions require no assertion that a research paper literally states them. For an
inference, check its empirical premises against its OWN citations and its logical implication
under the stated comparison type. Every paper-specific operation, platform, protocol, setting,
number or causal finding still requires its own original evidence; never invent one from this
reference. A generic possible confounder is not an established cause in the compared papers.
Report the available premises and a qualified judgement; do not use unrelated baseline captions
to establish a paper's own timing protocol. These definitions grant no automatic verification.'''
