# 定向来源与证据索引

本页只记录三份研究方案实际使用的外部来源和本仓库机器可读证据。外部资料用于说明方法与设计选择，不能替代本材料自己的收敛测试。访问日期均为 2026-09-21。

## 外部原始文献与官方文档

| 来源 | 直接链接 | 本计划采用的支持范围 |
| --- | --- | --- |
| Togo, *First-principles Phonon Calculations with Phonopy and Phono3py*, JPSJ 92, 012001 (2023) | https://doi.org/10.7566/JPSJ.92.012001 | 有限位移法以超胞中的 DFT 力反演力常数；有限超胞会截断/周期复制响应，必须按研究目的检查超胞收敛；离子晶体的长程极化作用可能超过超胞尺度。该文不提供本项目材料的收敛数值。 |
| Togo, Chaput & Tanaka, *Distributions of phonon lifetimes in Brillouin zones*, PRB 91, 094306 (2015) | https://doi.org/10.1103/PhysRevB.91.094306 | phono3py 三声子散射与晶格热导方法的理论来源；支持把 RTA κL 视为依赖 FC2、FC3 和布里渊区采样的计算量。 |
| phono3py 官方：cutoff pair-distance | https://phonopy.github.io/phono3py/cutoff-pair.html | `--cutoff-pair` 通过省略远距离双位移降低成本，但会牺牲 FC3 精度；因此截断半径必须做性质相关的收敛检查。 |
| phono3py 官方 API：不同 FC2/FC3 超胞 | https://phonopy.github.io/phono3py/phono3py-api.html#use-of-different-supercell-dimensions-for-2nd-and-3rd-order-fcs | FC2 与 FC3 可以使用不同超胞；这支持在 SrZrS3 中先用较大、较便宜的 FC2 超胞判断虚频，再决定是否承担 FC3 成本。 |
| phono3py 官方：倒空间网格 | https://phonopy.github.io/phono3py/phono3py-api.html#regular-grid-for-q-point-sampling | q 点通常使用 Γ 中心规则网格；网格只是对既定力常数的积分采样。它不能修复上游超胞、位移振幅或 FC3 截断误差。 |
| phonopy 官方 QE 接口：NAC | https://phonopy.github.io/phonopy/qe.html#non-analytical-term-correction-optional | 非解析修正（NAC）需要 Born 有效电荷和介电张量，可由 QE `ph.x` 的 DFPT 响应得到。缺少这些量时只能明确报告 no-NAC。 |
| Quantum ESPRESSO 官方 `pw.x` 输入说明 | https://www.quantum-espresso.org/Doc/INPUT_PW.html | `conv_thr` 是自洽能量误差阈值且具有广延性；`nosym` 会关闭电荷密度/布里渊区对称约化，`noinv` 关闭 k 与 -k 等价。支持所有 pristine/位移输入保持相同标志与设置。 |
| NIMS MDR：SrZrS3 / Pnma / mp-558760 声子数据 | https://mdr.nims.go.jp/datasets/847c52e8-791c-4534-a273-d0890e06145b | 同一 Materials Project 标识与空间群的独立 VASP/phonopy 数据集，可作结构、路径和模态的外部对照。其方法、赝势、结构与本项目不同，不能直接裁决本项目虚频真假。 |

## 本仓库直接证据

### SrCu2SnS4

- `thermo_candidates/SrCu2SnS4/phono3py/phono3py_disp.yaml`：`physical_unit.length: au`，历史矩阵 2×2×1、位移 0.06 bohr；原始 YAML 有 24 个 `included: true` 的 pair group，均对应零 pair distance，最近被排除的非零距离约 4.33833 bohr。由此可直接判断历史 `--cutoff-pair 4.0` 是 4 bohr，而非 4 Å。
- `thermo_candidates/SrCu2SnS4/phono3py/campaign_log.csv`：保存的代表性力计算计时只有 benchmark/k 点/低 cutoff 三项（4982、3074、2521 s）；不能据此给出完整 v2 总 core-hour 预算。
- `thermo_candidates/SrCu2SnS4/results/kappa_L_first_pass.csv` 与 `kappa_L_summary.md`：历史 13×13×6、no-NAC、RTA 数值是保留记录，不是当前验收下的收敛 κL。
- `thermo_candidates/SrCu2SnS4/phono3py_v2/campaign.json`、`README.md`、`WORKLOG.md` 与 `scripts/`：v2 是 no-submit 本地准备边界，统一 90/720 Ry、3×3×3、`conv_thr=1d-09`、`nosym/noinv`，将 4.0 Å 转为 7.5589045 bohr，并绑定生成器、赝势、数据集、输入和 pristine 健康证据。

### SrZrS3

- `thermo_candidates/SrZrS3/phono3py/evidence/first_pass_unconverged/force_audit_summary.json`：788 个 array row 完成；FC2/FC3 形状和有限值检查通过；pristine 最大分量 9.342e-5 Ry/bohr，高于已有首选门槛 5e-5，但低于一次性 1e-4 例外上限。
- 同一 JSON 的 `transport`：显式 no-NAC、12×5×3 网格，最低频率 -1.0716026422440281 THz，q=[0,0.4,0]，12 个采样模低于 -0.1 THz；因此 κL 诊断被拒绝，未继续更密 q 网格。
- `thermo_candidates/SrZrS3/phono3py/evidence/first_pass_unconverged/README.md`：说明 2×1×1、40 原子、3.5541348625 Å FC3 截断、0.03 Å 位移、80/640 Ry、3×3×3 力 k 网格均未获物理收敛证明。
- `thermo_candidates/SrZrS3/phono3py/campaign.json`：已有候选矩阵、0.02/0.03/0.04 Å 振幅 pilot、FC2-only 5×2×1 和 4×2×2 候选以及资源估算公式；这些是既有计划参数，不是已通过的结果。

### Rb2Cu2SnS4

- `thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/production/postprocess_22312417_evidence_summary_20260920.json`：恢复任务 22312416 完成；包装器 22312417 因把 `fc3.hdf5` 键误认成 `force_constants` 而失败。保存的完整 680-task force audit 通过，FC2、FC3 和五个 κ HDF5 已存在，但没有合格 summary/CSV。
- `thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/production/postprocess_22312417_hdf5_readonly_audit_20260920.json`：FC2 `(72,72,3,3)` 与 FC3 `(72,72,72,3,3,3)` 的形状、映射、有限值、版本和原子绑定通过；GRG 的 length-like 参数 45→60、60→75、75→90、90→105 Å 每一步都未通过现有门槛。最终一步各温度 trace/3 变化约 4.27%、4.08%、4.05%，最大对角分量变化约 10.19%、9.69%、9.59%。这些 Å 数值不是三个方向的整数 q-mesh。
- `thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/preflight/preflight_summary.json`：现有数据集是 72 原子 M72、3.70 Å、0.03 Å，共 679 个位移超胞；同一 M72 的 4.25 Å 和 5.00 Å 候选分别需要 1343 和 1811 个位移超胞，已有 3.70 Å 力不能补出新增 pair。
- `thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/pilot/pilot_audit.json`：七任务 pilot 的重复噪声、2×2×2→3×3×3 力差、80/640→100/800 Ry 力差通过当时既有门槛；这只是少量 probe 的力设置检查，不是振幅、超胞或 FC3 截断收敛。
- `thermo_candidates/Rb2Cu2SnS4/phono3py/campaign.json`：当前总 core-hour 批准预算为 null；未来预算只能用实测 P90 walltime、MPI ranks 和剩余任务数计算，不能从任务数臆造。

## 解释边界

- 外部文献给出方法依据，不给出本材料的接受阈值。
- Rb/SrZr 后处理代码中的 q 网格规则以当前（较密）网格值为分母，要求逐温度 trace 变化严格 `<3%`、最大对角分量严格 `<5%` 且连续两步通过；-0.1 THz 是另一个已有项目 gate。SrCu 历史运行只有平均量检查，新计划若采用上述张量规则属于移植的提议判据。它们都不是普适物理常数。
- 方案中新出现的差值阈值或决策规则全部标为**提议判据**，必须先经 Roy/课题组确认；本轮没有超算执行授权。
