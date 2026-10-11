import React from 'react';
import SourceList from './SourceCitation';
import { documentSources } from '../utils/documentSources';

export default function CollapsedSources({ value, onJumpToSource }) {
  const sources = documentSources(value);
  if (!sources.length) return null;
  return <details className="reader-chat-citations"><summary>证据片段（{sources.length}）</summary>
    <SourceList sources={sources} onJumpToSource={onJumpToSource} />
  </details>;
}
