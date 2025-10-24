# ICLR2026 Openreview 论文

## 环境安装

### 推荐方式（uv）

```bash
uv sync
```

导出到requirements

```bash
uv pip freeze > requirements.txt
```

### pip安装

建议python 3.12

```bash
pip install -r requirements.txt
```

## 抓取脚本

```bash
uv run ./scripts/fetch_openreview_iclr2026.py
```

```bash
python3 ./scripts/fetch_openreview_iclr2026.py
```