Python 性能与 GIL 锁限制：
虽然底层用到了 numpy, scipy 和 Sherpa-ONNX (C++ 核心)，但在实时循环 ShadowingOrchestrator.tick() 中，伴随着高频的队列操作、DTW 矩阵计算和 RapidFuzz 字符串匹配。Python 的全局解释器锁（GIL）在高负载多线程下可能导致偶发的 tick 超时（大于设定的 0.03 秒），从而引发音频卡顿或同步滞后。
建议： 考虑到商业化，最核心的 LiveAudioMatcher (特别是 DTW 算法) 和 IncrementalAligner 最终应使用 C++ 或 Rust 重写并暴露为 Python Binding。
传统特征 DTW 的局限性：
LiveAudioMatcher 使用的特征是包络、能量和 Mel 频谱。DTW 虽然好用，但在极度嘈杂环境下（非清晰人声），Mel 频谱匹配的置信度会急剧下降，甚至产生误判。
建议： 引入轻量级的端到端深度学习对齐模型（如基于 Wav2Vec2.0 提取的特征向量代替传统的 Mel 频谱），计算特征余弦相似度，其抗噪能力和对齐精度会远超传统 DSP 提取的特征。
蓝牙预检 (Bluetooth Preflight) 的高拒绝率风险：
BluetoothPreflight 逻辑非常严格，甚至播放探针音频 (Probe Tone) 来测试链路。在某些 Windows 机器或安卓机型上，声卡独占或重采样可能导致测试失败，从而拒绝用户使用。在实际商业产品中，这可能会带来较高的客诉率。
建议： 提供柔性降级方案，而不是直接 raise RuntimeError。当无法获取精准延迟时，退回到保守的固定延迟设置。
https://aistudio.google.com/prompts/1jOOVLVvjuwpqIQqsbbaTtvusVcyYP3Ii