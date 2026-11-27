"""Known visible parameter indices are identities, not new measurements."""
import re
from services.deep_research.audit_source_fields import resolve
from services.deep_research.measurement_numbers import parameter_identifiers,without_parameter_identifiers
from services.deep_research.verification import _measurement_numbers


_PAIR_OF_CONDITIONS = re.compile(
    r'(?<![A-Za-z0-9_.-])(?:both|two|2)\s+condi(?:-\s*)?tions\b'
    r'|(?<![零一二两三四五六七八九十百千万亿\d.])(?:两|二|2)\s*(?:种|项|个)\s*(?:评测|实验)?条件',
    re.I)


def scanner(own, *, alignment_words=False, explicit_condition_pairs=False):
    known=set()
    for eid in own:
        for path in (['quote'],['sourceContext'],['sourceContext','before'],['sourceContext','after']):
            resolved=resolve({'evidenceId':eid,'path':path},own)
            if resolved is not None:known.update(parameter_identifiers(resolved[1]))
    def numbers(text):
        if alignment_words:
            # 数量扫描不得把「统一条件」断成「一条」。
            text = text.replace('统一条件', '对齐条件')
        # Adjacent quantity/unit spellings remain conservatively numeric. A
        # coefficient assigned to the identifier is outside the removed token.
        allowed={name for name in known if not re.search(re.escape(name)+r'(?=[A-Za-z%％×倍])',text)}
        pairs = set()
        if explicit_condition_pairs and _PAIR_OF_CONDITIONS.search(text):
            # Retain the object of the count so two images or views cannot
            # provide the numeric evidence for two evaluation conditions.
            pairs.add('conditions:2')
            text = _PAIR_OF_CONDITIONS.sub(' ', text)
        return pairs | _measurement_numbers(without_parameter_identifiers(text,allowed),word_counts=True)
    return numbers
