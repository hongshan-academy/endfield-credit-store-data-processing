# Endfield 信用商店数据清洗工具

**自动修复**和**统计验证**由 [hongshan-academy/endfield-credit-store-ocr](https://github.com/hongshan-academy/endfield-credit-store-ocr) 和 [madSUNitist/endfield-credit-store-ocr](https://github.com/madSUNitist/endfield-credit-store-ocr) 生成的数据，方便后续数据处理。

## 快速使用

```bash
# 自动修复价格，生成 *_fixed.json，并输出验证报告
python main.py results_final.json --fix-price

# 只做价格验证（不修复）
python main.py results_fINAL.json --price-validation

# 导出需要关注的错误条目（不含 exact_match 和 close_match_pm1 类别）
python main.py results_final.json --dump-errors errors.json

# 过滤低质量图像（基于价格分类和物品数量）
python main.py results_final.json --filter --filter-min-score 7.0

# 先过滤再修复（推荐）
python main.py results_final.json --filter --fix-price

# 干运行：查看过滤和修复统计，但不写入文件
python main.py results_final.json --filter --fix-price --dry-run
```

**注意**：这里的 `results_final.json` 必须具有和 [madSUNitist/endfield-credit-store-ocr](https://github.com/madSUNitist/endfield-credit-store-ocr) 的输出相同的格式。

## 价格验证类别

运行 `--price-validation` 会将每个商品归入以下类别（按优先级从上到下检查，一旦匹配即停止）：

 | 类别 | 含义 | 自动修复 |
 |------|------|----------|
 | `exact_match` | 价格与折扣完全匹配 | 否（仅补原价） |
 | `close_match_pm1` | 数值差 ±1，保留原值 | 否（仅补原价） |
 | `close_match_edit` | 编辑距离 1，通常为拼写错误 | 是（保留原价，仅修正折扣和原价） |
 | `prefix_suffix_match_exact` | 价格字符串包含期望折扣价（完全匹配） | 是 |
 | `prefix_suffix_match_pm1` | 价格字符串包含期望折扣价 ±1 或拼接匹配 | 是（保留原价） |
 | `implied_match` | 价格本身可反推出合法折扣 | 是 |
 | `mismatch_with_discount` | 有折扣但价格错误 | 是 |
 | `discount_non_monotonic` | 折扣违反单调性（仅出现在动态验证中） | 是 |
 | `missing_discount` | 无折扣信息且无价格信息 | 否 |
 | `other_error` | 无法匹配任何规则 | 否 |

**优先级说明**：类别按表格从上到下依次检查，`exact_match` 优先于 `close_match_pm1`，后者优先于 `close_match_edit`，以此类推。因此一个条目只会被归入第一个满足条件的类别。

修复后再次验证时，所有可修复类别应转为 `exact_match` 或 `close_match_pm1`（尽管实际上会有误判/错判的情况，但那应该是极少数）。

## 修复逻辑

内置标准原价表，根据每个商品的类别采取不同修复策略：

- **`exact_match`**：不修改价格和折扣，仅补全 `original_price`
- **`close_match_pm1`**：保留原价格和折扣，仅补全 `original_price`
- **`close_match_edit`**：保留原价格，仅修正折扣为合法值并补全 `original_price`
- **`prefix_suffix_match_exact`**：从价格字符串中提取正确的折扣价（如 `35140` → `35`），并补全原价和折扣
- **`prefix_suffix_match_pm1`**：保留原价格（±1 或拼接匹配），仅修正折扣为合法值并补全 `original_price`
- **`implied_match`**：根据价格反推合法折扣，并补全原价
- **`mismatch_with_discount`**：使用现有折扣重新计算正确价格，并补全原价
- **`missing_discount`**：无法修复（价格缺失）
- **`other_error`**：无法修复（无法匹配任何规则）

所有可修复类别在修复后都会补充 `original_price` 为标准原价。

## 单调性约束修复

在 `--fix-price` 模式下，会对每个图像内的商品（按行列排序）**分组强制折扣单调非递增**：

- 售罄商品（`sold_out=true`）和未售罄商品分别独立成组。
- 每组内所有**可修复**商品（非 `missing_discount` / `other_error`）的折扣必须满足 **前一个折扣 ≥ 当前折扣**（即折扣不会增大，价格不会变得更便宜）。
- 若原始 OCR 数据违反单调性，算法通过动态规划（DP）选择全局代价最小的合法折扣序列，同时保留原始价格对 `close_match_pm1`、`close_match_edit`、`prefix_suffix_match_pm1` 等类别的影响。
- 不可修复商品（`missing_discount` / `other_error`）**跳过**，但不打断单调性传递（它们不参与 DP，但可修复商品之间依然保持单调）。

这一设计保证了修复后的数据在视觉顺序上折扣变化合理，减少了因 OCR 识别错误导致的折扣跳跃。

## 质量过滤（Filter）

使用 `--filter` 可以根据价格验证类别和物品数量对图像进行评分，并丢弃得分低于阈值的低质量记录。

### 评分规则

每个 `ImageRecord` 的总分 = 所有物品得分之和 - 数量惩罚（若物品数 ≠ 10）。

单个物品的得分基于其价格验证类别，归一化到 0~1 范围（允许负分）：

| 类别 | 基础分数 | 归一化得分 |
|------|----------|------------|
| `exact_match` / `close_match_pm1` / `concatenated_exact` | 100 | 1.0 |
| `discount_non_monotonic` | 80 | 0.8 |
| `close_match_edit` | 70 | 0.7 |
| `prefix_suffix_match_exact` / `prefix_suffix_match_pm1` | 70 | 0.7 |
| `implied_match` | 50 | 0.5 |
| `mismatch_with_discount` | 30 | 0.3 |
| `missing_discount` / `other_error` | -50 | -0.5 |

**数量惩罚**：物品数不等于 10 时，总分直接减去 **5.0** 分（相当于损失 5 个完美物品的得分）。

默认最低保留总分：`7.0`（即一个记录最多允许损失 3 分，例如一个缺失物品或几个低质量物品）。

### 使用示例

```bash
# 仅过滤，保存过滤后的结果（需指定输出路径）
python main.py results_final.json --filter --output filtered.json

# 先过滤再修复，保存修复后的文件
python main.py results_final.json --filter --fix-price

# 自定义最低总分阈值
python main.py results_final.json --filter --filter-min-score 5.0 --fix-price

# 干运行：查看统计但不写入任何文件
python main.py results_final.json --filter --fix-price --dry-run
```

## 命令行参数

| 参数 | 说明 |
|------|------|
| `--fix-price` | 自动修复，生成 `*_fixed.json`，随后自动验证 |
| `--output` | 指定修复后文件路径（默认与输入同目录，加 `_fixed`） |
| `--price-validation` | 仅执行价格验证，不修复 |
| `--dump-errors` | 导出非 `exact_match` 和非 `close_match_pm1` 的条目到 JSON |
| `--items` | 输出物品统计（名称、价格、折扣等） |
| `--uid` / `--refresh` / `--meta` | 分别输出 UID、刷新次数、OCR 元数据统计 |
| `--rounding` | 比较 floor / round / ceil 对价格匹配的影响 |
| `--filter` | 启用质量过滤（在修复前执行） |
| `--filter-min-score` | 保留记录的最低总分阈值（默认 7.0） |
| `--dry-run` | 干运行：不写入任何文件，仅打印统计信息（不影响过滤和修复的计算） |