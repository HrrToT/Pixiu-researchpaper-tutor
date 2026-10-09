"""Keep extracted inline expressions out of prose translation, without repairing math."""
import re

# Small identifiers prevent an English sentence from becoming one math span.
ATOM = r"(?:[A-Za-zΑ-Ωα-ω0-9]{1,6}(?![A-Za-z])(?:[′']|\([^\n]{1,24}?\))?)"
EXPRESSION = re.compile(
    rf"(?<![A-Za-z]){ATOM}(?:\s*[=∈×·+−^]\s*{ATOM})+(?:\s+[A-ZΑ-Ωα-ω0-9]{{1,12}}(?![A-Za-z]))*"
    r"|\bR(?:\d|\([^\n]{1,20}?\))+(?:\s*×\s*\d+)?"
)
TOKEN = re.compile(r"⟦原式\d+⟧")


def protect_inline_math(text, start_index=0):
    count = max([start_index, *[int(token[3:-1]) for token in TOKEN.findall(str(text or ''))]])
    def replace(match):
        nonlocal count
        count += 1
        return f'⟦原式{count}⟧'
    return EXPRESSION.sub(replace, str(text or ''))


def has_intact_math_tokens(source, translated):
    expected = TOKEN.findall(source)
    actual = TOKEN.findall(translated)
    return expected == actual
