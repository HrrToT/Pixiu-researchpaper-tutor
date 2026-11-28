import { useEffect, useState } from 'react';

/** Emphasize observed changes only: loading history and reopening a task stay quiet. */
export function useTransitionCue(identity, value) {
  const [observed, setObserved] = useState({ identity, value, cue: false });
  const sameSnapshot = observed.identity === identity && observed.value === value;
  if (!sameSnapshot) {
    setObserved({ identity, value, cue: observed.identity === identity && Boolean(observed.value && value) });
  }
  useEffect(() => {
    if (!observed.cue) return;
    const timer = setTimeout(() => {
      setObserved(current => current === observed ? { ...current, cue: false } : current);
    }, 1800);
    return () => clearTimeout(timer);
  }, [observed]);
  return sameSnapshot && observed.cue;
}
