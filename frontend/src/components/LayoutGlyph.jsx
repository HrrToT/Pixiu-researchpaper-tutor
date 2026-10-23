import React from 'react';

/** A shared window silhouette for the layout menu and its trigger. */
export default function LayoutGlyph({ mode, unpin = false }) {
  return <svg className="unified-layout-glyph" width="26" height="20" viewBox="0 0 26 20" fill="none" aria-hidden="true" focusable="false">
    <rect x=".75" y=".75" width="24.5" height="18.5" rx="2.5" stroke="currentColor" strokeWidth="1.5" />
    {mode === 'navigation' ? <>
      <rect x="3" y="3" width="4" height="14" rx=".75" fill={unpin ? 'none' : 'currentColor'} fillOpacity=".85" stroke={unpin ? 'currentColor' : 'none'} strokeDasharray={unpin ? '2 1.5' : undefined} />
      <rect x="9" y="3" width="6" height="14" rx=".75" fill="currentColor" opacity=".18" />
      <rect x="17" y="3" width="6" height="14" rx=".75" fill="currentColor" opacity=".18" />
    </> : <>
      <rect x="3" y="3" width={mode === 'chat' ? 3 : mode === 'reader' ? 15 : 9} height="14" rx=".75" fill="currentColor" opacity={mode === 'chat' ? '.12' : '.55'} />
      <rect x={mode === 'chat' ? 8 : mode === 'reader' ? 20 : 14} y="3" width={mode === 'chat' ? 15 : mode === 'reader' ? 3 : 9} height="14" rx=".75" fill="currentColor" opacity={mode === 'reader' ? '.12' : '.55'} />
    </>}
  </svg>;
}
