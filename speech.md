我先按你的硬约束重构：蓝牙播放、真人跟读、可用 ElevenLabs、且各模块必须能独立开发；接下来会先验证原方案的关键前提，再给你一版更稳的工业化架构。

另外我已确认两个能直接改写选型的点：ElevenLabs 现成支持带时间戳的 TTS 与实时 STT。与此同时，识别纠错应前移到 ASR 层，优先利用 hotwords、同音替换和 endpoint 规则。

Thought for 21m 26s

结论先说：这套方案方向非常对，但还不是最佳落地版。

它最值钱的两点没有问题：
一是把 ASR 留在本地，不让网络进入控制环；
二是用耳机，避免 AEC 地狱。

真正还差的 20%，主要在四个地方：

你现在既然能用 ElevenLabs，edge-tts 就不再是最佳 TTS 选型。edge-tts 本质上调用的是 Microsoft Edge 的在线 TTS 服务，并不是真“纯本地”；而 ElevenLabs 现在原生就有字符级时间戳 TTS 和 Forced Alignment，更适合做参考音频与时间地图。

你把“播放器零缓冲”和“用户耳朵里零延迟”混在了一起。对蓝牙播放来说，Python 回调只能压缩主机侧缓冲，Windows 到蓝牙耳机这段 A2DP 链路仍然有设备/编解码器相关的额外输出延迟；而且 Windows 的蓝牙媒体播放就是 A2DP，使用蓝牙设备麦克风时会切到 HFP。换句话说，蓝牙偏移必须被当作一个单独的系统参数建模和校准，不能假设 play_ptr / fs == 人耳听到的时间。

“全链路统一 16kHz”对 ASR 侧是对的，对蓝牙播放侧是错的。Windows 蓝牙输出支持的编解码器和采样率取决于 Windows 版本、蓝牙芯片和耳机能力；sounddevice 的 WASAPI 设置也明确区分了共享模式下的自动转换与独占模式下的格式匹配。因此正确做法不是“全系统 16k”，而是分成两个采样率域：输入/ASR 域固定 16k mono；输出/播放域按设备原生 44.1k 或 48k 走。

对齐和控制层还太“拍脑袋”。partial_ratio 拼接串 + PID 这套能跑，但不够稳。中文 shadowing 的主要问题不是“模糊匹配不够快”，而是重复、跳读、同音、回读、半句卡顿会把简单相似度算法带偏。这里应该换成受限窗口的增量对齐和带滞回的状态机控制，而不是继续堆阈值。这个部分决定最终是否“像产品”。

我对你这套方案的逐项判断
1）技术栈层面

sherpa-onnx + sounddevice + rapidfuzz + pypinyin 这条线是对的。
sounddevice 也确实比 pygame/vlc/pydub 更适合做交互式播放，因为它能用回调流、低延迟设置和 WASAPI 专项参数；回调里还能拿到 time.outputBufferDacTime，比你自己靠 play_ptr 猜时间更靠谱。它同时明确要求 callback 不能做分配内存、文件 IO 或阻塞调用，blocksize=0 在高实时负载下也更稳。

但 edge-tts 我会从核心架构里拿掉。原因不是它不能用，而是你既然有 ElevenLabs，继续围绕 edge-tts 设计时间戳层已经不划算了。ElevenLabs 的 /with-timestamps 直接返回字符级对齐，Forced Alignment 还能把任意现成音频和文本对齐；这两个接口都比“WordBoundary + 自己拼中文句界”更干净。

2）ASR 选型层面

sherpa-onnx 仍然是本方案最合理的本地 ASR 主引擎。当前官方文档已经列出了更新的中文 streaming Zipformer int8 模型，而不是早年的 14M 示例；更关键的是，官方明确写了 hotwords 只支持 transducer 模型，而同音替换模块支持所有能输出中文的模型。这意味着如果你的课文是已知文本，默认主力应该选 streaming Zipformer transducer，把全文作为 hotwords/context bias；同音替换再作为第二层容错。

如果你后面发现用户方言很重，再单独保留一个 ParaformerProvider 作为替代 provider。官方在线 Paraformer 有普通话/英语/粤语与多地方言支持，但文档也注明有的模型不支持 timestamps。因为你的 live 控制并不依赖 ASR 自身时间戳，所以它可以是备选，但不适合作为第一选择。

另外，“关闭 ASR VAD”这个说法不够准确。sherpa 的 endpoint 默认规则是：
无语音 5 秒超时；有过语音后 2 秒静音超时；整段 20 秒超时。shadowing 场景下这些默认值确实偏激进，但我建议是把 endpoint 放宽，而不是“永远关闭分段”。因为你仍然需要一个可控的 reset 点来防漂移和长句累积误差。

3）播放控制层面

你的“底层回调秒停”方向是对的，但要分清三种动作：

短暂停顿：继续开流、填静音。

硬快进/硬跳转：不要只是改 play_ptr，而是让播放引擎在安全边界执行 flush/seek。

真正立刻丢掉待播缓冲：abort() 的语义比 stop() 更接近你的目标，stop() 会等 pending buffers 播完。

而且你的当前骨架里 play_ptr、is_paused、T_user 被多个线程直接改，工程上不够稳。不是说它一定会炸，而是回调线程是实时线程，控制线程不应该直接写播放内部指针。正确做法是：
控制器发命令，播放模块在自己的线程/回调安全点消费命令。

最佳落地方案：在“蓝牙播放 + 本地跟读”约束下，我建议你这样做

这是我认为最稳、最像产品、同时又能模块化独立开发的版本：

           ┌──────────────────────────────┐
           │  Lesson Preprocessor         │
文本/课文 ─▶  ElevenLabs TTS / Alignment  ├──┐
           │  产出 audio chunks + ref map │  │
           └──────────────────────────────┘  │
                                              ▼
                                    ┌─────────────────┐
                                    │ Playback Engine │───▶ 蓝牙耳机(A2DP)
                                    │ host clock +    │
                                    │ bt offset model │
                                    └─────────────────┘
                                              ▲
                                              │ commands
                                              │
麦克风 ─▶ Capture Engine ─▶ Local ASR ─▶ Normalizer ─▶ Alignment Engine ─▶ Controller
                                              │
                                              └──────────────▶ Analytics / Logs
模块拆分
A. lesson_preprocessor

职责：把“文本”变成可播放的参考资产。
输入：课文、voice preset、分句规则。
输出：

audio_chunks/

reference_map.json

lesson_manifest.json

这里不要再围绕 edge-tts 设计。
直接做两条 provider：

ElevenLabsTTSProvider

最终课件音频：用 eleven_multilingual_v2

教师编辑预览：可用 eleven_flash_v2_5

调 ElevenLabs 的 convert_with_timestamps

把字符级时间戳转成你的统一 ReferenceMap

ForcedAlignmentProvider

如果以后你不用 TTS，而是换真人教师录音

直接用 ElevenLabs Forced Alignment 生成同样格式的 ReferenceMap

这两个 provider 最后都输出同一套内部结构：

@dataclass
class RefToken:
    idx: int
    char: str
    py: str
    t_start: float
    t_end: float
    sentence_id: int
    clause_id: int

这样以后你换 TTS、换真人音频、甚至换供应商，对齐层和播放层都不用改。
ElevenLabs 还提供 previous_text/next_text 或 request-id 连续性参数，所以你完全可以按句/短分句切块，同时维持跨块韵律连续。

我建议块粒度不要整篇一个文件，而是2–6 秒一个 clause chunk。
原因不是生成不了整篇，而是：

seek 更干净

chunk 级缓存更简单

对齐窗口天然有句法边界

后期局部重生成更便宜

如果全文在开播前就知道，TTS 生成优先用普通 HTTP 或 streaming HTTP 端点，不要默认上 WebSocket。ElevenLabs 官方文档明确说了：当完整输入提前已知时，WebSocket 因为内部 buffering，可能比标准 HTTP 更高延迟。

B. playback_engine

职责：本地低延迟播放参考音频，并提供统一播放时钟。
输入：audio chunks、seek/pause/resume 命令。
输出：PlaybackStatus

核心设计：

sounddevice.OutputStream

Windows 下优先尝试 WasapiSettings(exclusive=True)

latency='low'

blocksize=0

回调只做：

从预先准备好的 chunk/ring buffer 取数据

填充 outdata

更新时钟状态

不在 callback 里做字符串处理、匹配、文件 IO、网络请求、日志拼接

最重要的是时钟不要再用 play_ptr / fs 裸算。
应改成：

T_sched：来自 time.outputBufferDacTime

T_ref_heard = T_sched - bt_output_offset_ms / 1000

这里的 bt_output_offset_ms 就是蓝牙输出偏移，必须作为配置或校准参数存在。因为 sounddevice/PortAudio 能告诉你的是“系统/设备侧的输出时间估计”，但蓝牙耳机端的实际感知延迟仍受 A2DP 路径影响。

这里还有一个强约束：
输入设备不要用蓝牙耳机自己的麦克风。
Windows 文档写得很明确：打开蓝牙音频设备的输入端点后，系统会选择 HFP 而不是 A2DP；媒体播放会被拉到通话链路。你的方案里应该固定为：

输出：蓝牙耳机

输入：笔记本内置麦 / USB 麦

而不是同一个蓝牙设备的 mic。

C. capture_engine

职责：采集用户跟读音频。
输入：系统麦克风。
输出：16k mono PCM blocks。

这里才是你应该坚持 16k 的地方。
播放域不要 16k，采集/ASR 域固定 16k mono。
如果系统麦默认 48k，就在 capture 模块做一次性重采样，再交给 ASR 模块。不要让 ASR 模块自己兼顾设备差异。

D. asr_provider

职责：把 PCM block 变成 partial/final 文本。
接口：

class ASRProvider(Protocol):
    def start(self) -> None: ...
    def feed_pcm(self, pcm16: bytes) -> None: ...
    def poll_events(self) -> list[AsrEvent]: ...
    def reset(self) -> None: ...

默认实现：

SherpaZipformerTransducerProvider

当前中文 streaming Zipformer int8

开启 hotwords（课文全文或当前句段）

endpoint 放宽

打开 homophone replacer

备选实现：

SherpaParaformerProvider

给方言/口音更重的场景做 A/B

可选实现：

ElevenRealtimeSTTProvider

只用于 benchmark 或 debug，不放进热路径

为什么实时控制层不建议直接用 ElevenLabs Realtime STT？
因为它官方延迟指标本身就约 150ms，而且不含应用和网络延迟；这对会议转写很好，但对你这个“跟着电脑声音走”的闭环控制，不如本地 ASR 稳。它更适合做对照实验、日志对齐、后处理评分。

E. normalizer

职责：统一文本空间。
输入：ASR partial text。
输出：规范化 token 序列。

这个模块要单独拎出来，不要掺在对齐器里。
它做四件事：

去掉无关标点

中文数字口语化归一

同音替换结果融合

转拼音 syllable

输出最好保留两路：

chars

pinyin_syllables

因为真正稳定的 live 对齐不是“只看拼音”，而是字符匹配优先，拼音相似兜底。

F. alignment_engine

职责：把“用户当前说到哪”映射回参考时间轴。
这是整个系统的灵魂。

这里我建议你放弃 partial_ratio("".join(py), "".join(window_py))，改成：

受限窗口

token 级

增量式

加权编辑对齐

也就是在当前 committed_idx 附近，做一个小窗口的 weighted alignment：

精确字匹配：奖励最高

同拼音：次高

近音：次次高

插入（口吃/重复）：小惩罚

删除（漏读/跳读）：中惩罚

回退到已提交位置之前：大惩罚

对齐结果不要直接提交，要做稳定化：

连续 2～3 帧都指向差不多的位置

分数超过阈值

才推进 committed_ref_idx

这样“天天气”不会把系统拉飞，“跳到下一句”也不会误当成读错。

输出结构：

@dataclass
class AlignResult:
    committed_ref_idx: int
    candidate_ref_idx: int
    ref_time: float
    confidence: float
    stable: bool
G. controller

职责：根据 T_ref_heard 和 T_user 发控制命令。
这里不要 PID，换成有限状态机 + 滞回。

你这个系统不是电机，也不是连续可微对象。它有：

蓝牙固定偏移

ASR 观察延迟

对齐抖动

seek 是离散动作

pause/resume 是离散动作

所以更适合：

PLAY

HOLD

SEEK

RECOVER

控制量也别用 delta = T_play - T_user，而是：
lead=Tref_heard​−Tuser​


其中：

T_ref_heard：用户耳朵里参考音频真正对应的时间

T_user：对齐器给出的用户当前进度

一个好用的初始参数大概是：

control:
  target_lead_ms: 150
  hold_if_lead_ms: 450
  resume_if_lead_ms: 180
  seek_if_lag_ms: -900
  stable_frames: 2
  recover_cooldown_ms: 150

意思是：

正常时让参考音频略微领先用户 100~200ms

领先太多就 HOLD

人追上来再恢复

人明显跳读了才 SEEK

这比 PID 好调，也更像产品。

H. analytics

职责：课后评分，不参与实时控制。
这里才是 ElevenLabs STT 最有价值的地方。

你已经有 ElevenLabs，可以把用户整段录音在 session 结束后送去做：

Scribe v2 转写

word-level timestamps

keyterm prompting（把课文关键词喂进去）

最终准确率 / 跳读 / 停顿分析

这样闭源能力被放在后处理高精度环节，不污染实时延迟。ElevenLabs 官方模型说明里已经列了 Scribe v2 的 word-level timestamps 和 keyterm prompting。

我给你的最终推荐栈

如果你要今天就开工，我会这么配：

# 核心
sherpa-onnx
sounddevice
soundfile
numpy
rapidfuzz
pypinyin
scipy

# 云端预处理 / 后处理
elevenlabs
httpx

# 工程化
orjson
pydantic
pyyaml

edge-tts 不进主链路。
它最多保留成一个 fallback provider。

你原方案里最该立刻改掉的三件事

第一，删掉“全链路 16k”。
改成“输入域 16k，输出域跟设备走”。

第二，把 play_ptr 从全局共享变量改成播放模块私有状态。
控制器只发命令，不直接改播放指针。

第三，把对齐算法从字符串模糊匹配升级成 token 级增量对齐。
这是体验差距最大的地方。

一个真正可落地的开发顺序

先做 lesson_preprocessor + playback_engine
让蓝牙耳机下的播放、pause、seek、时钟输出先稳定。

再做 capture_engine + asr_provider
先把 partial text 稳定吐出来。

再做 alignment_engine
用录好的几段用户音频离线回放，先把“口吃 / 跳读 / 同音字”三类 case 跑通。

最后接 controller
先只实现 HOLD / RESUME，再加 SEEK。

analytics 最后做
不影响主链路。

最后一句判断

在“电脑通过蓝牙播放、用户戴蓝牙耳机跟读、实时控制尽量丝滑、模块要能独立开发”这个约束下，我认为最佳方案不是你贴的那版，而是：

ElevenLabs 预生成带字符时间戳的句块 + sounddevice/WASAPI 本地播放引擎 + 本地 sherpa-onnx streaming transducer + 官方同音替换 + 受限增量拼音/字符对齐 + 蓝牙偏移校准 + 滞回状态机控制。

这才是当前最稳、最像产品、也最容易模块化推进的版本。

如果你愿意，我下一条可以直接给你一份项目目录结构 + 每个模块的 Python 接口骨架。