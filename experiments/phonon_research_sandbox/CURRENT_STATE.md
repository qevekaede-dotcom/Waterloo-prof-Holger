# 当前科研状态与证据边界

仓库核对日期：2026-09-21。基线：`cf21cce`，本轮工作分支：`codex/phonon-research-sandbox`。
**本页不是实时超算监控。** 本轮没有登录 Nibi，状态来自已提交的日志、审计 JSON、CSV 和代码。

2026-09-22 本地扩展见 [第二轮入口](round2/README.md)：新增运行凭据原型、
q/超胞相容检查和 Rb 数据复用清单。没有新增材料计算，所以下表科学状态不变。
运行凭据原型未接入 v2，现有真实执行来源仍未验证。

## 可以确认到哪一步

| 材料 | 已有成果 | 未通过或未验证 | 当前允许的表述 |
|---|---|---|---|
| SrCu2SnS4 | 电子 first pass；历史声子与 κL 记录；v2 准备脚本 | 历史 4 bohr 非 4 Å、混合设置、终态不健康、张量网格未收敛；v2 无真实计算证据 | 跑通过历史流程，发现科学限制，正在准备独立修正方案 |
| SrZrS3 | 788 个力任务记录（含 pristine）；FC2/FC3 数组；有限诊断张量 | pristine 首选残余力门槛失败；采样虚频约 −1.0716 THz；κL 拒收 | 产生了可诊断的声子结果，虚频来源未确定 |
| Rb2Cu2SnS4 | 保存证据记录力恢复；FC2/FC3 和五级网格文件有限审计通过 | 所有四次相邻网格转换失败；力常数物理收敛未建立 | 已有可复用候选力数据和诊断网格，尚无验收 κL |

三种材料均不能用于最终 zT。电子表中的 PF/τ 不是绝对功率因子；zTₑ 使用电子热导，且仍需 τ 模型与验收后的 κL。PBE 电子 first pass 未含显式 SOC，采样最优点不是连续最优点，dense-k 输运性质收敛仍需检查。

## 证据索引（以内容为准）

1. **电子结果是已有派生表，本轮未重算。** 每个材料的 `results/workflow_summary.md`、`transport_best_power_factor.csv` 对应已保存 QE/BoltzTraP2 记录。可读入口：
   [SrCu2SnS4](../../thermo_candidates/SrCu2SnS4/results/workflow_summary.md)、
   [SrZrS3](../../thermo_candidates/SrZrS3/results/workflow_summary.md)、
   [Rb2Cu2SnS4](../../thermo_candidates/Rb2Cu2SnS4/results/workflow_summary.md)。
2. **SrCu2SnS4 历史限制：**
   [修正说明](../../fourth%20step%20result%20%28phono3py%20lattice%20thermal%20conductivity%29/README.md)、
   [原位移 YAML](../../thermo_candidates/SrCu2SnS4/phono3py/phono3py_disp.yaml)、
   [v2 配置](../../thermo_candidates/SrCu2SnS4/phono3py_v2/campaign.json)、
   [v2 说明](../../thermo_candidates/SrCu2SnS4/phono3py_v2/README.md)。
   正确换算 4 Å ≈ 7.5589045 bohr 是输入修正，不是计算结果正确的证据。
   v2 目前只分别检查输入字节与外部提供的输出健康；还没有受信任执行记录证明输出确由该输入产生。真实 pristine/pilot 前须补齐执行来源记录，不能把本地 preflight 当作运行来源验收。
3. **SrZrS3：**
   [力和声子审计 JSON](../../thermo_candidates/SrZrS3/phono3py/evidence/first_pass_unconverged/force_audit_summary.json)、
   [原文件哈希清单](../../thermo_candidates/SrZrS3/phono3py/evidence/first_pass_unconverged/remote_artifact_sha256.txt)、
   [被拒收的数值诊断 CSV](../../thermo_candidates/SrZrS3/phono3py/evidence/first_pass_unconverged/kappa_m1253_rejected_diagnostic.csv)。
   保存审计给出最低频率 −1.0716026422440281 THz，q=(0,0.4,0)，12 个采样模式低于 −0.1 THz。pristine 最大力 9.342e−5 Ry/bohr 高于 5e−5 首选门槛，历史例外不改变该门槛。
4. **Rb2Cu2SnS4：**
   [2026-09-20 只读保存文件审计](../../thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/production/postprocess_22312417_hdf5_readonly_audit_20260920.json)、
   [失败证据](../../thermo_candidates/Rb2Cu2SnS4/phono3py/evidence/firstpass_20260914/production/postprocess_22312417_failure_evidence_20260920.txt)。
   该 JSON 记录原 HDF5 的哈希、形状、有限值和采样频率检查；本轮读取 JSON，**没有重新审计远端 HDF5 字节**。最终作业失败源于 FC3 键名检查，不能把作业成功与文件可用性混为一谈。
   90→105 Å 网格密度长度的 trace/3 相对变化约 4.27%、4.08%、4.05%，最大对角分量变化约 10.19%、9.69%、9.59%（300、600、900 K）。平均值变化小不能替代逐分量收敛。这些 Å 是网格密度参数，非晶胞尺寸或 FC3 截断。

## 沟通状态与依赖

- 前三步电子汇报已发送；第四步 SrCu2SnS4 interim 邮件与两附件是冻结记录。
- 用户在 2026-09-21 确认发送修订阶段汇报。仓库有经过审阅的正文来源，本轮未独立取回已发送邮件，不能证明实际发送内容逐字相同。
- Roy 的研究方向回复未记录。选择 SrCu2SnS4 v2、SrZrS3 虚频诊断或 Rb 收敛路线应由讨论决定，本轮只提供可审阅的选项。
- 完整三材料声子报告仍是未发送草稿。面板/PPT 是本轮新汇报材料，未发送，不属于 `READY_TO_ATTACH/`。

后续依赖：科学方向选择与单独执行授权 → 实际环境/证据复核 → 最小 pilot → 依据结果决定扩展或停止。不能把本轮脚本测试通过写成材料已收敛。

## 历史文字冲突的处理

本轮改正根 `CLAUDE.md`、`README_START_HERE.md`、`README.md` 和 `thermo_candidates/Roy_task_status.md` 中仍称“待运行”“DONE”或 `main` 是当前基线的状态文字。原 HANDOFF 已[完整归档](../../docs/archive/HANDOFF_before_phonon_sandbox_2026-09-21.md)。历史日志、原始输入输出、历史结果、已发送正文和 `READY_TO_ATTACH/` 全部保留。

历史档案里的 RUNNING、pending、旧单位和“已完成”是当时的记录，不能覆盖本页的限定解释。没有通过删除不利证据来清理状态。
