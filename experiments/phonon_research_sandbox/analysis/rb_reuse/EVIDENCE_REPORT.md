# Rb2Cu2SnS4 复用证据短报

生成物：`rb_reuse_inventory.json`（可机器核查）与 `rb_reuse_decisions.csv`（三种变更的转移决定）。
脚本只读取本地小文件；没有重读 `FORCES_FC3`、没有读 HDF5、没有远端检查。

| 证据层级 | 可确认内容 | 不能据此确认 |
|---|---|---|
| 本地 manifest + YAML + preflight summary | `phono3py_disp.yaml` 的 SHA-256 为 `bb6973…2beda`，与 production manifest 一致，也唯一匹配 preflight 的 `M72_cutoff_3p70A`。后者记录 `--cutoff-pair 6.991986661115` bohr（3.699999999999815 Å）、679 个 displacement supercells；manifest 有 680 个任务（含 pristine）、72 atoms、18 primitive atoms、606 个 source-structure hash、680 个 force-input hash；设置为 100/800 Ry、2×2×2、`conv_thr=1e-10`、`nosym/noinv`。 | 原始 force/FC bytes 本地存在或仍可读取，或已物理收敛。 |
| 2026-09-20 保存的远端只读 HDF5 审计 | FC2 `08def0…d3867`，shape `(72,72,3,3)`，key `force_constants`；FC3 `b35e40…063d2`，shape `(72,72,72,3,3,3)`，key `fc3`；二者记录为 finite、float64、phono3py 4.4.0，且 p2s map 为 0,4,…,68。 | 今天的远端文件仍存在，或 FC 已物理收敛。 |
| 保存的五级 q-mesh 审计 | 45→60、60→75、75→90、90→105 Å 四个相邻跃迁都未通过；105 Å 只是 rejected diagnostic。 | κL 已经完成或可接受。 |
| pilot `sacct.txt` | 七项 M72 pilot 的真实用时为 19m30s–1h54m02s。原文件无 header；按当前工作流中相同顺序、但多一个 `MaxRSS` 的 schema 推断，32/62.50G 为 `AllocCPUS`/`ReqMem`，没有可用的测得 `MaxRSS` 字段。 | cutoff、M108/M216 或完整生产的运行时/核心小时。 |

因此，**仅改 q 网格**的最窄复用路径是：先在一次受限的只读远端检查中核对 FC2/FC3/YAML/manifest 的存在性与 SHA-256，并只读取 FC 的元数据。`FORCES_FC3` 的 lineage hash 与五个诊断 kappa HDF5 的档案核对都是可选项，不是该复用前提。通过才可以把相同 FC 对用于新的 q-mesh 诊断；仍不能把结果标为已收敛。

**改大 cutoff** 不能从“已有 3.70 Å 数据”直接推出复用。必须先有新的 count-only YAML 与内容级旧到新 displacement/configuration 映射，并核对输入、结构、输出和力 hash；生成器可重编号，所以数字 ID 不能单独证明对应。新增 pair 必须产生新力。**几何、超胞、DFT/赝势、位移幅度或位移定义改变**时，旧力在定义上不兼容，必须有新 pristine 和新数据集。
