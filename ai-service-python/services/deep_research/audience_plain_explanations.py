"""Reader wording policy only; preserves source permissions and verification."""
import re

_MATH=re.compile(r'公式|推导|算式|[α-ωΑ-Ω]|\b(?:formulas?|equations?|derive|derivation)\b',re.I)
_NEGATIVE=re.compile(r"(?:不要|无需|不需要|不用|避免|不含|without|\bno|do not|don't)[^，。；;.!?\n]{0,20}$",re.I)


def notation_requested(question):
    return any(not _NEGATIVE.search(question[max(0,m.start()-30):m.start()]) for m in _MATH.finditer(question))


def guidance(question):
    text="""Reader wording contract2:
Write the explanation in short connected Chinese prose. Lead with what the method
actually does, not a technical definition followed by an equation. For EVERY requested
mechanism explain the roles in words: what is retained/observed -> the actual operation
on it -> how that result is used in the next step. A term list, an equation or 'used for
updating/training' alone does not explain that relationship. Name necessary quantities
by what they do before naming the technical term. Keep each target's own contribution.
Explain only links supported by its own original sources; a familiar mechanism is not
evidence. State the specific unavailable link rather than fill it from memory. Distinguish
removing a stated cause of bias/error from removing every possible bias/error or guaranteeing
an outcome. Keep the source's assumptions in the same short explanation when needed.
This is a wording constraint, not permission for new claims, source bindings or approval.
Keep requested numeric comparisons and required table relationships; the original total
character limit still includes all texts and conditions. No extra sections or process log.
"""
    if notation_requested(question):
        return text+'The human explicitly requests mathematical notation: preserve the requested symbols/derivation, but explain each role in words before the notation.\n'
    return text+('The human did not request formulas or a derivation: omit optional equations, Greek '
                 'variables and parameter labels. Use their source-supported roles in words instead. '
                 'Do not omit a required quantity, comparison or necessary condition.\n')
