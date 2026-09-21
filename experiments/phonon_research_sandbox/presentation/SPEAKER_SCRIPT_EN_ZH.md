# Research update: bilingual speaker script

All slide content and embedded speaker notes are English. Chinese appears only in this companion file.

## 1. Thermoelectric sulfides

**EN**
I have completed the three electronic first passes and tested the phonon workflow. The present milestone is a traceable research record and a focused plan for the remaining scientific questions. None of the three materials currently has an accepted lattice thermal conductivity under our current criteria. This update uses saved repository evidence, not a current cluster check.

**中文**
我已完成三种材料的电子输运 first pass，并开展了声子流程。当前成果是可追溯的科研记录和针对剩余科学问题的计划。按照目前标准，三种材料都还没有验收后的晶格热导率。本汇报基于仓库保存证据，不是实时超算检查。

Sources: `experiments/phonon_research_sandbox/CURRENT_STATE.md`

## 2. Electronic workflow completed

**EN**
Each material used its own convergence workflow before the electronic transport first pass. This existing SrCu2SnS4 plot compares the Quantum ESPRESSO density of states with the BoltzTraP2 interpolation. It supports a workflow comparison but does not by itself establish convergence of every transport property. The calculations use PBE without explicit spin–orbit coupling.

**中文**
每种材料都独立进行了收敛工作后再进入电子输运初算。此图是已有的 SrCu2SnS4 QE 态密度与 BoltzTraP2 插值比较，它支持流程比较，但不能单独证明所有输运性质都已收敛。电子计算采用 PBE，未加入显式自旋轨道耦合。

Sources: `thermo_candidates/SrCu2SnS4/results/dos_qe_vs_boltztrap2.png`, `thermo_candidates/SrCu2SnS4/results/workflow_summary.md`, `thermo_candidates/SrZrS3/results/workflow_summary.md`, `thermo_candidates/Rb2Cu2SnS4/results/workflow_summary.md`

## 3. Electronic screening at 300 K

**EN**
The bars are the best power-factor-over-relaxation-time values selected independently for each carrier sign on the sampled 300 K grid. Rb2Cu2SnS4 has the largest p-type value among these first passes. This does not establish the best final thermoelectric material, because relaxation time and accepted lattice thermal conductivity remain missing. SrZrS3 carrier preference depends on the metric and temperature, so I do not assign one universal doping preference.

**中文**
柱状图对应 300 K 采样载流子浓度网格中，两种载流子分别选出的最佳 PF/τ。Rb2Cu2SnS4 的 p 型数值在这三种初算里最大，但弛豫时间和验收晶格热导率仍然缺失，不能据此判断最终热电性能。SrZrS3 的载流子偏好取决于指标和温度，不能简单给它贴上统一标签。

Sources: `thermo_candidates/SrCu2SnS4/results/transport_best_power_factor.csv`, `thermo_candidates/SrZrS3/results/transport_best_power_factor.csv`, `thermo_candidates/Rb2Cu2SnS4/results/transport_best_power_factor.csv`

## 4. Phonon evidence and acceptance

**EN**
The table separates artifact creation from scientific acceptance. SrCu2SnS4 preserves a historical campaign with known problems, while its corrected workflow remains preparation only. SrZrS3 produced force constants but failed a sampled-frequency gate. Rb2Cu2SnS4 has a saved artifact audit with limited integrity checks, but all tested mesh transitions fail the convergence rule. For the latter two, this update reads the saved audit records rather than revalidating the remote HDF5 files.

**中文**
这个表格把生成文件和科学验收分开。SrCu2SnS4 保留有问题的历史计算，修正流程仍只是准备。SrZrS3 已生成力常数，但没有通过采样频率检查。Rb2Cu2SnS4 的保存审计通过了有限完整性检查，却没有通过任何一次网格转换的收敛检查。这次读取的是已保存审计，并没有重新核验远端 HDF5。

Sources: `thermo_candidates/SrZrS3/phono3py/evidence/first_pass_unconverged/force_audit_summary.json`, `thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/production/postprocess_22312417_hdf5_readonly_audit_20260920.json`, `thermo_candidates/SrCu2SnS4/phono3py_v2/campaign.json`, `fourth step result (phono3py lattice thermal conductivity)/README.md`

## 5. SrCu2SnS4: a separate corrected campaign

**EN**
The historical Quantum ESPRESSO interface interpreted the pair cutoff in bohr. The value four therefore meant about 2.12 angstrom, and the included pair groups were onsite only. The new preparation explicitly converts four angstrom to about 7.5589 bohr and requests uniform force settings. These software corrections do not demonstrate a converged force dataset. The old raw outputs and sent attachments remain unchanged.

**中文**
历史 QE 接口的成对位移截断单位是 bohr，因此数值 4 实际只有约 2.12 埃，包含的 pair groups 仅限 onsite。新的准备流程显式换算 4 埃为约 7.5589 bohr，并要求统一力计算设置。修正代码不能证明力数据已收敛。旧输出和已发送附件全部保留。

Sources: `thermo_candidates/SrCu2SnS4/phono3py_v2/campaign.json`, `thermo_candidates/SrCu2SnS4/phono3py/phono3py_disp.yaml`, `fourth step result (phono3py lattice thermal conductivity)/README.md`

## 6. SrCu2SnS4 v2: minimal proposed pilot

**EN**
I propose beginning with a healthy independent pristine calculation and a small set of repeated single and pair displacement controls. The detailed plan defines how to distinguish numerical noise from incremental force signal and when to stop. Amplitude and force-setting sensitivity should inform any larger production campaign. The exact displacement count and cost require real generation and measured timing. No new campaign has been submitted.

**中文**
建议先做健康的独立 pristine SCF，再选少量单、双位移做重复对照。详细计划规定了如何区分数值噪声和增量力信号，以及何时停止。位移幅度和力设置敏感性应决定是否扩展。实际位移数量与费用需要真实生成和计时，目前没有提交新计算。

Sources: `thermo_candidates/SrCu2SnS4/phono3py_v2/campaign.json`, `experiments/phonon_research_sandbox/plans/`

## 7. SrZrS3: imaginary-mode origin is unresolved

**EN**
The saved first-pass audit reports a minimum frequency of minus 1.0716 terahertz at the stated q point. Twelve sampled modes are below minus 0.1 terahertz. The pristine residual force exceeded the preferred threshold, and a historical exception allowed a diagnostic continuation. Residual forces, force convergence and finite-range effects deserve targeted controls before a physical instability interpretation. Eigenvectors and structural response would help distinguish competing explanations. Simply removing imaginary modes would not validate thermal conductivity.

**中文**
保存审计给出的最低频率为 −1.0716 THz，12 个采样模式低于 −0.1 THz。pristine 残余力高于首选门槛，当时以例外继续了诊断计算。在解释成物理不稳定前，应通过最小对照区分残余力、力收敛和有限作用范围等因素，并结合本征矢及结构响应。不能靠直接删除虚频来得到有效热导率。

Sources: `thermo_candidates/SrZrS3/phono3py/evidence/first_pass_unconverged/force_audit_summary.json`, `experiments/phonon_research_sandbox/plans/`

## 8. Rb2Cu2SnS4: direction-dependent mesh response

**EN**
This figure replots the conventional Cartesian tensor components recorded in the September 20 audit. The horizontal axis is the phono3py q-mesh density length, not a real-space cutoff or a supercell size. The zz component changes substantially across the ladder, while yy is comparatively less sensitive. All values are rejected first-pass diagnostics. I have neither fitted an asymptote nor estimated a supposedly converged thermal conductivity.

**中文**
图中重新绘制了 9 月 20 日保存审计里的常规笛卡尔张量分量。横轴是 phono3py 的 q 网格密度长度参数，不是实空间截断或超胞尺寸。zz 随网格变化明显，yy 相对较不敏感。图中所有点都只是未验收的初算诊断，没有外推收敛值。

Sources: `thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/production/postprocess_22312417_hdf5_readonly_audit_20260920.json`

## 9. Rb2Cu2SnS4: the final step still fails

**EN**
I recalculated these changes using the same denominator as the implemented gate: the denser mesh result. At 300 kelvin, the average changes by about 4.266 percent and the largest diagonal by about 10.192 percent. Both fail. The same conclusion holds at 600 and 900 kelvin, and no earlier transition passes. A denser mesh could reuse the force constants only for the same underlying force model with retained provenance. It would still not establish supercell, cutoff or amplitude convergence.

**中文**
变化率采用与现有代码一致的分母，即更密一级网格值。在 300 K，平均值变化约 4.266%，最大对角分量约 10.192%，两项都失败；600 和 900 K 也一样。更密网格只能在保留来源、保持相同力模型的前提下复用力常数，它不能解决超胞、截断和幅度收敛。

Sources: `thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/production/postprocess_22312417_hdf5_readonly_audit_20260920.json`, `thermo_candidates/Rb2Cu2SnS4/phono3py/run_postprocess_firstpass.py`

## 10. Proposed next research choices

**EN**
These are alternatives for discussion, not a decision made on behalf of Roy. For SrCu2SnS4, the benefit is a clean corrected baseline. For SrZrS3, the key benefit is understanding a failure mechanism. For Rb2Cu2SnS4, existing force data may support a bounded convergence study, but provenance and force-model limitations must remain explicit. I will estimate resource use from actual task counts and measured timing before asking to expand any route.

**中文**
这些是讨论选项，并没有替 Roy 做决定。SrCu2SnS4 的收益是建立干净的修正基线；SrZrS3 的收益是理解失败机理；Rb2Cu2SnS4 的现有力数据可能支持小范围收敛研究，但必须明确来源和力模型局限。扩展前应依据真实任务数量与计时估算资源。

Sources: `experiments/phonon_research_sandbox/plans/`, `experiments/phonon_research_sandbox/CURRENT_STATE.md`

## 11. Discussion with Roy

**EN**
I have sent the revised status update and am awaiting guidance on the next priority. I would appreciate guidance on whether to prioritize the corrected SrCu2SnS4 baseline, diagnose SrZrS3, or continue a bounded Rb2Cu2SnS4 convergence study. The accompanying plans and local evidence dashboard make these options reviewable. No new cluster calculation or email was initiated during this preparation round.

**中文**
我已发送修订后的阶段汇报，目前还在等待下一步方向。希望 Roy 指导优先开展 SrCu2SnS4 修正基线、SrZrS3 虚频诊断，还是有明确边界的 Rb2Cu2SnS4 收敛研究。配套计划和本地证据面板便于审阅。本轮准备没有发起新的超算计算或邮件。

Sources: `experiments/phonon_research_sandbox/CURRENT_STATE.md`
