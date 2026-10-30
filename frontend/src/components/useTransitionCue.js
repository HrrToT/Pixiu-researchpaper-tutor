import { useEffect, useRef, useState } from 'react';

/** Emphasize observed changes only: loading history and reopening a task stay quiet. */
export function useTransitionCue(identity, value) {
  const previous = useRef({ identity, value });
  const [cue, setCue] = useState(null);
  useEffect(() => {
    const old = previous.current;
    previous.current = { identity, value };
    if (old.identity !== identity || !old.value || !value) { setCue(null); return; }
    if (old.value === value) return;
    setCue({ identity, value });
    const timer = setTimeout(() => setCue(null), 1800);
    return () => clearTimeout(timer);
  }, [identity, value]);
  return cue?.identity === identity && cue?.value === value;
}
