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

## 本地开发（推荐）

前提：本地先启动 pgvector（Docker Compose），再执行向量化脚本和启动服务。

1) 启动本地数据库（pgvector）

```bash
./scripts/dev_up.sh
# 本地连接串：postgres://iclr:iclrpass@127.0.0.1:5433/iclr2026
```

2) 抓取 OpenReview 数据（得到 data/iclr2026.json）

```bash
uv run ./scripts/fetch_openreview_iclr2026.py
```

3) 初始化数据库结构（pgvector 扩展、表、索引）

```bash
uv run python ./scripts/init_db.py
```

4) 配置并写入 Embedding（必须先启动数据库）

环境变量（支持同时配置 baseurl 和 apikey）：
- `OPENAI_API_KEY`（必需）
- `OPENAI_BASE_URL`（可选，如 `https://api.openai.com/v1`）
- `OPENAI_EMBED_MODEL`（默认 `text-embedding-3-small`）
- `OPENAI_EMBED_DIM`（默认 `1536`）

两种方式：
- 临时导出：

  ```bash
  export OPENAI_API_KEY=sk-...  # 可选：export OPENAI_BASE_URL=https://api.openai.com/v1
  uv run python ./scripts/embed_papers.py
  ```

- 使用 `.env`（推荐）：

  ```bash
  cp .env.example .env  # 填写 OPENAI_API_KEY/OPENAI_BASE_URL/模型配置
  ./scripts/with_env.sh uv run python ./scripts/embed_papers.py
  ```

5) 启动 API + Gradio（会读取 .env）

```bash
./scripts/serve_app.sh
# 访问 http://127.0.0.1:8000/gradio 进行检索
```

说明：表结构包含（title、abstract、link、embedding VECTOR(N)），按余弦相似度排序。

提示：若提示 `docker: unknown command: docker compose`，请安装 Compose v2 插件或使用 `docker-compose`（启动脚本已自动兼容）。

## 远程部署（pgvector + uv）

1) 准备环境变量（.env）

```bash
cp .env.example .env
# 填写 OPENAI_API_KEY（必需），可选：OPENAI_BASE_URL/OPENAI_EMBED_MODEL/OPENAI_EMBED_DIM
```

2) 构建并启动服务（首次会自动初始化数据库并向量化缺失数据，后续不会重复向量化）

```bash
./scripts/remote_up.sh
# 暴露端口：DB 5432，Web 8000
```

3) 访问服务

```bash
http://<服务器IP或域名>:8000/gradio
```

说明：
- 本地 `compose.local.yml` 仅启动数据库，端口映射 `5433:5432`，避免与本机 Postgres 冲突。
- 远程 `compose.remote.yml` 同时启动数据库与应用，并映射 `5432`（DB）与 `8000`（Web）。
 - 远程应用容器启动时会执行 `scripts/bootstrap.sh`：
   - `init_db.py`：幂等创建扩展/表/索引
   - `embed_papers.py`：默认仅向量化缺失记录（`EMBED_ONLY_MISSING=1`），可通过 `EMBED_FORCE=1` 强制重算
