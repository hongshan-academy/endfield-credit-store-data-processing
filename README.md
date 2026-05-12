# Endfield 信用商店数据清洗工具

**自动修复**和**统计验证**由 [hongshan-academy/endfield-credit-store-ocr](https://github.com/hongshan-academy/endfield-credit-store-ocr) 和 [madSUNitist/endfield-credit-store-ocr](https://github.com/madSUNitist/endfield-credit-store-ocr) 生成的数据，方便后续数据处理。

## 快速使用

```bash
# 自动修复价格，生成 *_fixed.json，并输出验证报告
python main.py results_final.json --fix-price

# 只做价格验证（不修复）
python main.py results_final.json --price-validation

# 导出需要关注的错误条目（不含 exact_match 和 close_match_pm1 类别）
python main.py results_final.json --dump-errors errors.json
```

**注意**：这里的 `results_final.json` 必须具有和 [madSUNitist/endfield-credit-store-ocr](https://github.com/madSUNitist/endfield-credit-store-ocr) 的输出相同的格式。

## 价格验证类别

运行 `--price-validation` 会将每个商品归入以下类别（按优先级从上到下检查，一旦匹配即停止）：

| 类别 | 含义 | 自动修复 |
|------|------|----------|
| `exact_match` | 价格与折扣完全匹配 | 否（仅补原价） |
| `close_match_pm1` | 数值差 ±1，保留原值 | 否（仅补原价） |
| `close_match_edit` | 编辑距离 1，通常为拼写错误 | 是 |
| `prefix_suffix_match` | 价格字符串包含期望折扣价 | 是 |
| `implied_match` | 价格本身可反推出合法折扣 | 是 |
| `mismatch_with_discount` | 有折扣但价格错误 | 是 |
| `missing_discount` | 无价格信息 | 否 |
| `other_error` | 无法匹配任何规则 | 否 |

**优先级说明**：类别按表格从上到下依次检查，`exact_match` 优先于 `close_match_pm1`，后者优先于 `close_match_edit`，以此类推。因此一个条目只会被归入第一个满足条件的类别。

修复后再次验证时，所有可修复类别应转为 `exact_match` 或 `close_match_pm1`（尽管实际上会有误判/错判的情况，但那应该是极少数）。

## 修复逻辑

内置标准原价表，根据每个商品的类别采取不同修复策略：

- **`exact_match`**：不修改价格和折扣，仅补全 `original_price`
- **`close_match_pm1`**：保留原价格和折扣，仅补全 `original_price`
- **`close_match_edit`**：将价格修正为期望值，并同步修正折扣
- **`prefix_suffix_match`**：从价格字符串中提取正确的折扣价（如 `35140` → `35`），并补全原价和折扣
- **`implied_match`**：根据价格反推合法折扣，并补全原价
- **`mismatch_with_discount`**：使用现有折扣重新计算正确价格，并补全原价
- **`missing_discount`**：无法修复（价格缺失）
- **`other_error`**：无法修复（无法匹配任何规则）

所有可修复类别在修复后都会补充 `original_price` 为标准原价。

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