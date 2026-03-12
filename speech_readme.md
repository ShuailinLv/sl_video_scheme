python tools\preprocess_lesson.py

python tools\run_shadowing.py --text-file "D:\sl_video_scheme\shadowing_app\assets\raw_texts\演讲稿3.txt"


set SHERPA_TOKENS=D:\sl_video_scheme\sherpa-onnx-streaming-zipformer-zh-14M\tokens.txt
set SHERPA_ENCODER=D:\sl_video_scheme\sherpa-onnx-streaming-zipformer-zh-14M\encoder-epoch-99-avg-1.int8.onnx
set SHERPA_DECODER=D:\sl_video_scheme\sherpa-onnx-streaming-zipformer-zh-14M\decoder-epoch-99-avg-1.onnx
set SHERPA_JOINER=D:\sl_video_scheme\sherpa-onnx-streaming-zipformer-zh-14M\joiner-epoch-99-avg-1.int8.onnx

