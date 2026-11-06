# Pika H3 Flex 云机验证记录（2026-11-06）

## 结论

Pika H3 Flex 的官方 Ref2VA 路径已在当前 RTX 5090 云机上以 768p 跑通，并已作为明琰AI平台当前 ComfyUI 视频工作流保存。正式验证成片为 `1344×768`、15.083 秒、24fps，带 AAC 双声道音轨；未调用付费视频 API。

仓库中的可复用工作流：[`../workflows/pika-h3-flex-ref2va-768p.json`](../workflows/pika-h3-flex-ref2va-768p.json)

## 云机与模型

- GPU：RTX 5090，ComfyUI 报告显存总量 33,668,988,928 字节。
- 系统内存：96,636,764,160 字节。
- ComfyUI：0.42.1。
- 主模型：`minimax/minimax_h3_ref2va_pruned_int8_convrot.safetensors`。
- 文本编码器：`qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`。
- 视频 VAE：`minimax_h3_video_vae_int8_convrot.safetensors`。
- 音频 VAE：`minimax_h3_audio_vae_fp32.safetensors`。
- 官方 Ref2VA LoRA：`minimax/pika_h3_flex_ref2va_v1_bf16.safetensors`。
- 同机还检测到官方 FL2VA LoRA：`minimax/pika_h3_flex_fl2va_v1_bf16.safetensors`。

两套 LoRA 的内部元数据显示基础模型为 `MiniMaxAI/MiniMax-H3`，转换布局为 `comfyui_minimax_h3`。本次使用 Ref2VA，因为明琰AI的生产链需要同时引用人物与场景资产。

上游资料：

- [Pika Labs / Pika-H3-Flex](https://github.com/Pika-Labs/Pika-H3-Flex)
- [Comfy-Org 官方 Pika H3 Flex 工作流模板](https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_pika_h3_flex_fl2va.json)
- [Pika H3 Flex 硬件说明](https://github.com/Pika-Labs/Pika-H3-Flex/blob/main/docs/hardware.md)

## 工作流关键参数

- 模式：Ref2VA，双参考图。
- 画幅：16:9。
- 分辨率选择：0.98 megapixels、32 倍数对齐，实际输出 `1344×768`。
- 时长：`{{seconds}}`，本次正式验证 15 秒。
- 采样器：LCM。
- Sigmas：`1.0, 0.972973, 0.923077, 0.8, 0.571429, 0.333333, 0.0`。
- LoRA 强度：1.0。
- 平台占位符：`{{prompt}}`、`{{reference_1}}`、`{{reference_2}}`、`{{seconds}}`、`{{seed}}`。
- 低显存块：Q/KV/MLP 均为 8192，KV 存储为 BF16 exact。
- `final_layer_chunk` 必须保持为 `0`。云机自带 MAINodes 的分块末层补丁与当前 ComfyUI H3 结构不兼容，启用时会报 `Tensor object has no attribute adaln_proj`。
- `trim_forward` 在当前 ComfyUI 版本因源码哈希变化被自动跳过；这是一条警告，不影响成功生成。

## 实测结果

| 项目 | 5 秒预检 | 15 秒正式验证 |
| --- | ---: | ---: |
| 输出 | 1344×768 | 1344×768 |
| 帧率 | 24fps | 24fps |
| 帧数 | 124 | 362 |
| 实际时长 | 5.165 秒 | 15.083 秒 |
| 云端耗时 | 158.18 秒 | 624 秒（日志 10:24） |
| 文件大小 | 2,758,031 字节 | 6,786,537 字节 |
| 视频/音频 | H.264 + AAC 32kHz 双声道 | H.264 + AAC 32kHz 双声道 |
| 采样显存峰值 | 约 32.35GB | 约 33.27GB |

显存为轮询 `/system_stats` 得到的采样峰值，不是逐毫秒硬件遥测。15 秒任务几乎占满 5090，单卡必须串行执行，不能同时跑两条 H3。

## 画面验收

参考 1 为云子姝人物图，参考 2 为明代寝房资产图。15 秒提示词按三个 5 秒镜头组织：卧房建立镜头、人物特写与对白、人物走向门口。

抽查 0.5、4.8、5.5、9.8、10.5、14.5 秒画面：

- 人物脸型、发型与头饰跨镜保持一致。
- 粉色上衣、青绿长裙、红腰带没有换装。
- 床榻、木构、屏风、门口方向与晨光保持连续。
- 10 秒由特写切回全身走位后，人物身份、服装与场景未重置。
- 无字幕、标签、水印或资产卡文字残留。
- 音轨存在；本轮未对中文台词做自动转写评分。

本地成片保存在用户数据目录的 `generated/pika-tests/` 下，不进入 Git。

## 平台接入状态

- 明琰AI的当前视频通道已保持为 `comfyui`。
- 当前工作流名称：`Pika H3 Flex · Ref2VA · 768p · 双参考图（5–15秒）`。
- 配置保存后，平台的 ComfyUI 连接与工作流校验通过，测试延迟 675ms。
- 生产任务会把提示词、两张参考图、时长和种子替换进工作流，再由 `/prompt`、`/history` 与 `/view` 完成提交、恢复和下载。
- 云机地址属于临时实例配置，不写入公开仓库；实例重建或映射地址变化后，只需在平台设置页更新地址。

## 已知边界

- 当前模板固定需要两张参考图；生产清单必须为每个镜头组提供两张有效素材。
- 768p 15 秒单条约 10 分钟，批量任务应保持 H3 单卡并发数为 1。
- Ref2VA 能明显约束人物、服装和场景，但仍不等于像素级身份锁定；对要求更高的连续剧，应继续使用身份母版、状态图与上一条终帧三层参考。
- 相邻视频之间的首尾帧硬衔接尚未完成，仍是下一项连续性工程。
