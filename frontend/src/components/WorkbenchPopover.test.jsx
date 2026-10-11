import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import WorkbenchPopover from './WorkbenchPopover';

it('keeps secondary actions closed, supports keyboard escape and restores the trigger', () => {
  render(<WorkbenchPopover label="更多操作"><button type="button">查看历史</button></WorkbenchPopover>);
  expect(screen.queryByRole('button', { name: '查看历史' })).not.toBeInTheDocument();
  const trigger = screen.getByRole('button', { name: '更多操作' });
  fireEvent.click(trigger);
  expect(screen.getByRole('button', { name: '查看历史' })).toHaveFocus();
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(trigger).toHaveFocus();
  expect(trigger).toHaveAttribute('aria-expanded', 'false');
});

it('allows forms inside the popover and closes on an outside pointer', () => {
  render(<WorkbenchPopover label="筛选"><input aria-label="关键词" /></WorkbenchPopover>);
  fireEvent.click(screen.getByRole('button', { name: '筛选' }));
  fireEvent.change(screen.getByRole('textbox', { name: '关键词' }), { target: { value: '论文' } });
  expect(screen.getByRole('textbox', { name: '关键词' })).toHaveValue('论文');
  fireEvent.pointerDown(document.body);
  expect(screen.queryByRole('textbox', { name: '关键词' })).not.toBeInTheDocument();
});
