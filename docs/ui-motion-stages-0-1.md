# UI motion stages 0–1

## Accepted visual baseline

- `d63bc6ec`: table columns, task navigation, composer footer and next-step menu.
- `a0b2cf5d`: learning-record hierarchy and evidence-list alignment.
- Keep the existing width of chat-only mode (user preference).
- Baseline screenshots covered desktop, dark appearance, narrow split panes and compact menus. Real mobile software-keyboard behavior is outside this acceptance scope.

## Citation focus contract

Only source-navigation requests activate citation focus; normal pagination does not.
Known saved annotation coordinates receive a region overlay. Other sources receive a page outline explicitly labelled as page-level positioning. This change does not add text matching or infer paragraph coordinates.

Focus persists without a timer. Clicking within its region, scrolling, selecting and copying text retain it. Pointer input outside the region or Escape fades it out in 200 ms. Another citation replaces it. Hiding the reader or switching documents clears it, and returning does not revive the consumed request. Reduced-motion preferences disable transitions.

## Validation

- 16 focused tests passed (citation lifecycle and PDF viewer lifecycle), including Strict Mode, page fallback and saved-area rendering.
- TypeScript check and production build passed. Existing dependency/bundle warnings remain.
- Real PDF browser check: page outline and page-level label, persistent focus during page click/scroll, opacity reaching zero after clicking the conversation input.
- Precise saved-area behavior has automated coverage; it has not been visually accepted on a real saved annotation. Dark appearance, reduced motion and mobile selection also remain separate visual checks.

Stages 2–4 (save feedback, general transitions, research-state guidance) are not included.
