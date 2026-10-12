"""Bound prompt size while retaining different papers and research obligations."""
from collections import deque


def balanced_sample(items, key, limit):
    groups = {}
    for item in items:
        groups.setdefault(key(item), deque()).append(item)
    selected = []
    while groups and len(selected) < limit:
        for group in list(groups):
            selected.append(groups[group].popleft())
            if not groups[group]:
                del groups[group]
            if len(selected) == limit:
                break
    return selected
