落地建议：0 真实数据时的上线策略
第一阶段

正式链路：

规则 matcher

规则 behavior

规则 fusion

规则 controller

并行 shadow：

model behavior

model fusion

model action

但 shadow 只写日志，不生效。

第二阶段

把 model behavior 接成正式 side signal
因为它风险最低、收益最大。

第三阶段

把 model fusion 接成正式 side signal
用于改进：

should_prevent_hold

should_prevent_seek

fused_confidence

第四阶段

在有少量真实数据后，再考虑让 model action 参与决策，且必须：

只影响软分数

不直接绕过规则护栏

最终结论

在 0 真实数据 前提下，我建议你这样定：

坚持纯规则：

state_machine_controller.py

tracking_engine.py / incremental_aligner.py

ASR gate / silence reset / bootstrap

最终 seek/hold/resume 下发链

先做 shadow model：

audio_behavior_classifier.py

evidence_fuser.py

live_audio_matcher.py 的 rerank / calibration 部分

action_model 仅 shadow，不接管

一句话说就是：

先让模型看、让模型打分、让模型提建议；先不要让模型按按钮。

如果你要，我下一条可以直接给你一张非常具体的表：
按文件列出“正式规则版 / shadow model / 未来可接管”的三级改造清单。