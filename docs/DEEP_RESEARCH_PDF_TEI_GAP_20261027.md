# 原 PDF 与 GROBID 正文缺口核对

本轮只读核验原 PDF、已保存 TEI、当前 GROBID 直接返回的 TEI；没有重建生产索引或修改历史研究，没有在 D1-v38 后增加模型案例。

## 已证实

- 原 PDF 19 个物理页，SHA-256 为 `803219bf205d0142621b1ac5339f8d918d3f883f814559f6336b8bfdec5ca634`。
- 物理页 2 真实包含 SSIM 下降 0.007 的总结。已检查页 1、2 图像与独立 pypdf 文本，撤回“总结可能被污染”的怀疑。
- 原 PDF 页 2 包含 `in virtual reality`、`mapping 3D locations`、`In this paper, we address` 所在的引言段落；这些锚点均不在旧 TEI 或新鲜直连 GROBID 的 body 中。对 XML 文本节点统一空白后仍如此，不是标签打断检索的假象。
- 两份 TEI 的归一化 body 完全相同，33,050 字符；原始文件哈希可因序列化换行和元数据不同而不同。当前生产来源与旧解析的正文缺口一致。
- 物理页 6 图像及文本明确区分 `3D-GS` 与作者重训的 `3D-GS*`。0.009 和 0.007 是不同基线下的 SSIM 差值，不是可互换数字。

证据为 `deep-research-evidence/pdf-tei-source-gap-20261027.json`。原始直连响应及页图保存在本地：

- `tmp/parser-heading-audit/lightgaussian-fresh-raw-20261027.tei.xml`
- `tmp/parser-heading-audit/lightgaussian-original-p1-20261027.png`
- `tmp/parser-heading-audit/lightgaussian-original-p2-20261027.png`
- `tmp/parser-heading-audit/lightgaussian-original-p6-20261027.png`
- `tmp/parser-heading-audit/lightgaussian-original-p1-p2-20261027.txt`

## 下一步实现要求

优先补齐正文来源：使用独立 PDF 页文本保留完整内容及准确物理页，GROBID 继续提供结构、表格与辅助位置；不要仅依赖其 body 是否非空认定正文提取足够。需要验证缺失段落可检索、引用片段与原 PDF 对应、页码正确、现有表格单元格身份不倒退。具体替换／补全策略须先用本地原文和离线检查验证，尚未在本轮实施。

新索引须有新版本并保留旧研究的来源快照；不得为了清理索引改写原回答、旧引用、未知请求或当前任务数据。实际重建前保存受影响论文的当前完整记录，并核对其他论文不变。之后再恢复真实内容验证。

本检查只证明具体段落缺失及基线身份差异，不证明所有历史失败都由解析引起。诊断幻觉、错误实验关系、条件／结果混装及比较核查格式仍需独立解决。原 DR0—DR5 完成边界不变。
