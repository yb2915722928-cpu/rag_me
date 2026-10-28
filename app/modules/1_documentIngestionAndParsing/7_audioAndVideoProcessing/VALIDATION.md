# 音视频处理验证记录

2026-10-28，Windows、Python 项目虚拟环境、FFmpeg/FFprobe 8.1.2。模型计算使用本地环境配置的阶跃 API；ASR 为 stepaudio-2.5-asr，视频为 step-5-preview。本记录不包含凭据。

## 默认行为测试

[基础公开入口测试](/E:/aaa-project/rag-me/tests/test_audio_video.py)的 18 项测试，以及[音频补充测试](/E:/aaa-project/rag-me/tests/test_audio_contract_extra.py) 7 项、[视频补充测试](/E:/aaa-project/rag-me/tests/test_video_contract_extra.py) 5 项均通过。使用真实媒体准备和真实 HTTP 客户端，本地服务返回固定内容。覆盖五种音频格式、三种视频容器、文件／字节契约、模式选择、片段来源、空转写、未知说话人、无法确认及明确失败。

视频时间测试使用独立构造的 6 秒红／绿／蓝素材，关键帧间隔 3 秒，包含 B 帧。目标切片为 2 秒时，实际两片为 [0,3)、[3,6) 秒，并通过解码首帧确认首片红色、第二片绿色。容器起点加 5 秒后，定位仍为从播放起点计算的 [0,3)、[3,6)。

最初使用 FFmpeg 默认的负时间戳平移时，清单出现 3.2 秒，实际画面边界为 3 秒；关闭该平移后通过同一测试。音轨准备也限制在真实媒体时长内，避免 AAC 尾部填充产生超出原片的无效末段。采样时间比较允许一个 16 kHz 样本的舍入误差。

## 真实 API

| 用例 | 证据 | 观察 |
| --- | --- | --- |
| 合成中文语音转写 | [音频运行](/E:/aaa-project/rag-me/tests/testFile/media_live_audio_check.json) | 真实调用通过；金额、问句、“不是，其他由财务审批”与“未经批准不得付款”全部保留。约 7.3 秒，定位为整段约 15 秒。 |
| 缺失审批节点的视频 | [不确定关系运行](/E:/aaa-project/rag-me/tests/testFile/media_live_video_check.json) | 真实调用通过；结果为 uncertain，保留可见金额条件，明确无法确认分支审批人并给出缺失终点的原因。约 8.9 秒。 |
| 同时转写与理解清晰审批视频 | [联合运行](/E:/aaa-project/rag-me/tests/testFile/media_live_combined_check.json)、[已保存响应复核](/E:/aaa-project/rag-me/tests/testFile/media_live_combined_revalidated.json) | 两个 API 调用均完成，约 18.9 秒；实际文字正确保留“超过 1 万元→负责人”“其他→财务”。原自动检查未去掉数字间空格，导致第一条关系误判失败；统一去空白后对原响应复核全部通过，未再次调用 API，历史证据原样保留。 |
| 修正检查后的联合真实验收 | [联合通过记录](/E:/aaa-project/rag-me/tests/testFile/media_live_combined_verified.json) | 重新经公开入口实际调用两个 API，全部语义、来源和待核验检查通过；本次约 24.1 秒。 |
| 首次真实运行与随后重跑 | [首次运行](/E:/aaa-project/rag-me/tests/testFile/media_live_initial.json)、[联合重跑](/E:/aaa-project/rag-me/tests/testFile/media_live_combined_final.json) | 多次出现 TLS 连接中断，结果明确为 network_error，无伪成功正文。相同配置的其他请求已成功，不能把该网络问题记为鉴权或模型不支持。 |

语音样本为 Windows Microsoft Huihui Desktop 合成，不是真实会议录音。画面复用本仓库原创审批图；样本和构造说明见[清单](/E:/aaa-project/rag-me/tests/testFile/media_constructed.json)。语音中“右侧分支”的说法与所用画面中负责人节点的左右位置不一致，结果分别保留两种来源，不据此自动融合成已核验的业务结论。

以上证明固定样本下真实接口可工作，不证明任意录音、长视频、方言、重叠讲话或快速操作均准确。视频 API 可能采样或遗漏画面；不能据模型输出宣称逐帧验证。未知说话人、片段级时间和所有模型结果的待核验状态均保留。

接口请求只执行一次，无自动重试。当前网络存在间歇性 TLS 中断，调用方需要检查网络并显式决定重新运行；失败不会清除已有输入来源，也不会输出部分成功内容。
