"""Final-answer completeness instructions, separate from factual verification."""

FINAL_COVERAGE_POLICY = '''Factual support was checked separately; truth, retrieval relevance,
obligationIds and citations alone do NOT prove a complete answer. Judge the accepted
text and conditions against the original question AND frozen completionCriteria.
Preserve requested brevity: require necessary parameters, activation/applicability,
assumptions and comparisons, not unrelated paper/implementation details or experiments.
For v2 proposals, text omits only the exact app-generated trailing rendering;
executionSpec retains every displayed value. Together they form the final answer.
Original prose/conditions remain unchanged; check their consistency too.

Audit each criterionId separately, preserving its planned responseType even if missing.
Explanation requires HOW/WHY inputs change/constrain operations or outputs; names,
technical terms or "X then Y" are identification. Novices need ordinary-word mechanisms.
For training/feedback, connect error/signal, updated intermediate/parameter, and later
predictions when the evidence establishes that path. Naming reparameterization or
"gradients flow" alone is insufficient. For requested measurements, the answer must
map EACH value to its entity, subgroup, aggregate and metric; source quotes/rejected
claims cannot supply an omitted mapping. Compare each requested dimension and paper.
A clearly scoped evidence limitation can answer an uncertainty question; do not demand
a universal guarantee. An unexecuted proposal needs no measured experimental results.
New proposed splits/resolutions/budgets need not reproduce author settings. Require
original counts/splits/iterations only when requested or needed by a stated factual
claim; ground existing dataset/subset membership independently.

supporting_research is auxiliary, not automatically required narration. Independently
judge its necessity for the actual deliverable. If genuinely unnecessary, return
not_required with a specific reason (>=12 characters), requestExcerpt (>=8 characters
copied exactly from the original question) and accepted-answer bindings showing why
that scope suffices. Never exempt the original question or an answer_requirement.
A label cannot waive requested facts, claim dependencies, interventions, assumptions
or required evidence. Necessary unanswered supporting work stays partial/missing.
not_required never means a source fact was checked. Separate proposed protocol
completeness from retelling author benchmarks. Do not rewrite/add claims, change
factual verdicts or judge rejected claims.

Before marking covered, enumerate minimal essential aspects from the QUESTION AND
SUPPLIED SOURCES, not just the answer: entities/relationships, distinct conditioning
inputs, activation/applicability, comparisons and guarantee boundaries. Do not merge
distinct inputs into a vague aspect. Every necessary aspect needs its own basis and
actual accepted-answer binding; a true but incomplete summary stays partial.

Prefer exact field references. A source basis is
{"kind":"source","evidenceId":"supplied ID","field":"quote"}.
sourceContext.before/after are permitted only when that exact supplied field exists;
the server binds the entire unchanged field. Never combine field and excerpt or infer
omitted context. Answer bindings are {"claimId":"accepted ID","field":"text"} or
field="conditions" (that claim's serialized conditions); use only content actually
covering the aspect. Legacy exact literal excerpts remain valid: no ellipses, spelling/
punctuation normalization or joined noncontiguous excerpts. Source-grounded factual
aspects must bind accepted factual claims citing that PRECISE evidenceId, paper/version.
Another paper's quote or an uncited source cannot fill a missing condition. Factual
coverage cannot rest only on a broad request basis. Purely proposed choices can use
{"kind":"request","excerpt":"exact question substring"}; unrelated proposals cannot
substitute for grounding facts.

For acquisition access-level requirements ONLY, use
{"kind":"source_metadata","evidenceId":"ID cited by the bound claim",
 "field":"accessLevel","value":"fulltext|abstract|user_note",
 "requestExcerpt":"exact relevant question substring, >=8 characters"}.
Copy the actual supplied metadata; never infer access from page numbers. All aspects
of a metadata-only obligation need this basis; mixed obligations still need source
quotes for scientific content. Keep exact answer bindings: downloading a PDF does not
prove the answer uses it unless the bound claim cites it. Metadata never proves a
method/result. Resolve contrasts/pronouns from preceding sentences; do not assign a
baseline limitation to the proposed method.

Return one JSON object per listed obligationId, including original-question scope:
{"obligationId":"ID","status":"covered|partial|missing|not_required",
 "bindings":[{"claimId":"accepted ID","field":"text"}],
 "criteria":[{"criterionId":"planned ID","responseType":"planned type",
   "status":"covered|partial|missing","bindings":[{"claimId":"accepted ID","field":"text"}]}],
 "aspects":[{"aspectId":"unique within obligation","requirement":"one essential aspect",
   "basis":{"kind":"source","evidenceId":"supplied ID","field":"quote"},
   "status":"covered|partial|missing","bindings":[{"claimId":"accepted ID","field":"text"}]}]}.
Every planned criterion needs exactly one verdict; original-question scope and legacy
obligations without criteria need none. Bind actual answer spans, never source sentences.
Missing criteria/aspects use empty bindings. Covered requires ALL essential aspects
answered with valid individual bindings, not just related statements or citations.
'''
