# 外部原文路径验证（2026-10-30）

当前目标仍是完整DR0—DR5；X1G是已知论文的外部路径开发案例，独立验收积分0。问题和准则在执行前冻结于DEEP_RESEARCH_EXTERNAL_MASKING_20261030.json，不改写旧未知请求或重跑它们。

## 实际通过的获取路径

X1G-v1使用空任务、external_only，目标全文外部缓存预检为空。真实external_discover调用成功，返回arxiv:2503.00357v2；external_fulltext调用成功，cacheHit=false、networkRequests=1、cacheStatus=stored。PDF SHA为6cff256c171332b72324f87ae7229c391cdc8ade63850f288d11289bda4699d5，与预先核对的v2原PDF相同；访问级别为fulltext。不能将它称为独立留出通过或完整研究质量通过。

## 未通过的内容及定位

完整案例完成/inconclusive：11次模型调用全部结算，38354 Token、194秒，外部发现1次、全文1次，未超出18/100000/360秒。0条最终接受陈述，未形成通过核验的结论。模型把当前引用未覆盖规则错写成原文没有给出，absence_not_established与语义检查保持拒绝，不能为通过而放宽。

原文第7页的相对训练视角使用频率权重、较高权重使删除更困难，以及训练/测试视角分布相似前提均已在readResults及evidence中；其中规则和前提位于page7 offset2032的两个连续单元。但综合候选排序先取概述/贡献及无关片段，20条候选上限和24KB输入分配未保留这两条，最终输入23942字节、固定部分21142字节，没有有效的完整规则分组。

下一步修复面向人类指定章节的证据优先级与跨已取得分页片段的连续规则分组，保留来源版本、原文区间、预算及独立检查；不是继续增加概述关键词或扩大Token上限。原始回执/响应/账本保存在tmp/dr-acceptance-receipts/X1G-v1.*。公共证据见deep-research-evidence/external-x1g-v1-validation-20261030.json。

本例新增26行账本，当前7915行、0活跃/13历史暂停。全部旧payload及调用前缀保持，未自动重试或新增未知。

## 后续修复状态

X1G-v2已在.363上完成内容复测，2条通过、完整性0缺口；该尝试读取此前真实下载的外部缓存，不新增全文网络下载，X1G-v1失败不升级。章节分配与编码修复、已知缓存案例的人工核对见DEEP_RESEARCH_SECTION_PREMISES_20261030.md。随后大PDF来源加入任务修复已完成实际幂等验证，见DEEP_RESEARCH_SOURCE_EXPORT_20261030.md。当前成果不替代独立留出集或单次新下载到内容验收的全范围证明。
