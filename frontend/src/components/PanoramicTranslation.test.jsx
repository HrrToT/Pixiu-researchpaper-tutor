import React from 'react';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
const mocks = vi.hoisted(() => ({getDocument:vi.fn(),draw:vi.fn()}));
vi.mock('pdfjs-dist', () => ({getDocument:mocks.getDocument,GlobalWorkerOptions:{}}));
vi.mock('./MarkdownContent', () => ({default:({children})=><div>{children}</div>}));
import PanoramicTranslation from './PanoramicTranslation';

const data = {translatedBlocks:[{id:'body',translatedText:'完整的中文译文'}],pageLayout:{
  viewport:{width:600,height:800},blocks:[{id:'body',text:'The paragraph describes the method.',
    bbox:{left:0.1,top:0.3,width:0.8,height:0.1}}]}};
const deferred = () => { let resolve; const promise = new Promise(done=>{resolve=done;}); return {promise,resolve}; };
const makePage = (width, completion = Promise.resolve()) => ({getViewport:({scale})=>({width:width*scale,height:800*scale}),
  render:vi.fn(()=>({promise:completion,cancel:vi.fn()}))});

beforeEach(() => {
  mocks.getDocument.mockReset(); mocks.draw.mockReset();
  vi.spyOn(HTMLCanvasElement.prototype,'getContext').mockReturnValue({drawImage:mocks.draw,
    getImageData:()=>({data:new Uint8ClampedArray([0,0,0,255])})});
});

afterEach(() => {
  delete HTMLDialogElement.prototype.showModal;
});

it('keeps the PDF document while changing pages and cancels old page rendering', async () => {
  const slow = deferred(), first = makePage(600,slow.promise), second = makePage(500);
  const getPage = vi.fn(number=>Promise.resolve(number===1?first:second));
  const destroy = vi.fn(async()=>{});
  mocks.getDocument.mockReturnValue({promise:Promise.resolve({getPage}),destroy});
  const view=render(<PanoramicTranslation fileUrl="A.pdf" pageIndex={0} pageData={data}/>);
  await waitFor(()=>expect(first.render).toHaveBeenCalled());
  view.rerender(<PanoramicTranslation fileUrl="A.pdf" pageIndex={1} pageData={data}/>);
  await waitFor(()=>expect(second.render).toHaveBeenCalled());
  await waitFor(()=>expect(mocks.draw).toHaveBeenCalled());
  expect(first.render.mock.results[0].value.cancel).toHaveBeenCalledOnce();
  expect(mocks.getDocument).toHaveBeenCalledOnce();
  expect(mocks.draw.mock.calls.every(call=>call[0].width===1000)).toBe(true);
  mocks.draw.mockClear();
  await act(async()=>{slow.resolve(); await slow.promise;});
  expect(mocks.draw).not.toHaveBeenCalled();
  view.unmount(); expect(destroy).toHaveBeenCalledOnce();
});

it('does not draw a late result from another paper', async () => {
  const old = deferred(), first=makePage(600,old.promise), second=makePage(450);
  const destroyA=vi.fn(async()=>{});
  mocks.getDocument.mockImplementation(({url})=>({promise:Promise.resolve({getPage:async()=>url==='A.pdf'?first:second}),
    destroy:url==='A.pdf'?destroyA:vi.fn(async()=>{})}));
  const view=render(<PanoramicTranslation fileUrl="A.pdf" pageIndex={0} pageData={data}/>);
  await waitFor(()=>expect(first.render).toHaveBeenCalled());
  view.rerender(<PanoramicTranslation fileUrl="B.pdf" pageIndex={0} pageData={data}/>);
  await waitFor(()=>expect(mocks.draw).toHaveBeenCalled());
  expect(mocks.draw.mock.calls.every(call=>call[0].width===900)).toBe(true);
  mocks.draw.mockClear();
  await act(async()=>{old.resolve(); await old.promise;});
  expect(mocks.draw).not.toHaveBeenCalled();
  expect(destroyA).toHaveBeenCalledOnce();
});

it('keeps the completed translation readable when source PDF rendering fails', async () => {
  mocks.getDocument.mockReturnValue({promise:Promise.reject(new Error('unavailable')),destroy:vi.fn(async()=>{})});
  render(<PanoramicTranslation fileUrl="missing.pdf" pageIndex={0} pageData={data}/>);
  expect(await screen.findByText('原图暂时无法显示，请切回原文查看。')).toBeInTheDocument();
  expect(screen.getByText('完整的中文译文')).toBeInTheDocument();
});

it('opens a local enlargement of the original image without loading another document', async () => {
  const show = vi.fn(function(){this.open=true;});
  Object.defineProperty(HTMLDialogElement.prototype,'showModal',{configurable:true,value:show});
  mocks.getDocument.mockReturnValue({promise:Promise.resolve({getPage:async()=>makePage(600)}),destroy:vi.fn(async()=>{})});
  render(<PanoramicTranslation fileUrl="A.pdf" pageIndex={0} pageData={data}/>);
  await waitFor(()=>expect(mocks.draw).toHaveBeenCalled());
  fireEvent.click(screen.getAllByRole('button',{name:'放大论文原图、公式或尚未翻译内容'})[0]);
  expect(show).toHaveBeenCalledOnce();
  expect(screen.getByRole('dialog',{name:'原图放大查看'})).toBeVisible();
  expect(mocks.getDocument).toHaveBeenCalledOnce();
});
