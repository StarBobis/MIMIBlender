# Code Optimization Task Index

There are **10 optimization tasks** in total, sorted by severity. Each task has its own detailed document.

| # | Task | Severity | Document | Estimated Change Scope |
|:--:|------|:------:|------|:--:|
| 01 | Bare `except:` blocks | 🔴 Critical | [01-bare-except.md](./01-bare-except.md) | 43 replacements across 6 files |
| 02 | Wildcard imports | 🔴 Critical | [02-wildcard-import.md](./02-wildcard-import.md) | 5 files; confirm which symbols are actually used |
| 03 | GlobalProterties misspelling | 🟡 Medium | [03-globalproperties-typo.md](./03-globalproperties-typo.md) | 1 Rename Symbol operation |
| 04 | Magic strings | 🟡 Medium | [04-magic-strings.md](./04-magic-strings.md) | Define constants + replace in 3-5 files |
| 05 | Commented-out code | 🟡 Medium | [05-commented-code.md](./05-commented-code.md) | Delete 90 comment lines + scattered cleanup |
| 06 | Chinese comments (known bug) | 🟡 Medium | [06-chinese-comments.md](./06-chinese-comments.md) | Translate 3-5 key comments |
| 07 | Missing type annotations | 🟡 Medium | [07-missing-type-hints.md](./07-missing-type-hints.md) | Add type annotations in 5+ files |
| 08 | Game exporters lack documentation | 🟡 Medium | [08-missing-docstrings.md](./08-missing-docstrings.md) | Add docstrings to 8 classes |
| 09 | Inconsistent naming | 🟢 Low | [09-naming-inconsistency.md](./09-naming-inconsistency.md) | 1-3 renames |
| 10 | Overly long methods | 🟢 Low | [10-long-methods.md](./10-long-methods.md) | Split 2-4 methods |

## Recommended Fix Order

```
01 → 02 → 03 → 05 → 04 → 06 → 07 → 08 → 09 → 10
```

**Rationale:**

- 01-02 are the most severe issues for runtime safety / maintainability
- 03 is the smallest change (Rename Symbol), fix it while you are at it
- 05 removes code, which is also quick
- 04/06/07 require understanding the business logic, so leave them for later
- 08/09/10 are icing on the cake

## Usage

Just tell GitHub Copilot: **"Please fix it according to the docs/0X-xxx.md document."**
