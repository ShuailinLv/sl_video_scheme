python tools\preprocess_lesson.py --text-file "D:\sl_video_scheme\shadowing_app\assets\raw_texts\演讲稿3.txt" --api-key "sk_7e4f1c94ccc6e8a64633d6a7b1e1a8edaaaea47d53b78537"

python tools\preprocess_lesson.py

python tools\run_shadowing.py --text-file "D:\sl_video_scheme\shadowing_app\assets\raw_texts\演讲稿3.txt"


set SHERPA_TOKENS=D:\sl_video_scheme\sherpa-onnx-streaming-zipformer-zh-14M\tokens.txt
set SHERPA_ENCODER=D:\sl_video_scheme\sherpa-onnx-streaming-zipformer-zh-14M\encoder-epoch-99-avg-1.int8.onnx
set SHERPA_DECODER=D:\sl_video_scheme\sherpa-onnx-streaming-zipformer-zh-14M\decoder-epoch-99-avg-1.onnx
set SHERPA_JOINER=D:\sl_video_scheme\sherpa-onnx-streaming-zipformer-zh-14M\joiner-epoch-99-avg-1.int8.onnx






python tools/run_shadowing.py --text-file "D:\sl_video_scheme\shadowing_app\assets\raw_texts\演讲稿3.txt" --asr sherpa --aligner-debug --startup-grace-sec 2.0 --low-confidence-hold-sec 1.5 --output-device 4 --playback-latency high --playback-blocksize 4096 --capture-backend sounddevice --input-device "耳机" --input-samplerate 48000 --asr-debug-feed --asr-debug-feed-every 10 --event-logging