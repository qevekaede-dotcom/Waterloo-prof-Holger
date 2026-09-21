# 声子研究实验区 / Phonon research sandbox

本轮从远端 `codex/complete-three-material-phonons` 的 `cf21cce05c7107120a52ac2658f8dbe05bc0a864` 分出。分支：`codex/phonon-research-sandbox`。本轮只核对仓库保存证据，未查询 Nibi 当前状态。

**三种材料目前均无通过当前验收的 κL。** 已完成本地科学方案、轻量分析、工具改进、进度面板和科研汇报。待计算条目不是执行授权。

## 直接打开

- [中文离线进度与证据面板](dashboard/index.html)
- [全英文汇报 PPT（11 页）](presentation/output/Waterloo_Phonon_Research_Update.pptx)
- [中英对照讲稿](presentation/SPEAKER_SCRIPT_EN_ZH.md)
- [Rb 图表预览](presentation/output/Rb_Qmesh_Diagnostic_Preview.png)
- [第二轮成果：运行凭据、超胞几何、数据复用与答辩准备](round2/README.md)
- [Rb 全温度分量判读图](analysis/rb_component_diagnostics/rb_component_changes.png)
- [12 个汇报答辩问答（中英对照）](round2/REPORT_QA_EN_ZH.md)

## 研究与复现入口

- [当前状态与证据边界](CURRENT_STATE.md)
- 三份方案：[SrCu2SnS4 v2](plans/SrCu2SnS4.md)、[SrZrS3 虚频](plans/SrZrS3.md)、[Rb2Cu2SnS4 收敛](plans/Rb2Cu2SnS4.md)
- [Rb 全温度、全张量 CSV](results/rb_qmesh_ladder_all_tensors.csv)、[分析复现](analysis/README.md)
- [工具修复与尚未解决的执行来源问题](tooling/README.md)
- [QE 到 κL 的文件导读](LEARNING_GUIDE.md)
- [官方文档和原始论文索引](references/targeted_sources.md)
- [验证记录](VALIDATION.md)、[独立 Sol 审查及修正记录](review/INDEPENDENT_SOL_REVIEW.md)
- [追加 WORKLOG](WORKLOG.md)、[下次可直接继续的 HANDOFF](HANDOFF.md)

HTML 使用相对证据链接，保留整个仓库目录后直接打开即可。全部科研图表来自已有保存证据，没有 synthetic 科研数据、外推“收敛值”或新物理计算。Rb 变化分母是当前更密网格值。第二轮的运行凭据测试使用独立标注的 SYNTHETIC 程序，q 相位图只是数学示意；二者与科研数据分开。

## 分工和验收范围

Sol High 分别完成科学方案与工具修复；Terra Medium 完成面板和 Rb 分析；主代理集成、制作 PPT 和指南；未参与实现的新 Sol High 独立审查。三项审查发现均已按记录处理，交付仅限 **local plan/preparation**，不包含材料科学通过或运行授权。逐代理 token 数没有可核实统计，不声称精确使用账户额度。

第二轮新增独立运行凭据原型、精确有理数 q/超胞检查器和 Rb 复用清单，详情与本轮验证见 [round2](round2/README.md)。原型尚未接入 v2 或真实 QE/MPI；现有 v2 仍明确 `execution_provenance_verified=false`。接受真实 pristine/pilot 前仍须完成可信运行器的集成与审阅。

没有提交、重跑或取消 Nibi 作业，没有本地重型 QE/FC/κL 求解，没有发送邮件，没有更改 main、其他 worktree 未提交内容、原始记录或任何 `READY_TO_ATTACH/`。
