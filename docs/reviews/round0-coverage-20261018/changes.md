# 第0轮所有代码变更

本轮应用源码、既有测试、Prompt和依赖声明没有修改。下面三个文件均为新增离线诊断工具。统一差异见 [code-changes.diff](code-changes.diff)。

| 文件 | 用途 | 行数 |
|---|---|---:|
| [inventory.py](inventory.py) | 临时合成case中记录原生注册和最终模型schema | 122 |
| [measure.py](measure.py) | 执行现有pytest、行/分支覆盖、可选原生接口旁观及源hash核对 | 247 |
| [summarize.py](summarize.py) | 仅汇总已保存结果、失败、接口/路径矩阵和Host源码声明 | 140 |

## 文档和测量结果

- [baseline.md](baseline.md)：实测值、局限、缺口、下一轮代码边界与验证方案。
- [neo-final-review.md](neo-final-review.md)：Neo独立审查和优先级决定。
- [neo-scope-review.md](neo-scope-review.md) 与 [JSON](neo-scope-review.json)：24协议族、18条件组、3组条件输入/断言对照。
- [metrics.json](metrics.json)：实测汇总；[file-coverage.csv](file-coverage.csv)/[JSON](file-coverage.json)：93个应用文件逐项覆盖。
- [interface-matrix.json](interface-matrix.json)、[host-interface-inventory.json](host-interface-inventory.json)、[path-matrix.json](path-matrix.json)：有限配置分母、源码声明和精确测试映射。
- [failures-and-skips.md](failures-and-skips.md)：全部失败、setup错误、用例/模块跳过；未删减失败来修绿。

## 其他写入及边界

原始测试日志、JUnit、coverage数据、原始schema和脚本版本保存在`.analysis/round0-coverage-20261018/`。Neo用户决定文件`.analysis/neo/current-user-decisions-20261015.md`追加了本轮原话及范围；没有改写历史。上述raw文件是诊断产物，不是应用代码。
.outputs/、deliveries/、outputs/在本轮开始时已存在且未跟踪，未纳入本轮变更。没有git add/commit、目录迁移或原报告重写。

## 复现

在项目根目录，使用已有WSL Python：

```text
python docs/reviews/round0-coverage-20261018/measure.py --tools-dir /tmp/report-agent-round0-tools-20261018 --out <new-result-directory>
python docs/reviews/round0-coverage-20261018/measure.py --observe --tools-dir /tmp/report-agent-round0-tools-20261018 --out <new-observed-directory>
python docs/reviews/round0-coverage-20261018/inventory.py
python docs/reviews/round0-coverage-20261018/summarize.py
node --test --experimental-test-coverage tests/test_ui_static.cjs
```

实际历史执行脚本版本和参数见raw目录。inventory/summarize默认目标是本轮目录，重新取基线前应更换归档目录，不覆盖这次历史结果。coverage.py测量工具目前只在隔离/tmp目录，重启清理后须按记录版本提供。
