# ZIP 集成验证

2026-10-28，以规格 #39 的 API 优先版本为依据。默认回归通过公开文件/字节入口、真实本地解析器、真实客户端和本地 HTTP 协议服务验证；真实质量验收使用相同 ZIP 入口与固定教学样本，不用固定 HTTP 响应冒充模型质量。

## 默认回归

实现前：270 项，263 通过、7 个真实服务测试跳过，27.116 秒。四票集成后：319 项，309 通过、10 个真实服务测试跳过，44.024 秒。命令为 `python -m unittest discover -s tests -q`。评审修复后的最终结果在完成修复后追加。

## 真实 API 结果

八类文档、六类图片任务/状态和三个媒体任务均有通过记录，共 17 个代表场景。以下仅列真实通过的那次输出；初次失败和诊断记录保留在同一测试样本目录，不能据此声称所有首次请求都成功。

| 场景 | 耗时（秒） | 脱敏证据 |
| --- | --- | --- |
| pdf_digital | 16.943 | [zip_document_live_20261028_initial.json](/E:/aaa-project/rag-me/tests/testFile/zip_document_live_20261028_initial.json) |
| docx | 16.491 | [zip_document_live_20261028_initial.json](/E:/aaa-project/rag-me/tests/testFile/zip_document_live_20261028_initial.json) |
| pptx | 10.648 | [zip_document_live_20261028_initial.json](/E:/aaa-project/rag-me/tests/testFile/zip_document_live_20261028_initial.json) |
| xlsx | 14.553 | [zip_document_live_20261028_initial.json](/E:/aaa-project/rag-me/tests/testFile/zip_document_live_20261028_initial.json) |
| html | 15.001 | [zip_document_live_20261028_initial.json](/E:/aaa-project/rag-me/tests/testFile/zip_document_live_20261028_initial.json) |
| mhtml | 11.759 | [zip_document_live_20261028_initial.json](/E:/aaa-project/rag-me/tests/testFile/zip_document_live_20261028_initial.json) |
| pdf_scan | 16.138 | [zip_document_live_20261028_pdf_final.json](/E:/aaa-project/rag-me/tests/testFile/zip_document_live_20261028_pdf_final.json) |
| pdf_mixed | 19.933 | [zip_document_live_20261028_pdf_final.json](/E:/aaa-project/rag-me/tests/testFile/zip_document_live_20261028_pdf_final.json) |
| ocr | 7.331 | [zip_image_live_20261028_initial.json](/E:/aaa-project/rag-me/tests/testFile/zip_image_live_20261028_initial.json) |
| describe | 8.955 | [zip_image_live_20261028_initial.json](/E:/aaa-project/rag-me/tests/testFile/zip_image_live_20261028_initial.json) |
| understand | 6.719 | [zip_image_live_20261028_initial.json](/E:/aaa-project/rag-me/tests/testFile/zip_image_live_20261028_initial.json) |
| uncertain | 12.881 | [zip_image_live_20261028_initial.json](/E:/aaa-project/rag-me/tests/testFile/zip_image_live_20261028_initial.json) |
| crop | 7.125 | [zip_image_live_20261028_initial.json](/E:/aaa-project/rag-me/tests/testFile/zip_image_live_20261028_initial.json) |
| no_text | 8.481 | [zip_image_live_20261028_no_text_verified.json](/E:/aaa-project/rag-me/tests/testFile/zip_image_live_20261028_no_text_verified.json) |
| audio | 7.238 | [zip_media_live_20261028_initial.json](/E:/aaa-project/rag-me/tests/testFile/zip_media_live_20261028_initial.json) |
| video | 18.62 | [zip_media_live_20261028_initial.json](/E:/aaa-project/rag-me/tests/testFile/zip_media_live_20261028_initial.json) |
| both | 17.871 | [zip_media_live_20261028_initial.json](/E:/aaa-project/rag-me/tests/testFile/zip_media_live_20261028_initial.json) |

PDF（数字、扫描、混合）核验关键维护规则、否定词、数字/单位、表格配对和实际原页来源。DOCX、PPTX、XLSX、HTML/MHTML 分别检查固定事实、表格及服务实际提供的归属；不把 Office 服务页序当作原生工作表或对象位置。图片核验金额两分支、否定、60°C/30 天、场景描述、正常空识字、截断图无法确认和裁剪映射。媒体核验语音原话、金额与否定规则、两条画面分支、语音/画面分离及片段级来源，匿名说话人保持未知。

## 失败与网络诊断

图片初次空白图请求发生连接错误，其他五例成功；单独重验空白图通过。文档首轮扫描/混合 PDF 网络失败，其他六例通过；后续失败及轮询间隔比较结果继续保留，没有自动重试或改写失败证据。

进程内阶段探针定位到申请上传地址或轮询时的 TLS 连接重置/EOF，故障阶段不固定。本机 Python 读取到本地代理；诊断时使用进程内直连的扫描 PDF 成功。最终对原验收入口仅设置子进程 `NO_PROXY=mineru.net`，扫描及混合 PDF 都通过；未修改全局代理、业务客户端或仓库配置。部署出现相同现象时应先检查服务器网络/代理，不把连接失败掩盖为正常空结果，也不为了本机代理问题引入自动重试框架。

首次结果：[文档](/E:/aaa-project/rag-me/tests/testFile/zip_document_live_20261028_initial.json)、[图片](/E:/aaa-project/rag-me/tests/testFile/zip_image_live_20261028_initial.json)。后续原入口通过记录：[扫描/混合 PDF](/E:/aaa-project/rag-me/tests/testFile/zip_document_live_20261028_pdf_final.json)、[空白图片](/E:/aaa-project/rag-me/tests/testFile/zip_image_live_20261028_no_text_verified.json)。中间文件名包含 verified 不代表其内容已通过，应以文件内逐项核验结果为准。

## 局限

这是固定教学样本的定向核验，不保证任意文档、图片或音视频质量。生成内容、表格和复杂关系仍需对照原资料；Office 原生单元格、公式缓存、正文块和对象位置并未因远程解析自动恢复。服务器仍需 ZIP/文本结构处理、网络请求与 FFmpeg/FFprobe 媒体准备，API 优先不等于零 CPU/磁盘消耗。预算默认值不是实测容量，协作截止不能强制终止已进入的 API/解析器。此交付止于解析表示，不包括存储、切块、索引或完整问答。
