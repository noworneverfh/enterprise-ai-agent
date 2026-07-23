# 工业设备智能运维 AI Agent 平台 v1.1

> English Subtitle: Enterprise Industrial AI Agent Platform

企业设备智能运维与 AI Agent 诊断平台。项目面向工业设备运维场景，整合设备运行数据、报警记录、企业维修知识库、RAG 检索、Reranker 二阶段重排、Agent 编排、真实 LLM 推理、Report V2 结构化报告、设备长期上下文、维修闭环、JWT/RBAC 权限与 Docker 部署，形成一套可演示、可面试、可持续维护的企业级 AI Agent 应用。

## 1. 项目定位

本项目不是简单的“设备故障问答工具”，而是一个工业设备智能运维 AI Agent 平台。

它解决的问题：

- 设备运行数据分散，运维人员难以及时判断设备风险。
- 报警只有代码和描述，缺少结合实时参数、历史记录和维修知识的综合分析。
- 维修手册、历史案例和专家经验沉淀在文档中，现场检索效率低。
- 普通大模型容易脱离真实数据生成泛化建议，缺少可追溯依据。
- 企业需要从“被动处理故障”升级为“主动发现风险 + AI 辅助诊断 + 维修经验沉淀”。

核心业务闭环：

```text
设备运行数据
  -> 报警与异常发现
  -> AI Agent 规划任务
  -> Tool Calling 获取设备事实
  -> Context-aware RAG 检索维修知识
  -> Reranker 二阶段重排
  -> 风险规则 + LLM Reasoning
  -> Report V2 结构化诊断报告
  -> 维修处理与结果反馈
  -> 形成设备长期记忆与历史案例
```

## 2. 项目亮点

### 2.1 真实 Agent 工作流

系统不是直接把用户问题丢给大模型，而是通过 `DiagnosisOrchestrator` 分阶段完成诊断：

1. `IntentPlanner`：识别用户意图，例如设备状态查询、故障原因分析、维修建议、多设备风险分析。
2. `ToolExecutionEngine`：调用设备状态工具、报警查询工具、知识检索工具。
3. `EvidenceAggregator`：把工具结果归一化为可信证据包，约束 LLM 只能基于证据推理。
4. `RiskEngine`：基于设备参数、报警等级和历史上下文计算风险区间。
5. `KnowledgeRetriever`：结合设备类型、报警码、运行参数和历史案例检索知识库。
6. `Reranker`：对 Chroma 召回结果进行二阶段重排，提高引用准确率。
7. `LLM Reasoning Layer`：负责总结、解释可能原因和组织处理建议。
8. `ReportBuilder V2`：生成结构化诊断报告，保存历史，供前端展示。

### 2.2 RAG + Reranker

v1.1 在原有 Chroma 向量检索基础上增加 Reranker 二阶段检索：

```text
Query
  -> Embedding Retriever
  -> Chroma Top-K 召回
  -> bge-reranker-v2-m3 重排序
  -> Top-N 高相关知识
  -> Evidence Bundle
  -> LLM Reasoning
  -> Report V2
```

RAG 结果保留：

- 文档来源
- 文件名
- chunk 内容
- vector similarity score
- rerank score
- citation 信息

关闭 `RERANKER_ENABLED=false` 时，系统保持原有向量检索逻辑。

### 2.3 设备长期上下文

系统维护 `Device Context`，Agent 诊断时不只看当前状态，还会参考：

- 设备基础信息
- 实时运行参数
- 当前报警
- 历史报警
- 历史诊断报告
- 风险变化
- 维修闭环记录
- 关联知识与类似案例

这让 Agent 可以回答：

- 这个设备过去发生过什么？
- 为什么现在风险升高？
- 有没有类似维修案例？
- 当前建议是否有历史依据？

### 2.4 Report V2 可信输出

前端不自行编造风险、原因、建议或评分。正式报告来自后端 `Report V2`：

- 诊断结论
- 风险等级 / 风险区间
- 已确认事实
- 参数异常分析
- 可能原因
- 验证步骤
- 处理方案
- 知识库引用
- LLM provider / generation metadata

LLM 负责自然语言解释，不负责编造设备事实、报警、风险等级或引用来源。

### 2.5 企业工程能力

- FastAPI 后端分层
- React + TypeScript + Tailwind 前端
- PostgreSQL + Alembic 迁移
- ChromaDB 向量数据库
- JWT + RBAC 权限控制
- Audit Log 审计日志
- Docker Compose 一键部署
- OpenAI-compatible / Ollama / Mock Provider 可切换
- 本地 Embedding 模型部署
- Reranker 可配置启停

## 3. 系统架构

```mermaid
flowchart TD
    A["React 前端控制台"] --> B["FastAPI API 层"]
    B --> C["DiagnosisOrchestrator"]
    C --> D["IntentPlanner"]
    D --> E["ToolExecutionEngine"]
    E --> F["设备状态 / 报警 / 知识库工具"]
    F --> G["EvidenceBundle"]
    G --> H["RiskEngine"]
    G --> I["Context-aware RAG"]
    I --> J["Chroma Vector Search"]
    J --> K["Reranker"]
    K --> L["Knowledge Evidence"]
    H --> M["LLM Reasoning"]
    L --> M
    M --> N["ReportBuilder V2"]
    N --> O["DiagnosisReport / History"]
```

## 4. 主要功能

### 4.1 运营总览

- 设备总数、正常设备、异常设备、维护设备
- 今日诊断报告数量
- 待处理报警数量
- 风险设备排行
- 最近分析报告
- AI Agent 运行状态摘要

### 4.2 设备中心

- 设备资产列表
- 实时运行参数
- 报警状态
- 设备详情中心
- 设备历史上下文
- 关联知识与类似案例

### 4.3 智能诊断

- 单设备诊断
- 多设备风险分析
- Agent 执行流程展示
- Tool Calling 结果展示
- RAG / Rerank 状态展示
- Report V2 诊断结果

### 4.4 知识中心

- PDF / Markdown / TXT 文档上传
- 文档解析与切片
- Embedding 入库
- Chroma 检索
- Reranker 重排
- 知识来源追踪

### 4.5 维修闭环

- AI 处理建议
- 现场实际处理
- 最终根因
- 是否解决
- 形成维护记忆与历史案例

### 4.6 系统管理

- 用户与角色
- 权限治理
- 服务健康
- LLM / RAG / Reranker 配置状态
- 审计日志

## 5. 目录结构

```text
enterprise-ai-agent/
├── backend/
│   ├── app/
│   │   ├── agent/              # Agent Runtime、Orchestrator、Tool Calling、Trace
│   │   ├── api/                # FastAPI 路由
│   │   ├── auth/               # JWT / RBAC
│   │   ├── context/            # Device Context、Session Context、Maintenance Memory
│   │   ├── core/               # 配置与日志
│   │   ├── domain/             # 诊断领域模型与 Report V2
│   │   ├── models/             # SQLAlchemy 模型
│   │   ├── schemas/            # Pydantic Schema
│   │   └── services/           # 设备、知识库、Embedding、Reranker 等服务
│   ├── alembic/                # 数据库迁移
│   ├── scripts/                # 初始化与演示数据脚本
│   └── tests/                  # 后端测试
├── frontend/
│   ├── src/
│   │   ├── api/                # 前端 API 封装
│   │   ├── components/         # 公共组件
│   │   ├── pages/              # 页面
│   │   ├── router/             # 路由与权限
│   │   ├── utils/              # 格式化与业务展示工具
│   │   └── types.ts            # 类型定义
├── docs/                       # 架构文档
├── examples/                   # 示例知识库文档
├── models/                     # 本地模型目录，默认不提交 Git
└── docker-compose.yml
```

## 6. 环境变量

根目录 `.env` 用于 Docker Compose 基础配置；`backend/.env` 用于后端 LLM 运行配置，避免真实 API Key 多处复制。

关键变量：

```env
APP_VERSION=1.1.0
DATABASE_URL=postgresql://agent:agent_password@postgres:5432/agentdb
AUTH_ENABLED=true

CHROMA_HOST=chromadb
CHROMA_PORT=8000
CHROMA_COLLECTION_NAME=knowledge_chunks

EMBEDDING_MODEL_PATH=/app/models/bge-small-zh-v1.5

RERANKER_ENABLED=true
RERANKER_MODEL_PATH=/app/models/bge-reranker-v2-m3
RERANKER_CANDIDATE_K=20
RERANKER_BATCH_SIZE=16
```

`backend/.env` 示例：

```env
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat
LLM_API_KEY=your_api_key_here
LLM_TIMEOUT_SECONDS=60
LLM_MAX_RETRIES=3
LLM_TEMPERATURE=0.2
LLM_MAX_TOKENS=1200
LLM_JSON_MODE=true
```


## 7. 本地模型准备

### 7.1 Embedding 模型

默认本地路径：

```text
models/bge-small-zh-v1.5/
```

可使用脚本下载：

```powershell
python scripts/download_embedding_model.py
```

### 7.2 Reranker 模型

推荐模型：

```text
BAAI/bge-reranker-v2-m3
```

Docker 内默认路径：

```text
/app/models/bge-reranker-v2-m3
```

宿主机路径：

```text
models/bge-reranker-v2-m3/
```

确认目录中至少包含：

- `config.json`
- `tokenizer.json` 或 tokenizer 相关文件
- `model.safetensors` 或 `pytorch_model.bin`

## 8. Docker 启动

```powershell
docker compose up -d
```

服务：

- Backend: <http://localhost:8000>
- Frontend: <http://localhost:5173>
- ChromaDB: <http://localhost:8001>
- PostgreSQL: localhost:5432

查看状态：

```powershell
docker compose ps
curl.exe http://localhost:8000/health
```

健康检查应返回：

```json
{
  "status": "ok",
  "database": "connected",
  "vector_db": "connected",
  "rag": {
    "retriever": "chroma",
    "reranker_enabled": true,
    "mode": "two_stage_rerank"
  },
  "llm": {
    "provider": "openai_compatible",
    "model": "deepseek-chat",
    "mode": "real"
  }
}
```

## 9. 数据初始化

演示数据脚本：

```powershell
docker compose exec backend python backend/scripts/seed_demo_data.py
```

如果在容器内执行路径不同，可使用：

```powershell
docker compose exec backend python scripts/seed_demo_data.py
```

演示数据覆盖：

- DEV-002 电机驱动单元，E404 通信异常
- DEV-003 温度传感器，E101 温度异常
- DEV-004 空压机，正常运行
- DEV-005 振动电机，E201 振动异常
- DEV-006 液压泵站，运行关注
- DEV-007 输送线减速箱，高风险
- DEV-008 冷却风机，正常运行
- DEV-009 PLC 网关，通信延迟

## 10. 常用验证命令

后端测试：

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests
```

前端构建：

```powershell
cd frontend
npm run build
```

Docker 配置：

```powershell
docker compose config
```

RAG + Reranker 抽样：

```powershell
docker compose exec backend python -c "from app.services.knowledge import search_knowledge; print(search_knowledge('E201 振动异常 处理方法', top_k=3))"
```


## 11. 安全说明

- `.env`、`backend/.env`、本地模型、上传文件、日志和数据库文件不提交 Git。
- 公开注册不能创建 admin。
- 诊断、知识库管理、系统治理接口受 RBAC 控制。
- 生产环境必须替换 `JWT_SECRET_KEY`。
- Docker Compose 配置检查可能展开环境变量，输出前应注意不要泄露 API Key。

## 12. 后续扩展方向

v1.1 已完成企业级 AI Agent Demo 的核心闭环。后续可继续扩展：

- 真实工业时序数据库接入
- 工单系统集成
- 多租户组织隔离
- 更细粒度权限管理
- RAG 评估集与自动化评测
- 设备预测性维护模型
- 本地 LLM 私有化部署
