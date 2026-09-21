# Rb2Cu2SnS4 已保存数据复用清单（只读）

运行 `python3 build_inventory.py` 会由小型、本地提交的 JSON/YAML/文本记录重新生成
`rb_reuse_inventory.json` 与 `rb_reuse_decisions.csv`。脚本不读取 HDF5、不连接集群，也不拟合
力常数。它把“本地文件存在且 hash 可复核”与“2026-09-20 的只读远端审计曾报告该 hash”分开。

当前结论是 **false / no-production**：Rb 仍为 `first_pass_unconverged`，没有可接受的
κL。保存的五个 q-mesh HDF5 是拒收诊断；其数值或文件存在不能改变这一状态。

## 可复用边界

| 变化 | 结论 | 所需证据 |
|---|---|---|
| 只改 q 网格 | 条件式复用 FC2/FC3 | 一次受限远端核对确认 FC2/FC3 的 SHA-256、键/shape/dtype、18/72 atom binding、p2s_map、phono3py 版本与无 NAC。 |
| 同 M72 增大 FC3 cutoff | 目前不能证明子集复用 | 新 YAML 必须给出内容级旧到新 displacement/configuration 映射，并核对结构、输入、输出和力 hash；生成器可重编号，数字 ID 集合本身不能证明复用；新增 pair 必须新算。 |
| geometry、supercell、DFT/pseudo、位移幅度或 displacement 定义改变 | 构造上不兼容 | 新 pristine 与新 force dataset；旧数据只能作方法/对照证据。 |

生产 manifest 记录 680 个任务（1 pristine + 位移任务），每项为 72 atoms；全部记录为
100/800 Ry、2×2×2、`conv_thr=1e-10`、`nosym/noinv`。本地 YAML hash 与 manifest 的 dataset
hash 都是 `bb69732c8161dfe57d508777fa85209e6103a07c11df120cb0ac3cc01c02beda`；YAML 可直接给出
M72、位移向量的 0.03 Å 幅度与映射来源。`preflight/preflight_summary.json` 有唯一候选的
`phono3py_disp_sha256` 与此 YAML/manifest 完全相同；该保存的生成记录名为
`M72_cutoff_3p70A`，记录 `--cutoff-pair 6.991986661115` bohr（3.699999999999815 Å）和
679 个 displacement supercells。因此 3.70 Å 是由 YAML hash 绑定的**保存生成记录**，不只是
`campaign.json` 的计划候选；它仍不证明当前远端 FC/FORCES 字节存在、FC 物理收敛或 κL 已验收。
manifest 中的赝势 SHA-256 也只是记录值；本轮没有本地赝势字节可重新 hash。

`pilot/sacct.txt` 有七条真实 pilot 调度记录（19m30s–1h54m02s）。该存档没有字段头；它的
十列布局与当前工作流所记录的 sacct 列一致，只是少了插在 `ReqMem` 和 `NodeList` 之间的
`MaxRSS`，故 JSON 将 32/62.50G 标为**推断的** `AllocCPUS`/`ReqMem`，不是测得的 `MaxRSS`。
结果 JSON 保留逐条数值，但明确其只适用于该小样本，绝不预测后续
cutoff、supercell 或生产 core-hours。

## 一次未来的最小远端请求（尚未执行）

仅对历史 M72 目录读取并 hash：`fc2.hdf5`、`fc3.hdf5`、`phono3py_disp.yaml` 与 production
manifest；同时只读取 FC 元数据并与 JSON 比较。这是 q-mesh-only 的最小检查，不需要重读
`FORCES_FC3` 或五个诊断 `kappa-*.hdf5`。如需重建力 provenance 或保存档案证据，可另选 hash。
若讨论较大 cutoff，则另做 count-only YAML 与**内容级**旧到新 displacement/configuration 映射及
hash 核对；生成器可重编号，数字 ID 集合相同不能证明复用。缺一项就报告“subset 未证明”，不得
把零填充或历史路径当作数据。
