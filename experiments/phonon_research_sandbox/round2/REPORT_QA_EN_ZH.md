# Research update — discussion practice / 汇报答辩准备

Companion to the [11-slide English deck](../presentation/output/Waterloo_Phonon_Research_Update.pptx). English answers use a modest first-person student voice. Chinese notes explain the reasoning. This is an unsent practice document; questions are anticipated, not quotations from Roy or Holger.

## 1. What have you actually completed?

**EN — short answer:** I have completed electronic first passes for all three materials and produced or audited the available phonon workflow evidence. The useful outcome is a reproducible record of what worked, what failed and what needs a targeted control. I do not yet have an accepted lattice thermal conductivity for any of the three materials.

**中文：** 已完成的是电子初算与声子流程的计算/审计工作，不是三种材料的最终热导。可以展示真实图表、失败原因和下一步判别实验，不必把“有成果”等同于“κL 已验收”。

Evidence: [current state](../CURRENT_STATE.md), [electronic comparison](../../../learning/05_comparing_materials.md).

## 2. Why can you not report the final zT from the existing electronic tables?

**EN:** The electronic tables report quantities such as PF/τ and electronic-only zT. A final zT requires the lattice contribution and an explicit treatment of the electronic relaxation time. The existing band calculations also remain first passes: dense-k transport convergence and explicit SOC have not been established.

**中文：** 标量或指定方向上 `zT = S²σT/(κe+κL)`。把 `σ/τ` 和 `κe/τ` 乘上同一 τ 后，电子项中的 τ 可相消；一旦分母加入 κL，它就不能这样直接消掉。因此不能把电子表中的 zTₑ 改个名字当完整 zT。张量情况下还须明确方向和输运定义。

Evidence: [standing scientific rules](../../../CLAUDE.md), [file-anchored guide](../LEARNING_GUIDE.md).

## 3. What exactly was wrong with the SrCu2SnS4 cutoff?

**EN:** The historical QE interface used bohr for that cutoff. Four meant approximately 2.12 angstrom, rather than four angstrom. The saved displacement dataset includes only zero-distance pair groups. The corrected preparation converts four angstrom explicitly, but I still need fresh force data and cutoff controls to determine the numerical effect.

**中文：** 不能说“把单位修好，热导就会是多少”，也不能根据原结果偏小就认定单位错误解释了全部差异。输入定义错误是已证实事实，误差大小仍需对照。

Evidence: [SrCu plan and YAML evidence](../plans/SrCu2SnS4.md), [original YAML](../../../thermo_candidates/SrCu2SnS4/phono3py/phono3py_disp.yaml).

## 4. Is the corrected v2 calculation ready for production?

**EN:** No. The input preparation is more consistent, but there is no corrected production force dataset yet. The existing audit checks input integrity and supplied-log health separately. The new standalone receipt prototype is a local development step, not a validated QE runner or a production release.

**中文：** “脚本测试通过”“真实运行有来源”“力足够精确”“材料结果收敛”是不同问题。新原型用 SYNTHETIC 程序演示输入与输出记录，不会把 v2 的 execution provenance 状态改成 true。

Evidence: [v2 limitations](../../../thermo_candidates/SrCu2SnS4/phono3py_v2/README.md), [receipt prototype](../tooling/execution_receipts/README.md).

## 5. Does the imaginary frequency prove SrZrS3 is unstable?

**EN:** It shows a problem in the current harmonic calculation, but it does not yet establish an instability of the real material. The reference residual force exceeds our preferred threshold, and the force-constant range and force settings need controls. I would first check whether the same mode persists after those numerical and structural tests.

**中文：** 负频率是软件常用来表示负的频率平方本征值的记号，不是原子以“负次数”振动。它提示当前近似势能面存在负曲率；数值误差、参考结构和真实软模都可能参与。有限温度相稳定性还不是 0 K 谐波计算能单独决定的问题。

Evidence: [saved SrZr audit](../../../thermo_candidates/SrZrS3/phono3py/evidence/first_pass_unconverged/force_audit_summary.json), [SrZr diagnostic plan](../plans/SrZrS3.md). Method: [phonopy dynamical matrix formulation](https://phonopy.github.io/phonopy/formulation.html#dynamical-matrix), accessed 2026-09-22.

## 6. Why does the q=(0, 0.4, 0) mode need special care in a frozen-mode test?

**EN:** A real periodic distortion must fit the chosen supercell. In the same direct and reciprocal basis, its phase must repeat across every supercell translation. For q=(0, 2/5, 0), a diagonal construction therefore needs a b repeat divisible by five. That condition alone does not verify our archived q basis or eigenvectors, so the 100-atom example remains conditional.

**中文：** 在 `exp(2πi q·T)` 约定下要求 `q·T` 为整数。用于插值得到声子频率的 FC2 超胞，和用于实际冻结某个 q 模的超胞，不承担同一个任务。不能因为 2×1×1 不容纳这个冻结模，就断言它不能插值该 q；也不能直接用插值超胞做不相容冻结位移。

Evidence: [geometry helper and conventions](../tooling/q_commensurability/README.md), [SrZr plan](../plans/SrZrS3.md).

## 7. Why not simply remove the imaginary frequencies or enforce a sum rule?

**EN:** A sum-rule treatment is a useful numerical diagnostic, and I would compare its effect explicitly. It does not by itself explain a substantial non-Gamma imaginary mode. Removing or ignoring that mode just to obtain a finite conductivity would leave the underlying physical question unresolved.

**中文：** 要保留修正前后对照及修正幅度。当前显著负模在非 Γ 点，不能把“结果变成有限数值”当作稳定性证据。任何物理模型改变先作为方案讨论，不能为了通过门槛临时改变标准。

Evidence: [SrZr plan and stop conditions](../plans/SrZrS3.md).

## 8. Why is Rb not converged when some average changes are below 3%?

**EN:** The average is only one part of the existing criterion. At all three saved temperatures, the zz component fails every tested transition. Some average changes are small because component changes cancel or are diluted. I need the average and every diagonal component to pass together at all temperatures, with two consecutive passing steps.

**中文：** 本轮新增图将 48 个变化率放在一起。45→60 的平均含正负抵消；75→90 的平均则受较小的 xx/yy 变化稀释。两者均不足以说明张量收敛。

Evidence: [all-temperature component diagnostics](../analysis/rb_component_diagnostics/README.md), [implemented Rb criterion](../../../thermo_candidates/Rb2Cu2SnS4/phono3py/run_postprocess_firstpass.py).

## 9. Can you reuse the existing Rb force calculations?

**EN:** For another q-mesh diagnostic using exactly the same force model, the saved FC2 and FC3 are candidates for reuse after their identity and metadata are checked. The local repository contains audit records, not those FC files themselves. A larger cutoff needs an exact displacement correspondence and new forces for additional configurations. A changed structure, supercell or force-calculation definition requires new data.

**中文：** “复用”必须说清复用哪一层：只改 q 网格可复用相同 FC；扩大截断不能从旧数据补出新增双位移的力；改结构或超胞则响应本身改变。编号相同也不能替代位移内容、原子顺序与输入哈希对应。

Evidence: [Rb reuse inventory](../analysis/rb_reuse/README.md), [Rb plan](../plans/Rb2Cu2SnS4.md).

## 10. Can you estimate the converged value by extrapolation?

**EN:** I would not present an extrapolation as a converged result. The saved ladder does not yet satisfy the component criteria, and the force-model convergence is still unresolved. I can show the observed trends and changes, but I do not have evidence for a reliable asymptotic model or a total physical error bar.

**中文：** 拟合曲线“很顺”不能替代收敛；q 网格变化也不是 cutoff、超胞、振幅、NAC 或模型误差的总和。已有图只展示真实保存点和相邻变化。

Evidence: [Rb plan](../plans/Rb2Cu2SnS4.md), [diagnostic source data](../results/rb_qmesh_ladder_all_tensors.csv).

## 11. Why not spend the remaining computing resources on all three routes now?

**EN:** The three routes answer different questions. I would appreciate guidance on which has the highest scientific priority. Before expanding it, I would obtain actual task counts and representative timings, then use a bounded pilot to determine whether a larger calculation is justified. The existing scripts and small-sample timings do not establish a production budget.

**中文：** 账户推理额度不是超算核心小时；本地工具开发也不会自动获得 Nibi 作业授权。先明确想区分什么解释，再用少量有对照的计算换取答案。

Evidence: [three proposals](../README.md), [resource formula and null production budget](../../../thermo_candidates/Rb2Cu2SnS4/phono3py/campaign.json).

## 12. What would make the next round a successful research result?

**EN:** A successful next step would resolve a specific uncertainty: a clean corrected SrCu baseline, a controlled explanation of the SrZr mode, or a defensible convergence decision for Rb. A well-documented failure or a decision to stop can still be useful if it rules out an explanation. I would report the evidence and its limits before claiming an accepted conductivity.

**中文：** 成功不等于三种材料都得到小而漂亮的 κL。能证明某种解释不成立、知道何时停止，或避免重复错误，都能减少下一轮无效计算。

Evidence: [current state](../CURRENT_STATE.md), [SrCu](../plans/SrCu2SnS4.md), [SrZr](../plans/SrZrS3.md), [Rb](../plans/Rb2Cu2SnS4.md).

## A short practice routine / 练习方式

1. Give the 30-second answer in English without reading the Chinese note.
2. Open one linked evidence file and point to the exact quantity or limitation.
3. If pressed beyond the evidence, use: “I have not established that yet. The control I would use is …”.

This document does not introduce a new result or record an actual supervisor response. Its scientific claims must remain consistent with the linked plans and evidence.
