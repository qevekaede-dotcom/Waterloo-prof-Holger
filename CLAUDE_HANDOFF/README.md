# 给 Claude 的接手入口

交接日期：2026-09-22。仓库：`qevekaede-dotcom/Waterloo-prof-Holger`。
科研工作检查点：`712602c9fb1b6d8414b9e5cc34256a3978d6f275`。
本交接包随用户明确授权的更新发布到 **main**；接手时先 fetch 并核对远端，不依赖本机旧分支。

## 用五分钟建立正确状态

1. 先检查当前目录、`git status --short --branch`、`git worktree list`、`git fetch origin`。保留所有未提交和 ignored 内容。
2. 读取根 [CLAUDE.md](../CLAUDE.md)、[AGENTS.md](../AGENTS.md)、[HANDOFF.md](../HANDOFF.md)，再读涉及材料/目录的 scoped `CLAUDE.md`。
3. 读本包的 [完成记录与科学状态](STATE_AND_HISTORY.md)，区分真实结果、保存审计、方案和模拟测试。
4. 从 [下一步任务卡](NEXT_ACTIONS.md) 选一个符合当前用户范围的任务。刚提出的“晶型核验＋电子再分析＋文献对照”**尚未开展**，不是 Roy 已选方向。
5. 需要定位/重现时用 [运行与文件索引](REPRODUCE.md)；核心工件的路径、角色和 SHA-256 在 [ARTIFACT_MANIFEST.json](ARTIFACT_MANIFEST.json)。

## 不可误读的五件事

- **三种材料都没有通过当前验收的 κL，也没有最终 zT。** 电子 first pass 完成不等于所有输运性质已经收敛。
- SrCu v2 只有准备工具；新运行凭据是独立 SYNTHETIC 原型，没有接入 QE/MPI/v2，`execution_provenance_verified=false` 仍然成立。
- SrZr 保存结果有显著虚频；原因尚未确定。不要直接宣布真实材料不稳定，也不要移除虚频来获得可用 κL。
- Rb 保存 HDF5 审计通过有限完整性检查，但四次 q 网格转换全部失败。本地没有被该审计引用的 FC2/FC3 本体，不能把历史路径当成现有文件。
- 9 月 21 日修订汇报已发送是**用户确认**；本阶段未独立读取已发送邮件，未记录 Roy 的后续方向回复。PPT、完整三材料写作稿和新交接包没有发邮件给任何人。

## 可以马上打开的成果

- [中文离线证据面板](../experiments/phonon_research_sandbox/dashboard/index.html)（clone 整个仓库后本地打开；GitHub 不执行该 HTML）
- [11 页全英文 PPT](../experiments/phonon_research_sandbox/presentation/output/Waterloo_Phonon_Research_Update.pptx)
- [中英对照讲稿](../experiments/phonon_research_sandbox/presentation/SPEAKER_SCRIPT_EN_ZH.md)、[12 个答辩问答](../experiments/phonon_research_sandbox/round2/REPORT_QA_EN_ZH.md)
- 三份方案：[SrCu](../experiments/phonon_research_sandbox/plans/SrCu2SnS4.md)、[SrZr](../experiments/phonon_research_sandbox/plans/SrZrS3.md)、[Rb](../experiments/phonon_research_sandbox/plans/Rb2Cu2SnS4.md)
- [两轮完整成果入口](../experiments/phonon_research_sandbox/README.md)、[追加式工作日志](../experiments/phonon_research_sandbox/WORKLOG.md)

## 用户授权与习惯

本次用户明确要求“写给 Claude 的交接包，然后 push 到 GitHub main”。它取代了先前对本轮成果“不要合并 main”的限制，**仅说明本次发布已获准**；不能据此推断未来任意 main 更新、超算作业或邮件也已授权。

后续科研默认保持本地准备、轻量分析、公开来源核对。不要提交/重跑/取消 Nibi 作业，不在本机运行重型 QE、FC2/FC3 拟合或 κL 求解，不做持续轮询，不发送邮件，不替 Roy 选择方向。需要新物理计算时，先做完整可审阅的方案，转去做其他独立工作。

保留所有原始输入/输出、历史结果、已发送正文和 `READY_TO_ATTACH/`。WORKLOG 只能追加。不得上传凭据、私人邮件地址、私有背景材料、QE scratch 或大型原始文件。普通可逆本地工作不必反复询问；科学模型/标准变化应先形成方案。

用户希望充分推进，但不要求耗尽额度。有限任务、适度并行、每项有交付物；复杂实现/结论由未参与实现的 Sol 独立审查。技能不可用时说明实际执行方式，不假称已调用。PPT 必须全英文；中文可以放在独立双语讲稿。对用户的解释以中文、具体文件和物理直觉为主。

## 可直接粘贴给 Claude

> 请接手 qevekaede-dotcom/Waterloo-prof-Holger。先检查 Git 状态和 worktree，fetch origin，以更新后的 main 为接手来源；不要覆盖本地未提交或 ignored 内容。读取 CLAUDE.md、AGENTS.md、HANDOFF.md 和 CLAUDE_HANDOFF/README.md，再按包内 STATE_AND_HISTORY、NEXT_ACTIONS、REPRODUCE 建立状态。先区分已完成、只做了方案/原型、尚未开展的工作。三种材料都没有验收 κL；Roy 下一步方向未记录。若继续本地研究，优先从 SrZrS3 晶型身份核验和公开数据对照开始，不把空间群相同当成晶型相同。不要启动超算计算、持续轮询或发送邮件。保留原始记录，追加工作日志，以实际证据和独立审查交付。

Git 发布依据和本包核对结果见 [INTEGRATION.md](INTEGRATION.md) 与 [REVIEW.md](REVIEW.md)。
