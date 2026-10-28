# #40 实施与验证记录

2026-10-28，在独立工作树 `C:/Users/29157/.codex/worktrees/zip-base/rag-me` 的 `feat/40-zip-base` 上实施；起点为集成分支 `feat/39-zip-integration` 的 `a999833`。未修改主工作区。正式依据为 #39 API 优先修订及 #40；未实现后续 API 工单。

已确认的测试接缝为 ZIP 公开文件/字节入口与 CLI 烟测。遵循 TDD 技能及 tests/mocking 规则；读取真实固定 ZIP，运行真实子解析器，只有截止控制系统单调时钟。所有下列命令工作目录均为上述工作树，使用 `E:/aaa-project/rag-me/.venv/Scripts/python.exe`，不读取环境文件或凭据，不运行真实收费 API。

## red → green

每次先增加一个行为切片并执行失败，再增加对应实现、重跑通过；未批量预写全部测试。

| 切片 | red 观察 | green 行为 |
| --- | --- | --- |
| TXT/Markdown 文件与字节入口 | 模块没有 convert_file | 两入口相同结果，保留中文来源与两份独立正文。 |
| JSON/XML/CSV | Unsupported format: json | 真实节点路径、XML 原文、CSV 列/单元格原值及分类选项保留。 |
| 重复成员与局部失败 | 目录条目触发 Unsupported format，整包抛错 | 区分忽略与失败，同路径条目独立，尾成员继续完成。 |
| 危险路径、加密、CRC/读取 | 加密成员导致整个入口抛 RuntimeError | 逐成员拒绝/失败，尾成员仍成功；修正 Windows 名称规范化后保留 orig_filename。 |
| 损坏容器 | BadZipFile 逃出公开入口 | 返回容器级错误，空包/仅忽略/全失败状态正确。 |
| 输入/选项校验 | 没有 ZipLimits，非法参数未隔离 | 入口一次校验，错误返回无成员结果。 |
| 结果 ZIP 预算接入约束 | parser_options 可覆盖 limits | limits 由内部 convert_member 显式传递，调用选项不得覆盖。 |
| 压缩输入与成员数 | 越界仍 success | 分派前失败，无成员解析和展开消耗。 |
| 单成员预算 | 大成员仍 success | 只失败超限成员，其他合格成员继续。 |
| 累计预算 | 预算 8 仍 success | 保留首项，后续未处理，元数据仍忽略。 |
| 协作截止 | 可控时间推进后仍 success | 成员/分块检查，保留完成项和已耗用预算。 |
| JSON 投影 | 没有 to_dict | 显式输出计算状态、原生来源/警告，不回显配置。 |
| CLI | 没有可执行 __main__ | 真实子进程输出 JSON，成功/部分/失败退出码 0/2/1。 |
| 空包/仅忽略说明 | error 为 None | 明确说明没有可处理资料。 |

后续沿用已经形成的公开行为补验：CRC 失败仍消耗预算、GB18030 名称与 UTF-16 正文独立、UTF-8 名称标志优先、恰好用尽预算、CLI 编码与配置不回显。没有 mock 解析器或重写汇总算法。

## 规范与规格自查

此阶段为实施者自查；后续集成分支的两轴独立评审见 [CODE_REVIEW.md](/E:/aaa-project/rag-me/app/modules/1_documentIngestionAndParsing/8_zipContainers/CODE_REVIEW.md)。修正了空包诊断、Windows 原始路径保留、复杂成员处理从主流程分离，以及原生结构化错误的外层 message 投影。无通用插件系统、未扩展其他业务模块；新增样本构造说明与摘要，预算限制不声称覆盖子解析器内部峰值内存。

## 验证命令

重建样本：

```powershell
& 'E:/aaa-project/rag-me/.venv/Scripts/python.exe' tests/testFile/zip_build_samples.py
```

ZIP 行为及真实 CLI 子进程：

```powershell
& 'E:/aaa-project/rag-me/.venv/Scripts/python.exe' -m unittest tests.test_zip_containers tests.test_zip_containers_limits tests.test_zip_containers_cli -q
```

结果：17 项全部通过；CLI 同时验证完整成功、部分成功、损坏/不存在文件及累计预算停止，stdout 为可读取的 UTF-8 JSON。

最终受影响回归（含 ZIP）：

```powershell
& 'E:/aaa-project/rag-me/.venv/Scripts/python.exe' -m unittest tests.test_zip_containers tests.test_zip_containers_limits tests.test_zip_containers_cli tests.test_text_web_txt tests.test_text_web_markdown tests.test_text_web_json tests.test_text_web_html tests.test_text_web_mhtml tests.test_tabular_csv tests.test_presentations_json tests.test_presentations_xml tests.test_presentations_contract -q
git diff --check
```

结果：合并集成分支最新 `05900b6` 后重跑，122 项全部通过，无跳过（3.654 秒）；diff 空白检查通过。未运行完整仓库或真实 API 质量验收，后者由主代理统一进行。

## 接入约定

公共协作契约已写入仓库外 `C:/Users/29157/.codex/tmp/zip39-20261028/base-contract.md`。内部 convert_member 的关键字 `limits` 接收调用方同一个 ZipLimits，未来 document_api 须透传以约束远端结果 ZIP；parser_options 禁止覆盖该字段。后续仅需独立适配文件和简单分派分支，不修改本工单公开入口。
