# 工具修复与验证

本轮只修复可由代码和回归测试直接证明的软件缺陷。没有改变物理阈值、
模型、超胞、位移幅度、pair cutoff、q 网格或任何既有科研结果，也没有运行
QE、phono3py 后处理、SSH 或 Slurm。

## 已修复

1. **QE stdout 的失败状态漏检。** 共享 `qe_output.py` 原先只在
   `inspect_force_run()` 的组合检查中扫描一般失败标志；直接调用
   `inspect_output()` 的验收路径可能把“完整力块 + `JOB DONE` + 随后的
   `MPI_ABORT`”判为健康。现在失败标志在最后一个 PWSCF run 的 stdout
   检查中统一拒绝，stderr 仍由 `inspect_force_run()` 单独检查。
2. **v2 pristine 审计写入过早。** `audit_pristine_v2.py` 原先验证外部保存的
   manifest digest，却没有在写入不可变 health 证据前确认当前
   `forces/pristine/scf.in` 仍与 manifest 中的输入 digest 一致。被改动或替换的
   pristine 输入可能先生成 `healthy=true` 记录，再到 preflight 才失败。现在
   审计在任何 health 写入前检查 manifest 文档类型、pristine digest、非符号
   链接普通文件和 96 原子契约。
3. **数据集语义验证器未纳入生成谱系。** `prepare_v2.py` 会导入
   `dataset_semantics.py`，但原 manifest 只记录 preparer 本身。现在 manifest
   记录验证器 SHA-256，`preflight_v2.py` 在重放语义检查前要求该 digest 与
   当前验证器完全一致。

## 尚未建立：输入到执行的 provenance

当前 pristine audit 同时保存两类事实：已审阅 manifest 所绑定的 `scf.in`
hash，以及调用者提供的 stdout、stderr、exit-code 的终态健康检查。两者之间
没有可信执行收据，因此不能证明这些日志确实由该份 `scf.in` 运行产生。
`healthy=true` 只表示所提供日志通过终态解析；health 与 preflight 报告均明确
写入 `execution_provenance_verified: false`。preflight 只是准备门槛，不是执行
provenance，也不是科学验收。

未来若要关闭这一缺口，应由一个经过审阅的可信 runner 实现以下收据协议：

1. QE 启动前记录精确 argv、工作目录、`scf.in` hash、四个 pseudo hash 和
   runner/script hash，并把这份启动记录保存在运行目录外的独立锚点中。
2. QE 结束后记录真实 process exit code，以及 stdout、stderr hash，并把结束
   收据绑定到启动记录和同一次执行身份。
3. audit/preflight 只接受与外部保存锚点完全一致的启动、结束收据，再重放输入、
   pseudo、脚本和日志 hash。

本轮没有实现真实 runner 或 receipt gate，也没有据此释放任何执行或提交路径。

## 历史 residual-force `awk` 的迁移

两个历史 `run_campaign.sh` 都是已冻结、已拒绝的来源记录，保持不变。旧
`awk` 范围会吞入 `Total SCF correction` 文本，并曾在 macOS 上把非零最大
残余力打印为零。新流程应调用共享解析器：

```bash
set -o pipefail
python3 thermo_candidates/scripts/phono3py_campaign/qe_output.py inspect \
  /path/to/scf.out --stderr /path/to/scf.err --expected-atoms 96 \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["max_abs_force_ry_bohr"])'
```

必须保留管道失败状态。解析出的数值不等于计算健康，更不等于数值收敛或
科学验收；解析器只证明最后一个 PWSCF run 的终态和主力块满足软件契约。

## 验证结果

- `test_qe_output` 与真实历史 SrCu2SnS4 gate：13 tests passed。
- 共享 `phono3py_campaign` 完整测试集：435 tests passed。
- SrCu2SnS4 v2 对抗性测试：18 tests passed（使用仓库既有
  `thermo-bt2` Python，因为系统 Python 没有 PyYAML）。
- 四个改动脚本通过 `py_compile`。

v2 仍是本地准备边界：没有生成真实位移集，没有 pristine QE 结果，没有
力常数或 κL。2x2x1 超胞、0.06 bohr 位移、4.0 Å pair cutoff、90/720 Ry 和
3x3x3 force k mesh 都只是待验证起点；没有 NAC 或显式 SOC，也没有 q 网格、
超胞、振幅或 cutoff 收敛证据。
