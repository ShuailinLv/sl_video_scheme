一、最终方案定位

这套系统应定义为：

一个在 Windows 域完成需求理解、脚本编译、外部素材整理、ElevenLabs 语音与音频规划，在 Linux 域完成首帧锚点、视频生成、后处理、成片合成与交付归档的跨域视频生产平台。

它支持四类项目输入：

一类是纯文本输入
二类是文本加图片参考
三类是文本加视频参考
四类是文本加混合素材输入，也就是一部分镜头生成，一部分镜头直接采用现成视频素材

最终目标不是“能生成视频”，而是：

能把一句话、一段话或完整剧本稳定转成可交付视频
能导入外部参考并显著提高效果上限
能用 ElevenLabs 输出可消费的语音时间线
能给出结构化配乐建议，并允许你后续替换成任何现成音乐
能只改配乐、只改字幕、只换外部素材而不重跑整条视频生成链
能长期接入新模型，不推翻主架构
能完全通过 Python 自动化执行，而不是依赖人工点 ComfyUI

二、顶层设计原则

原则一：创意、视觉、时间线、执行四类真值分离

A 模块定义创意和镜头意图真值
C 模块定义视觉锚点和一致性真值
B 模块定义语音、字幕、音效、配乐规划和时间线真值
E 模块定义执行真值和交付真值

原则二：外部素材不是附件，而是一等输入

图片、视频、已有音频、已有配乐、品牌素材、产品图、真人照片、B-roll、动作模板视频，都必须被结构化导入，而不是只放在附件目录里。

原则三：跨域协作只靠 package

Windows 域和 Linux 域之间不依赖任何在线共享状态，一切协作都通过 package 导入导出完成。

原则四：模型治理必须包化，执行必须租约化

模型、权重、工作流、运行时、环境、健康检查、适配器必须进入 model bundle。
业务执行前必须申请 lease，不能看到模型目录就直接跑。

原则五：执行必须阶段化

统一走：

preview
lock
final
enhancement
composition

而不是一步终渲染。

原则六：音频和音乐必须独立可替换

换配音、换字幕、换音效、换配乐，不应默认触发整条视频重渲染。
音频和音乐应该有独立 package 和独立 composition-only 重跑机制。

原则七：Python 自动化优先

所有执行默认通过 Python adapter 调用模型、CLI 或本地服务。
ComfyUI 仅允许作为可选的无头 backend，不允许要求人工打开页面操作。

三、可独立开发的模块

下面这些模块都可以独立开发、独立测试、独立部署、独立回放。

一共七个业务模块，加一个只读共享契约层。

一号模块：director-agent-service

部署位置：Windows 域

职责：
把一句话、一段话、完整剧本，转成导演可看、机器可跑、可 diff、可修订的项目脚本定义。

输入：
用户原始输入
输入模式 prompt / brief / screenplay
参考资料
历史修订信息
人工约束
品牌或交付要求

输出：
script_package

核心产物：
creative_brief.json
screenplay.md
render_script.json
shot_graph.json
story_bible.json
style_bible.json
camera_bible.json
delivery_profile.json
risk_tiers.json
render_ladder.json

禁止职责：
不生成语音文件
不生成首帧
不生成视频
不控制 GPU
不安装模型
不感知服务器 worker

独立开发边界：
只要 shared_contracts 稳定，A 可以完全独立开发和单测。
它不依赖任何视频模型，可以先用固定输出做空跑。

二号模块：reference-media-ingest-service

部署位置：Windows 域

职责：
把外部图片、视频、音频、品牌素材、配乐素材、现有 B-roll 统一导入、分析、分类、打标签、做质量检查，并输出标准引用包。

输入：
外部图片
外部视频
外部音频
现成配乐
品牌素材
产品素材
用户上传素材

输出：
reference_media_package

核心产物：
reference_index.json
usage_contracts.json
quality_report.json
provenance.json
license_manifest.json
extracted_keyframes/
motion_templates/
insertable_clips/
style_refs/
audio_refs/

支持的使用模式：
hard_reference：强参考，尽量严格贴近
soft_reference：软参考，只借鉴风格或构图
motion_template：动作或运镜模板
direct_insert：可直接上时间线的现成镜头

禁止职责：
不改脚本
不改镜头规划
不做视频生成
不做最终封装

独立开发边界：
它本质上是素材治理模块，不依赖视频生成。
可以最早开发，并先服务 A/B 两个模块。

三号模块：audio-music-timeline-service

部署位置：Windows 域

职责：
基于 ElevenLabs 生成语音、对话、时间戳、字幕草稿、音效计划、配乐策略和可选临时配乐，形成项目级音频时间线真值。

输入：
voiceover_plan
对白文本
旁白文本
已有录音
参考音色
delivery_profile
可选音乐参考
可选外部配乐素材

输出：
audio_music_package

核心产物：
voice_manifest.json
utterance_timing.json
word_timing.json
timeline_track.json
draft.srt
music_strategy.json
cue_sheet.json
music_search_queries.md
selected_music_refs.json
sfx_plan.json
ambience_plan.json
temp_score/
voice_tracks/
sfx_tracks/
music_tracks/

推荐用法：
草稿迭代阶段优先用 Eleven Flash 或 Turbo，正式长旁白优先 Multilingual v2，情感表演对白优先 Eleven v3，已有录音或人工录音则走 Scribe / alignment 路线拿词级时间戳。官方文档和模型总览都支持这类使用方式。

禁止职责：
不改写导演脚本
不决定镜头切法
不控制视频模型
不负责视频封装

独立开发边界：
B 可以完全独立于视频生成开发。
即便 Linux 侧模型都还没接好，B 也可以先完整输出音频和时间线包。

四号模块：keyframe-and-visual-bible-service

部署位置：Linux 服务器域

职责：
把脚本和外部参考转成项目级视觉锚点、首帧资产和视觉记忆层。

输入：
script_package
reference_media_package
人工覆盖记录

输出：
keyframe_asset_package

核心产物：
visual_bible.json
asset_manifest.json
asset_registry.json
asset_lineage.json
consistency_binding.json
candidate_scores.json
locked_assets.json
identity_anchors/
scene_anchors/
prop_anchors/
shot_keyframes/

visual_bible 至少包含：
identity canon
scene canon
cinematography canon
style canon

禁止职责：
不改写故事意图
不改镜头语法
不做视频封装
不做全局模型路由

独立开发边界：
C 可在没有 D 的情况下先开发完。
只要给它固定 script_package 和 reference_media_package，它就能独立产出首帧和视觉锚点包。

五号模块：video-production-orchestrator

部署位置：Linux 服务器域

职责：
根据脚本、音频时间线、外部素材和视觉锚点，完成预览、主渲染、后处理、合成和交付。

输入：
script_package
reference_media_package
audio_music_package
keyframe_asset_package
capability_view
lease_token
manual overrides

输出：
video_delivery_package
必要时 revision_request_package

内部必须再拆成两层：

D1：Execution Planner
负责 preflight、policy route、pass planning、retry planning、degrade boundary check、composition planning

D2：Execution Runtime
负责真正拿租约、驱动执行、落缓存、收结果、触发 QC、输出交付包

执行阶段固定为：
preview pass
asset lock / timing lock / route lock
final render pass
enhancement pass
composition pass
delivery export

禁止职责：
不改创意真值
不改身份锚点定义
不安装模型
不改 registry
不解释桥接语义

独立开发边界：
D 依赖包契约和 E 的租约接口，但仍可用 mock adapter 独立开发。
首期甚至可以先只做黑帧、占位视频、composition 骨架。

六号模块：offline-model-runtime-control-plane

部署位置：Linux 服务器域

职责：
管理离线模型包、运行环境、workflow、worker、GPU 和租约。

输入：
model_bundle_package
runtime specs
capability query
lease request
healthcheck request
bundle import / revoke / deprecate

输出：
available_model_view
health report
worker state
lease_token

北向接口必须极少：
capability query
lease request
health report
import bundle
revoke / deprecate bundle

运行时类型建议统一成四类：
native_python_runtime
diffusers_runtime
repo_cli_runtime
headless_comfy_runtime

ComfyUI 只允许出现在第四类 runtime 里，而且只能通过本地 API、无头方式被 Python 调用；官方文档明确支持本地 API 和无头调用，但也同时支持 API Nodes 连接外部服务，所以离线域必须做 node allowlist，默认禁用所有需要外部 API 的节点。

独立开发边界：
E 完全可以独立开发。
它不关心业务镜头语义，只关心模型能否运行、资源是否可租约化。

七号模块：package-exchange-bridge

部署位置：Windows 域和 Linux 域各有一套

职责：
完成跨域 package 的导入、导出、签名校验、哈希校验、原子落位、逻辑 URI 映射、隔离审计。

输入：
package manifest
payload
import / export request

输出：
ready package
import receipt
export receipt
quarantine report
local mapping record

桥接必须遵守：
先 payload 后 manifest
staging 不可见
验签通过后再 ready
ready 只靠原子 rename 暴露
下游只消费 ready
只做可信导入导出，不做业务解释

独立开发边界：
G 是纯基础设施模块，可和业务模块并行开发。

八号共享层：shared_contracts

这是只读宪法层，不是业务模块。

只允许放：
package schema
protocol definition
error envelope
core state machines
id rules
timebase protocol
trace protocol
logical URI protocol
lease protocol
schema version rules
compatibility rules

不允许放：
业务实现
模型 adapter
工具函数
service 代码

四、外部资源支持的正式方案

这次优化里，外部资源必须成为一等能力。

支持导入的资源类型包括：

人物照片
品牌 KV
产品图
包装图
logo
场景参考图
风格参考图
首帧种子图
动作模板视频
镜头语言参考视频
现成 B-roll
现成广告镜头
已有旁白
已有录音
音乐参考
最终要入片的现成配乐

每个外部资源必须被结构化定义，而不是只做文件挂载。

每个资源至少要有这些字段：

media_id
media_type
usage_mode
authority_level
provenance
license_scope
allowed_transformations
quality_score
related_scene_ids
related_shot_ids
primary_subjects
asset_hash

外部图片的主要价值是：

提升人物或产品一致性
锁定服装、场景、空间关系
提升首帧锚点质量
减少 prompt 碰运气

外部视频的主要价值是：

可以作为动作模板
可以作为运镜模板
可以作为直插镜头
可以作为序列节奏参考

最重要的一条是：

外部视频不一定要“再生成一遍”，而是允许 direct_insert。
如果某段现成素材足够好，系统应直接走稳像、裁切、调色、变速、字幕挂载和合成，而不是强行重生成。

五、音频、字幕、配乐、音效的完整方案

这版方案里，B 模块已经不再是单纯的“语音生成服务”，而是项目级音频中枢。

它负责四层内容：

第一层，语音层

负责：
旁白
对白
多角色对话
草稿语音
正式成片语音
已有录音对齐

第二层，时间线层

负责：
句级时间戳
词级时间戳
字幕草稿
对白卡点
镜头时长约束
口型同步预留

第三层，音效层

负责：
转场 whoosh
hit
braam
环境底噪
雨声
风声
街道 ambience
Foley 建议
可选 ElevenLabs Sound Effects 生成

第四层，配乐层

负责：
music_strategy
cue_sheet
music_search_queries
selected_music_refs
可选 temp score
可选 final score

你特别关心“系统是否考虑配乐”，答案是：这版里已经正式考虑，而且不是附属品。

系统会默认输出两类配乐产物。

第一类是配乐建议：

music_strategy.json
里面写清楚整片要什么功能的音乐，比如：
主叙事推动
情绪垫底
节奏驱动
温暖品牌感
科技感
悬疑感
广告感

它还会给出：
情绪词
BPM 区间
配器建议
是否人声
是否电子元素
是否 cinematic rise
是否需要 silence window
是否需要 ending resolve

第二类是检索建议：

music_search_queries.md

这份文件是给你后面去找现成音乐用的。
系统会把每个段落拆成可搜索的关键词组，例如：

warm cinematic piano inspirational 92 bpm no vocal
uplifting tech corporate minimal synth 110 bpm clean drop
tension build trailer hybrid pulse 100 bpm no choir

这样你后面找现成音乐就不是拍脑袋找，而是按镜头结构和节奏点找。

如果你愿意，也可以让 B 模块调用 Eleven Music 生成临时配乐或最终配乐。ElevenLabs 官方文档已经提供了 composition plan 和 music create 的接口说明，所以这部分是可接的；但我建议在首版里把它定义成 optional，而不是主依赖。

六、纯 Python 自动化执行方案

你的要求是不要手动用 ComfyUI，这里我直接给出明确结论：

主执行链必须统一成 Python orchestration，不允许“人工打开 ComfyUI 点工作流”进入正式生产链。

推荐执行优先级如下：

第一优先级：原生 Python adapter
第二优先级：Diffusers adapter
第三优先级：官方 repo CLI / Python adapter
第四优先级：Headless ComfyUI adapter

也就是说，ComfyUI 若存在，只是 E 模块控制下的一种 runtime type。
它不能成为人工操作入口，只能成为 Python 自动提交 workflow 的 backend。

统一要求每个 runtime adapter 都实现以下接口：

prepare()
validate_inputs()
submit_job()
poll_job()
collect_outputs()
cancel_job()
cleanup()
healthcheck()

Headless ComfyUI adapter 的工作方式是：

Python 启动本地 ComfyUI 服务
Python 生成或加载 workflow JSON
Python 通过本地 API 提交任务
Python 轮询执行状态
Python 拉取输出文件
Python 把结果写回标准 package

这样对业务模块来说，它和 native python runtime 没区别。

七、模型与显卡资源约束下的最佳路由

这是这版方案里最需要现实化的部分。

你有 2×4090，真正可持续的策略一定是：

小模型做 preview
中等模型做主线
重模型只打 hero shot
外部素材能直插的尽量直插
音频和音乐永远从视频重渲染里解耦

基于你当前模型和官方信息，我建议这样定。

首帧与视觉锚点默认路线：

FLUX.1-dev
它负责角色、产品、场景、关键 pose 的首帧锚点和 hero asset，不负责全片视频。

预览默认路线：

CogVideoX-5B-I2V
Wan2.2-TI2V-5B
LTX-Video 13B Distilled

这样做的原因是，CogVideoX 公开可用的 5B I2V 线已经成熟，而且 1.5-5B-I2V 官方文档也给出了较低的单卡显存下限；这类路线非常适合做 preview、试镜头和低成本语义验证。

主成片默认路线：

HunyuanVideo-1.5

原因是官方把它明确定位为 8.3B、consumer-grade GPU 可推理、同时覆盖 T2V/I2V，比原始 HunyuanVideo 和 HunyuanVideo-I2V 更适合作为 2×4090 的生产主干。

高风险 I2V 路线：

HunyuanVideo-I2V
但必须降级成“可选、受限、非默认”路线。

原因很简单：官方 README 给出的 720p batch1 峰值显存约 60GB，这和 24GB 单卡差距太大，所以它不适合作为你当前机器的默认量产路线。它可以保留为特殊镜头、实验路线或后续优化验证路线，但不能写进默认主路由。

Hero-shot 可选路线：

Wan2.2-I2V-A14B
Wan2.2-Animate-14B

它们的定位应是：

少量关键镜头
模板动作镜头
角色替换镜头
强表演镜头

不应成为默认全片主线。

官方 Wan2.2 集合中已经覆盖 TI2V-5B、I2V-A14B、Animate-14B，所以这套池化路由是成立的；但从工程角度，14B 路线只应进入低并发 hero-shot 队列，而不是日常大规模镜头主线。

后处理路线：

RIFE 主用
AMT 回退
Real-ESRGAN 主用
AnimeVideo-v3 用于动漫风或强二次元风格

八、执行全流程

第一步，Windows 域接收输入

输入可以是：
一句话
一段话
完整剧本
外部图片
外部视频
已有旁白
已有音乐
品牌素材
产品素材

第二步，A 编译脚本真值

输出：
screenplay.md
render_script.json
shot_graph.json
story_bible.json
style_bible.json
camera_bible.json
delivery_profile.json
risk_tiers.json

第三步，B2 reference-media-ingest-service 导入外部素材

输出：
reference_media_package

第四步，C audio-music-timeline-service 调 ElevenLabs

输出：
旁白
对白
句级时间戳
词级时间戳
字幕草稿
音效计划
配乐策略
检索建议
可选临时配乐
audio_music_package

第五步，G package-exchange-bridge 导出 package 到 Linux 域

输出：
script_package
reference_media_package
audio_music_package

第六步，Linux 域导入 package

遵守 staging、校验、ready 规则。

第七步，D keyframe-and-visual-bible-service 生成视觉锚点

输出：
keyframe_asset_package

第八步，E video-production-orchestrator 先做 preview

这一步只验证：
镜头是否可执行
动作是否成立
运镜是否成立
节奏是否成立
这个镜头值不值得上贵路线

第九步，锁三件事

asset lock
timing lock
route lock

第十步，final render

按镜头重要性和类型走不同路线。

第十一步，enhancement

插帧
超分
稳像
统一编码
统一画幅
统一色彩

第十二步，composition

把生成镜头、直插镜头、旁白、对白、字幕、音效、临时配乐、最终配乐全部挂到统一时间线。

这一步是系统里最关键的一步之一，因为你后面换配乐、换 B-roll、换字幕，都应该优先走 composition-only 重跑，而不是回去重渲染镜头。

第十三步，delivery

输出：
video_delivery_package

九、Package 体系

这版正式定义七类 package。

script_package

作用：
导演与机器可执行脚本真值包

主要内容：
creative_brief
screenplay
render_script
shot_graph
story_bible
style_bible
camera_bible
delivery_profile
risk_tiers
render_ladder

reference_media_package

作用：
外部素材导入包

主要内容：
reference_index
usage_contracts
provenance
license_manifest
quality_report
extracted_keyframes
motion_templates
insertable_clips
style_refs
audio_refs

audio_music_package

作用：
音频、字幕、音效、配乐规划与可选音乐资产包

主要内容：
voice_manifest
utterance_timing
word_timing
timeline_track
draft.srt
music_strategy
cue_sheet
music_search_queries
selected_music_refs
sfx_plan
ambience_plan
temp_score
music_tracks

keyframe_asset_package

作用：
首帧与视觉锚点包

主要内容：
visual_bible
asset_manifest
asset_registry
asset_lineage
consistency_binding
candidate_scores
locked_assets
identity_anchors
scene_anchors
shot_keyframes

video_delivery_package

作用：
成片交付与审计包

主要内容：
timeline_composition
qc_report
model_usage_summary
provenance_report
retry_report
project_summary
final_video
shot_videos
audio
subtitles
stems

revision_request_package

作用：
不可恢复业务错误回流包

主要内容：
revision_request
minimal_change_plan
reproducibility_bundle
failure_evidence

model_bundle_package

作用：
离线模型运行治理包

主要内容：
model_registry_entry
runtime_spec
healthcheck_spec
workflow_templates
node_allowlist
env_lock
license_manifest
provenance
weights
adapters
tokenizer
vae

十、状态、缓存与局部重跑

系统必须支持三类最常见的局部重跑：

第一类，只改音频和音乐

比如：
换旁白
换字幕
换音效
换配乐
换网上找来的现成音乐

这类修改只更新 audio_music_package，然后只 rerun composition。

第二类，只改外部素材

比如：
换参考图
换 B-roll
换品牌素材
换现成镜头

如果镜头只是直插或只影响合成，则只 rerun composition。
如果改变了首帧或视觉锚点，则 rerun C 和依赖的少量镜头。

第三类，改脚本和镜头意图

这才进入 revision flow，重新编译脚本和重跑相关镜头。

缓存必须分成两类：

可复用缓存：
首帧候选
锁定锚点
preview 视频
final render
enhancement 输出
composition 中间件

证据缓存：
失败 preview
QC 截图
错误日志
debug 对比图
side-by-side 对比视频

十一、人工干预

必须保留人工干预，但必须结构化。

统一定义 ManualOperationRecord，至少包含：

operator_id
action_type
action_scope
target_object_id
reason_code
free_text_reason
before_snapshot_hash
after_snapshot_hash
trace_id
created_at
expires_at

常见人工动作包括：

锁首帧
替换参考图
强制指定模型
禁止自动降级
强制某镜头人工复核
批准交付规格降级
替换最终配乐
强制 composition-only 重跑

十二、推荐目录组织

Windows 域建议组织为：

director-agent-service/
reference-media-ingest-service/
audio-music-timeline-service/
package-exchange-bridge/
shared_contracts/
common/

Linux 域建议组织为：

keyframe-and-visual-bible-service/
video-production-orchestrator/
offline-model-runtime-control-plane/
package-exchange-bridge/
shared_contracts/
common/

shared_contracts 推荐子目录：

core/package_envelope/
core/ids/
core/trace/
core/timebase/
core/logical_uri/
core/lease/
core/error_envelope/
core/state_machine_core/
evolving/render_policy/
evolving/qc_policy/
evolving/candidate_scoring/
evolving/revision_feedback/
evolving/delivery_profile/
evolving/manual_operation/

十三、开发顺序

第一阶段，先冻结核心宪法

优先冻结：
package envelope
project object model
timebase protocol
logical URI protocol
lease protocol
trace protocol
error envelope
core state machine

第二阶段，先做空跑骨架

A 输出固定 script_package
B2 输出固定 reference_media_package
C 输出固定 audio_music_package
D 输出固定 keyframe_asset_package
E 输出固定黑帧或占位视频 delivery package
F 跑通原子导入导出
G 输出固定 capability view 和 lease token

第三阶段，先把上游做稳

优先完成：
A
reference-media-ingest-service
audio-music-timeline-service

因为这三块决定系统的创意真值、素材真值、音频真值。

第四阶段，再做模型治理和 Python adapter

优先完成：
model_bundle_package
runtime_adapter_protocol
native python runtime
repo cli runtime
diffusers runtime
headless comfy runtime

第五阶段，再做首帧和视频生成

先把 preview 跑通，再做 final，再做 enhancement，再做 composition。

第六阶段，最后补高级能力

sequence-level QC
revision intelligence
复杂自动降级
高级配乐自动生成

十四、最终结论

这版优化后的最终方案，可以概括成一句话：

它不再是“文本到视频”的单链路系统，而是“脚本、外部素材、语音时间线、视觉锚点、分阶段生成、音乐与合成分层可替换”的生产平台。

它最核心的升级有五点：

第一，外部图片、视频、音频、现成配乐被正式纳入一等输入
第二，ElevenLabs 被正式提升为音频与时间线中枢，而不只是 TTS 插件
第三，配乐被拆成“建议层 + 检索层 + 可选生成层 + 可替换成片层”
第四，ComfyUI 不再需要人工操作，只保留为可选的 headless Python backend
第五，考虑到 2×4090 的限制，主渲染路线改成“5B 预览 + HunyuanVideo-1.5 主干 + 14B hero-shot 队列 + composition-only 局部重跑”的现实最优解

如果你现在就要进入落地，我建议最先定义并写死的六个文件是：

project_object_model.json
reference_media_package.schema.json
audio_music_package.schema.json
runtime_adapter_protocol.md
timebase_protocol.md
composition_rerun_protocol.md

这六个文件定稳了，后面再接模型和服务，系统才不会退化成“一堆脚本拼调用”。