import React from 'react';
import { act, render, screen } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { useTransitionCue } from './useTransitionCue';
function State({ identity = 'task:run', value }) {
  const cue = useTransitionCue(identity, value);
  return <span data-testid="state" data-cue={cue}>{value}</span>;
}
afterEach(() => vi.useRealTimers());
it('does not animate history or the first asynchronous snapshot, only observed changes', () => {
  vi.useFakeTimers();
  const view = render(<React.StrictMode><State /></React.StrictMode>);
  view.rerender(<React.StrictMode><State value="running" /></React.StrictMode>);
  expect(screen.getByTestId('state')).toHaveAttribute('data-cue', 'false');
  view.rerender(<React.StrictMode><State value="completed" /></React.StrictMode>);
  expect(screen.getByTestId('state')).toHaveAttribute('data-cue', 'true');
  act(() => vi.advanceTimersByTime(1800));
  expect(screen.getByTestId('state')).toHaveAttribute('data-cue', 'false');
  view.rerender(<React.StrictMode><State value="completed" /></React.StrictMode>);
  expect(screen.getByTestId('state')).toHaveAttribute('data-cue', 'false');
  view.rerender(<React.StrictMode><State identity="other" value="running" /></React.StrictMode>);
  expect(screen.getByTestId('state')).toHaveAttribute('data-cue', 'false');
});
