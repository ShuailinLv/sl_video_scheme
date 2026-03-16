python tools\preprocess_lesson.py --text-file "D:\sl_video_scheme\shadowing_app\assets\raw_texts\演讲稿3.txt" --api-key "sk_7e4f1c94ccc6e8a64633d6a7b1e1a8edaaaea47d53b78537"

python tools\preprocess_lesson.py

python tools\run_shadowing.py --text-file "D:\sl_video_scheme\shadowing_app\assets\raw_texts\演讲稿3.txt"


set SHERPA_TOKENS=D:\sl_video_scheme\sherpa-onnx-streaming-zipformer-zh-14M\tokens.txt
set SHERPA_ENCODER=D:\sl_video_scheme\sherpa-onnx-streaming-zipformer-zh-14M\encoder-epoch-99-avg-1.int8.onnx
set SHERPA_DECODER=D:\sl_video_scheme\sherpa-onnx-streaming-zipformer-zh-14M\decoder-epoch-99-avg-1.onnx
set SHERPA_JOINER=D:\sl_video_scheme\sherpa-onnx-streaming-zipformer-zh-14M\joiner-epoch-99-avg-1.int8.onnx




set DASHSCOPE_API_KEY=你的key
set QWEN_CHAT_MODEL=qwen-plus



python tools/run_shadowing.py --text-file "D:\sl_video_scheme\shadowing_app\assets\raw_texts\演讲稿3.txt" --asr sherpa --output-device 4 --capture-backend sounddevice --input-device "耳机" --input-samplerate 48000 --playback-latency high --playback-blocksize 4096 --startup-grace-sec 2.8 --low-confidence-hold-sec 2.0 --tick-sleep-sec 0.03 --event-logging --hotwords-source qwen --qwen-max-hotwords 20 --hotwords-score 1.35 --aligner-debug --asr-debug-feed --asr-debug-feed-every 20


python shadowing_app/tools/run_shadowing.py \
  --text-file your_text.txt \
  --event-logging \
  --force-bluetooth-long-session-mode





一、最终推荐执行顺序
标准顺序
第 1 步：准备 lesson 文本

输入：

lesson_id

lesson_text

产出目标：

这一课的原始文本输入

第 2 步：分句/分 segment 生成 TTS

入口：

ElevenLabsTTSProvider.synthesize_lesson(...)

它现在会做：

segmenter.py 切段

每段带前后文 continuity 调 ElevenLabs

生成逐段 chunks/*

生成逐段 alignments/*.alignment.json

生成 segments_manifest.json

生成初始 SegmentTimelineRecord

这一步的核心目的不是直接给 runtime 播放，而是先把每个局部段落做稳定。

产物：

lesson_manifest.json

reference_map.json（已经比原来好，但还不是最终形态）

chunks/*.wav

alignments/*.alignment.json

segments_manifest.json

第 3 步：assembler 重建连续参考音和真实时间轴

入口：

audio_assembler.py

已经在你现在的 ElevenLabsTTSProvider 第三版里接进去了

它会做：

逐段音频轻量 trim

短 crossfade

生成 assembled_reference.wav

计算每段真实：

trim_head_sec

trim_tail_sec

assembled_start_sec

assembled_end_sec

然后回写到 segments_manifest.json 对应记录中，并且最终用：

ReferenceBuilder.build_from_segment_records(...)

重建新的 reference_map

这一步其实是离线参考链路里最关键的一步。
因为从这一步开始，你的“参考音频”和“参考时间轴”才真正对齐到连续轨。

产物重点变成：

assembled_reference.wav

更新后的 segments_manifest.json

基于真实时间轴重建后的 reference_map.json

第 4 步：对 assembled 参考音提 acoustic features

入口：

ReferenceAudioFeaturePipeline.run(lesson_id)

现在这条 pipeline 已经改成优先：

assembled_reference.wav

segments_manifest.json

如果存在，就不再优先分析老的逐 chunk 轨道，而是分析连续参考音。

这一步会生成：

reference_audio_features.json

这份特征会被 runtime 的：

LiveAudioMatcher

ReferenceAudioStore.load(...)

直接吃掉。

第 5 步：进入 runtime 跟读

入口：

tools/run_shadowing.py

build_runtime(...)

ShadowingOrchestrator.start_session(...)

runtime 阶段优先依赖这些资产：

lesson_manifest.json

reference_map.json

reference_audio_features.json

其中最关键的是：

reference_map.json 必须是 assembler 后真实时间轴版

reference_audio_features.json 必须优先来自 assembled_reference.wav

这样 matcher、fusion、progress estimator 才会站在正确地基上。







cd shadowing_app

PYTHONPATH=src python tools/preprocess_lesson.py \
  --text-file assets/text/lesson.txt \
  --lesson-base-dir assets/lessons \
  --elevenlabs-api-key "$ELEVENLABS_API_KEY" \
  --voice-id "$ELEVENLABS_VOICE_ID" \
  --model-id "$ELEVENLABS_MODEL_ID" \
  --output-format pcm_44100 \
  --timeout-sec 120 \
  --seed 2025 \
  --target-chars-per-segment 28 \
  --hard-max-chars-per-segment 54 \
  --min-chars-per-segment 6 \
  --context-window-segments 2 \
  --continuity-context-chars-prev 100 \
  --continuity-context-chars-next 100 \
  --max-retries-per-segment 2 \
  --assembled-reference-filename assembled_reference.wav \
  --silence-rms-threshold 0.0035 \
  --min-silence-keep-sec 0.035 \
  --max-trim-head-sec 0.180 \
  --max-trim-tail-sec 0.220 \
  --crossfade-sec 0.025 \
  --reference-frame-size-sec 0.025 \
  --reference-hop-sec 0.010 \
  --reference-n-bands 6 \
  --print-summary



PYTHONPATH=src python tools/run_shadowing.py \
  --text-file assets/text/your_lesson.txt \
  --lesson-base-dir assets/lessons \
  --asr sherpa \
  --capture-backend sounddevice \
  --input-device "AirPods" \
  --output-device "AirPods" \
  --input-samplerate 48000 \
  --bluetooth-offset-sec 0.30 \
  --playback-latency low \
  --playback-blocksize 512 \
  --preflight-duration-sec 6.0 \
  --tick-sleep-sec 0.03 \
  --profile-path runtime/device_profiles.json \
  --session-dir runtime/latest_session \
  --event-logging \
  --force-bluetooth-long-session-mode \
  --hotwords-source local