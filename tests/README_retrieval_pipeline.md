# #94 检索完整流水线：组合场景与运行前提

状态：**源码已静态对齐；所有测试、SQL、分词输出、后端组合和性能均未执行。**
[场景数据](retrieval_pipeline_cases.py)、[确定性公共查询测试](test_retrieval_pipeline.py)、[真实后端测试](test_retrieval_pipeline_postgres.py) 与 [外部端口及断言辅助](retrieval_pipeline_support.py) 已接到最终公共接口。
已静态对齐 #83–#94 的公开配置、FAQ、父展开、去重、MMR及真实后端夹具，并修复最终审阅发现的超时分类、查询恢复入口与融合预算问题。12 个新增测试模块均沿用仓库的 `unittest` 流程；静态核对不构成运行通过。
本阶段没有安装依赖、下载模型、连接数据库、启动服务、部署、联调或 benchmark。

## 已确认的测试边界

沿用 [#82](https://github.com/yb2915722928-cpu/rag_me/issues/82) 与 [#94](https://github.com/yb2915722928-cpu/rag_me/issues/94) 已确认的最高公开链路：

1. 通过公开接入接口写入带完整身份、版本、来源、父子关系的文档和 FAQ。
2. 通过公开接口完成索引准备及知识库快照发布。
3. 通过 `RetrievalService.query` 提交问题、知识库、已确认授权、业务条件和配置。
4. 观察最终候选、逐路贡献、来源/版本/命中问法、路径状态、整体状态与整理状态。

确定性测试仅在外部编码/存储搜索/时钟/调度边界注入；不 mock 内部融合或后处理函数，也不以观察私有函数调用次数证明顺序。真实后端测试由 PostgreSQL 执行存储、过滤、排名、正文读取与发布；测试替身的成功不构成数据库兼容性证据。

固定顺序：**召回 → 身份归并与融合 → 一层父块展开及合并 → 可选正文去重 → MMR → 最终截断**。
截断前必须留有工作候选池；不能在父合并前取最终 K，不能复制证据补位。

## 组合矩阵及独立预期

[FEATURE_CASES](retrieval_pipeline_cases.py) 提供 24 个组合输入，两套公共查询测试各自以 `unittest.TestCase.subTest` 消费全部组合；`BOUNDARY_CASES` 是更广的边界核对清单，不能将其条目数算作已实现测试数。场景数据本身没有测试函数或数据库动作。每个数据库组合创建独立的随机 schema，并在该组合结束时执行 `addCleanup` 登记的清理。真实后端仅在缺显式 DSN 时 skip；已声明的 psycopg 依赖缺失会报错。

| 父块 | 去重 | MMR | 关键公开断言 |
|---|---|---|---|
| 关 | 关 | 关 | 默认保留子块及跨来源相同正文；融合后最终截断 |
| 开 | 关 | 关 | 同父多子取最高子分；保留所有命中子块与贡献；不递归到祖父 |
| 关 | 开 | 关 | 只有规范化正文相等且可信证明兼容才合并；完整来源/身份保留 |
| 关 | 关 | 开 | 文档实际正文和 FAQ 答案进入统一编码；末尾再取最终 K |
| 开 | 开 | 关 | 先父合并，再对父全文做保守去重，从保留池补位 |
| 开 | 关 | 开 | MMR 比较展开后的父全文，不能复用子块向量 |
| 关 | 开 | 开 | 去重之后执行 MMR；合并证据的所有依据仍在 |
| 开 | 开 | 开 | 父展开、去重、MMR 顺序可通过不同最终正文和候选集合辨别 |

每行分别使用 RRF、归一化加权 Min-Max、归一化加权 L2；同时放入文档和 FAQ、多知识库、相同局部 ID 但不同完整身份。加权失败路径不重新分配权重；FAQ 多问法每路按条目一次贡献，不给 FAQ 自动回答或短路权限。

`document_corpus` 的 parent/grandparent 只进入权威正文清单；显式 vector/BM25 manifest 仅选择 child-a、child-b、duplicate、diverse。parent 与 duplicate 只差换行/首尾空白；两个孩子指向同一直接父块，父块再指向祖父，用于发现递归错误。`DOCUMENT_ROUTE_ORDER` 仅用于注入路由的确定性测试，不要求真实 embedding/BM25 产生相同次序。

两个等权 RRF 路径分别命中相同第一/第二名时，独立算例得分为 `0.03278688524590164` / `0.03225806451612903`。同父两子合并后取前者，不能相加。设置最终 K=2、池≥4，保证合并后有额外独立证据可补位；另写候选不足 K 的场景，不能把“必须恰好 K 条”当成通用断言。

针对 MMR 使用独立的手算几何样例：父全文和重复正文的向量相同，另一份证据向量正交；选择融合分使默认 lambda=.7 下重复惩罚能改变第二条。另用 FAQ 问句向量与答案向量方向不同的样例，断言选择依据是答案。真实编码器集成只断言方案、正文指纹和有效结果，不假定语义质量或固定名次。

## 全链必须补齐的边界

| 场景 | 必须观察到的行为 |
|---|---|
| 默认值 | 每路50 / 工作池100 / 最终20；RRF k=60，权重1；10秒总预算 / 5秒单路 / 并发4；所有可选步骤关；MMR lambda=.7 |
| 授权与过滤 | 各路径、FAQ答案和父正文都受同一授权/条件约束；父自身失败时默认保留合规子块；不泄露父文 |
| 过滤类型 | 嵌套AND/OR、标量IN/集合contains、missing/null、带时区半开区间、高选择性过滤；查询前拒绝未知字段/错类型 |
| 当前时间 | 一次固定 now；临界生效条件在排队、不同路径和后处理保持一致 |
| 快照切换 | 查询 pin s1 后发布 s2，本请求的文档/FAQ/父正文/索引仍全属 s1；下一请求读 s2 |
| 准备失败 | 新版本缺必需物理索引/正文成员不能发布；旧已发布资料仍可查询 |
| 历史版本 | 默认无旧版本混入；只有显式 snapshot selection 能读取保留历史 |
| 证据身份 | 跨方案同证据合并并保留scheme依据；跨KB/文档版本/块版本/FAQ版本不可误合并 |
| 父合并 | 直接父完整正文不依赖父向量；最高子分；保留所有命中子块；无父关系是“不适用” |
| 去重证明 | `BodyDedupProof` 的两个引用字符串由可信caller提供；元数据相等不是适用性/版本兼容证明；未知/不兼容保留 |
| 去重精度 | 仅统一换行和去首尾空白；内部空白、标点变化保留；FAQ与普通文档默认不跨类型合并 |
| MMR复用 | 完整scheme及实际body fingerprint均匹配才复用；否则重新编码；全池任一向量不可用则整步降级 |
| 整理失败 | 默认安全降级，严格模式失败明确可见；保留已记录route statuses；安全原因码不含SQL/凭据/父正文 |
| 路径状态 | success / empty / failed / timeout / not_executed 分开；全部成功但零命中为complete空结果；全部失败为incomplete |
| pin失败 | 合法请求运行时pin失败可返回scope=None、路径not_executed、overall incomplete；不得扩大范围重试 |
| 分数边界 | Min-Max单条/全同分记1且标无区分度；L2全零记0；非法数值/未声明度量不能参与；完整身份稳定同分 |
| 总预算 | 排队、pin/数据库、召回、父读取、去重、补编码、MMR共享root；子路预算不能刷新总预算 |
| 取消/迟到 | root cancel传播；单路child超时不误杀健康兄弟；到期运行路timeout、未开始路not_executed；结果返回后不再变化 |
| 有界资源 | 重复超时场景不增加无界worker/连接；故障通过事件/可控时钟协调，测试本身不能无界等待 |

父处理 `expand_parents` 返回 `ParentExpansionResult(candidates, step)`；去重 `process_body_dedup(..., scope, enabled, prover, remaining)` 返回 pool/step；MMR `select_mmr(..., encoder, remaining, limit, config, postprocess_strict)` 返回 pool/step。这些是接收到的接口交接，最终以集成源码为准。统一的 `postprocess_strict` 必须作用于全部显式请求步骤，并且不能因抛出阶段异常丢失路径诊断。

## 真实后端运行前提（留待用户后续统一执行）

| 项目 | 固定要求与尚未验证的边界 |
|---|---|
| PostgreSQL | **17.11**，`server_version_num=170011`；需要一次性测试数据库与隔离schema权限 |
| pgvector | 扩展名 **vector**，版本 **0.8.6**；服务端扩展文件需事先可用 |
| pg_search | **0.26.4**，固定tag commit `727a888fd2801f013d765b1936c6e8eb3a3edf15`；使用PG17对应构建 |
| 分析器 | 内置Jieba随pg_search发行版固定；search_mode=true、trim=true；当前代码Jieba和regex均保留大小写，k1=1.2、b=.75 |
| 型号regex | `[A-Za-z0-9]+([._+-][A-Za-z0-9]+)*`；USB-C、AX-100、v2.1完整词项及大小写、后缀/Unicode边界待真实核验 |
| Python | 使用标准库 unittest 与 requirements.txt 已声明的 psycopg、项目及模块3公开编码/持久化依赖；本次不安装 |
| 编码方案 | 查询与索引scheme一致；MMR单独指定统一scheme；实际正文指纹和document角色绑定 |
| MMR持久化 | `Module3BodyEncoder(adapter, request_repository, ...)` 需要可用RequestRepository；真实集成使用真实持久化receipt |
| 网络编码 | 目前没有远端network adapter；不能声称真实网络超时/取消/服务商联调已覆盖。真实模块3公开API调用不等于真实远端模型调用 |
| 模型资源 | 本次无需模型下载；BM25使用数据库扩展，不假装需要下载BM25模型；未来确需资产时用户指定目录为 `app/models/db/BM35/` |

Windows应用可配受支持Linux数据库环境，但尚未确认具体发行包、CPU/libc、容器digest或Windows原生pg_search。固定tag中的 `docker/Dockerfile.paradedb-17` 仍下载pg_search 0.26.3且没有固定PG minor，不能直接当作精确组合安装证明。

实际源码的Jieba `lowercase=False` 与外部研究笔记的示例 `lowercase=true` 不同；本矩阵按已集成case-preserving契约准备。分析器fingerprint须包含扩展/tag、词典、字段、tokenizer、k1/b；任何变化准备新索引/快照。未确认自定义词典热更新API。

现有测试入口使用不同显式DSN变量：

| 测试代码 | 环境变量 | 行为边界 |
|---|---|---|
| [权威正文与发布](test_retrieval_postgres.py) | `TEST_DATABASE_URL` | PostgreSQL正文/发布/父读取，不要求向量/搜索扩展；创建和清理随机schema |
| [向量过滤链路](integration/test_filtered_vector_retrieval.py) | `RAG_RETRIEVAL_TEST_DSN` | 真实pgvector，确定性外部编码；创建/清理随机schema |
| [文档BM25](test_retrieval_bm25.py) | `RETRIEVAL_BM25_TEST_DSN` | 固定PG/扩展组合；创建/清理随机schema，包含显式物理索引丢失故障 |
| [公共流水线](test_retrieval_pipeline_postgres.py) | `RETRIEVAL_PIPELINE_TEST_DSN` | 显式一次性数据库；检索数据与module3回执分别使用随机schema，均清理；检查PG和扩展精确版本，不启动服务 |

仅设置DSN不代表本阶段授权执行。最终 #94 公共查询集成测试应复用明确的测试DSN约定、隔离随机schema，并在夹具中说明创建/清理范围；不能使用真实业务数据库。缺环境导致skip不能记作兼容性通过。

公开生命周期需要连接、建schema/表/索引、迁移/写入/发布权限；`migrate` 可能执行扩展DDL，预装与权限必须由后续运行者准备。集成故障场景应限制在夹具持有的schema：物理索引缺失、连接异常、数据库语句超时、父读取预算耗尽、编码失败/未决receipt、查询中快照切换。观察点仍为公共查询/发布结果；不能只断言注入工具自己报错。

`Module3BodyEncoder` 测试应覆盖真实模块3的 `embed_texts`、durable request receipts、缓存scheme/body不匹配重编码及未决请求不得自动重提。确定性Embedding可用于无需模型下载的适配协议测试；不可称作线上模型质量测试。没有远端适配器时明确保留网络超时/取消验证缺口。

## 后续维护者实际运行命令（本次未执行）

从仓库根目录使用已配置项目依赖的 Python 环境。下面为 PowerShell 命令；无需启动Web服务或下载模型。数据库必须已由维护者准备为可丢弃测试库，安装上表精确版本扩展于public，账号有CONNECT、CREATE schema、表/索引DDL与DML权限。夹具创建 `pipeline_<uuid>` / `receipts_<uuid>` 两个schema；只在这些schema写数据及注入索引丢失，finally执行DROP SCHEMA CASCADE。进程强杀可能遗留schema，应由维护者确认名称后清理。

确定性公共查询（不需要数据库）：

```powershell
python -m unittest discover -s tests -p 'test_retrieval_pipeline.py' -v
```

真实四路召回、发布、后处理与模块3回执全链：先通过自己的凭据管理方式设置 `RETRIEVAL_PIPELINE_TEST_DSN`，不得指向业务数据库。下面示例使用libpq service配置，需将service名替换成已有测试连接配置；命令文本不保存密码。

```powershell
$env:RETRIEVAL_PIPELINE_TEST_DSN = 'service=rag_retrieval_disposable'
python -m unittest discover -s tests -p 'test_retrieval_pipeline_postgres.py' -v
```

两套一起运行：

```powershell
python -m unittest discover -s tests -p 'test_retrieval_pipeline*.py' -v
```

缺 DSN 导致的 skip 不是通过。依赖缺失、版本检查失败、缺 DDL 权限及扩展/SQL/tokenizer 不兼容均应作为失败保留。以上命令没有在本次工作中执行，不提供运行报告、通过数量或性能数据。

## 未验证与后续收口

- 已编写两套各24组合的公共查询测试源码（确定性外部端口、真实数据库全链）；未运行、未collection，不能计作通过。确定性测试使用独立手算分数及MMR几何预期，真实后端不假定语义名次。
- 故障源码覆盖父/去重/MMR默认降级和严格失败、路由失败不重分权重、空结果与全失败、pin失败、迟到MMR结果、真实父业务过滤、保留历史/多KB、查询中发布、物理FAQ索引丢失和编码器提前超时。最终审阅已修复提前 TimeoutError 被转为 failed 的问题；保留真实公共查询回归断言，尚未运行。
- 已静态对齐config.body_dedup/mmr/mmr_lambda、query(body_dedup_prover=...)与RetrievalService(mmr_encoder=...)。去重证明失败的step在默认/严格模式都为failed；默认保留incoming pool，严格返回空最终结果；父/MMR默认降级为partial。测试按该公开契约区分，不做反射兼容或skip掩盖不匹配。
- 本阶段不运行测试（含发现/收集）、Python import/compile smoke、SQL、迁移、服务、容器、联调、benchmark或模型下载；也不以静态审阅宣称运行通过。
- 所有SQL/tokenizer组合、`pdb.score`与MATERIALIZED CTE、过滤计划和扩展加载均未运行。全量文本命中再授权/过滤/排序/LIMIT是当前正确性基线，代价未经测量。
- 每KB×snapshot独立语料/物理索引；FAQ与文档分别排名。独立统计、精确词项、ANN限制和业务过滤实际执行行为仍需真实后端验证。
- 十万chunk仅为设计参考，不设置本阶段规模门槛；不承诺延迟、召回质量或融合优于单路。
- [统一执行错误分类](../app/modules/4_retrievalAndFusion/execution_errors.py) 将原生 TimeoutError、模块3 `EMBEDDING_TIMEOUT` 及 PostgreSQL statement timeout 标为 timeout，用户主动取消等其他失败仍为 failed。两条向量路在 [RouteResult.query_recovery](../app/modules/4_retrievalAndFusion/fusion_contracts.py) 保留原始持久化查询结果；`QueryRecovery` 只公开 key/status/request_id/error_code，诊断不回显查询或提供方原文。调用方通过 `query_recovery.resolve(adapter, store, request_repository=..., ...)` 显式调用模块3恢复，提供遵循原授权与快照的搜索 store；未决 UNKNOWN 不会被自动重提。原生传输异常若没有模块3持久化结果，恢复字段为 None。
- [公共查询预算](../app/modules/4_retrievalAndFusion/service.py) 在 pin 后将当前剩余预算的 90% 分给整个召回阶段，保留末尾 10% 给融合及后处理。融合在调用线程做纯 CPU 计算，逐项协作检查同一个原始 root 截止，不会因挂起路由占满后台 worker 而无法开始；其余后处理仍接收原始 root。融合到期时丢弃迟到结果，保留逐路状态及失败步骤。RRF/加权的“先成功、另一条路耗尽阶段预算且占满 worker”与 pin 完成后 root 已到期/取消均有公共回归源码，未运行。

官方版本依据：[PostgreSQL 17.11](https://www.postgresql.org/docs/17/release-17-11.html)、[pgvector v0.8.6](https://github.com/pgvector/pgvector/tree/v0.8.6)、[pg_search v0.26.4](https://github.com/paradedb/paradedb/releases/tag/v0.26.4)。版本存在及源码推导不等于运行兼容性证明。
