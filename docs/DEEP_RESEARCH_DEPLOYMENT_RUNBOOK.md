2026-10-20 E1真实开发验证检查点：在`a023b204`先冻结新的3DGStream阶段2整体取舍问题、材料哈希与审查标准，再按`.197`仅提交一次。它不是旧未知案例改名重试，也不计独立留出；运行`dr_run_fcb70c713976545e940d0b5a0380374e`，约115秒后failed / invalid_experiment_planning_response。8次模型调用均结算，共30,667tokens；规划本身8,992tokens（输入2,848、输出6,144），finishReason=length，部分JSON被保留并拒绝，未发完整配置或修订请求。没有新增未知请求，不推测具体思考Token或费用。

原始私有草稿还假定未获原文支持的coffee_martini成员及新内容，并把要求的NTC替换成相机中心Umeyama刚体对齐；这些是未通过的草稿缺陷，没有发布或升级为方案成果。实际规划请求12,080字节、只有2条正文：阶段2固定旧高斯，以及N3DV聚合测量口径。尽管本轮池中已有25条证据，完整配置固定封装22,562字节使24KB窗口只留下2条；分配器缺口0不能证明方法/数据前提充分。

当前源码与服务仍`7751bd22` / `.197`，完整离线3,181项是此前实现证据，不能据此覆盖本次真实失败。账本由4,732到4,754条（本例22条全部结算），旧账本前缀、所有旧Python负载及三组旧任务消息/笔记/成果保持，0活动、11个旧未知暂停不变。选定诊断累计449次已结算调用/1,826,615tokens，非全历史。

下一步在新不可变契约下使用直接的有界科学规划输出，保留旧低推理请求身份；无损精简重复目标/来源元数据，并在原读取/提取名额内补齐显式共享方法的操作定义，避免以猜测简化替代。不能只扩Token或重发原请求。E1冻结问题和失败记录不改；修复后若做明确的一次性验证，应沿用同一已结算开发题的新attempt，不绕过任何旧未知结果。DR0—DR5和新独立验收仍未完成，Goal active、PR草稿保持。

证据：[冻结开发题](DEEP_RESEARCH_DEVELOPMENT_CASES_20261020.json)、[真实失败与实际输入](deep-research-evidence/E1-v1-diagnostic-20261020.json)、[账本与旧对象保留](deep-research-evidence/runtime-postcases-dr197-e1-v1-20261020.json)。官方接口规则已核对：[Thinking Mode](https://api-docs.deepseek.com/guides/thinking_mode/)、[Chat Completions](https://api-docs.deepseek.com/api/create-chat-completion/)；非思考模式可显式关闭思考，JSON模式也不能把length截断变成完整响应。以下保留历史检查点。

2026-10-20 实验候选取证检查点：代码与Python服务`7751bd22` / `.197`。新实验修订可为无引用的建议/假设补选本轮已取得且实际读过的全文候选，限定唯一来源ID、work/version/contentHash及发表版本元数据；本地来源须匹配冻结材料及文件哈希，外部来源须为获准的固定arXiv版本。冻结问题指定的来源继续约束候选，具体版本优先于宽泛工作ID。候选不是引用或支持判定，原稿不变，最终输出仍须自己的E引用与原有独立核验。

完整离线3,181项通过（166.24秒、1条既有警告），新增39项专项重叠；此前与旧来源/共享修订联合86项通过，之后增加两项并纳入最终全量。22个旧实际请求指纹保持，包括H2F-v9核验与H5F-v6未知生成。新服务加载前后4,732条账本哈希、0活动、11个未知暂停身份完全保持；新增真实模型调用0。

归档H5F-v5的受控新策略输入，三批由1/0/0条原文变为10/2/4条，均实际保留定义公式与来源身份，输入为19,240/18,978/19,063字节，仍在原19,252容量内。相同来源映射按义务组无损合并，重复行元数据从同次注册表引用，起草提示用已有精简策略；原文/配置/具体拒绝原因和独立审查不删改。这里没有新读到数据集成员证据，也没有模型修订响应，不能把候选链路通过升级为科学方案或数据选择通过。

下一步用真正不同的冻结开发实验验证两阶段规划、完整配置和修订内容，不通过改题号/任务重发未知案例。DR0—DR5、实际内容质量与新独立验收仍未完成，Goal active、PR草稿保持。

证据：[回归及边界](deep-research-evidence/experiment-candidate-evidence-regression-20261020.json)、[实际归档输入受控重放](deep-research-evidence/experiment-candidate-evidence-input-20261020.json)、[加载及账本保留](deep-research-evidence/runtime-load-dr197-experiment-candidate-evidence-20261020.json)。以下保留历史检查点。

2026-10-20 共享实验修订检查点：代码与Python服务`d3f454a4` / `.196`。新建实验修订采用按当前可写角色选择的共享语法，替代叠加的配置/工作流/预算/输出模板。完整离线3,142项通过（189.26秒、1条既有警告）；48项专项重叠，新增20项，22个旧实际请求指纹保持，包括H2F-v9核验及H5F-v6未知生成身份。

实际归档H5F-v5重放复现19,261字节超过19,252容量的失败；新三批分别14,719、17,775、16,645字节，均在同一19,252字节内。逐对象比对原文/上下文/表、原稿、具体拒绝原因、兄弟配置和自身来源权限完全相同，未删内容以凑通过；调度器以三个空响应夹具验证发送前检查，无真实模型调用。最高24KB、最多三批、整轮预算及独立科学审查均未放宽。

同时定位另一项尚未修复的问题：原建议/假设若未填引用，旧取证规则只允许事实类扩展候选，导致本归档科学与执行两批仍为0条证据。保留原对象的容量通过不代表能完成来源忠实修订。下一步单独版本化实验建议候选选择，以冻结任务材料/指定来源、全文字面核对及论文版本身份为界，不能自动赋予引文或支持结论。

服务加载保持4,732条账本哈希、0活动、11个未知暂停；本轮新增真实模型调用0。两阶段生成、完整实验质量和新独立验收仍未通过；DR0—DR5未完成，Goal active、PR草稿保持。

证据：[回归与待办](deep-research-evidence/shared-experiment-repair-regression-20261020.json)、[真实输入容量重放](deep-research-evidence/shared-experiment-repair-capacity-20261020.json)、[加载与保留](deep-research-evidence/runtime-load-dr196-shared-experiment-repair-20261020.json)。以下保留历史检查点。

2026-10-20 两阶段实验生成检查点：代码及Python服务`901309dc` / `.195`。新建实验契约3先生成最多4,000 UTF-8字节的私有科学方案（低推理、6,144输出），持久化原始响应后再直接生成完整配置（16,384输出）。两步共用原18调用/100kToken/6分钟预算与全部独立科学/来源检查，不增加整轮额度。规划只是未核验上下文，不是证据；最终声明仍须自己的原文引用。

完整离线3,122项通过（165.96秒、1条既有警告），新增33项专项重叠覆盖来源权限、未知/无效响应、落盘恢复、请求身份及同一账本预算。18个旧综合/新手改写和3个旧核验请求指纹保持。受控输入夹具两步分别12,379和20,252字节，均保留完整公式和成员表原文；科学方案为模拟结果，不冒充新真实读取或模型内容验收。

规划原响应先落盘，再检查结构/自己的E引用/容量；截断或无效响应保留并停止，不回退重发。完整配置请求先固定身份；恢复复用已得规划，已准备的配置即使时间已晚仍回到原账本守卫。新请求发送前分别保留150秒/90秒时间门槛，不能据此保证真实时延。旧契约1/2请求不改；4,732条账本哈希、0活动、11个未知暂停身份在加载前后完全保持。

本轮没有新增真实模型调用，H2F-v9/H5F-v6仍未知、不重发。新两阶段的真实耗时、科学方案质量、完整可执行性及新独立验收尚待证明；全DR0—DR5未完成，Goal active，PR仍为草稿。下一步以真正不同的冻结开发输入验证新链路，并处理共享修订上下文容量，不能换题号重复未知请求或放宽审核。

证据：[回归与边界](deep-research-evidence/staged-experiment-regression-20261020.json)、[两步输入夹具](deep-research-evidence/staged-experiment-generation-input-20261020.json)、[旧综合指纹](deep-research-evidence/staged-experiment-legacy-replay-20261020.json)、[旧核验指纹](deep-research-evidence/staged-experiment-h2f-v9-request-replay-20261020.json)、[加载及账本保留](deep-research-evidence/runtime-load-dr195-staged-experiment-20261020.json)。以下保留历史检查点。

2026-10-20 成员证据链路检查点：当前服务`eb72fa8a` / `.194`。`84a9c755`将数据集表头/成员行纳入同一12段读取、每段3条提取及20条/24KB综合的原有上限；只保存连续原文，列映射仍未验证，成员归属仍需独立审查。完整离线3,084项通过（167.89秒、1条既有警告）。`b449bc09`试验在同一次16,384输出上限内低推理生成，并把私有科学起草记录与公开声明隔离；完整离线3,089项通过（173.73秒、1警告）、44项定向重叠、18个旧综合/新手请求指纹保持。`.194`仅把新建实验默认恢复直接生成，23项定向通过；3,089全量对应`.193`，不能混称为`.194`新跑全量。

H5F-v6仅提交一次：新成员表链路在真实运行中执行，完整公式和成员表实际装入8条/23,762字节请求，分配缺口0，实际请求指纹匹配。但同次完整生成在180秒请求期限内没有取得响应，整轮约221秒即暂停未知，未到6分钟上限；没有取得designBasis、方案或内容验收。7次调用已结算21,247tokens，另一次生成预留41,170tokens未知，不计实测。旧未知身份及原H2F-v9仍保留，不通过换attempt/任务重发。

已检查同哈希原PDF物理第12页：Table4的D-NeRF表头下确有Lego，邻接的Table3是另一张质量比较表。解析器把两表收在Table3章节下，章节元数据不能覆盖原表布局。Table4属于补充的逐场景FPS/点数测量；此前诊断简称“扫描”不能被理解成固定其他变量的受控参数扫描。这项人工原文核对不赋予程序数值列通过，也不升级任何旧案例。

当前4,732条账本、0活动、11个未知暂停；原4,709条账本、全部旧负载及原H5任务实体逐项保持。选定诊断累计441次已结算调用/1,795,948tokens，非全历史，费用未知；H2F-v9与H5F-v6共78,908tokens的未知预留不计实测。当前默认仍需独立核验，不能据恢复直接生成声称实验内容已修好。

后续应把有界科学规划与配置成文拆分：先核对操作/来源/数据/配对与有效观测，再按完整配置语法写作，仍共享18调用/100kToken/6分钟整轮预算，未知请求不重试。检查发现精确剥离生成协议重复早已存在，不重复实现或把9字节阈值做例外；需从共享契约/上下文分配实质解决修订容量。全DR0—DR5、实验内容及新独立验收仍未完成；Goal active，PR保持草稿。

证据：[回归](deep-research-evidence/dataset-members-and-design-basis-regression-20261020.json)、[读取/提取受控重放](deep-research-evidence/dataset-membership-retrieved-input-replay-20261020.json)、[原始版面](deep-research-evidence/deformable-member-table-manual-layout-20261020.json)、[真实未知](deep-research-evidence/H5F-v6-diagnostic-20261020.json)、[实际输入](deep-research-evidence/H5F-v6-synthesis-input-audit-20261020.json)、[旧对象保留](deep-research-evidence/runtime-postcases-dr193-h5f-v6-20261020.json)、[当前加载](deep-research-evidence/runtime-load-dr194-direct-default-restored-20261020.json)。以下保留历史检查点。

2026-10-20 当前源码与Python服务`ba3669a1` / `.191`。本轮分开提交：`22c6c6bf`区分不定图像集合与精确计数；`104c670d`核对同论文/版本/实验的主表测量用途及跨论文证据缺席；`6a7b8105`共享实验配置语法，给原始操作留出输入空间；`ba3669a1`为新短事实回答降低初始核验输出预留并增加发送前时间准入。旧请求与原文不改，未知请求不重发。完整离线3,077项通过（1条既有警告、164.78秒），20个旧实际请求指纹保持。新短事实核验低推理配置及时间准入目前只有离线证据，不能宣称真实耗时或质量通过。

H2F-v9仅提交一次，综合实际输入20条/23,953字节/分配缺口0。初始逐条高推理核验的前两次分别52秒、63秒；第三次在剩余约74秒时发起，到整轮6分钟时结果未知，研究暂停、没有最终报告。11次已结算模型调用/50,043tokens；另一次未知请求的37,738tokens仅是预留，不是实测用量。原回执与新未知身份保留，不换attempt或任务重发。`.191`回放该发送点会拒绝新增发送，并给最终覆盖留时间；缓存复用与未知账本守卫仍保持。

H5F-v5仅提交一次，11次已结算调用/43,435tokens/96秒，inconclusive，内容不通过。共享语法在真实请求中装入12条/23,969字节，完整AST定义公式已实际送达，分配缺口0；生成9个角色但未形成可执行方案。干预和场景缺自身引文、初始化缺必要高斯/网络状态，位姿扰动未具体化；原始光流幅度标准差不能区分真实运动与抖动。修订发送前最低19,261字节超过当时19,252容量，未发送。也记录审查对拟议基线预算、固定预算检查点另要验证集的过度要求，不能据此升级真实缺陷。

当前4,709条账本、0活动、10个未知暂停（原9个加H2F-v9）；旧账本、全部旧负载、原任务实体逐项保持。选定诊断累计434次已结算调用/1,774,701tokens，费用未知，非全历史；未知预留不计入实测消耗。Docker启动故障来自两处陈旧Unix套接字，已在停服后改名保留运行目录，未重置镜像/持久卷；Java已从H2冷备份后的既有包恢复。Python加载前后账本与暂停身份一致。

下一步完善实验联合起草的自身来源绑定、实际场景成员与完整初始化/位姿/渲染配置、有效的时间残差观测；修订投影只移除可精确重建的重复生成协议，并纠正对自由拟议设置的过度审查。不能用加预算、9字节豁免、放宽事实检查或同案例重发掩盖问题。全DR0—DR5仍未完成；原首批0/5、新独立替代案例待做、Goal active、PR草稿；不追加用户已省略的旧导入、完整新手参与及独立Edge恢复。

证据：[完整回归](deep-research-evidence/bounded-factual-review-regression-20261020.json)、[数量/用途实际重放](deep-research-evidence/result-attribution-actual-replay-20261020.json)、[时间/旧核验输入](deep-research-evidence/bounded-factual-review-actual-replay-20261020.json)、[H2未知](deep-research-evidence/H2F-v9-diagnostic-20261020.json)、[H5内容](deep-research-evidence/H5F-v5-diagnostic-20261020.json)、[H5实际输入](deep-research-evidence/H5F-v5-synthesis-input-audit-20261020.json)、[加载保留](deep-research-evidence/runtime-load-dr191-bounded-review-20261020.json)、[最新保留](deep-research-evidence/runtime-postcases-dr191-h5f-v5-20261020.json)。以下保留历史检查点。

2026-10-19 当前代码与服务9b5f68d4 / `.187`，完整离线3,019项通过（1条既有警告、148.72秒）；前一提交46686ac4 / `.186`为3,018项及97项定向通过。事实修订精简重复说明，移除同次注册表中完全相同的身份/权限元数据及上下文已有的章节标签，完整保留原有自身引文/有界上下文及全部拒绝原因。入口按实际批次输出额度预留，仍受原Token、调用、24KB和6分钟上限；短事实时间门槛按版本2/目标数估算，复杂和旧路径保持。

H2F-v8只提交一次，15次已结算调用/59,872tokens/143.518秒，机器partial，人工内容不通过（目标2、证据2、条件2、综合2、可读性3）。本次四个目标实际完成一次修订，未跳过或重发；四目标仍用原90秒门槛，因此两目标60秒边界只有离线证据。初稿全部被程序硬检查拒绝，流程与v7不同，不据本次较短耗时宣称受控性能提升。

最终正文遗漏输入，因为程序把原文a set of images对应的“一组图像”误作实测计数1；时间表示又缺NTC一侧。训练阶段的有据内容已保留，但FPS推断错误地把点数扫描实验称作主表，又只引用Deformable便断言3DGStream证据未说明条件，语义核验放行了这项关键错误。执行成功不等于内容成功。下一步修复不定集合用语与真实计数的边界，以及结果用途/跨论文缺席的来源支持；不追加无变化付费重试。

另做受控H5输入夹具：在同段原三条摘录名额中用已核对的定义公式替换一条，保留池总数。实验综合23,795字节却只装入1条，7组前提未装入，公式未进入；这是假设提取池的容量检查，没有新实际提取/生成或内容信用。先精简实验固定封装并验证完整操作/状态/预算/指标，再付费验证。实际修订请求的终态重构指纹未匹配，单独保留失败审计，不算已重放成功；成功调用/原始响应/预算结算另有真实证据。

当前4,631条账本、0活动、9历史未知，原4,583条账本、全部旧负载/任务对象保持。选定诊断序列412次调用/1,681,223tokens，费用未知、非全历史。原首批0/5、新独立验收待做、全DR0—DR5未完成、Goal active、PR草稿保持；用户省略的旧导入、完整新手参与及独立Edge恢复不追加。

证据：[当前回归](deep-research-evidence/compact-factual-repair-time-regression-20261019.json)、[真实修订输入容量](deep-research-evidence/compact-factual-repair-input-replay-20261019.json)、[时间边界](deep-research-evidence/compact-factual-repair-time-admission-20261019.json)、[真实内容失败](deep-research-evidence/H2F-v8-diagnostic-20261019.json)、[实际综合输入](deep-research-evidence/H2F-v8-synthesis-input-audit-20261019.json)、[修订重构未匹配](deep-research-evidence/H2F-v8-repair-input-audit-20261019.json)、[实验容量夹具](deep-research-evidence/experiment-equation-synthesis-capacity-20261019.json)、[保留](deep-research-evidence/runtime-postcases-dr187-h2f-v8-20261019.json)。以下保留历史检查点。

2026-10-19 当前代码与服务c02c5a63 / `.185`，完整离线3,006项通过（1条既有警告、106.17秒），209项定向与33项端到端重叠。综合前提契约1按冻结完成标准/来源分配必要原文，去除重复封装与共享同来源/版本表格，仍限20条/24KB；数值5区分空间标签与真实次数/倍数，范围3核查完整断言，缺席6拒绝任务证据池缺失与剖析冒充主表，新手8保留相同硬检查。15个旧真实请求指纹保持。一次沙箱全量进程卡在本地asyncio路由，原生单例通过后明确停止；其未完成日志不计通过，最终全量在既有原生环境运行。

H2F-v7仅一次真实提交，14次已结算调用/73,480tokens/292秒，机器partial，人工内容未通过（目标3、证据4、条件3、综合3、可读性4）。实际综合送入20条证据、23,980字节、缺失前提组0；初始化/后续联合训练与逐帧两阶段原文均保留。正文正确发布双方输入和时间表示，七条引用与各自原文核对。更强的“整体离线”reported断言及把未知FPS对齐条件写成已知不同均被整条核验拒绝，没有发布；不能因为拒绝正确或取得材料就算比较完成。

修订在发送前因剩余预算下的输入容量10,263字节小于准备的17,763字节而跳过，未重试或超预算。下一步精简来源感知的事实修订封装，保留逐项要求、完整自身前提、原文权限、拒绝原因及独立复核；不能放宽科学审查或扩大预算来凑通过。实验方案仍需共同状态、正匹配训练预算、忠实干预与有效抖动指标，未追加无变化真实实验。

当前4,583条账本、0活动、9历史未知；原4,529条账本/全部旧负载和任务实体逐项保持。选定诊断序列397次调用/1,621,351tokens，费用未知、非全历史用量。H3F-v8、D1-v27、窄D5-v14和F1既有开发证据保持，独立信用0。原首批0/5、全DR0—DR5未完成、新材料独立验收待做、PR草稿、Goal active；不追加用户省略的旧导入/完整新手参与/独立Edge恢复。

证据：[完整回归](deep-research-evidence/synthesis-premise-regression-20261019.json)、[历史真实输入](deep-research-evidence/synthesis-premise-real-input-replay-20261019.json)、[15个旧请求](deep-research-evidence/synthesis-premise-legacy-replay-20261019.json)、[真实内容核查](deep-research-evidence/H2F-v7-diagnostic-20261019.json)、[实际输入审计](deep-research-evidence/H2F-v7-synthesis-input-audit-20261019.json)、[账本保留](deep-research-evidence/runtime-postcases-dr185-h2f-v7-20261019.json)。以下保留历史检查点。

2026-10-19 当前代码与服务3b69f81e / `.184`，完整离线2,987项通过（1条既有警告、127.19秒），168项定向检查重叠。来源精度6、阅读2、提取优先级7分别照顾冻结完成标准中的输入/时间/训练；保留同次检索、五个结果、12/24读取与每段三条提取上限。中文紧邻FPS等标识可识别，主表请求兼顾定量比较与测量条件。明确标注的完整方法公式占用原三条名额之一，仍为语义未检查。14个历史Provider指纹、两组旧输入提取差分保持。

H2F-v6只提交一次，15次模型调用均已结算，共74,344tokens、246.761秒；机器partial，人工内容不通过（目标2、证据2、条件2、综合1、可读性3）。完整草稿已生成，截断消失；13段检查、34条证据中已含三条Deformable训练实施原文。但实际综合请求只装入11条，三条训练原文全部被最终20条/24KB选择丢掉。程序又把“三维高斯”的维度标签误当测量数值3，拒绝两条原始方法陈述，触发错误修订。最终仍放行“另一篇的信息未出现在证据中”和把渲染剖析当主表的错误。机器partial和事实核验标记不能算内容成功。

下一步修复最终综合的逐项前提分配，保持原20条/24KB上限；区分中文维度标签和实际计数；堵住任务证据池缺失断言及结果用途错误，不能靠来源数或语义passed标签放行。实验方案的共同状态/预算/有效抖动指标仍待完善，未追加真实实验复测。当前4,529条账本、0活动、9历史未知，原4,482条账本、全部旧负载与任务对象保持。选定序列383次调用/1,547,871tokens，费用未知、非全历史用量。原首批0/5、独立验收待做、DR0—DR5未完成、PR草稿、Goal active。

证据：[回归](deep-research-evidence/criterion-operative-regression-20261019.json)、[真实输入重放](deep-research-evidence/criterion-operative-real-input-replay-v2-20261019.json)、[旧输入差分](deep-research-evidence/criterion-legacy-extraction-differential-20261019.json)、[真实内容失败](deep-research-evidence/H2F-v6-diagnostic-20261019.json)、[实际综合输入审计](deep-research-evidence/H2F-v6-synthesis-input-audit-20261019.json)、[账本保留](deep-research-evidence/runtime-postcases-dr184-h2f-v6-20261019.json)。以下保留历史检查点。

2026-10-19 当前代码b942bd06 / `.183`，完整离线2,968项通过（1条既有警告、182.27秒），14个旧请求指纹保持。新增取证调度先处理有限已读池再做付费覆盖评估；普通池按约60%取证、40%修订目标分配，独立综合/核验预留及整轮18次/100k/6分钟上限保持。301—700字多材料比较改低推理强度、仍限8,192输出Token；不超过300字的事实配置及旧请求保持。`.183`尚未加载或真实验证，服务仍为fab469c6 / `.182`。

`.182`固定H2F-v5各请求只发送一次：15段已检查、36条证据，取得NTC、时间场与FPS设置前提；10次模型调用均已结算，共36,967tokens、141秒。综合的高推理请求用满8,192输出Token，返回截断JSON，系统正确失败且未发布。内容未形成，保持未通过/未评分，不能按取证改善宣称比较通过。当前4,482条账本、0活动、9历史未知；原4,443条账本/全部旧负载与任务原对象保持。选定诊断序列368次调用/1,473,527tokens，费用未知、非全历史用量。

下一步先按冻结的逐项完成标准选择方法证据，修复复合计划问题掩盖训练细节的缺口；实验仍需完整AST定义公式、正确训练干预、共同状态/预算及有效抖动测量。完成具体修复再做有界真实验证，不追加已知仍缺关键前提的复测。H3F-v8限定新手开发通过保持；原首批0/5、独立验收待做、DR0—DR5未完成、PR草稿、Goal active。

证据：[取证调度回归](deep-research-evidence/extraction-frontier-regression-20261019.json)、[实际输入重放](deep-research-evidence/extraction-frontier-input-replay-20261019.json)、[真实生成失败](deep-research-evidence/H2F-v5-diagnostic-20261019.json)、[账本保留](deep-research-evidence/runtime-postcases-dr182-h2f-v5-20261019.json)、[比较配置回归](deep-research-evidence/bounded-comparison-regression-20261019.json)、[14个旧请求](deep-research-evidence/bounded-comparison-legacy-replay-20261019.json)。以下保留历史检查点。

2026-10-19 当前Python e2133482 / `.181`，完整离线2,944项通过（1条既有警告、165.95秒），150项定向检查重叠。读取按问题/论文排序，保留原索引归属与前文；方法操作、训练次序、测量口径及具名场景取证优先。复用作者方法的实验操作独立核验；场景候选只辅助字面绑定，不能自动批准成员关系。11个旧真实请求指纹保持。

H2F-v4、H5F-v4各只提交一次，共25次已结算模型调用/123,444tokens，均未通过内容验收。比较最终只回答输入差异；NTC与训练实现段已读却未提取，唯一联合就绪检查只覆盖输入。实验已提取AST方法及Lego成员原文，但遗漏定义公式，仍把作者操作替换为通用平滑权重；共同状态、分组训练预算和抖动指标不一致，被核验拒绝。另记录审查对具名场景数量和描述性分析不确定性的过度要求，不能因此升级失败案例。

下一步调整研究与修订的预算分配，并让关键问题/来源先完成取证，避免概述占满首批后过早进入写作；改善实验生成的操作忠实性与步骤/指标一致性。当前4,443条账本、0活动、9历史未知，原4,383条账本/所有旧负载及两任务原对象逐项保持。选定诊断序列358次调用/1,436,560tokens，费用未知、非全历史用量。H3F-v8限定新手开发通过保持；原首批0/5、独立验收待做、DR0—DR5未完成、PR草稿、Goal active。

证据：[完整回归](deep-research-evidence/operational-evidence-regression-20261019.json)、[旧请求重放](deep-research-evidence/operational-evidence-legacy-replay-20261019.json)、[比较失败](deep-research-evidence/H2F-v4-diagnostic-20261019.json)、[实验失败](deep-research-evidence/H5F-v4-diagnostic-20261019.json)、[比较账本保留](deep-research-evidence/runtime-postcases-dr181-h2f-v4-20261019.json)、[实验账本保留](deep-research-evidence/runtime-postcases-dr181-h5f-v4-20261019.json)。以下保留历史检查点。

2026-10-18 当前Pythonfc9916d7 / `.180`，完整离线2,922项通过（1条既有警告、171.23秒）。新手定性why在改为推断前复用reported程序硬检查，实际运行的核验策略固定在请求身份与日志中；不定数学对象、参数下标和实测计数分开处理。复杂多材料比较可使用原有有界推理配置；实验指标与假设/分析/限制同批修订，完整配置与原24KB预算保持。九个旧真实请求指纹一致。

固定H3F-v8仅一次真实验证，9次已结算模型调用/36,708tokens/153.937秒，1次外部发现、1次固定v1全文获取。通俗改写实际采纳，正文328字；主代理按原冻结标准人工核查通过：解释前帧高斯移动与新增内容补偿，以及数据大小与重建误差的可能取舍；没有编造性能数字或质量保证。所有原文/逻辑与最终覆盖检查通过。这是退役开发材料的限定范围通过，不是独立验收，也不证明通用方向调研全部成熟。

H5F-v3新诊断修正了“缺少Lego证据”的粗略判断：其自身引用已经有Lego与D-NeRF关系，但模型dataAvailability误选另一条仅说明父数据集的引文，字面守卫正确拒绝。AST操作的25—27段也已取得并读取，只是两次提取选了引言/结果段，最终证据池没有操作；配置审查还把“论文所述AST＋通用平滑权重”当成可执行开关，缺少方法忠实性检查。原失败结果和分数保留，不能因这次离线诊断而升级。

下一步补齐操作性证据提取、已引用场景的准确审计绑定、论文方法干预的科学核验及实现级训练依据，再验证完整比较与实验方案；暂不重跑这两例。当前4,383条账本、0活动、9历史未知；原4,360条账本/负载及H3任务原对象保持。选定序列333次调用/1,313,116tokens，费用未知；不是全部历史用量。原首批0/5、DR0—DR5未完成、Goal active、PR草稿保持。证据：[完整回归](deep-research-evidence/grouped-source-science-regression-20261018.json)、[精确重放](deep-research-evidence/grouped-source-science-replay-20261018.json)、[新手内容通过](deep-research-evidence/H3F-v8-diagnostic-20261018.json)、[保留](deep-research-evidence/runtime-postcases-dr180-20261018.json)、[实验缺口诊断](deep-research-evidence/experiment-operation-and-membership-diagnosis-20261018.json)。以下保留历史检查点。

2026-10-18 当前Python04b8c4f1 / `.179`，完整离线2,886项通过（1条既有警告、178.71秒）。方法取证按输入/时间表示/训练意图组织，原始PDF首页版本经哈希核对进入证据链；新手改写记录采纳/拒绝原因。实验生成与修订压缩重复说明，仍保留完整配置、原文和24KB上限；已有证据全装不下时不调用生成。九个旧真实请求指纹回放一致。离线预检与机器终态均不等于内容验收。

三例固定开发复测各一次，共31次已结算模型调用/129,190tokens，均未通过内容验收。H3F-v7机器complete：引用内λ1已正确识别，但“一个平衡参数”仍被误当实测计数，通俗改写整份弃用。H2F-v3机器partial：12条证据全部带正确2403.01444v4/2309.13101v2身份，输入与方法归属改善；仍缺完整训练组织/FPS判断，修订把未知条件写成已知差异，被正确拒绝。H5F-v3机器partial：已拒绝以PSNR波动代抖动，描述性意图正常；仍缺共同初始化、实际AST操作与明确测量，且本次必需修订输入24,724字节超过24,000，未发送该批。

下一组修复：新手解释在分类前保留原实测硬检查，并区分不定数学对象和实际样本计数；为复杂多论文比较检查有界推理配置及取证覆盖；将指标与假设/分析共同修订，保持最多三批、完整原文和原24KB预算。先离线重放具体失败输入，再安排有界真实验证，不继续零散重复发送。

当前4,360条账本、0活动、9历史未知、92任务，旧账本/负载和三个任务实体逐项保持。选定诊断序列324次模型调用/1,276,408tokens，费用未知；不是全部历史用量。D1-v27及窄D5-v14开发通过保持，原首批0/5、DR0—DR5未完成、Goal active、PR草稿保持。证据：[回归](deep-research-evidence/experiment-intent-regression-20261018.json)、[新手解释](deep-research-evidence/H3F-v7-diagnostic-20261018.json)、[多论文比较](deep-research-evidence/H2F-v3-diagnostic-20261018.json)、[实验方案](deep-research-evidence/H5F-v3-diagnostic-20261018.json)、[共同保留](deep-research-evidence/runtime-postcases-dr179-regression-three-20261018.json)。以下保留历史检查点。

2026-10-18 当前Pythonce1fdf7d / `.177`，完整离线2,866项通过（1条既有警告、178.73秒），84项定向重叠。服务端对符合条件的纯定性why保守标为推断，所有陈述仍独立核验；七个旧真实请求指纹一致。

H3F-v6仅一次真实复测，11次已结算调用/43,047tokens/130秒，1次发现、1次固定v1全文获取。模型已给出314字的通俗改写，但程序把自身原文已建立的λ1参数名当作测量数值，整份改写被弃用、classificationChanges为空，最终发布旧术语草稿。原文支持、机器complete，人工新手内容不通过（目标3、可读性2）。下一组修复同时处理：引用中既有符号与测量值的区别、改写是否被采纳的明确记录、方法意图选择/提取和原始PDF版本身份传递；完成整组离线回归后再分题验证，不继续碎片式复测。

当前4,280条账本、0活动、9历史未知、92任务，旧负载与任务实体保持。选定序列293调用/1,147,218tokens，费用未知。两份本地比较论文已按原文件哈希核对首页2403.01444v4/2309.13101v2；此核对本身还不等于应用全链路身份修复。原首批0/5、DR0—DR5未完成、Goal active、PR草稿保持。证据：[回归](deep-research-evidence/server-classification-regression-20261018.json)、[真实失败](deep-research-evidence/H3F-v6-diagnostic-20261018.json)、[保留](deep-research-evidence/runtime-postcases-dr177-20261018.json)、[首页版本](deep-research-evidence/H2F-original-revision-check-20261018.json)。以下保留历史检查点。

2026-10-18 当前Python803c2192 / `.176`，完整离线2,859项通过（1条既有警告、177.68秒）。新手定性why可在固定自身引文下转为推断；原测量/计数/表格绑定不能借此绕过核验，六个旧真实请求指纹一致。

H3F-v5仅一次真实复测，12次已结算调用/50,633tokens/161.625秒，1次发现、1次固定v1全文获取。服务端候选为c2，但模型省略可选kind，实际classificationChanges为空；解释仍为reported。“同时优化才能找到平衡点”的必要性断言被正确拒绝，修订又退化成λ1和目标描述。最终原文支持、机器complete，人工新手内容不通过（目标/可读性3）。下一步由服务端保守分类符合条件的纯定性why，模型只负责解释；仍拒绝无依据保证及必要性，不自动批准推断。

当前4,255条账本、0活动、9历史未知、92任务，旧负载与任务实体保持。选定序列282调用/1,104,171tokens，费用未知。独立材料初筛发现CAT-3DGS/PFGS-360也已有旧回执；3DGV/Goal-Oriented/SpaGS仅通过精确哈希初筛，还不能直接宣称独立资格。原首批0/5、DR0—DR5未完成、Goal active、PR草稿保持。证据：[回归](deep-research-evidence/qualitative-audience-regression-20261018.json)、[真实失败诊断](deep-research-evidence/H3F-v5-diagnostic-20261018.json)、[保留](deep-research-evidence/runtime-postcases-dr176-20261018.json)、[材料初筛](deep-research-evidence/fresh-candidate-hash-screen-20261018.json)。以下保留历史检查点。

2026-10-18 当前Python48ec3b29 / `.175`，完整离线2,843项通过（1条既有警告、167.36秒），定向113项重叠。新手改写从各条原始来源和冻结问题重建，省略未核验草稿措辞；内部范围审计严格引用实际目标字段，来源与目标命名空间分离。五个旧真实请求指纹一致，原文、权限与预算保持。

H3F-v4仅一次真实复测，12次已结算调用/47,143tokens/118秒，1次发现、1次固定v1全文获取。实际改写改善了运动分工说明，目标/来源字段绑定正常；但因原kind固定reported，解释码率与画质取舍的推导被当作作者直接报告，修订后退化成损失函数/λ1描述。最终事实支持、机器complete，人工新手内容仍未通过（目标回应3、可读性3）。下一步允许有自身原文前提的定性解释明确分类为推断，保留独立语义与数值检查，不能把无依据保证改个kind就发布。

H2F实际八次检索指纹已核对：只有FPS子问题包含FPS，不存在把整段FPS问题附给所有检索的污染。真正缺口是方法细节意图/词项选择与提取覆盖，NTC操作及单目输入依据没进入提取池；原PDF版本身份也需贯通。当前4,229条账本、0活动、9历史未知、92任务，旧负载与任务实体保持。选定序列270调用/1,053,538tokens，费用未知。D1-v27、窄D5-v14开发通过保持；前端490项/类型/构建通过，Java27ac4beb未变。原首批0/5、DR0—DR5未完成、Goal active、PR草稿保持。证据：[回归](deep-research-evidence/source-first-audience-regression-20261018.json)、[真实内容](deep-research-evidence/H3F-v4-diagnostic-20261018.json)、[检索诊断](deep-research-evidence/H2F-v2-retrieval-intent-diagnosis-20261018.json)、[账本保留](deep-research-evidence/runtime-postcases-dr175-20261018.json)。以下保留历史检查点。

# Deep Research 单实例备份、恢复与回退

2026-10-18当前Python6e931a51 / `.174`，Java27ac4beb、前端123b0d29；4,203条账本、0活动、9历史未知、92任务，旧对象保持。真实内部源字段绑定与最终事实支持通过，H3F-v3新手表达仍未通过；原独立成绩不改。证据：[最新保留](deep-research-evidence/runtime-postcases-dr174-20261018.json)。

2026-10-18当前Python7186e037 / `.173`，Java27ac4beb、前端123b0d29；4,179条账本、0活动、9历史未知、92任务。`.172`修订异常处理同次加载；D5窄追问人工通过，三例开发回归仍内容失败。旧对象逐项保持，不改原独立成绩。证据：[最新保留](deep-research-evidence/runtime-postcases-dr173-regression-three-20261018.json)。

2026-10-18当前Python6c89dad1 / `.171`，Java27ac4beb、前端123b0d29；4,087条账本、0活动、9历史未知、92任务。D1-v27开发内容人工通过，原对象保持，不计独立信用。`.172`修订异常/栏目修复源码008a288d全量离线通过，尚未单独加载。证据：[最新保留](deep-research-evidence/runtime-postcases-dr171-20261018.json)。

2026-10-18当前Python279edb95 / `.170`，Java27ac4beb、前端123b0d29。加载保持4,033条账本，两例后4,064条、0活动、9历史未知、92任务；旧对象及所有旧账本/负载保持。新表引用守卫生效，但D1-v26/D5-v13内容均未通过。已定位枚举格式与非断言语法误拦，尚未加载后续修复。证据：[最新保留](deep-research-evidence/runtime-postcases-dr170-20261018.json)。

2026-10-18当前Pythoncf111653 / `.168`，Java27ac4beb、前端e6c14f57。加载保持4,027条账本；本版仅一例后4,033条、0活动、9历史未知、92任务。旧负载和任务实体保持。新综合推理深度真实启用，但D5-v12仍内容失败；当前证据缺席语法误拦与正文逻辑错误分别记录。证据：[诊断与保留](deep-research-evidence/runtime-postcases-dr168-20261018.json)。

2026-10-18当前Python469bbaae / `.167`，Java27ac4beb、前端e6c14f57。加载保持4,005条账本；两例后4,027条、0活动、9历史未知、92任务。正式草稿字段实际返回、直接修订有正文；旧对象保持。两例内容仍失败，机器partial/inconclusive不计质量通过。证据：[真实字段与保留](deep-research-evidence/runtime-postcases-dr167-20261018.json)。

2026-10-18当前Python4c68f300 / `.166`，Java27ac4beb、前端e6c14f57。加载保持3,979条账本；两例后4,005条、0活动、9历史未知、92任务，旧负载及目标任务原实体保持。新范围结构契约仅新运行有效，旧请求/结果不改写。真实内容均不通过，私有草稿字段遗漏及stop/空正文已留档；未加载后续未测源码。证据：[当前诊断与保留](deep-research-evidence/runtime-postcases-dr166-20261018.json)。

2026-10-18当前Python17f10918 / `.165`，Java27ac4beb、前端e6c14f57。3,956条账本加载保持；两例后3,979条、0活动、9历史未知、92任务，全部旧负载和任务实体保持。有限推理仅新短事实/比较有效，旧请求身份不变；条件显示不暴露context键。两例真实内容失败，不表示质量发布就绪。证据：[真实失败与保留](deep-research-evidence/runtime-postcases-dr165-20261018.json)。

2026-10-18当前Python e6c14f57 / `.164`，Java27ac4beb，前端e6c14f57。加载前后3,935条账本保持；真实追问后3,956条、0活动、9历史未知、92任务。原91任务内容/旧账本/旧负载与用户编辑成果均保持。追问点数契约只作用于新运行，旧请求指纹与结果不改写；未知不重发。一次前端编辑追问流程通过不代表原内容验收完成。证据：[工作流保留](deep-research-evidence/F1-fresh-continuation-workflow-20261018.json)。

2026-10-18最新Python6f6a7b92 / `.162`，Java27ac4beb、前端c3843700保持。加载前后3,848条账本不变，三例后3,875条、0活动、9个历史未知身份和91任务。联合/原话/事实修订仅新契约生效，旧请求/未知及旧对象不改写。D5实际语义负例被正确拒绝，D1机器complete仍人工不通过；内容质量不能从部署健康推出。详见[实际内容诊断](deep-research-evidence/D1-v21-diagnostic-20261018.json)。

2026-10-18最新加载Python7b7d5e1c / `.158`，Java27ac4beb保持。加载核对3,822条账本不变，D5-v6后3,843条、0活动、9个未知身份不变，父对象保持。比较审计只作用于带新契约的新运行，旧请求/未知不改写；实际新案例在更早硬检查被拒绝，不算内容通过。详见[新案例](deep-research-evidence/D5-v6-diagnostic-20261018.json)。

2026-10-18最新加载：Python ea10273c / `.157`，Java27ac4beb。加载时3,795条账本及9个未知保持；H1F-v11后3,822条、0活动、91任务，全部旧对象保持。新手契约2只在新运行启用；旧待发请求和已结算请求不改写，未知继续暂停。详见[加载](deep-research-evidence/runtime-load-dr157-beginner-conditions-20261018.json)、[真实开发案例](deep-research-evidence/H1F-v11-diagnostic-20261018.json)。

2026-10-18读取修复已加载：Python9bd9e1fa、提示`.155`，Java27ac4beb保持。每次结果查询统一检查实时快照，不逐片段重复检查；GET慢调用移出事件循环。加载/读取复核保持3,795条账本、9个历史未知、0活动；父数据保持，无模型重发。实际耗时见[只读复核](deep-research-evidence/read-responsiveness-live-20261018.json)。

2026-10-18回执恢复检查点：harness `a82f2b25`，应用仍`.153`，未额外重启。验证入口可通过独立封条及实时GET识别精确的创建前幂等失败；原回执不改，其他未确认/未知仍阻止重发。D5-v4完成后3,770条账本、0活动、9个未知身份和91任务保持，父负载及旧对象不变。D5-v4仍partial，不算内容通过；详见[回归与边界](deep-research-evidence/exact-action-reconciliation-regression-20261018.json)。

2026-10-18最新检查点：Python/Java `.153`，源码`27ac4beb`。Java包为`tmp/dr153-java-target/backend-java-0.0.1-SNAPSHOT.jar`，PID161948、官方校验JDK21、本机隐藏进程；H2备份`tmp/dr153-runtime-backup-20261018/academic_db.mv.db`。加载保护曾在旧PID退出窗口中止；后续已从确认停服状态仅启动一次，禁止再次运行旧停服脚本。完整91个任务、3,747条账本及9个未知暂停身份保持。只读动作回执API已实际验证，验证CLI恢复尚未接入，不能据此直接重试未知请求。当前内容尚未验收。证据：[运行时保留](deep-research-evidence/action-receipt-java-runtime-20261018.json)、[实际GET无写入](deep-research-evidence/action-receipt-live-api-20261018.json)。

2026-10-18当前检查点：Python `.151` / `03d6c25e`，完整回归2,389项通过；Java `47f94b28`、前端 `c3843700`未改。加载时无活动研究，3,708条账本前后相等；两例单次诊断后3,747条、0活动、9个历史未知暂停身份保持。新契约由服务器固定，旧任务不补跑新规则。内容仍未验收，PR保持草稿。证据见[加载核对](deep-research-evidence/runtime-load-dr151-human-grounding-20261018.json)及[运行后账本](deep-research-evidence/runtime-postcases-dr151-20261018.json)。

适用：当前 Java/H2 + Python/SQLite + Chroma 单实例部署。2026-10-13 已在本机完成配套恢复演练；不是多实例、生产高可用或在线热备方案。质量发布门槛仍以实施记录和固定案例为准。

## 备份边界

必须一起保存：

| 内容 | 本机开发位置 | 作用 |
| --- | --- | --- |
| Java 数据库 | `backend-java/target/stage0-data/academic_db.mv.db` | 任务、消息、笔记、成果、研究投影、论文原文件和解析结果 |
| Python 业务数据 | `ai-service-python/data` | 原研究、任务操作等已有业务记录 |
| 新版研究库和 checkpoint | Linux 卷 `academic_dr_runtime_20261012` 中 `/research_data/store` | 执行状态、证据、调用账本、检查点、外部全文 |
| Chroma 索引 | `tmp/dr-container-validation/chroma` | 当前论文向量索引 |
| Java 包、Python 镜像和源码版本 | 本次部署实际使用版本 | 与数据契约一致的程序 |
| 配置清单 | 目录、端口、Provider、功能开关 | 恢复实际挂载和路由；密钥通过原有安全配置注入 |

这些是本机实测位置，不是固定生产路径。先检查实际 Java 启动参数、容器挂载和环境中的目录项。不要把旧 `tmp/dr-live-data` 当作当前运行库。不要把密钥写入备份日志或提交仓库。

## 一致备份

1. 从权威研究库检查 `queued/running/stopping`，等待结束或通过正常操作暂停；不要将未知调用重新发出。
2. 保存代表性任务、成果和论文文件的内容指纹。关闭 Java 入口并停止 Python 服务，防止备份期间新写入。
3. 在停服后复制 H2、Python 业务目录和 Chroma 到一个全新备份目录。不要直接复制运行中的 H2 文件或仅复制 SQLite 主文件而丢掉 WAL。
4. 在可访问 Linux 数据卷的工具容器中运行研究备份工具：

   ```sh
   python /app/scripts/deep_research_backup.py backup \
     --database /research_data/store/research.sqlite3 \
     --sources /research_data/store/sources \
     --destination /backup/research --services-stopped
   python /app/scripts/deep_research_backup.py verify /backup/research
   ```

   `--services-stopped` 是操作人的停服确认，不负责停止服务。工具用 SQLite backup API 导出独立数据库，校验完整性及被引用全文。源连接使用只读模式，但 WAL 数据库可能需要创建共享内存文件，数据卷的只读挂载可能导致 `unable to open database file`；停服后使用正常可写挂载，由工具保持业务记录只读。
5. 对备份全部文件计算 SHA-256，最后写入部署清单；保存实际应用包及版本信息。恢复原服务并确认健康及原任务内容不变。

## 恢复到隔离副本

先恢复到新目录/新 Linux 卷，不覆盖原库。Windows 文件夹绑定中的研究 SQLite 曾复现重开 `disk I/O error`，当前已改用 Linux 命名卷；恢复继续使用 Linux 卷。

```sh
python /app/scripts/deep_research_backup.py restore \
  --backup /backup/research --destination /restore/store
```

Java 使用复制的 H2 文件和备份包，设置新端口（本次 `8083`），将 `PYTHON_URL` 指向恢复 Python（本次 `http://127.0.0.1:8003/api`）。Python 必须使用独立的数据、索引和研究挂载，并明确设置：

```text
DEEP_RESEARCH_DB_PATH=/research_data/store/research.sqlite3
DEEP_RESEARCH_SOURCE_DIR=/research_data/store/sources
CHROMA_DB_PATH=/app/chroma_data
CHROMA_DB_DIR=/app/chroma_data
DEEP_RESEARCH_V2_ENABLED=false
DEEP_RESEARCH_EXTERNAL_ENABLED=false
DEEP_RESEARCH_FULLTEXT_ENABLED=false
```

本次恢复检查将模型密钥置空，不执行新研究。嵌入模型使用已有离线缓存。不要漏掉 `CHROMA_DB_PATH`：默认目录位于源码挂载内，会因只读挂载导致索引初始化失败。Docker Desktop 的本次内部网络未发布主机端口，容器内 200 不能代替 Java 到 Python 的链路验证；改用正常开发网络并明确绑定本机端口后才通过。

预热完成后检查：

- Java 能读取既有任务、消息、笔记、成果与研究；从 Java 下载原论文并核对 SHA-256。
- 已存报告仍可读；关闭新版入口时新请求被拒绝，不能交给旧引擎继续执行。
- 对同一既有运行同步发布两次，消息和成果均不增加。
- 比较全部研究主要内容及完整调用账本指纹；验证外部全文缓存哈希和按论文身份限定的索引数量。
- 结束演练后停止隔离服务，保持原服务可用；保留备份和验证记录。

## 本次实测结果及范围

证据摘要：[`deep-research-evidence/deployment-20261013.json`](deep-research-evidence/deployment-20261013.json)。本地原始记录位于 `tmp/dr-deployment-drill-20261013`。

- 配套备份与新目录恢复通过；33 条研究主要内容、971 条完整调用账本前后指纹一致。
- 代表性 D2 任务经 Java API 核对：2 篇论文、8 条消息、16 项成果、15 条研究记录及报告指纹一致。该任务笔记为 0 条，不以此宣称非空笔记编辑路径已覆盖。
- 两篇实际 PDF 字节和哈希一致；被引用外部全文缓存哈希一致。
- 恢复索引中四篇冻结论文分别为 55、82、57、56 个片段。集合含其他旧身份，总数 363，不能把总数当四篇论文数量。
- 新版开关关闭，实际新请求返回 503；重复发布两次均 200 且没有新增消息/成果；账本没有新增调用。

此演练验证本机停服一致备份、恢复读取和关闭入口后的行为。它不替代真实研究内容质量、完整浏览器体验、生产环境发布演练或多实例故障转移。恢复检查使用的源码包含表格提取修复 `14ad3f8`，Java 代码本轮未修改。

## 固定案例执行工具

从仓库根目录运行。默认只预览清单中的冻结问题、材料身份和预算，不发HTTP请求：

```powershell
.venv-refactor/Scripts/python.exe ai-service-python/scripts/verify_deep_research_case.py H1
```

在已授权发送范围内，显式指定`--submit --attempt 1`才允许一次研究提交。同一案例和attempt已有回执时只GET查询，即使再次传入`--submit`也不会重新生成。研究POST前以独占文件写入并fsync意图；未收到确认则保持unconfirmed，后续运行拒绝重发，需要先核对服务端请求账本。不要删除不确定回执或用新attempt绕过核对。

默认回执目录为`tmp/dr-acceptance-receipts`，`CASE-vN.json`记录意图和运行身份，`CASE-vN.result.json`保存最近一次读取。不同输入不能复用同一回执；D5还需`--task-id`及`--parent-run-id`，不能创建无父运行的追问。D6/H6故障用例使用离线集成测试，不走模型提交入口。

工具不会把服务端completed标记当作质量通过，也不会把问题清单中的预期答案发送给模型。留出案例一旦用于调参，仍须按设计稿退出留出集并登记替换。


## 2026-10-18 当前开发实例

当前Java使用`tmp/dr119-java-target/backend-java-0.0.1-SNAPSHOT.jar`（源码47f94b28、PID81764），仍连接`backend-java/target/stage0-data/academic_db`。Python为`academic-dr-runtime`（.119），持久卷`academic_dr_runtime_20261012`不变。加载核对85个任务、3,210条账本、9个未知暂停记录，未发模型请求。停服H2备份在`tmp/dr119-runtime-backup-20261018`；之前的`tmp/dr118-runtime-backup-20261018`保留。

Docker启动曾被旧Unix套接字阻止，已保留运行时目录隔离副本`C:/Users/Lenovo/AppData/Local/Docker/run.quarantine-20261018-dr118`及`C:/Users/Lenovo/AppData/Local/docker-secrets-engine.quarantine-20261018-dr118`，没有删除数据卷或重置Docker。最后一次端点备份由既有WSL脚本完成。该故障不得通过重复重启或恢复无关数据来处理。

旧同项目容器`ai_service_python`原为`restart=always`，会自动抢占8000；现保持停止且`restart=no`。如需要恢复旧部署，先停止新版实例再执行`docker update --restart=always ai_service_python`；不能让两者同时争用端口。新版实例保持原`restart=no`，由明确的开发启动操作管理。其他项目容器未修改。


## 2026-10-18 依赖调度加载

Python已加载64104406（`.120`），Java/前端仍为前节`.119`。确认无活动研究后重启一次`academic-dr-runtime`，3,210条账本与9个未知暂停记录全量相等，RAG/GROBID健康。依赖契约仅作用于新运行，不能将历史unknown换编号重跑。真实案例开始后不得为文档提交再次重启；下一次源码加载仍需先检查活动研究。运行证明见`deep-research-evidence/runtime-load-dr120-dependencies-20261018.json`。


## 2026-10-18 条件身份检查加载

Python当前为92598500（`.123`）。加载前无活动研究，3262条完整账本与9个历史未知暂停记录前后一致；RAG/GROBID健康。Java/前端沿用`.119`。既有case回执与原回答不覆写，任何真实案例期间不为文档提交而重启。加载证明见`deep-research-evidence/runtime-load-dr123-condition-identity-20261018.json`。


## 2026-10-18 逐条事实核验加载

Python当前1bf96858（`.124`）；确认无活动研究及新论文解析已完成后重启一次，3,284条完整账本和9个未知暂停身份相等，RAG/GROBID健康。后续真实运行期间不再重启。证明见`deep-research-evidence/runtime-load-dr124-fact-isolation-20261018.json`。


## 2026-10-18 原生JSON路由修复加载

Python ebcf570c（`.126`），可信消息契约2；旧契约1保留原身份。确认无活动研究后重启一次，3,299条完整账本和9个未知暂停身份一致，RAG/GROBID健康。证据：`deep-research-evidence/runtime-load-dr126-routed-json-20261018.json`。


## 2026-10-18 修订进展与比较目的加载

Python 74673c96（`.128`），原生JSON契约3/修订进展契约1；旧运行规则保留。确认全部六个新验证运行已终态后重启一次，3,440条完整账本及9个历史未知暂停身份一致；没有追加Provider请求。`deep-research-evidence/runtime-load-dr128-purpose-20261018.json`。


## 2026-10-18 方法细节与中性规划加载

Python 2ee36ac2（`.130`），来源精度契约1/原生JSON契约4；旧运行保留原规则。确认无活动研究后重启一次，3,459条完整账本与9个历史未知暂停身份一致；RAG/GROBID健康。`deep-research-evidence/runtime-load-dr130-source-precision-20261018.json`。

## 2026-10-18 原PDF补查、方法前提与回答格式加载

Python先加载1e6daa48（`.133`），确认无活动研究，3,482条完整账本与9个历史未知暂停身份相等。H4F-v2/H1F-v3各执行一次，结束后3,526条账本，仅这两例追加44条已结算调用，历史行哈希保持。

随后加载4bd2a7d3（`.135`）；完整2,193项离线回归通过，加载前后3,526条账本和9个暂停身份一致，RAG/GROBID健康。H1F-v4仅执行一次，结束后3,547条账本、无活动研究，原账本全量哈希及历史暂停身份保持。上述诊断均无新unknown，原有unknown不重新发出；手动保留的旧回答不改写。Java/前端仍沿用前述`.119`源码/包，本次无数据迁移、无卷重置。

证明：`deep-research-evidence/runtime-load-dr133-original-pdf-priority-20261018.json`、`runtime-postcases-dr133-20261018.json`、`runtime-load-dr135-method-premise-format-20261018.json`、`runtime-postcases-dr135-20261018.json`。这些是加载与记录完整性证据，实际内容门槛仍见各案例人工评分；不得为文档提交再次重启服务。

## 2026-10-18 分项取证与实际语义工厂修复加载

8be225d9（`.136`）和e28e7474（`.137`）分别在无活动研究时加载，3,547条完整账本及9个历史未知暂停身份前后相等。`.137`H1F-v5执行一次，追加22条已结算记录，结束后3,569条账本；原行哈希、暂停身份保持，无新unknown。

f55df4ca（`.138`）在2,222项完整回归通过后加载；3,569条账本和9个暂停身份相等，RAG/GROBID健康。新runtimeSemanticContractVersion=1接上实际工厂的单条事实策略；旧生产批次不迁移、不改写未知请求指纹。Java/前端、数据库、持久卷和来源范围不变，未执行`.138`真实模型案例。

证明：`deep-research-evidence/runtime-load-dr136-criterion-coverage-20261018.json`、`runtime-load-dr137-criterion-budget-20261018.json`、`runtime-postcases-dr137-20261018.json`、`runtime-load-dr138-runtime-isolation-20261018.json`。真实质量仍见H1F-v5人工失败评分；旧基础组件检查不能替代实际工厂验证。

## 2026-10-18 数字词、取证顺序与修订指令加载

4a2da0e7（`.140`）通过2,264项全量回归后加载，3,569条旧账本及9个未知暂停身份前后相等。H1F-v6完成后3,591条账本；原行哈希保持。

5da25372（`.142`）通过2,294项全量回归后加载，3,591条账本及9个暂停身份前后相等，RAG/GROBID健康。H1F-v7及D1-v17各执行一次，追加39条已结算记录，总3,630条；原前缀及暂停身份保持，无活动研究。两例都partial，不能当作质量通过。事实隔离在v7实际两个单事实请求中得到确认。

证明：`deep-research-evidence/runtime-load-dr140-quantity-priority-20261018.json`、`runtime-postcases-dr140-20261018.json`、`runtime-load-dr142-revision-instructions-20261018.json`、`runtime-postcases-dr142-20261018.json`。旧契约、回执、未知预留、原文与用户成果均不迁移或改写；Java/前端/持久卷保持。

## 2026-10-18 同时反馈与原文重建修订加载

959011ea（`.144`）通过2,313项全量回归后加载，3,630条旧账本和9个暂停身份前后相等；H1F-v8、D1-v18结束后为3,666条，均未通过完整内容。

77e16747（`.146`）通过2,329项全量回归后加载，3,666条旧账本和9个暂停身份前后相等，RAG/GROBID健康。H1F-v9、D1-v19追加42条已结算记录，总3,708条；旧前缀哈希及暂停身份保持。实际图的修订输入摘要与新模式、冻结要求匹配；两例仍partial/inconclusive，不能作为质量通过。

两次低推理组件探测使用独立本地SQLite和canonical回执，原生产数据库只读，凭据留在运行容器；原生产前缀及新42行均复核不变。探测结果没有提升全局模型路由，也不代表生产路径内容验收。回退或恢复不能用改变后的提示重新生成旧的未决请求。

证明：`deep-research-evidence/runtime-load-dr144-table-condition-feedback-20261018.json`、`runtime-postcases-dr144-20261018.json`、`runtime-load-dr146-source-redraft-20261018.json`、`runtime-postcases-dr146-20261018.json`、`factual-repair-low-component-probes-20261018.json`。Java/前端和持久卷保持。
