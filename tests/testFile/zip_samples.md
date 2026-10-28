# ZIP 固定样本

全部为仓库自行构造的教学数据，不含凭据或下载内容；不代表生产容量、模型质量或真实加密解密能力。默认回归读取这些已提交文件，不在运行时构造或下载。

使用 [zip_build_samples.py](/E:/aaa-project/rag-me/tests/testFile/zip_build_samples.py) 重建：在仓库根目录执行 `python tests/testFile/zip_build_samples.py`。脚本使用固定时间、平台标识、UTF-8 正文和标准库存储/DEFLATE；显式标注的正文使用 GB18030/UTF-16。摘要由脚本生成到 [zip_samples.sha256](/E:/aaa-project/rag-me/tests/testFile/zip_samples.sha256)，不要手改生成结果。DEFLATE 字节可能随 zlib 版本变化，更新时一并检查成员预期和摘要。

| 样本 | 成员与独立预期 |
| --- | --- |
| zip_text.zip | 两个成员：中文路径 TXT 含 CRLF，两行正文；大写 MD 后缀保留标题与强调。 |
| zip_lightweight.zip | JSON 节点 `/rules/0/city` 对应北京，XML 保留属性与注释；CSV 用 GB18030、分号、原值 `00500`，最后 TXT 另用 GB18030。 |
| zip_members.zip | 按序 13 条：目录、两份不同目录同名文档、两份同路径重复文档、三份系统元数据、一份合法隐藏文档、内嵌 ZIP、未知格式、错误 JSON、末尾有效 TXT。默认结果 6 成功、3 失败、4 忽略。 |
| zip_rejected.zip | 7 个父跳转/绝对/盘符/UNC 路径、1 个加密标志成员、1 个 CRC 错误、1 个本地文件头损坏、1 个有效尾成员。结果 1 成功、10 失败，原始反斜杠来源不改写。 |
| zip_empty.zip | 空中央目录，不得报告成功。 |
| zip_metadata.zip | 目录、`__MACOSX`、`.DS_Store`，三项忽略，没有可处理资料。 |
| zip_all_failed.zip | 非法 JSON 与未知 EXE，两项失败，没有成功正文。 |
| zip_corrupt.zip | 固定非 ZIP 字节，无中央目录，容器级失败。 |
| zip_budgets.zip | TXT 分别为 5、100000、4 字节，外加元数据。单成员上限 5 时 2 成功/1 失败/1 忽略；总量 8 时仅首项完成，后续两项未处理；总量恰好 100009 时成功。 |
| zip_crc_budget.zip | STORED 归档，首项 5 字节，CRC 错误项 70000 字节，尾项 4 字节。总量 70008 时，失败读取消耗 70000 字节，尾项因剩余 3 字节未处理。 |
| zip_legacy_names.zip | 将等长 ASCII 名称替换为 GB18030 的 `资料.txt` 且不设 UTF-8 标志；正文单独为 UTF-16。显式名称编码后恢复中文；正文编码不与名称编码混用。 |
| zip_document_deadline.zip | 按序为成功 TXT、可完成 PDF、截止 PDF、尾随 TXT/PDF、目录及三类系统元数据。前一结果在 250 秒返回、后一结果在 301 秒返回时，默认 300 秒整包截止得到 2 成功、3 未处理、4 忽略；当前截止 PDF 不暴露部分正文。 |

加密样本仅设置中央目录与本地头的 encryption 标志，不构造密码算法，因为首版在读取前拒绝所有加密成员。CRC 样本翻转 STORED 成员正文的一个字节，保留原 CRC；损坏头样本破坏对应本地头签名。旧名称编码通过等长替换保留偏移。这些变体只验证 ZIP 容器的明确拒绝和预算行为。

截止测试只控制系统单调时钟，仍使用固定 ZIP 与真实子解析器；不等待实际 300 秒。读取以 64 KiB 为块；标准库在 CRC 失败时不会返回失败块，容器按本次请求范围保守计费并保留之前消耗，不声称测得标准库内部的精确峰值内存。

文档截止样本由 [zip_documents_build_samples.py](/E:/aaa-project/rag-me/tests/testFile/zip_documents_build_samples.py) 的 `build_deadline_sample` 构造，复用固定数字 PDF；可单独执行 `python -c "from tests.testFile.zip_documents_build_samples import build_deadline_sample; build_deadline_sample()"`，无需重建 live 输入。SHA-256：`ffc5360ad7738d3cfe707718b8337926b922705f7a9c7b00cdcdaa7c392f36f9`。文档截止测试通过真实本地 HTTP 响应推进系统单调时钟，覆盖整个容器的绝对截止，而不是各文档重新开始的相对期限。
