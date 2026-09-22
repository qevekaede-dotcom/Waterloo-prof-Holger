# 完成了什么，科研状态到哪里

本文件概括已有仓库记录和本次会话完成的两轮工作；不冒充当前 Nibi 状态。原始数字以链接文件为准，交接文字只是索引。

## 1. 进入这段工作以前

三材料的 QE → BoltzTraP2 电子 first pass 已完成并向 Roy 汇报。每种材料分别选取自己的数值参数，结果保存在材料 `results/`；PF/τ 不是绝对 PF，zTₑ 不是最终 zT，采样最优点不是连续最优点。dense-k 输运收敛和显式 SOC 仍未建立。

随后按 Roy/课题组方向开发 QE → 位移力 → FC2/FC3 → 声子 → κL 流程。历史作业、恢复链和保存审计在材料目录及 [归档 handoff](../docs/archive/HANDOFF_before_phonon_sandbox_2026-09-21.md) 中；归档内“运行中”等词属于当时快照，不是当前任务。

## 2. 三材料当前状态

| 材料 | 保存证据支持什么 | 尚未解决/不能声称什么 | 主证据 |
|---|---|---|---|
| SrCu₂SnS₄ | 有历史声子/κL first pass；原 YAML 使用 au，4.0 实际为 4 bohr≈2.1167 Å；纳入的 pair groups 仅零距离。v2 准备统一单位和输入设置。 | 历史输入混用、终态不健康、物理与张量收敛不足；没有修正后的真实 v2 force dataset/pristine/FC/κL。 | [历史限制说明](../thermo_candidates/SrCu2SnS4/CLAUDE.md)、[原 YAML](../thermo_candidates/SrCu2SnS4/phono3py/phono3py_disp.yaml)、[v2](../thermo_candidates/SrCu2SnS4/phono3py_v2/README.md) |
| SrZrS₃ | 保存记录包含 788 个力任务（含 pristine）及 FC2/FC3。最低采样频率 −1.0716026422440281 THz，q=(0,0.4,0)，12 个采样模低于 −0.1 THz。 | pristine 最大力 9.342e−5 Ry/bohr 超过首选 5e−5；历史例外不是新标准。虚频原因未确定，有限 κ 张量是拒收诊断。真实 q/参考胞/本征矢映射未完成。 | [审计 JSON](../thermo_candidates/SrZrS3/phono3py/evidence/first_pass_unconverged/force_audit_summary.json)、[原件哈希](../thermo_candidates/SrZrS3/phono3py/evidence/first_pass_unconverged/remote_artifact_sha256.txt) |
| Rb₂Cu₂SnS₄ | 保存 680-task force audit；FC2/FC3 通过有限文件完整性检查，存在五级 q 网格诊断记录。后处理包装器因 FC3 键名误判而失败，后续独立审计区分了作业失败与文件完整性。 | 四次网格转换均失败；无验收 κL。本地未重新打开远端 HDF5；当前文件存在性、物理收敛和可复用条件仍需各自证据。 | [保存的 HDF5 审计](../thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/production/postprocess_22312417_hdf5_readonly_audit_20260920.json)、[复用清单](../experiments/phonon_research_sandbox/analysis/rb_reuse/README.md) |

Rb 密度长度 45/60/75/90/105 Å 是 q 网格参数，不是 FC3 截断或超胞尺寸。HDF5 的 mesh 向量是 SNF 对角量，不是实际三轴网格矩阵。变化率使用 `|new-old|/|new|`；原有 Rb 判据是所有温度平均严格 <3%、各对角严格 <5%、两次连续转换通过。不能把此规则倒写成历史 SrCu 已采用的规则。

## 3. 首轮 sandbox（2026-09-21）

- Fetch 后从 `origin/codex/complete-three-material-phonons` 的 `cf21cce` 创建独立实验分支，未从落后的 main 开始。
- 整理三份可执行科研方案，包含最小 pilot、对照、门槛、依赖、资源估算依据与停止条件；新提议阈值明确为提议。
- 修复共享 QE parser：最终 PWSCF stdout 即使已出现力块和 JOB DONE，后续 fatal signature 仍应拒绝。
- 加强 v2：在写 pristine health 之前核对精确输入哈希/合同；记录并复核 `dataset_semantics.py` 哈希。明确输入完整性和外部日志健康不证明它们属于同一次执行。
- 统一当前状态入口，保留历史工作日志、原始记录和冻结附件；旧 handoff 原样归档。
- 制作中文离线 HTML 面板、105 行 Rb 全张量表和图、文件导读、11 页全英文 PPT、独立中英讲稿。
- 独立 Sol 提出并修正三点：冻结模需要 q 相容超胞；真实执行来源尚未证明；“两次连续通过”需要至少三个层级，单次比较仅 pilot。

验证历史：共享套件 435 项，主会话针对 parser/真实旧输出 13 项，v2 18 项；PPT 11 页全部渲染检查，非原生 PowerPoint UI 测试。详见 [首轮验证](../experiments/phonon_research_sandbox/VALIDATION.md) 与 [原审查](../experiments/phonon_research_sandbox/review/INDEPENDENT_SOL_REVIEW.md)。

## 4. 第二轮本地开发（2026-09-22）

| 工件 | 实际新增能力/认识 | 明确没有做到 |
|---|---|---|
| [运行凭据原型](../experiments/phonon_research_sandbox/tooling/execution_receipts/README.md) | 保存交给子进程 stdin 的精确字节、命令/目录/有限环境、退出码、输出摘要和独立 final anchor；11 项 SYNTHETIC 测试。 | 没有外部启动前承诺；不证明语义消费或全部依赖实际使用；没有 QE/MPI/v2 集成。 |
| [q/超胞检查](../experiments/phonon_research_sandbox/tooling/q_commensurability/README.md) | 明确定义列向量基，精确检验 Sᵀq∈Z³；支持非对角矩阵、负行列式与有理数；9 项测试和非原子相位示意。 | 不验证真实 q 基底/原子/本征矢，不生成冻结位移。100 原子只是 20 原子参考胞成立时的条件几何值。 |
| [Rb 复用清单](../experiments/phonon_research_sandbox/analysis/rb_reuse/README.md) | 本地 YAML、manifest、preflight 通过哈希绑定，支持保存的 3.70 Å/679 位移生成记录；区分记录值与本地文件。2 项回归测试。 | 文件名存在不能把 readiness 改成 true；没有当前远端 FC 核验。请求内存不是测得 RSS，无新 core-hour 预算。 |
| [分量判读图](../experiments/phonon_research_sandbox/analysis/rb_component_diagnostics/README.md) | 复算 48 项变化率、12 个整体判定；12 项 zz 全失败，但平均值有 6 项单独通过。 | 无外推、无“收敛值”、无物理误差条或已收敛各向异性结论。 |
| [重复来源候选](../experiments/phonon_research_sandbox/round2/duplicate_sources/README.md) | 680 个任务对应 606 个来源哈希：541 单条组、64 双条组、1 个 11 条组。该 11 条组在保存 YAML 中同原子两位移相消。 | 没比较原始力；其来源哈希不同于 pristine；不能自动去重、删除任务、复用力或保证节省。 |
| [12 个中英答辩问答](../experiments/phonon_research_sandbox/round2/REPORT_QA_EN_ZH.md) | 将关键问题与具体证据相连；更新面板导航。 | 未实际举行英文模拟组会；没有重做原 PPT。 |

第二轮新增 22 项定向测试通过；主会话还核对选定行为、源哈希、图表和 1440/390 px 面板。新的独立 Sol 对全部新增工件和重复来源候选给出 **SHIP，仅本地准备范围，零待修复问题**。[验证](../experiments/phonon_research_sandbox/round2/VALIDATION.md)／[审查](../experiments/phonon_research_sandbox/review/ROUND2_SOL_REVIEW.md)。没有重跑不变的 435 项套件来消耗额度。

## 5. 最近提出但没有执行的第三轮

用户询问剩余额度还能做什么。只做了短暂公开来源检索并提出：

1. SrZrS₃ 晶型身份核验和公开声子对照。
2. 已有三材料电子输运数据的公平比较和机制分析。
3. 直接服务研究选题的原始文献证据表。
4. 可选的真人参与英文模拟组会。

**没有开展这些分析，没有产生第三轮结构图/比较表/新结论，没有把它们加入 PPT。** 唯一新线索是 α、β-SrZrS₃ 均可为 Pnma，因此空间群不能单独识别晶型；目前未判定仓库属于哪一种，也没有据此判定虚频真假。具体来源和可开始任务见 [NEXT_ACTIONS](NEXT_ACTIONS.md)。

## 6. 提交与沟通时间线

| 提交/记录 | 内容 |
|---|---|
| `cf21cce` | sandbox 的远端科研基线；记录用户确认 Roy 修订汇报已发送 |
| `246037c` | 实验区、当前状态、旧 handoff 归档 |
| `25555c1` | 共享 QE parser 与 v2 输入/脚本完整性修复 |
| `a2bf49d` | 三份方案、证据面板、英文 PPT、执行来源限定 |
| `dfefd48` | 首轮导航、CSV LF 与交接完善 |
| `323ccc6` | 全温度 Rb 分量诊断、中英答辩问答 |
| `712602c` | 第二轮三工具、复用候选与独立审查，已推送实验分支 |
| 本交接提交 | 用户随后明确要求交接给 Claude 并发布到 main；以 Git log 和远端 main 确认提交号 |

前三步电子汇报、第四步 interim 邮件/附件属于冻结历史；后续完整三材料声子写作稿仍未发送。不要编辑已发送正文。具体沟通状态入口为 [CURRENT_STATE](../experiments/phonon_research_sandbox/CURRENT_STATE.md)。
