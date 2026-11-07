import { useEffect, useRef, useState, type RefObject } from 'react';

// A citation is a reading state, not a timed notification. Only a new request
// can reactivate it after dismissal or after the reader has been hidden.
export function useCitationFocus(root: RefObject<HTMLDivElement | null>, token: number, ready: boolean, active: boolean, documentKey: string) {
  const consumed = useRef(0);
  const previousDocument = useRef(documentKey);
  const [focus, setFocus] = useState<{ token: number; leaving: boolean } | null>(null);
  useEffect(() => {
    if (previousDocument.current !== documentKey) {
      previousDocument.current = documentKey;
      setFocus(null);
    }
    if (!active || !token) { setFocus(null); return; }
    if (ready && consumed.current !== token) {
      consumed.current = token;
      setFocus({ token, leaving: false });
    }
  }, [token, ready, active, documentKey]);
  useEffect(() => {
    if (!focus || focus.leaving) return;
    const dismiss = () => setFocus(current => current ? { ...current, leaving: true } : null);
    const pointer = (event: PointerEvent) => {
      const scroller = root.current?.querySelector('.rpv-core__inner-pages');
      if (!(event.target instanceof Node) || !scroller?.contains(event.target)) { dismiss(); return; }
      // Overlays never intercept selection. Hit-test their actual screen rects
      // because the click target will normally be the PDF text layer below.
      const inside = [...(root.current?.querySelectorAll('[data-citation-focus-region]') || [])].some(node => {
        const rect = node.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && event.clientX >= rect.left && event.clientX <= rect.right && event.clientY >= rect.top && event.clientY <= rect.bottom;
      });
      if (!inside) dismiss();
    };
    const key = (event: KeyboardEvent) => { if (event.key === 'Escape') dismiss(); };
    document.addEventListener('pointerdown', pointer, true);
    document.addEventListener('keydown', key, true);
    return () => {
      document.removeEventListener('pointerdown', pointer, true);
      document.removeEventListener('keydown', key, true);
    };
  }, [focus, root]);
  return focus;
}
