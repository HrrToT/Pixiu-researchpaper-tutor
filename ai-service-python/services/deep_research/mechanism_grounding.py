"""Mechanism attribution guidance, not a verdict or an additional model call."""

GUIDANCE = '''Check the named component's actual operation, inputs, reference and output
against that target's OWN sources, including the source's subject and contrast.
An adjacent component's statement or a combined training result does not establish
this component's independent operation, localization, supervision or measured benefit.
Relative consistency among predictions does not supply an absolute reference or
known true target. A penalty minimizing differences among predictions can encourage
agreement without identifying where the correct solution is. A claimed true-reference
anchor needs evidence identifying that reference and its use; co-occurrence of words
about actual objects in a neighboring paragraph is not that evidence.
Separate what the objective penalizes/encourages, the author's intended purpose,
and an observed or guaranteed outcome. Do not promote the first into the latter.
When a reported mechanism adds an unsupported anchor, causal effect or supervision,
fail the unsupported clause precisely; a true prefix does not approve the full claim.
Conversely, a faithful explanation of an evidenced input and penalized relation needs
no extra measured result or proof of perfect reconstruction. Do not add requirements.
This applies to facts inside proposals too; unexecuted design choices remain proposals.
'''
