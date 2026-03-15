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