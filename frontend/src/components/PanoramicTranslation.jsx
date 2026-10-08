import React, { useEffect, useMemo, useRef, useState } from 'react';
import { getDocument, GlobalWorkerOptions } from 'pdfjs-dist';
import workerUrl from 'pdfjs-dist/build/pdf.worker.min.js?url';
import MarkdownContent from './MarkdownContent';
import { buildPanoramicTranslation, sourcePixelRect } from '../utils/panoramicTranslation.js';
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
  const [empty, setEmpty] = useState(false);
  useEffect(() => {
    const canvas = ref.current;
    if (!canvas || !image) return;
    const rect = sourcePixelRect(bbox, image.width, image.height);
    if (!rect.width || !rect.height) { setEmpty(true); return; }
    const context = canvas.getContext('2d', {willReadFrequently:true});
    canvas.width = rect.width;
    canvas.height = rect.height;
    context.drawImage(image,rect.x,rect.y,rect.width,rect.height,0,0,rect.width,rect.height);
    if (trim) {
      const pixels = context.getImageData(0,0,rect.width,rect.height).data;
      let first = rect.height, last = -1;
      for (let y = 0; y < rect.height; y++) {
        for (let x = 0; x < rect.width; x++) {
          const offset = (y * rect.width + x) * 4;
          if (pixels[offset+3] && Math.min(pixels[offset],pixels[offset+1],pixels[offset+2]) < 254) {
            first = Math.min(first,y); last = y; break;
          }
        }
      }
      if (last < first) { setEmpty(true); return; }
      const top = Math.max(0,first-4), height = Math.min(rect.height,last+5)-top;
      canvas.height = height;
      context.drawImage(image,rect.x,rect.y+top,rect.width,height,0,0,rect.width,height);
    }
    setEmpty(false);
  }, [image, bbox, trim]);
  return <canvas ref={ref} role="img" aria-label={label} className="panoramic-source" hidden={empty} />;
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
  const renderItems = items => items.map(item => item.kind === 'translation'
    ? <Paragraph key={item.id} item={item} image={image} />
    : image ? <SourceRegion key={item.id} image={image} bbox={item.bbox} /> : null);
  return <div className="panoramic-page" aria-label="当前页图文译文">
    {!image && <p className="panoramic-status" role="status">{error || '正在载入原图…'}</p>}
    {plan ? plan.sections.map((section,index) => section.type === 'columns'
      ? <div key={index} className="panoramic-columns"><div>{renderItems(section.left)}</div><div>{renderItems(section.right)}</div></div>
      : <div key={index}>{renderItems(section.items)}</div>)
      : <>{image && <SourceRegion image={image} bbox={{left:0,top:0,width:1,height:1}} />}
        {pageData?.translatedText && <MarkdownContent>{pageData.translatedText}</MarkdownContent>}</>}
  </div>;
}
