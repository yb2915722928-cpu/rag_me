# Embedding 与向量索引

本模块提供同步库接口。领域记录位于 `app.models.embedding`，数据库实现位于 `app.models.db.pgvector`，应用流程通过 `VectorStore` 与 `RequestRepository` 协议调用存储。数字目录模块可用 `importlib.import_module("app.modules.3_embeddingAndIndexing")` 导入。

## 角色与不可变身份

adapter 必须声明 `EmbeddingMetadata.document_role` 和 `query_role`，各自包括 `encoder_id`、`instruction`、`config_version`、`tokenizer_policy`。基础 `embed_role` 对原始文本添加相应指令后调用 `embed`；不同 encoder 端点须覆盖 `embed_role` 或显式实现 `supports_request_metadata` / `embed_request(BatchRequest)`。数据库和流程不会根据维度推断兼容性。`prepare_text` 必须精确返回声明的 instruction 与原文本的拼接；隐藏的大小写、空白或 Unicode 转换会在发送前拒绝。其他文本转换应先创建显式 Chunk 修订，并版本化其处理策略。

`IndexSchemeVersion` 对完整表示契约的规范 JSON 计算 SHA-256。`ChunkRecord` 必须由上游提供 `document_id`、`document_version`、`chunk_id`、`chunk_version`。Chunk 修订不会用文档修订代替。指纹采用 `sha256`、规范化版本 `v1`，包含精确原始文本、实际准备文本、角色配置和切分策略；不自动 trim、转小写或做 Unicode 归一化。同一五元逻辑身份的不同指纹会原子拒绝。同指纹重复写入保持已有向量，允许更新元数据。

`index_chunks` 固定使用 document 角色；`search_chunks` 使用 query 角色。返回检索命中包含精确文档和 Chunk 修订、方案身份、指纹算法/值和生成时间。`EmbeddingBatchResult.items` 包含逐项状态与诊断；成功索引状态为 `stored`。

## 批次、Token 和重试

`max_batch_size` 限制每次请求的文本数，`max_tokens` 限制准备后文本的批次 Token 总量。传入 `token_counter`（返回数量或 token sequence），或由 adapter 提供。计数包含角色 instruction。只设置 Token 配额时也必须提供计数器。

默认长输入策略为拒绝。`LongInputPolicy("truncate" | "rechunk", policy_id, handler)` 要求显式转换函数，并把 `policy_id` 绑定到对应角色声明的 `tokenizer_policy`；不同处理策略应使用不同策略版本。转换后再次计算 Token。`index_chunks` 为转换结果创建新的 Chunk 修订并保存来源、原文本和策略诊断。直接调用 `embed_texts` 时 rechunk 要先经过 `prepare_long_inputs`，由上游为输出分配新修订；截断返回的 `version_suffix` 同样表示新修订，不能覆盖旧身份。

`LocalRateLimiter` 约束滑动时间窗口内的请求数、Token 数以及同时在途请求数。默认配额按 adapter 实例和配置共享，可显式注入一个 limiter 在多个 adapter 间共享。限制在当前进程内生效；多进程部署应由调用方提供跨进程协调。每次实际重试重新经过配额。最大等待时间同时约束配额等待和退避等待，clock、sleeper、jitter 可注入测试。

adapter 使用 `ProviderError` 明确区分 `failed`、`retryable`、`unknown`。普通异常默认永久失败；`TimeoutError` 保守归为 unknown。自动重试默认最多 2 次，并使用有界指数退避、jitter 和 Retry-After。维度、归一化和返回数量等合同错误不能伪装成可重试错误。`retry_failed` 仅重试 retryable；持久化流程必须使用 `index_chunks(..., retry_retryable=True)`，并保留累计尝试次数。

## 请求持久化与恢复

流程在真正发送前，使用 `reserve_batch_attempts` 原子保存完整 `BatchRequest` 与每个逻辑身份。持久化失败会阻止发送。提供方成功结果先保存到请求记录，再写入索引；索引写入失败后重复调用可复用已保存的向量。每个批次完成即保存结果，后续批次失败不会覆盖先前结果。

unknown 和进程崩溃留下的 pending 都阻止自动重发。完整请求负载包含 request ID、幂等键、文本、准备文本、角色、身份列表和指纹，重启后可恢复。支持状态查询的 adapter 显式声明 `supports_status_query=True`，通过 `resolve_index_requests` 和 `resolve_request(BatchRequest)` 返回 `UnknownResolution`。只有完整请求身份及所有向量验证通过后才能入库。

不支持状态查询时，调用方可在确认外部事实后使用 `adjudicate_index_request(identity, repository, state="failed" | "retryable", actor=..., reason=...)`。该函数不会代替调用方猜测是否已执行。确认 retryable 后，再显式调用持久化重试流程。查询失败抛出 `EmbeddingQueryError`，其中 `result` 保存已持久化的请求；可用 `resolve_query_request` 显式确认后继续检索。

## pgvector 与物理配置

需要 PostgreSQL 和 pgvector **>= 0.8.0**，安装 Python 依赖后调用 `PostgresVectorStore(dsn).migrate()`。迁移事务检查扩展版本并创建/增补 schema；旧行缺失修订或指纹时保留为 legacy/unverifiable，不能直接加入新 serving。`search_legacy` 提供按原持久身份的 exact 读取，缺失字段保持未知。回填需由上游提供真实修订并重新编码，迁移不会猜测指纹或伪造来源。

`PhysicalIndexConfig` 独立于表示方案，支持：

| algorithm | 建索引参数 | 查询参数 |
|---|---|---|
| exact | 无 | 无 |
| hnsw | m、ef_construction | ef_search |
| ivfflat | lists | probes |

调用 `register_physical_config(scheme, config)` 从已有已验证向量建立资源，不重新调用模型。每种配置拥有独立物理关系，防止 PostgreSQL 选到另一配置的 ANN 索引；exact 使用物化边界确保精确排序。所有 ANN 索引采用 `vector_cosine_ops`。ANN vector 索引最多 2000 维；IVFFlat 建立前至少需要 lists 条已验证向量。已注册配置参数不可变，重建通过注册新配置完成，旧资源保留到显式清理策略决定处理。

`search` 接受 `limit`、`candidate_limit`、`filters`、互斥的 `score_threshold` / `distance_threshold`、`config`、`query_parameters`。score 为 `1 - cosine_distance`，结果按 score 降序；score 阈值范围 [-1,1]，distance 范围 [0,2]。等分按文档/Chunk 修订身份稳定排序。过滤支持 document_id、document_version 和 constructor `metadata_fields={"field": type}` 声明的元数据等值；不接收 SQL。查询参数使用事务局部设置。候选预算和 ANN 参数是显式控制，过滤或阈值后允许不足 limit 条，不自动扩展或保证 Recall。

## 激活与回滚

`validate_and_activate` 要求完整四元身份清单 `(document_id, document_version, chunk_id, chunk_version)`、数量、代表查询向量、预期第一条命中和阈值，并检查状态、维度、指纹/生成时间以及物理资源健康。通过后在同一事务切换 scheme 和物理配置，并写入 actor、reason、前后配置、动作与校验报告。

`rollback` 对保留旧方案重新执行相同校验，不能直接翻转标志。`delete_scheme` 拒绝删除活动方案；删除非活动方案时清理物理表及其索引，保留逻辑身份的 deleted 墓碑和请求/审计记录以阻止复活。`active_binding()` 用一个查询返回完整 scheme/config。`search_serving_chunks(query, adapter_for_scheme, store)` 捕获这个绑定，再由 factory 提供匹配 adapter，避免分别读取 active scheme 与 config 时跨越切换。`search_chunks` 是指定 adapter/方案的显式检索入口，可用于验证保留方案。

## 验证

执行 `python -m unittest discover -s tests -p "test_*.py"`。数据库 SQL 契约测试使用注入连接运行；设置 `TEST_DATABASE_URL` 后还会执行真实 pgvector 集成测试，包括迁移、exact/ANN、过滤、生命周期和 serving 切换。数据库测试会创建隔离 schema 并在结束后清理；使用专用测试数据库。未设置该环境变量时真实数据库测试明确跳过，契约测试不能替代真实 SQL/执行计划验证。
