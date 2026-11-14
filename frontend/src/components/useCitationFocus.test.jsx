import React, { useRef } from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { useCitationFocus } from './useCitationFocus';

function Reader({ token = 1, ready = true, active = true, documentKey = 'A' }) {
  const root = useRef(null);
  const focus = useCitationFocus(root, token, ready, active, documentKey);
  return <div ref={root}><div className="rpv-core__inner-pages" data-testid="page">{focus && <div data-testid="focus" data-citation-focus-region data-leaving={focus.leaving} />}</div></div>;
}

it('keeps the initial citation through Strict Mode effect replay', () => {
  render(<React.StrictMode><Reader /></React.StrictMode>);
  expect(screen.getByTestId('focus')).toHaveAttribute('data-leaving', 'false');
});

it('retains focus through reading, selection and copy; fades only on outside pointer or Escape', () => {
  vi.useFakeTimers();
  const view = render(<Reader />);
  const region = screen.getByTestId('focus');
  region.getBoundingClientRect = () => ({ left: 10, top: 10, right: 100, bottom: 100, width: 90, height: 90 });
  fireEvent.pointerDown(screen.getByTestId('page'), { clientX: 20, clientY: 20 });
  fireEvent.scroll(document.body);
  fireEvent(document, new Event('selectionchange'));
  fireEvent.copy(document.body);
  vi.advanceTimersByTime(30000);
  expect(region).toHaveAttribute('data-leaving', 'false');
  fireEvent.pointerDown(document.body, { clientX: 120, clientY: 20 });
  expect(region).toHaveAttribute('data-leaving', 'true');
  view.rerender(<Reader token={2} />);
  expect(screen.getByTestId('focus')).toHaveAttribute('data-leaving', 'false');
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.getByTestId('focus')).toHaveAttribute('data-leaving', 'true');
  vi.useRealTimers();
});

it('waits for load and does not revive a consumed request when returning to a hidden reader', () => {
  const view = render(<Reader ready={false} />);
  expect(screen.queryByTestId('focus')).toBeNull();
  view.rerender(<Reader />);
  expect(screen.getByTestId('focus')).toBeInTheDocument();
  view.rerender(<Reader active={false} />);
  view.rerender(<Reader />);
  expect(screen.queryByTestId('focus')).toBeNull();
  view.rerender(<Reader token={2} documentKey="B" />);
  expect(screen.getByTestId('focus')).toBeInTheDocument();
  view.rerender(<Reader token={0} documentKey="B" />);
  expect(screen.queryByTestId('focus')).toBeNull();
});
