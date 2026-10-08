import React, { useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';

export default function PaperPageNavigation({ pageIndex, totalPages, onJump }) {
  const [input, setInput] = useState(String(pageIndex + 1));
  useEffect(() => setInput(String(pageIndex + 1)), [pageIndex]);
  const submit = event => {
    event.preventDefault();
    const requested = Number(input);
    if (Number.isInteger(requested) && requested >= 1 && requested <= totalPages) onJump(requested - 1);
    else setInput(String(pageIndex + 1));
  };
  return <form className="unified-page-navigation" aria-label="论文页码" onSubmit={submit}>
    <button type="button" aria-label="上一页" disabled={!totalPages || pageIndex <= 0} onClick={() => onJump(pageIndex - 1)}><ChevronLeft size={16} /></button>
    <label>第 <input aria-label="跳转到页码" inputMode="numeric" value={input} disabled={!totalPages} onChange={event => setInput(event.target.value)} /> / {totalPages || '—'} 页</label>
    <button type="submit" disabled={!totalPages}>跳转</button>
    <button type="button" aria-label="下一页" disabled={!totalPages || pageIndex >= totalPages - 1} onClick={() => onJump(pageIndex + 1)}><ChevronRight size={16} /></button>
  </form>;
}
