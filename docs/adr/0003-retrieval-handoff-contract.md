# ADR-0003: 模块 3 向模块 4 的检索交接契约

- 状态：已接受；检索融合身份与发布快照部分由 [ADR-0004](0004-retrieval-postgres-published-snapshots.md) 及规格 #82 细化取代，以下保留原模块 3 交接约束的历史说明。
- 日期：2026-11-01

## 背景

模块 3（Embedding 与索引）已经提供区分编码角色的同步编码、版本化向量索引和活动服务绑定。模块 4（检索与融合）将消费这些能力，完成向量检索、关键词检索、FAQ 检索、多知识库扇出、融合、去重与截断。

两个模块如果各自在实现过程中向对方"顺带"改动接口，检索链路会出现两个互不兼容的分数语义、两套身份格式和两种"查询未完成"的表达方式，而这种漂移在事后很难从结果中分辨。因此需要在模块 4 动工之前，先把模块 3 交给模块 4 的内容写死。

本决策只固定**已经存在的交接面**，不新增模块 4 的需求，也不预判模块 4 内部的检索策略。

## 决策

1. 模块 4 只通过模块 3 的公开导出消费检索能力：`search_serving_chunks`、`search_chunks`、`resolve_query_request`，以及 `SearchHit`、`ChunkRecord`、`IndexSchemeVersion`、`LogicalIndexIdentity`、`EmbeddingContractError`、`EmbeddingQueryError`、`VectorStore`、`PostgresVectorStore`、`PhysicalIndexConfig`。模块 4 不直接依赖模块 3 的私有模块。
2. 命中分数是余弦相似度，取值范围 `-1..1`，越大越相关；exact 与 ANN 对外语义一致。模块 4 不得把向量距离当作分数，也不得假定分数落在 `0..1`。
3. 每个命中携带自己的 `scheme_identity`（`scheme:v2:<sha256>`，legacy 数据为 `legacy:<sha256>`）。模块 4 用它区分不同向量空间的命中，不得自行重算、改写或跨方案合并身份。
4. 去重键是 `LogicalIndexIdentity(document_id, document_version, chunk_id, scheme_identity, chunk_version).key`，即五个字段的规范 JSON。模块 4 的去重与截断以该键为准，不得只用 `chunk_id` 判断同一内容。
5. 服务查询在编码之前一次性读取活动方案与物理检索配置；调用方不得传入自己的物理配置，模块 3 会以契约错误拒绝这类调用。多知识库扇出时，每个知识库各自读取一次绑定。
6. 查询失败或结果无法确认时，模块 3 抛出 `EmbeddingQueryError` 并在异常上保留 `result`。模块 4 必须区分"没有命中"和"查询未完成"，不得把未知状态当作空结果继续下游处理；未知状态可以通过 `resolve_query_request` 显式核实后继续。
7. 已知缺口：`VectorStore` 协议只声明 `upsert` 与 `search`，`active_binding` 只在服务查询路径上被实际调用。模块 4 应在自己的端口中一并声明 `active_binding`，不为此修改模块 3 的公开契约。

## 取舍

冻结边界优先于接口便利。模块 4 若需要新的检索能力（例如新的过滤维度或新的排序入口），应先扩展模块 3 的契约，并同步更新本决策与契约测试，而不是在模块 4 内部绕过模块 3 直接访问存储实现。

本决策不引入新的公开类型，也不规定模块 4 的融合算法、去重策略和截断预算；这些属于模块 4 自身的规格。

## 后果

模块 3 的检索入口调用形态、命中字段、分数语义、身份格式和错误语义在模块 4 实现期间不得改变。相关断言固化在 `tests/testFile/test_retrieval_handoff_contract.py`；任何变更都必须同时修改该测试与本决策，并说明迁移方式。
