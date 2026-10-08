import React, { useEffect, useMemo, useRef, useState } from 'react';
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.js?url';
import MarkdownContent from './MarkdownContent';
import { buildPanoramicTranslation, sourcePixelRect, usesUnpositionedTranslation } from '../utils/panoramicTranslation.js';
import './PanoramicTranslation.css';

GlobalWorkerOptions.workerSrc = workerUrl;

function usePdfPageImage(fileUrl, pageIndex) {
  const [document, setDocument] = useState(null);
  const [image, setImage] = useState(null);
  const [error, setError] = useState('');
  useEffect(() => {
    let active = true;
    setDocument(null);
    setError('');
    const loadingTask = getDocument({ url: fileUrl });
    loadingTask.promise.then(doc => { if (active) setDocument({url:fileUrl, doc}); })
      .catch(() => { if (active) setError('原图暂时无法显示，请切回原文查看。'); });
    return () => { active = false; void loadingTask.destroy().catch(() => {}); };
  }, [fileUrl]);
  useEffect(() => {
    let active = true;
    let renderTask;
    setImage(null);
    if (!document || document.url !== fileUrl) return;
    setError('');
    (async () => {
      const page = await document.doc.getPage(pageIndex + 1);
      if (!active) return;
      const base = page.getViewport({scale:1});
      const viewport = page.getViewport({scale:Math.min(2, 1600 / base.width)});
      const canvas = globalThis.document.createElement('canvas');
      canvas.dataset.pdfScale = String(viewport.scale || 1);
      canvas.width = Math.ceil(viewport.width);
      canvas.height = Math.ceil(viewport.height);
      renderTask = page.render({canvasContext:canvas.getContext('2d'), viewport, background:'#ffffff'});
      await renderTask.promise;
      if (active) setImage({canvas, fileUrl, pageIndex});
    })().catch(error => {
      if (active && error?.name !== 'RenderingCancelledException') setError('原图暂时无法显示，请切回原文查看。');
    });
    return () => { active = false; renderTask?.cancel(); };
  }, [document, fileUrl, pageIndex]);
  return { image: image?.fileUrl === fileUrl && image?.pageIndex === pageIndex ? image.canvas : null, error };
}

function SourceRegion({ image, bbox, label = '论文原图、公式或尚未翻译内容', trim = true }) {
  const ref = useRef(null);
  const dialogRef = useRef(null);
  const zoomRef = useRef(null);
  const [empty, setEmpty] = useState(false);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !image) return;
    const rect = sourcePixelRect(bbox, image.width, image.height);
    if (!rect.width || !rect.height) { setEmpty(true); return; }
    const context = canvas.getContext('2d', {willReadFrequently:true});
    canvas.width = rect.width;
    canvas.height = rect.height;
    canvas.style.width = `${rect.width / (Number(image.dataset.pdfScale) || 2) * 1.5}px`;
    context.drawImage(image,rect.x,rect.y,rect.width,rect.height,0,0,rect.width,rect.height);
    if (trim) {
      const pixels = context.getImageData(0,0,rect.width,rect.height).data;
      let first = rect.height, last = -1, left = rect.width, right = -1;
      for (let y = 0; y < rect.height; y++) {
        for (let x = 0; x < rect.width; x++) {
          const offset = (y * rect.width + x) * 4;
          if (pixels[offset+3] && Math.min(pixels[offset],pixels[offset+1],pixels[offset+2]) < 254) {
            first = Math.min(first,y); last = y;
            left = Math.min(left,x); right = Math.max(right,x);
          }
        }
      }
      if (last < first) { setEmpty(true); return; }
      const top = Math.max(0,first-4), height = Math.min(rect.height,last+5)-top;
      const cropLeft = Math.max(0,left-4), width = Math.min(rect.width,right+5)-cropLeft;
      canvas.width = width;
      canvas.height = height;
      canvas.style.width = `${width / (Number(image.dataset.pdfScale) || 2) * 1.5}px`;
      context.drawImage(image,rect.x+cropLeft,rect.y+top,width,height,0,0,width,height);
    }
    setEmpty(false);
  }, [image, bbox, trim]);
  const openOriginal = () => {
    const original = ref.current, zoom = zoomRef.current;
    if (!original || !zoom) return;
    zoom.width = original.width; zoom.height = original.height;
    zoom.style.width = `${original.width / (Number(image.dataset.pdfScale) || 2) * 2}px`;
    zoom.getContext('2d').drawImage(original,0,0);
    dialogRef.current.showModal();
  };
  return <>
    <button type="button" className="panoramic-source-button" hidden={empty} aria-label={`放大${label}`} onClick={openOriginal}>
      <canvas ref={ref} role="img" aria-label={label} className="panoramic-source" hidden={empty} />
      <span>放大原图</span>
    </button>
    <dialog ref={dialogRef} className="panoramic-image-dialog" aria-label="原图放大查看">
      <header><span>原图</span><button type="button" onClick={()=>dialogRef.current.close()}>关闭</button></header>
      <div tabIndex={0} aria-label="可滚动的原图"><canvas ref={zoomRef} role="img" aria-label={label}/></div>
    </dialog>
  </>;
}

function Paragraph({ item, image }) {
  return <article className="panoramic-paragraph">
    <MarkdownContent>{item.translatedText}</MarkdownContent>
    {image && (item.preserveMath ? <div className="panoramic-math-source">
      <span>原文公式上下文</span><SourceRegion image={image} bbox={item.bbox} label="本段原文与公式" trim={false} />
    </div> : <details><summary>原文</summary><SourceRegion image={image} bbox={item.bbox} label="本段论文原文" trim={false} /></details>)}
  </article>;
}

export default function PanoramicTranslation({fileUrl,pageIndex,pageData}) {
  const {image,error} = usePdfPageImage(fileUrl,pageIndex);
  const plan = useMemo(() => buildPanoramicTranslation(pageData?.pageLayout,
    pageData?.translatedBlocks || [],pageData?.excludedZones || []),[pageData]);
  const unpositioned = usesUnpositionedTranslation(pageData?.pageLayout, pageData?.translatedBlocks || []);
  const renderItems = items => items.map(item => item.kind === 'translation'
    ? <Paragraph key={item.id} item={item} image={image} />
    : image ? <SourceRegion key={item.id} image={image} bbox={item.bbox} /> : null);
  return <div className="panoramic-page" aria-label="当前页图文译文">
    {!image && <p className="panoramic-status" role="status">{error || '正在载入原图…'}</p>}
    {unpositioned ? <>
      {pageData?.translatedText && <article className="panoramic-paragraph"><MarkdownContent>{pageData.translatedText}</MarkdownContent></article>}
      {pageData?.translatedBlocks?.length > 0 && <p className="panoramic-status">译文未按段落定位，可展开原图核对。</p>}
      {image && <details className="panoramic-original-page"><summary>查看整页原图与公式</summary>
        <SourceRegion image={image} bbox={{left:0,top:0,width:1,height:1}} /></details>}
    </> : plan ? plan.sections.map((section,index) => section.type === 'columns'
      ? <div key={index} className="panoramic-columns"><div>{renderItems(section.left)}</div><div>{renderItems(section.right)}</div></div>
      : <div key={index}>{renderItems(section.items)}</div>)
      : null}
  </div>;
}
