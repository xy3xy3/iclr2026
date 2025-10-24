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

## 语义搜索（FastAPI + Gradio + pgvector）

1) 初始化数据库结构（含 pgvector 扩展与索引）

```bash
uv run python ./scripts/init_db.py
```

2) 生成并写入 Embedding（使用 OpenAI 兼容接口）

要求环境变量：`OPENAI_API_KEY`（可选：`OPENAI_BASE_URL`、`OPENAI_EMBED_MODEL`）。

```bash
export OPENAI_API_KEY=sk-...           # 或者设置 OPENAI_BASE_URL 指向兼容服务
uv run python ./scripts/embed_papers.py
```

3) 启动服务（FastAPI + Gradio）

```bash
./scripts/serve_app.sh
# 访问 http://127.0.0.1:8000/gradio 进行检索
```

说明：表结构包含三列字段（title、abstract、link）与 `embedding VECTOR(1536)`，
检索时以余弦相似度（`<=>`）排序。

## Docker Compose 部署

- 仅本机数据库（pgvector），使用本机 `uv` 开发：

  ```bash
  ./scripts/dev_up.sh
  # 本地连接串：postgres://iclr:iclrpass@127.0.0.1:5433/iclr2026
  ```

- 远程服务器同时部署 pgvector + uv 容器：

  ```bash
  ./scripts/remote_up.sh
  # 首次会构建 uv 镜像，然后在容器内提供 uv 工具
  # 进入 uv 容器：
  docker compose -f compose.remote.yml exec uvapp bash
  # 容器内执行（示例）：
  uv sync && uv run python ./scripts/fetch_openreview_iclr2026.py
  ```

说明：

- 镜像使用华为云镜像仓库（中国区），请确保服务器能正常拉取。
- 本地 `compose.local.yml` 只启动数据库，端口映射为 `5433:5432`，避免与本机已有 Postgres 冲突。
- 远程 `compose.remote.yml` 默认映射 `5432:5432`，并为将来可能的 Web 开发预留了 `8000` 端口。
