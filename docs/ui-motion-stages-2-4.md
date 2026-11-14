# UI motion stages 2–4

## Stage 2: confirmed save feedback

The existing pending/error/saved controls remain authoritative. A successful conversation save briefly emphasizes its confirmation and the destination navigation row. The cue is scoped to the task and expires after 1.8 seconds. It does not navigate, scroll the list or change filters. Existing records reuse the same save destination. Failed saves never create a destination cue.

## Stage 3: local transitions and learning

Popover panels, expanded evidence, research details and follow-up forms reveal in 160 ms with a 3 px displacement. Discrete layout changes use a 200 ms opacity transition; divider widths and PDF geometry are not interpolated. Learning question/status changes briefly emphasize the available action and fade the corresponding answer in; a newly finished record emphasizes its record link. Finished and demonstrated remain separate domain states.

## Stage 4: research state and contextual guidance

Both legacy and version-2 cards observe real state changes. Initial history loading, reopening a task and unchanged polling results do not produce a completion cue. A completed full or partial report emphasizes the appropriate report entry once. Failed and cancelled runs retain their own labels without a success cue. No synthetic percentage, simulated progress, automatic action or provider request was added.

The shared transition observer resets on task/run identity changes and cleans up its timer. Reduced-motion preferences disable animations/transitions and preserve a temporary static emphasis plus the ordinary text status.

## Validation and limits

- First focused run: 88 tests passed across transition observer, chat save/error behavior, navigation, popovers and research cards; TypeScript passed.
- Second run: 95 tests passed across the main application, navigation and version-2 research cards, including historical completion versus live completion and failed/cancelled boundaries.
- Production build passed, with existing dependency and bundle-size warnings.
- Browser-isolated preview used the actual components with synthetic state, not a real research run. Verified pending save, saved destination, completion emphasis, failure without success emphasis, and dark partial-completion wording. Screenshots are stored in the task visualization directory.
- Browser connection timeouts prevented the final integrated narrow-window pass. Real mobile keyboard/selection, reduced-motion visual playback and provider-backed research execution are not claimed as verified by this work.
- No changes to backend research behavior or chat-only reading width.
