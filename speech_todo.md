我先按“商用可用到底意味着什么、现有系统离它差在哪、要补哪几层能力”来拆。不会只停在调阈值，而是会把它当成一个实时人机闭环系统来设计。

已思考几秒

要做到商用级别可用，不能再把它当成“ASR + 对齐 + 几个阈值”的 demo 系统，而要把它当成一个实时、弱观测、强反馈的人机闭环控制产品来做。

一句话先定性：

你现在的系统已经开始从“能跑”走向“可用”，但离商用还差的是：可观测性、鲁棒性、可恢复性、个体适配、设备适配、评估闭环这六层能力。

下面我按“商用品质目标 → 当前根因 → 系统级方案 → 落地路线”深度拆开。

一、先定义“商用级别可用”到底是什么

如果目标只是“我自己试几次感觉还行”，那把启动早 hold 和 hold 后难恢复修掉，已经很有帮助。
但如果目标是商用，标准完全不同。

商用不是“平均情况能跑”，而是：

1. 首次体验不能崩

用户第一次打开：

设备能识别

音频链路能自动校准

不会一上来就乱停

不会说了系统没反应

不会一出错就彻底失控

2. 大多数设备和环境下表现一致

不是只在你现在这台 Windows + 某个耳机 + 某个文本上好用，而是：

板载麦

USB 麦

蓝牙耳机

不同输出设备

不同延迟

不同噪声环境

都要在一个可接受区间内。

3. 允许用户“不是完美跟读”

商用用户不会像测试员那样标准：

会停顿

会重复

会跳读

会读错再改

会跟不上

会突然追上

系统不能把这些都当故障。

4. 出错时要优雅退化

不是“判断错一次就卡住”，而是：

低置信时先宽容

失锁时尝试重新锁定

长时间失效时进入降级模式

至少不能让用户觉得系统在跟自己对着干

5. 质量必须可量化

商用不能靠“我感觉更顺了”迭代，必须有指标：

启动成功率

误 hold 率

hold 后恢复时间

长程失锁率

用户有效跟读占比

不同设备分层表现

这才是商用。

二、你当前系统离商用差的，不是一个点，而是三个层级

我建议把问题分成三层。

第一层：控制层问题

也就是你现在最明显看到的：

启动过早 hold

hold 后难恢复

partial 抖动导致误判

低质量输入时进度冻结

这一层你已经在修了，但还没完全闭环。

第二层：状态理解问题

这是更本质的一层：

系统现在只是在判断：

有没有进度

lead 是多少

confidence 高不高

但商用品质需要系统理解更多状态：

用户在正常跟

用户只是短暂停顿

用户重复上一小段

用户跳到了前面

ASR 暂时没看清

对齐已经失锁

当前设备链路过慢

当前噪声导致观测不可信

如果不能区分这些状态，controller 永远只能“猜”。

第三层：产品系统问题

即使算法本身不错，没有这些也达不到商用：

设备探测与自动校准

运行时监控与自恢复

用户级个性化参数

离线回放评测框架

线上日志与失败聚类

配置分层和灰度能力

这一层往往是 demo 到商用的最大鸿沟。

三、当前架构的根本限制

你现在大概是这条链：

audio in → ASR → normalize → partial adapter → aligner → progress estimator → controller → player

这条链是对的，但商用级别的问题在于：
它还是一条单主线启发式链路，而不是一个“带置信传播和异常恢复”的控制系统。

核心限制有 5 个。

限制 1：观测质量没有独立建模

你现在有 confidence、local_match_ratio、repeat_penalty，这是好事。
但它们还只是 aligner 的附带字段，不是系统一级信号。

商用系统需要一个明确的：

tracking_quality

signal_quality

observation_reliability

它应该综合：

最近 event 到达频率

局部匹配率

单调一致性

重复污染度

ASR 输出稳定性

RMS/VAD 活跃度

partial 回改频率

generation 切换频率

没有这个，controller 只能看“位置”，不能看“我是不是看清了位置”。

而商用品质里，很多错误不是“位置错”，而是“在看不清时做了太强动作”。

限制 2：用户行为模型太弱

当前系统隐含假设是：

用户大致线性顺读，只是有点快慢和停顿。

但真实用户行为不是这样。
商用品质至少要能区分：

正常跟读

暂停思考

跟丢后重新接入

重复上一句

跳读

大段漏读

被打断

干脆沉默

这些行为如果都被压成“没推进”，controller 必然误判。

限制 3：时间建模仍然太粗

你已经开始修 progress_age，这很好。
但真实系统里至少有这些延迟：

麦克风采集延迟

驱动缓冲延迟

输入设备固有延迟

ASR decode 累积延迟

partial 发射节流延迟

输出设备蓝牙延迟

控制回路采样间隔

player callback 对齐误差

也就是说，lead 不是纯物理量，而是带动态偏差的估计量。

商用品质下必须有“时间校准层”，而不是只靠一个固定 bluetooth_output_offset_sec。

限制 4：失锁恢复能力弱

现在系统更多是：

有 tracking 就继续

tracking 差了就 hold

很差时 seek

这不够。

真正商用品质要区分三类坏状态：

A. 短时不确定

比如 300~800ms 内 partial 没来。
应该宽容，不动作。

B. 中度失锁

比如 candidate 乱跳，但用户还在说。
应该进入“重捕获模式”，减小动作强度，等待稳定证据。

C. 长时失锁

比如 3~5 秒完全不可信。
才允许进入强恢复策略，如提示、重新锚定、半自动跳转。

现在系统对失锁的中间层不够。

限制 5：没有“离线评测-线上校验”闭环

这是最致命的商用缺口之一。

如果没有：

标注数据

回放评测

分场景对比

参数版本管理

线上日志回灌

你就只能靠真人试，调一个地方好一点，另一个地方可能悄悄变差。

商用品质一定要靠评测闭环，不是靠感觉。

四、要做到商用，系统应该升级成什么形态

我建议把系统升成六层。

第一层：音频链路与设备适配层

这是商用最容易被低估的一层。

目标

在用户真正开始跟读前，系统要知道：

输入设备是否真有有效信号

输出设备延迟大概多少

当前输入电平是否太低

当前麦克风是不是蓝牙窄带 / 有强降噪 / 有噪声门

必做能力
1. 输入设备探测与分级

每个设备打开后要采样一个短窗口，估计：

噪声底

峰值

动态范围

是否长期静音

是否疑似蓝牙耳机窄带链路

然后给设备打标签：

builtin_mic

usb_mic

bluetooth_headset_mic

unknown_low_signal

不同标签套不同默认策略。

2. 自动输入校准

根据前几秒：

自动估 VAD 阈值

自动估最小有效 RMS

自动估初始 speaking detection 灵敏度

不要把所有设备都用同一个 vad_rms_threshold=0.01。

3. 输出延迟校准

不能只靠手填 bluetooth_output_offset_sec。
至少要支持：

设备类型默认表

用户首次引导校准

运行中微调

否则 lead 会一直偏。

第二层：ASR 观测层

这里的目标不是“识别尽可能准”，而是“给控制系统提供可用观测”。

必做升级
1. partial 质量建模

不要只把 partial 当文本。
每个 partial 都要附带质量特征：

文本长度

增量长度

回改比例

连续重复比例

token 新鲜度

与上一帧重合率

近几帧稳定度

形成 asr_observation_quality。

2. 观测节流策略分层

现在是固定 emit_partial_interval_sec。
商用品质应该区分：

高质量输入：更频繁输出

低质量输入：更保守、减少抖动

发现回改剧烈时：降低控制权重

3. 双通道观测

保留两类信号：

快但脏：partial 增量

慢但稳：final / endpoint / 高稳定 partial

controller 不能只看一个通道。

第三层：对齐与跟踪层

这是现在最值得升级的算法核心。

目标

aligner 不只是“找最像的位置”，而要变成tracking engine。

应该输出什么

不仅是：

candidate idx

confidence

还应该输出：

tracking mode（locked / weak / reacquire / lost）

monotonic consistency

local tail hit rate

backward suspicion

repetition suspicion

jump suspicion

anchor consistency

关键升级 1：引入“锚点”概念

现在几乎每帧都在窗口内重新猜位置。
商用品质更稳的做法是：

平时依赖连续 tracking

但定期寻找高可信锚点

锚点之间靠平滑推进

失锁时重新找锚点，而不是一直在漂

锚点可以来自：

高置信 final

长度足够的高质量 partial

明确句首/句末特征

稳定连续命中区段

关键升级 2：显式失锁检测

比如定义：

连续 N 帧 candidate 波动过大

local match ratio 长时间低

progress 单调性被破坏

source candidate 与 estimated 长期背离

则进入 tracking_mode = weak/reacquire/lost

这会比单纯看 confidence 更可靠。

关键升级 3：重复/跳读检测

要单独加行为识别：

repeat_recent_span

skip_forward

restart_from_recent_anchor

这会极大提升真实用户场景下的自然性。

第四层：进度估计与状态理解层

这层比 aligner 更靠近“用户行为解释”。

目标

从 noisy alignment 中恢复出：

用户现在大概在哪

最近是不是在积极说

是不是短暂停住

是不是已经失锁

是不是正在重接入

建议新增两个核心对象
1. TrackingState

例如：

locked

weak_locked

reacquiring

lost

2. UserReadState

例如：

not_started

warming_up

following

hesitating

paused

repeating

skipping

rejoining

这样 controller 就不再直接从几个数值硬猜行为。

estimator 的升级方向

你现在的 MonotonicProgressEstimator 是必要第一步，但商用需要进一步升级为：

单调约束

时间老化

速度估计

观测质量调权

tracking mode 调权

行为模式调权

短时外推 + 长时收敛

本质上接近一个轻量级状态估计器。

不一定非要卡尔曼滤波，但思路应该像状态估计器，而不是简单 EMA。

第五层：控制策略层

这是用户最直接感知的一层。

商用品质的控制策略核心原则不是“正确”，而是：

宁可偶尔慢一点，也不能频繁和用户对抗。

控制层必须具备的 5 个特性
1. 分级动作

不能只有 HOLD / RESUME / SEEK 这种硬动作。
至少应该有：

keep_playing

soft_duck

slow_follow

hold

guided_resume

seek_recover

也就是说，先轻干预，再重干预。

2. 动作需要成本模型

不是能 hold 就 hold，而要考虑：

当前 tracking 质量

当前用户状态

这个动作对体验的破坏程度

失败后的恢复成本

比如在低质量观测下，HOLD 的成本很高，就应更保守。

3. holding 不是终态，要有 re-entry 设计

当前一个关键痛点就是 hold 后难恢复。
商用品质要把 holding 设计成一个“等待重新接入”的引导态，而不是静止态。

例如 holding 期间：

降低 resume 门槛

更看重新鲜 speaking 证据

允许短暂试探性 resume

若恢复失败再 hold

4. guide/follow/wait 要再细化

建议至少扩成：

bootstrapping

guiding

following

uncertain_follow

waiting

reacquiring

recovering_after_seek

这样状态语义才够用。

5. 长时间异常要降级

比如长时间 tracking 差时，不应继续精细控制。
应进入降级模式：

少 hold

不 seek

只做轻度 ducking

或提示用户重新开始

商用品质不是永远强控，而是知道什么时候退出强控。

第六层：评测、监控、数据闭环层

这是商用品质的决定性部分。

1. 离线回放评测框架

你必须能离线回放真实录音，得到：

每帧 alignment

progress 曲线

hold/resume/seek 决策

误判点

失锁段

并能对比不同版本策略。

2. 场景数据集

至少按场景分：

正常顺读

慢读

快读

断续停顿

重复读

跳读

噪声

蓝牙耳机

板载麦

不同文本难度

没有这个，你不会知道“优化到底对谁有用”。

3. 指标体系

建议至少定义：

启动指标

first_valid_progress_time

startup_false_hold_rate

startup_resume_latency

跟踪指标

tracking_lock_ratio

mean_progress_error

drift_rate

long_lost_rate

控制指标

false_hold_per_min

unnecessary_resume_per_min

hold_recovery_latency

user_speaking_while_holding_ratio

wrong_seek_rate

体验指标

uninterrupted_following_ratio

assistive_action_accept_rate

task_completion_rate

4. 线上日志与失败聚类

商用后最重要的问题不是“有没有 bug”，而是：

哪类用户、哪类设备、哪类文本、哪类链路最容易失败？

所以日志必须能回溯：

设备类型

输入输出采样率

链路延迟参数

partial 序列

aligner 关键信号

controller 状态机轨迹

最终失败类型

这样才能聚类。

五、实现商用品质的技术路线

我建议分四个阶段，不要一口气全重写。

阶段 1：先把“可用性底线”打稳

目标：从现在提升到“普通用户第一次也大概率能用”。

必做

修启动过早 hold

修 hold 后激进 resume

增加设备分类与启动链路检测

给 progress 增加 tracking quality

加入显式 tracking_mode

加离线日志记录与回放工具

交付标准

首次启动误 hold 显著下降

不同设备上 first_valid_progress_time 可观测

hold 后恢复时间可统计

阶段 2：把系统从“可用”提到“稳”

目标：长时间跟读不容易漂，不容易失锁。

必做

aligner 增加锚点机制

estimator 增加状态估计与轻外推

区分 lost / weak / locked

controller 引入 uncertain_follow 和 reacquiring

重复读 / 跳读 检测

交付标准

长文本场景 drift 下降

噪声与回改场景误 hold 下降

失锁后重新捕获成功率提高

阶段 3：做设备与用户自适配

目标：不是靠一套全局参数吃天下。

必做

设备 profile

自动校准 VAD / speaking threshold

输出延迟自动修正

用户级阅读速度 profile

文本难度分层参数

交付标准

蓝牙耳机与板载麦差距缩小

快读型用户/慢读型用户都能稳定工作

新用户不需要手调太多参数

阶段 4：做真正商用产品化

目标：可迭代、可监控、可灰度。

必做

参数版本化

策略灰度能力

在线指标 dashboard

自动失败回传与聚类

A/B 测试框架

降级与 fallback 策略

交付标准

每次策略变更都能被量化验证

线上问题可以快速定位到链路/设备/策略层

失败时用户体验可控

六、如果只选最关键的三件事，我会先做什么

如果你资源有限，我会把优先级定成这三个。

第一：显式建模 tracking_quality + tracking_mode

这是最大的杠杆点。

没有它，controller 永远分不清：

真的停住了

只是没看清

正在失锁

正在恢复

这是控制器所有误判的根源。

第二：把 hold/resume 从硬阈值动作升级成“分级恢复策略”

这是用户体感最直接的改进。

尤其是：

启动阶段

holding 状态

重接入阶段

要更宽容、更渐进。

第三：建立离线回放评测闭环

这是从工程到商用的分水岭。

没有它，你永远只能“感觉好像好了”。
有了它，你才能真正做出稳定产品。

七、我对你这个项目的最终判断

这个方向是能做到商用的，但前提是你接受一个现实：

商用级别的难点，不在某个对齐算法本身，而在把不确定观测、用户行为、设备链路、控制动作、评测闭环一起做成一个完整系统。

也就是说，终局不是：

再调一个 hold_if_lead_sec

再调一个 min_confidence

而是：

有观测质量层

有状态理解层

有失锁恢复层

有设备适配层

有评测与监控层

这样系统才会从“聪明 demo”变成“稳定产品”。

如果你愿意，我下一步可以直接给你一版商用化架构蓝图，包括模块边界、核心数据结构、状态机定义和评测指标表。



我给你直接落成一版“商用化架构蓝图”，按可实施来写：模块边界、核心数据结构、状态机、关键指标、分阶段里程碑都会给出来。重点不是泛泛而谈，而是让你能据此拆任务和排期。

已思考若干秒

下面是一版面向商用级跟读系统的架构蓝图。目标不是“算法更聪明一点”，而是让系统在真实设备、真实用户、真实噪声下，做到稳定、可恢复、可评估、可迭代。

1. 总体目标

系统目标可以定义成一句话：

在不完美的 ASR 和不稳定的音频链路下，持续估计“用户当前朗读进度”和“观测是否可信”，并用低对抗性的控制策略帮助用户跟上参考音频。

商用化后，系统需要同时满足四件事：

首次启动不崩

长时间跟读不乱

失锁后能恢复

线上问题可定位、可量化、可迭代

2. 顶层分层架构

建议拆成 8 层，而不是一条直链。

L1. Device & Audio IO 层

负责：

输入/输出设备探测

采样率与通道协商

输入增益与噪声底估计

输出延迟估计

音频流健康监控

输出给上层的是：

原始音频帧

设备 profile

音频健康状态

L2. Signal Observation 层

负责：

VAD

音频活动特征提取

speaking likelihood

静音/断流检测

输入质量分数

输出：

AudioObservation

SignalQuality

这一层不要依赖 ASR 文本，先给系统“用户是否在说、链路是否正常”的独立证据。

L3. ASR Observation 层

负责：

partial/final 接入

partial 增量抽取

回改检测

观测新鲜度与稳定度

ASR 质量估计

输出：

AsrObservation

AsrObservationQuality

这层的目标不是追求识别全文最准，而是给 tracking 提供对控制友好的观测。

L4. Alignment & Tracking 层

负责：

窗口内匹配

尾部增量对齐

锚点建立

锚点间连续跟踪

失锁检测

重捕获

输出：

TrackingObservation

TrackingMode

TrackingQuality

这是算法核心层，角色从“aligner”升级成“tracking engine”。

L5. Progress Estimation 层

负责：

单调进度估计

时间老化

短时速度估计

观测融合

用户行为状态解释

输出：

ProgressEstimate

UserReadState

这层把 noisy tracking 变成 controller 真正可用的状态。

L6. Control Policy 层

负责：

guide/follow/wait/reacquire 等状态机

动作成本建模

分级动作生成

hold/resume/seek/duck 决策

输出：

ControlDecision

这里不直接关心 ASR 细节，只吃“解释过的状态”。

L7. Playback Execution 层

负责：

实际播放

ducking

hold/resume

seek

播放时钟与 generation 管理

输出：

PlaybackStatus

PlaybackHealth

L8. Evaluation & Telemetry 层

负责：

全链路事件日志

指标聚合

离线回放

失败聚类

版本对比

这是商用能力的基础设施层。

3. 关键模块边界

下面给出建议模块目录。

shadowing/
  audio/
    device_profiler.py
    io_manager.py
    latency_calibrator.py
    signal_monitor.py

  observation/
    vad.py
    signal_quality.py
    asr_observer.py
    partial_stability.py

  tracking/
    anchor_manager.py
    incremental_aligner.py
    tracking_engine.py
    loss_detector.py
    reacquirer.py

  progress/
    progress_estimator.py
    behavior_interpreter.py

  control/
    policy.py
    state_machine.py
    action_cost.py

  playback/
    player.py
    playback_clock.py
    generation_sync.py

  runtime/
    orchestrator.py
    session_context.py
    health_guard.py

  telemetry/
    event_logger.py
    metrics.py
    replay_loader.py
    failure_classifier.py

  types.py
4. 核心数据结构设计

这部分最重要。商用系统要靠“明确的数据契约”而不是散落的字段。

4.1 DeviceProfile
@dataclass(slots=True)
class DeviceProfile:
    input_device_id: str
    output_device_id: str
    input_kind: str          # builtin_mic / usb_mic / bluetooth_headset / unknown
    output_kind: str         # speaker / wired_headset / bluetooth_headset
    input_sample_rate: int
    output_sample_rate: int
    estimated_input_latency_ms: float
    estimated_output_latency_ms: float
    noise_floor_rms: float
    input_gain_hint: str     # low / normal / high
    reliability_tier: str    # high / medium / low

作用：给后续阈值和控制策略一个设备上下文。

4.2 SignalQuality
@dataclass(slots=True)
class SignalQuality:
    rms: float
    peak: float
    vad_active: bool
    speaking_likelihood: float
    silence_run_sec: float
    clipping_ratio: float
    dropout_detected: bool
    quality_score: float

作用：提供“用户在说吗、链路正常吗”的独立证据。

4.3 AsrObservation
@dataclass(slots=True)
class AsrObservation:
    event_type: str              # partial / final
    raw_text: str
    normalized_text: str
    chars: list[str]
    pinyin_seq: list[str]
    emitted_at_sec: float
    is_incremental: bool
    overlap_with_prev: int
    rollback_chars: int
    delta_chars: int
4.4 AsrObservationQuality
@dataclass(slots=True)
class AsrObservationQuality:
    freshness_sec: float
    stability_score: float
    rewrite_ratio: float
    incremental_value_score: float
    repetition_score: float
    quality_score: float
4.5 TrackingObservation
@dataclass(slots=True)
class TrackingObservation:
    candidate_ref_idx: int
    committed_ref_idx: int
    candidate_ref_time_sec: float
    local_match_ratio: float
    monotonic_consistency: float
    repeat_penalty: float
    backward_suspicion: float
    anchor_consistency: float
    emitted_at_sec: float
4.6 TrackingMode
class TrackingMode(str, Enum):
    BOOTSTRAP = "bootstrap"
    LOCKED = "locked"
    WEAK_LOCKED = "weak_locked"
    REACQUIRING = "reacquiring"
    LOST = "lost"

这会成为 controller 的核心输入之一。

4.7 TrackingQuality
@dataclass(slots=True)
class TrackingQuality:
    overall_score: float
    observation_score: float
    temporal_consistency_score: float
    anchor_score: float
    mode: TrackingMode
    is_reliable: bool
4.8 ProgressEstimate
@dataclass(slots=True)
class ProgressEstimate:
    estimated_ref_idx: int
    estimated_ref_time_sec: float
    progress_velocity_idx_per_sec: float

    event_emitted_at_sec: float
    last_progress_at_sec: float
    progress_age_sec: float

    source_candidate_ref_idx: int
    source_committed_ref_idx: int

    tracking_mode: TrackingMode
    tracking_quality: float
    stable: bool
    confidence: float

    active_speaking: bool
    recently_progressed: bool
4.9 UserReadState
class UserReadState(str, Enum):
    NOT_STARTED = "not_started"
    WARMING_UP = "warming_up"
    FOLLOWING = "following"
    HESITATING = "hesitating"
    PAUSED = "paused"
    REPEATING = "repeating"
    SKIPPING = "skipping"
    REJOINING = "rejoining"
    LOST = "lost"

这个对象比 phase_hint 强得多，是真正的行为解释层。

4.10 ControlDecision
class ControlAction(str, Enum):
    NOOP = "noop"
    SOFT_DUCK = "soft_duck"
    HOLD = "hold"
    RESUME = "resume"
    SEEK = "seek"
    STOP = "stop"


@dataclass(slots=True)
class ControlDecision:
    action: ControlAction
    reason: str
    target_time_sec: float | None = None
    target_gain: float | None = None
    confidence: float = 0.0
    aggressiveness: str = "low"   # low / medium / high
5. 核心状态机设计

商用品质的关键不是更多阈值，而是正确的状态机。

5.1 顶层控制状态机

建议不是 3 态，而是 6 态。

1. bootstrapping

刚启动，设备链路与首个 progress 尚未稳定。
策略：

不允许强 hold

只允许轻 duck

等待首个可靠观测

2. guiding

开始带用户进入节奏。
策略：

更宽容

允许短暂无 progress

不急于判断停顿

3. following

已稳定跟踪。
策略：

正常 follow

轻量 hold/resume

可有限 seek

4. uncertain_follow

用户可能还在跟，但 tracking 不稳定。
策略：

减少强动作

降低 seek 频率

更依赖 signal quality 而非单帧位置

5. waiting

用户大概率停住。
策略：

hold

观察重新开口信号

降低 resume 门槛

6. reacquiring

已失锁，正在尝试重捕获。
策略：

暂停强控

等锚点或高质量 partial

若恢复则进 following

若长时间失败则降级

5.2 状态转移原则
bootstrapping → guiding

条件：

设备链路健康

有首个有效音频活动或首个可靠 ASR event

guiding → following

条件：

有连续 progress

tracking quality 达阈值

active speaking 持续一段时间

guiding/following → uncertain_follow

条件：

tracking quality 明显下降

candidate 波动大

但 signal 表明用户仍在说

following/uncertain_follow → waiting

条件：

播放明显 ahead

最近 progress stale

signal 不支持 active speaking

条件持续一定时间

waiting → following

条件：

新鲜 speaking 信号

或新 progress

或高质量重捕获

any → reacquiring

条件：

tracking mode = LOST

或连续失锁超过阈值

reacquiring → following

条件：

找回稳定锚点

连续若干帧一致

6. Tracking Engine 设计

这是你当前系统最需要升级的核心。

6.1 从“对齐器”变“跟踪器”

当前 aligner 更像：

给定一个 hypothesis，在窗口内找最优位置。

商用 tracking engine 应该是：

在已有历史位置、锚点、速度和观测质量的前提下，持续维护一个参考位置分布。

也就是说，核心不是“这一帧最像哪”，而是“这一帧在历史上下文里最可信的是哪”。

6.2 锚点机制

建议加入两类锚点。

强锚点

来自：

final

高置信稳定 partial

长度足够的局部稳定命中

句首/句末等结构性位置

弱锚点

来自：

短时间连续一致的 tail match

高 local_match_ratio 但未 final 的观测

作用：

平时用锚点限制漂移

失锁时用锚点重捕获

控制层可根据“距最近强锚点多远”调整动作强度

6.3 失锁检测

建议显式计算：

candidate jitter

backward suspicion

temporal inconsistency

anchor divergence

low-quality run length

然后综合成：

LOCKED

WEAK_LOCKED

REACQUIRING

LOST

不要让 controller 自己从零碎字段猜失锁。

7. Progress Estimator 设计
7.1 目标

它不是简单做 EMA，而是做“状态估计”：

保证单调

防止短时噪声跳变

允许短时平滑前滑

长时间无证据则停住

失锁时进入保守模式

7.2 推荐逻辑

估计值由 4 个因素共同决定：

当前 tracking candidate

最近 committed anchor

最近速度估计

tracking quality

高质量 locked

更相信 candidate

允许快速前进

weak_locked

更相信历史速度与 committed

减小跳变

reacquiring

暂时冻结或极慢推进

等新锚点

lost

不再驱动强控制

进入降级

8. 控制策略设计
8.1 动作分级，而不是只有硬控制

建议保留至少 4 档干预：

1. NOOP

不动作。

2. SOFT_DUCK

只降音量，给用户空间，但不断播。

3. HOLD

确实停下来等。

4. SEEK

重定位，只在高把握时用。

商用品质下，SOFT_DUCK 非常重要。
很多场景不需要立刻 hold，只要让参考音频退到“陪跑”即可。

8.2 控制动作的成本模型

每个动作都该有成本。

HOLD 的成本高

因为会打断节奏。
所以必须要求：

tracking 质量不低

用户大概率不在说

ahead 已明显持续

RESUME 的成本低

因为恢复播放即使错了，还能再次 hold。
所以在 waiting 状态下应更积极。

SEEK 的成本最高

因为一旦跳错，用户会完全失去上下文。
所以只在强锚点支持下触发。

8.3 推荐策略原则
原则 1

低质量观测下，减少强动作。

原则 2

waiting 态下，resume 要比 hold 时宽松。

原则 3

uncertain_follow 时优先 soft_duck，而不是 hold。

原则 4

reacquiring 时停止频繁 seek。

9. 启动与链路校准流程

商用系统的启动需要显式设计。

9.1 建议启动序列
Step 1

初始化 player、recorder、ASR，但还不进入强控制。

Step 2

收集 0.8~1.5 秒设备与信号信息：

噪声底

输入电平

device profile

asr readiness

Step 3

进入 bootstrapping：

播放开始

只允许 soft_duck

不允许 no-progress hold

Step 4

收到首个可靠 progress 后进入 guiding。

这样能避免你当前“播放一开，ASR 还没 ready 就被 hold”的问题。

10. 评测体系

没有这部分，商用化会失控。

10.1 离线回放框架必须支持

给定：

参考 lesson

用户录音

可选人工标注

输出：

per-tick progress

tracking mode

user state

control decisions

错误段落统计

10.2 指标定义
启动类

first_signal_active_time

first_asr_partial_time

first_reliable_progress_time

startup_false_hold_rate

跟踪类

tracking_locked_ratio

tracking_lost_events_per_min

reacquire_success_rate

mean_progress_lag_error

控制类

false_hold_rate

hold_recovery_latency_ms

resume_success_rate

wrong_seek_rate

soft_duck_usage_ratio

用户体验代理指标

continuous_follow_duration_sec

user_speaking_while_holding_ratio

assistive_vs_intrusive_action_ratio

11. Telemetry 设计

每次 session 至少记录：

device profile

runtime config

signal quality timeline

asr observation timeline

tracking mode timeline

progress estimate timeline

control decision timeline

playback generation events

final outcome summary

这样你才能知道：

哪个设备最容易失锁

哪种文本最容易误 hold

哪类用户最常重读

哪个版本把 resume 变差了

12. 产品化落地路线图
Phase 1：把底盘打稳，2~4 周

目标：从 demo 到稳定内测。

做这些：

增加 DeviceProfile

增加 SignalQuality

增加 TrackingMode

bootstrapping/guiding/waiting/reacquiring 状态机

soft_duck 动作

离线 replay logger

交付标准：

启动误 hold 显著下降

hold 后恢复更自然

失锁可见

Phase 2：tracking engine 升级，3~6 周

目标：长时间跟读不漂。

做这些：

anchor manager

loss detector

reacquirer

tracking quality

progress estimator 升级为状态估计器

交付标准：

长文本稳定性提升

失锁率下降

seek 更少但更准

Phase 3：设备与用户自适配，3~5 周

目标：跨设备一致性提升。

做这些：

设备 profile 分类参数

自动输入阈值估计

输出延迟校准

用户阅读速度 profile

交付标准：

蓝牙耳机与板载麦差距缩小

新用户开箱体验稳定

Phase 4：线上闭环，持续建设

目标：真正商用可迭代。

做这些：

配置版本化

指标 dashboard

失败聚类

A/B 能力

灰度策略

13. 你当前代码最优先要重构的地方

如果直接对照你现有工程，我建议优先做这几步：

第一步

把 SignalQuality 从 recorder 侧抽出来，进入 orchestrator 主循环。

现在 controller 几乎完全依赖 ASR/progress。
商用品质下必须有“独立 speaking 证据”。

第二步

给 IncrementalAligner 外面包一层 TrackingEngine，不要让 aligner 直接承担全部 tracking 语义。

第三步

把 MonotonicProgressEstimator 升级成吃三种输入：

tracking observation

tracking quality

signal quality

而不是只吃 align result。

第四步

controller 改吃：

ProgressEstimate

UserReadState

TrackingMode

SignalQuality

而不是只吃 progress。

14. 最终目标态

最终这个系统不应该表现得像：

一旦你慢了我就停，一旦我没看清我就乱猜。

而应该像：

我大致知道你在哪；看清时我帮你精确跟；看不清时我先宽容；你停了我等你；我丢了就重新找，不和你对抗。

这就是商用品质。

下一步最实用的是：我可以继续把这份蓝图收敛成一版**“工程任务拆解表”**，按模块列出要新增/重构的类、字段、函数和优先级。