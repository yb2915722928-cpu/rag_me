# ADR-0002: Embedding 表示契约与索引服务配置

- 状态：已接受
- 日期：2026-10-31

## 背景

Embedding 检索不仅由向量维度决定。query/document 角色、模型输入指令、模型版本、归一化和切分策略都会影响向量是否兼容。与此同时，exact、HNSW 和 IVFFlat 是同一向量集合上的物理检索策略，不应导致重复生成向量。Embedding 请求还可能在超时后处于无法确认的状态；文档修订和实际编码内容也必须能够追溯。

## 决策

1. Embedding adapter 支持显式 `document` 与 `query` 编码角色。角色配置与模型、维度、度量、归一化和输入策略共同构成索引方案身份。旧 `embed(texts)` 实现钩子必须先显式声明兼容角色对；共享 encoder 可以按角色加入不同指令，不同 encoder 端点必须实现角色路由。缺少角色声明的元数据保留为 legacy，不参与新写入或激活。
2. 一个索引方案可以拥有多个物理检索配置：exact、HNSW 或 IVFFlat；同一时刻只有一个 serving 配置。建索引参数与查询参数分离，所有 SQL 标识符和参数名采用白名单。
3. exact 与 ANN 对外使用统一 cosine score 语义。过滤只接受声明过的等值字段；阈值和候选预算由调用方显式传入，不自动承诺过滤后的 Recall。
4. 限流和重试是有界同步策略，支持请求/Token 预算、最大等待时间、指数退避和 jitter。超时或响应丢失进入 `unknown`；只有存在幂等键和状态查询能力时才可自动确认。
5. 索引项绑定 `document_id`、`document_version`、`chunk_id`、`chunk_version`、`content_fingerprint` 和 `scheme_identity`。同一逻辑身份的指纹冲突必须拒绝，不能静默覆盖。
6. active scheme/serving 配置的激活与回滚必须在事务内完成，并记录审计信息。旧数据缺少新身份字段时标记为 legacy/unverifiable，不自动猜测。

## 取舍

本决策保持同步库 API 和 PostgreSQL + pgvector 首个正式后端，不在本阶段引入 HTTP、后台队列、Qdrant/Milvus、自动 ANN 调参或自动模型评测。物理索引配置与表示契约分离，允许在不重新 Embedding 的情况下比较检索结构；unknown 状态牺牲部分自动化以避免重复计费和错误覆盖。

## 后果

需要扩展 adapter、批处理状态、索引项身份和 PostgreSQL schema；需要为物理索引参数、状态转换、指纹冲突、迁移切换和回滚增加契约测试。旧 API 和旧数据只能通过显式兼容声明或迁移回填继续参与新 serving 配置。
