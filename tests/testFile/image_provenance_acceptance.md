# #31 文档来源与裁剪映射验收

## 样本真值

手工运行 [image_provenance_build_samples.py](/E:/aaa-project/rag-me/tests/testFile/image_provenance_build_samples.py) 构造固定图片，测试本身不生成或下载。图中文字由项目编写，不以模型输出建立真值；系统微软雅黑只用于栅格渲染，不分发字体文件。没有新增下载图片。

完整尺寸、字节数、SHA-256、字体摘要、Pillow 版本与构造方法见 [image_provenance_samples.json](/E:/aaa-project/rag-me/tests/testFile/image_provenance_samples.json)。

| 固定图 | 尺寸 | 来源关系 |
| --- | --- | --- |
| `image_provenance_original.png` | 1200×600 | 原图；上方标题、中心付款条件、下方区域外财务规则 |
| `image_provenance_crop.png` | 1000×260 | 原图像素矩形 `(120,180,1120,440)`；右下不含 |
| `image_provenance_crop_v2.png` | 1000×260 | 仅将裁剪图文字中的金额 1 万改成 2 万，验证同名不同字节版本 |

目视检查原图与裁剪图：框内是“付款条件”“金额超过 1 万元时，须负责人审批。”“未经批准不得付款。”；框外是“文档示例：付款规则”和“区域外文字：其他情况由财务审批。”。文档身份 `payment-policy`、业务版本 `approved-2026-10`、实际 PDF 页序 3、原图标识 `archive/payment-rules/source-image-01` 均为调用方提供的固定测试元数据。

## TDD 与离线验收

用户已确认公开 `convert_file` / `convert_bytes` 为测试 seam。使用真实图像解码和本地 HTTP 服务，不 mock 模块内部，不测试私有辅助函数，不在测试里重写来源判断。

| 红 → 绿切片 | 红灯 | 绿灯 |
| --- | --- | --- |
| 文档来源和有类型位置通过两个入口保留 | 缺少 `DocumentSource`，公开调用报错 | 共同 Source / 入口增加可选文档来源，测试通过 |
| 文档元数据边界 | 7 个非法元数据子用例落到 `missing_config`，未在入口拒绝 | 一次入口校验，返回 `invalid_options` 并保留输入标识 |
| 原图矩形、输入尺寸和摘要分离 | 缺少 `CropMapping`，公开调用报错 | 两个入口返回相同裁剪来源和实际输入尺寸、摘要 |
| 裁剪元数据完整性和范围 | 19 个非法／缺失子用例落到 `missing_config` | 入口拒绝缺整组、缺字段、非法尺寸／坐标、空框和越界，保留已知来源 |

补充回归涵盖独立图片未知来源、PDF 页序与幻灯片序号区别、同字节不同文档、同名不同字节、正常空 OCR、服务与协议错误、读取／解码失败不伪造尺寸、模型不能改写调用方来源。OCR 既有测试的完整 Source 字典仅增加新字段的 `None` 默认值。

合并 integration 前：来源 8 项 + OCR 9 项共 17 项通过；仓库默认测试 217 项，其中 4 项显式 live 测试跳过，其余通过。坏 PDF 样本的已有 `EOF marker not found` 诊断未导致失败。

结束前已合入 integration 的 `30355bc`（包含 #29 图像描述），完整保留任务分派与描述响应校验。增加描述正常／失败结果的文件与字节入口来源回归；来源测试现为 9 项，合并后仓库默认测试 225 项，其中 5 项显式 live 测试跳过，其余通过。来源改动相对 integration 的 `git diff --check` 通过。#30 尚未出现在该 integration tip，其来源沿用共同流程，不为等待理解任务添加替代实现。

## 真实阶跃星辰验收

2026-10-28 显式加载 `E:\aaa-project\rag-me\.env`，分别通过文件与字节入口调用固定裁剪图，各一次，无重试或回退。请求与响应模型均为 `step-5-preview`，提示词版本 `ocr-v1`。裁剪输入 SHA-256：`736abe346736fe62951854cc84dc28708fad0725574b18661cea83020ec80c73`。

两次均正常成功，返回：

```text
付款条件
金额超过 1 万元时，须负责人审批。
未经批准不得付款。
```

条件、金额、审批人及否定均通过核验，未把框外财务规则或标题写进正文；PDF 页序、业务版本、原图矩形及输入尺寸／摘要均通过。两次耗时约 6.53 秒和 6.56 秒，仍带待核验标记。完整结果与逐项检查保存于 [image_provenance_live_evidence.json](/E:/aaa-project/rag-me/tests/testFile/image_provenance_live_evidence.json)，不含密钥。

上述质量结论仅覆盖该固定轴对齐裁剪图；不能外推为任意图片 OCR 正确，也不能用来源字段存在代替文字与实际区域对应的核验。主流程不负责保管或访问原图。
