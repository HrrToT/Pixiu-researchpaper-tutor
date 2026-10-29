# 大PDF来源加入任务修复与验证

来源加入任务的真实首次请求返回500；随后只读确认任务仍为空、版本18、无来源回执，没有部分写入。Python缓存导出返回200；实际CAT-3DGS v2 PDF为17019833字节，Base64为22693112字符。

普通RestTemplate JSON读取路径在17MiB PDF回归用例中触发StreamConstraintsException。修复仅使exportV2Source采用来源专用有界JSON解析器：字符串限额与原64MiB PDF上限对应，整个响应也有字节上限；超限或损坏导出返回502，不盲目重试。普通接口仍按原JSON约束拒绝大字符串，PDF文件头和SHA校验保持。来源加入之前仍检查任务归属、外部权限、来源身份和版本。

5项定向用例及包含它们的完整Java161项测试通过，有重叠不累计。构建使用独立目录和测试内存H2，不写运行数据库。f4c9fc0e已加载；重启前确认无活跃研究，停机后保存H2备份，9任务、7940行账本、全部运行payload和完整索引完全相同。新Java PID35824，Python仍为.363。启动器因继承句柄等待，独立核对后只清理了专用Python启动脚本进程，Java保持健康，没有再次重启。

修复后使用同一原请求ID成功加入1篇论文，任务版本18到19；重复同一请求仍是1篇、1条来源回执，版本保持19。读取任务中的PDF并核对SHA，阅读和问答状态均为ready；复用已有同SHA已索引论文，AI分析状态not_requested，没有重新索引、模型调用或新PDF网络下载。账本及全部旧运行payload、研究成果和研究记录、完整索引均未改变。

该验证证明已就绪同SHA外部来源的加入与重复请求行为，不证明全新论文解析质量、跨版本论文替换或全部前端交互。完整DR0—DR5仍未完成，独立积分0。原始请求和结果在tmp/dr-acceptance-receipts/X1G-v2.add-source-*，公共证据见deep-research-evidence/source-export-364-*.json及external-x1g-v2-add-source-20261030.json。
