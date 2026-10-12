# Gemini 三次盲标操作手册

## 1. 目的

本手册用于对同一批36条 BPLL v2 Demo 文本进行三次相互独立的 Gemini 标注。研究者合议表是答案卷，不得上传给 Gemini。

## 2. 运行前准备

每次运行准备以下五个文件：

1. `codebook_v2_中文版.md`
2. `brand_alias_map.csv`
3. `brand_scope_decisions_v2.csv`
4. `annotation_schema_v2.json`
5. `demo_v2_36_input.json`（私有文件，不在公开 Git 仓库）

另打开 `prompt_v2.md`，在粘贴前替换：

- 第一次：`RUN_ID` → `gemini_demo_run_1`
- 第二次：`RUN_ID` → `gemini_demo_run_2`
- 第三次：`RUN_ID` → `gemini_demo_run_3`
- `MODEL_NAME` → Gemini 界面实际显示的模型名称

不要让模型自行猜测版本。记录运行日期、账号产品层级和界面显示名称。

## 3. 对话设置

三次运行分别使用全新对话。不要使用包含 BPLL 历史的项目、Gem、自定义记忆或上一轮对话。不要开启 Deep Research、联网搜索或外部资料检索。

模型只允许使用本次上传的五个文件和固定 Prompt。不要提供：

- 研究者 reference Excel/JSON；
- 120条探索样本或60条关键案例；
- 抽样层、`crisis_flag`、原始行号或文本哈希；
- 其他模型的答案；
- 哪些标签最重要、哪类样本被富集等暗示。

## 4. 对话框中粘贴的内容

完成文件上传后，将 `prompt_v2.md` 的全文粘贴到对话框。确认 `RUN_ID` 和 `MODEL_NAME` 已替换，再发送。不要另加“请多标一些机制”“尽量不要漏判”等临时指令。

## 5. 保存输出

模型完成后，将完整回复原样保存为：

```text
reports/validation_v2/runs/gemini_demo_run_1_raw.json
reports/validation_v2/runs/gemini_demo_run_2_raw.json
reports/validation_v2/runs/gemini_demo_run_3_raw.json
```

这些文件含真实原文证据，受 `.gitignore` 排除，不上传公开仓库。

如果输出包含 Markdown 代码围栏，先保存原始回复，再复制围栏内 JSON 为 `_parsed.json`。如果 JSON 无法解析，只发送一次以下修复指令：

> 请保持所有标注判断、代码、证据和顺序完全不变，只修复 JSON 语法，使输出符合已上传的 annotation_schema_v2.json。最终只输出 JSON。

修复结果另存为 `_repaired.json`，不得覆盖原始输出。

## 6. 单次运行记录

每次运行至少记录：

| 字段 | 内容 |
|---|---|
| run_id | 本次固定运行编号 |
| run_date | 当地日期与时间 |
| model_name | 界面显示的实际名称 |
| files_uploaded | 五个输入文件名 |
| prompt_version | v2.0.1 |
| schema_version | 2.0 |
| raw_output_saved | 原始输出路径 |
| repair_needed | 是/否 |
| notes | 超时、截断或其他异常 |

## 7. 禁止事项

- 不在第一次答案后指出错误并要求重新标；
- 不把一次对话中的答案复制给另一次；
- 不因输出看起来“不够丰富”而临时追加标签要求；
- 不在跑完第一轮后修改 Codebook，再继续把三轮当成同一版本；
- 不把聊天界面的原始输出直接提交到公开 Git。

## 8. 三次完成后

先运行：

```bash
python scripts/validate_annotation_json.py \
  --schema docs/annotation_schema_v2.json \
  reports/validation_v2/runs/gemini_demo_run_1_raw.json \
  reports/validation_v2/runs/gemini_demo_run_2_raw.json \
  reports/validation_v2/runs/gemini_demo_run_3_raw.json
```

所有文件通过结构检查后，再用私有 reference JSON 运行 `scripts/evaluate_v2.py`。先计算一致率，再阅读分歧案例。

