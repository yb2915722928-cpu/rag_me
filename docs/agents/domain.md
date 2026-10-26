# Domain Docs

本项目采用 single-context（单一上下文）布局，所有工程技能共享一套领域术语与架构决策。

## 探索代码前的阅读顺序

1. 阅读根目录的 [GLOSSARY.md](/E:/aaa-project/rag-me/GLOSSARY.md)，了解项目已经确定的领域术语。
2. 阅读 [架构决策目录](/E:/aaa-project/rag-me/docs/adr/) 中与当前工作有关的 ADR。
3. 将来若存在 [GLOSSARY-MAP.md](/E:/aaa-project/rag-me/GLOSSARY-MAP.md)，先通过它定位相关上下文的术语表，并阅读对应上下文的 ADR。

上述文档不存在时，静默继续。不要报告缺失，也不要预先建议或创建占位文档；由 domain-modeling 在术语或决策实际确定后按需创建。

## 文档布局

- 领域术语：根目录的 [GLOSSARY.md](/E:/aaa-project/rag-me/GLOSSARY.md)。
- 架构决策：[docs/adr](/E:/aaa-project/rag-me/docs/adr/)，每个决策使用连续编号的独立 Markdown 文件。

## 使用统一术语

事项标题、设计建议、假设、测试名称等输出涉及领域概念时，采用术语表中的正式名称，遵循其中明确规定的命名边界，避免使用被排除的同义词。

若需要的概念尚未收录，先判断是否引入了项目不使用的说法；确认存在真实缺口后，记录为后续 domain-modeling 的输入。

## 显式说明 ADR 冲突

建议与既有 ADR 冲突时，明确指出决策编号、冲突内容以及重新讨论的原因，再推进修改。
