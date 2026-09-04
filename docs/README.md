# 代码优化任务索引

共 **10 个优化任务**，按严重程度排序。每个任务有独立的详细文档。

| # | 任务 | 严重程度 | 文档 | 预计改动量 |
|:--:|------|:------:|------|:--:|
| 01 | 裸 except: 块 | 🔴 致命 | [01-bare-except.md](./01-bare-except.md) | 43 处替换，6 个文件 |
| 02 | 通配符 import | 🔴 致命 | [02-wildcard-import.md](./02-wildcard-import.md) | 5 个文件，需确认实际使用的符号 |
| 03 | GlobalProterties 拼写错误 | 🟡 中等 | [03-globalproperties-typo.md](./03-globalproperties-typo.md) | 1 个 Rename Symbol 操作 |
| 04 | 魔法字符串 | 🟡 中等 | [04-magic-strings.md](./04-magic-strings.md) | 定义常量 + 3-5 文件替换 |
| 05 | 被注释掉的代码 | 🟡 中等 | [05-commented-code.md](./05-commented-code.md) | 删除 90 行注释 + 零散清理 |
| 06 | 中文注释（已知 BUG） | 🟡 中等 | [06-chinese-comments.md](./06-chinese-comments.md) | 翻译 3-5 处关键注释 |
| 07 | 类型标注缺失 | 🟡 中等 | [07-missing-type-hints.md](./07-missing-type-hints.md) | 5+ 文件添加类型标注 |
| 08 | 游戏导出器缺少文档 | 🟡 中等 | [08-missing-docstrings.md](./08-missing-docstrings.md) | 8 个类添加 docstring |
| 09 | 命名不一致 | 🟢 低 | [09-naming-inconsistency.md](./09-naming-inconsistency.md) | 1-3 处重命名 |
| 10 | 过长方法 | 🟢 低 | [10-long-methods.md](./10-long-methods.md) | 2-4 个方法拆分 |

## 推荐修复顺序

```
01 → 02 → 03 → 05 → 04 → 06 → 07 → 08 → 09 → 10
```

**理由**：
- 01-02 是运行时安全/可维护性最严重的问题
- 03 改动最小（Rename Symbol），顺手解决
- 05 删代码，也快
- 04/06/07 需要理解业务逻辑，放在后面
- 08/09/10 锦上添花

## 使用方式

对 GitHub Copilot 说：**"请按 docs/0X-xxx.md 文档进行修复"** 即可。
