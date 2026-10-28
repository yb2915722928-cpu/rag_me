# OCR 固定样本与验收

所有输入均固定提交于本目录；默认测试不下载、不随机生成，不用模型输出充当参考真值。

## 原始公开下载

`image_ocr_stepfun_clear.png` 保留[阶跃星辰官方 Cookbook 的原始图片](https://github.com/stepfun-ai/Step-Cookbook/blob/main/examples/step-5-vision-structured/assets/vision/clear.png)字节，2026-10-28 下载。该仓库为 MIT，署名 `Copyright (c) 2026 stepfun-ai`；本地保留完整许可。原始下载 URL、来源、许可、大小与 SHA-256 见[下载记录](/E:/aaa-project/rag-me/tests/testFile/image_ocr_downloads.json)，[完整许可](/E:/aaa-project/rag-me/tests/testFile/image_ocr_stepfun_LICENSE.txt)。图片含字段 A／B／C，已知值分别 12／7／5；参考来自官方示例及人工检查。

## 自建样本

[构造脚本](/E:/aaa-project/rag-me/tests/testFile/build_image_ocr_samples.py)使用 Pillow 12.2.0、Windows 微软雅黑 42 px 绘制白底黑字，不分发字体文件。构造方法、字体摘要、每份固定文件的字节数及 SHA-256 均见[构造记录](/E:/aaa-project/rag-me/tests/testFile/image_ocr_constructed.json)。需要重建时人工执行脚本，测试不会调用它。中文图已人工查看，四行完整、没有裁切。

- `image_ocr_rules.png/.jpg/.webp`：1100×340，三种真实编码。固定真值包含“金额超过 1 万元时，须负责人审批。”“其他情况由财务审批。”“未经批准不得付款。”“温度不得超过 60 °C；每 30 天检查一次。”JPEG quality=95，WebP lossless。
- `image_ocr_blank.png`：320×240 白图，预期正常 `no_text`，依然待核验。
- `image_ocr_override.bin`：PNG 原始字节，测试显式格式覆盖。
- `image_ocr_corrupt.png`：PNG 前 120 字节，测试必须完整解码。
- `image_ocr_multiframe.png/.webp/.gif/.tiff`：两帧，第二帧为蓝色；TIFF 使用 deflate。验证不静默取第一帧；不支持的解码格式可优先报不支持。
- `image_ocr_static.gif`：单帧不支持格式，验证不能把 PNG 声明当作真实格式。

## TDD 与离线协议

仅在已确认的公开 `convert_file` / `convert_bytes` 边界测试。真实本地 HTTP 服务检查路径、认证、严格结构化请求、图片 data URL 的 MIME 与原始字节；未 mock 自有客户端／辅助函数。文件与字节等价、结果和来源直接从公开返回值观察。

| 纵向切片 | 先观察到的红 | 绿后的行为 |
| --- | --- | --- |
| 可追溯正常 OCR | 模块无公开配置／入口 | 同输入两入口结果相等，正文、来源、模型、版本和待核验分离 |
| 正常空 OCR | 缺失模型不确定性记录 | `no_text` 空正文、待核验、独立警告 |
| 参数与文件失败 | 未显式任务等参数抛出或流入处理 | 独立结构化错误，文件读失败不伪造摘要／尺寸 |
| 图片解码 | 损坏抛出；格式不符／多帧流入请求 | 真实解码并明确拒绝，保留原字节摘要 |
| 配置边界 | 无配置进入客户端异常 | 显式配置或进程环境，缺失／非法配置独立诊断 |
| HTTP／网络失败 | 401 异常直接冒出 | 鉴权、限流、服务失败、超时和连接失败独立诊断 |
| 响应协议 | 空响应抛出；不一致状态误成功 | 21 种无效响应情形均失败，不冒充空 OCR |

三种静态格式、格式别名、格式覆盖，以及未披露模型版本的补充测试在已有实现上直接通过，不虚构额外红灯。最终离线套件为 9 个 unittest 方法，包含上述参数化情形。Windows 对关闭端口的连接拒绝需要超过一次 TCP 重试，离线连接失败测试使用 5 秒超时；延迟响应另用 0.03 秒超时验证超时分支。

合并集成文档 tip `ca9ab04` 后，完整默认命令 `python -m unittest discover -s tests -v`：208 tests，OK（skipped=3：既有两项 MinerU live 和本项 StepFun live），无外部 API 调用。原基线 198 tests 在补齐仓库已声明的 python-pptx 后通过；本项同时声明并安装 Pillow 和 python-dotenv。

## 真实 API：2026-10-28

通过显式 `STEP_OCR_LIVE_TEST=1` 和 `STEP_ENV_FILE` 加载用户原环境文件，实际请求模型为 `step-5-preview`，响应披露同名模型；未知内部修订不推测。提示词 `ocr-v1`，每次只发一张实际图片，没有自动重试。原始图片摘要、完整输出、各项检查及耗时保留在两份结构化记录中：

- [首轮记录](/E:/aaa-project/rag-me/tests/testFile/image_ocr_live_initial.json)：PNG、JPEG、官方表格成功；WebP 和空白图在约 0.2–0.3 秒内连接失败。
- [第二轮记录](/E:/aaa-project/rag-me/tests/testFile/image_ocr_live_evidence.json)：JPEG、WebP、空白图成功；PNG 和官方表格在约 0.2–0.3 秒内连接失败。
- [CLI 冒烟记录](/E:/aaa-project/rag-me/tests/testFile/image_ocr_cli_evidence.json)：明确载入原环境文件，结构化返回连接失败并退出 1，仍保留图片 SHA-256、1100×340 和请求模型。

两轮共 10 次请求，6 次成功、4 次连接失败，均未收到鉴权或模型拒绝。五个固定样本均至少有一次成功的真实质量验收，成功请求约 5.3–9.7 秒：三种编码逐项保留金额条件、两类审批人、否定付款限制、60 °C 及 30 天；官方图保留 A=12／B=7／C=5；白图返回 `no_text` 和空正文。每份正常输出仍为待核验。

集成分支进一步通过 CLI 显式载入用户环境文件，对固定 PNG 复验成功，进程退出 0，响应模型为 `step-5-preview`，状态为 `content` 且 `requires_review=true`。结果保存在[集成 CLI 记录](/E:/aaa-project/rag-me/tests/testFile/image_ocr_integration_cli.json)。环境文件原有两段不可解析内容已注释，全部有效配置值保持一致；该本地文件仍被忽略，不进入提交。

质量结论是这些固定样本取得了正确结果；两次 live 测试命令均因瞬时连接失败退出失败，不能宣称整轮 live 测试全绿或服务稳定。离线协议通过不代表识别质量通过；这里分别保存了真实模型输出。中文标点、复杂版面、模糊字及任意业务关系仍需人工核验，没有泛化准确率保证。
