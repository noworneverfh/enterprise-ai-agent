# Enterprise AI Agent Platform Architecture

## System Overview

```mermaid
flowchart LR
  Browser["React Industrial Console"] --> Nginx["Nginx Static Hosting"]
  Nginx --> FastAPI["FastAPI Backend"]
  FastAPI --> Auth["JWT / RBAC"]
  FastAPI --> SQL[("SQLite Dev / PostgreSQL Prod")]
  FastAPI --> Agent["Diagnosis Orchestrator"]
  Agent --> Context["Context Intelligence"]
  Agent --> Tools["Device / Alarm / Knowledge Tools"]
  Tools --> RAG["Context-aware RAG"]
  RAG --> Embedding["Embedding Service"]
  Embedding --> Chroma[("Chroma Vector DB")]
  Agent --> Risk["Risk Engine"]
  Agent --> LLM["LLM Provider"]
  Agent --> Report["Report Builder V2"]
  Report --> History["Diagnosis History / Trace / Audit"]
  Report --> Memory["Maintenance Memory"]
  Risk --> Events["Risk Events"]
```

## Product Positioning

Enterprise AI Agent Platform is an industrial equipment intelligent operations platform. It supports the full maintenance loop:

1. Device status sensing
2. Risk discovery
3. Agent planning
4. Tool execution
5. Context-aware knowledge retrieval
6. Evidence aggregation
7. Report V2 generation
8. Field maintenance feedback
9. Maintenance memory accumulation

## Request Data Flow

1. User or Admin opens the React console.
2. FastAPI validates JWT/RBAC and opens a SQLAlchemy session.
3. Diagnosis Orchestrator loads Device Context and creates Diagnosis Session Context.
4. Intent Planner decides what data is required.
5. Tool Execution Engine reads device status, alarms, knowledge, and maintenance memory.
6. Evidence Aggregator normalizes trusted facts.
7. Risk Engine calculates risk level and score.
8. Context-aware RAG retrieves maintenance manuals, fault knowledge, and historical cases.
9. LLM Reasoning Layer expresses causes and recommendations from trusted evidence only.
10. Report Builder V2 persists the final business report.
11. Maintenance Memory and Risk Monitoring feed future device context.

## Agent Diagnosis Flow

```mermaid
sequenceDiagram
  participant U as User/Admin
  participant A as Agent API
  participant C as Context Builder
  participant P as Intent Planner
  participant T as Tool Engine
  participant K as Knowledge Retriever
  participant R as Risk Engine
  participant L as LLM Layer
  participant B as Report Builder
  participant M as Memory

  U->>A: Diagnosis request or risk event
  A->>C: Load device profile and session context
  C->>P: Provide device history, alarms, reports, maintenance memory
  P->>T: Execute device/alarm/history tools
  T->>K: Retrieve context-aware knowledge
  T->>R: Provide trusted facts and observations
  R->>L: Send bounded reasoning context
  L->>B: Cause explanation and action wording
  B->>M: Save Report V2, trace, audit, session
  M-->>U: Structured diagnosis report
```

## Context Intelligence

```mermaid
flowchart TD
  Base["Device Base Info"] --> DeviceContext["Device Context"]
  Runtime["Runtime History"] --> DeviceContext
  Alarm["Alarm History"] --> DeviceContext
  Reports["Diagnosis History"] --> DeviceContext
  Maintenance["Maintenance Memory"] --> DeviceContext
  Knowledge["Related Fault Knowledge"] --> DeviceContext
  Cases["Similar Maintenance Cases"] --> DeviceContext
  DeviceContext --> Session["Diagnosis Session Context"]
  Session --> Retrieval["Context-aware Retrieval"]
  Session --> Monitoring["Risk Monitoring Agent"]
  Monitoring --> RiskEvent["Risk Event"]
  RiskEvent --> Diagnosis["Diagnosis Orchestrator"]
  Diagnosis --> Report["Report V2"]
  Report --> Feedback["Field Maintenance Feedback"]
  Feedback --> Maintenance
```

## RAG Pipeline

```mermaid
flowchart TD
  File["PDF / Markdown / TXT"] --> Parser["Document Parser"]
  Parser --> Cleaner["Text Cleaning"]
  Cleaner --> Structure["Fault Knowledge Structure"]
  Structure --> Sections["Business Sections"]
  Sections --> Embedding["Embedding"]
  Embedding --> Chroma["Chroma Collection"]
  Chroma --> Hybrid["Hybrid Retrieval"]
  Hybrid --> Citation["Document / Section / Summary"]
  Citation --> Evidence["Evidence Bundle"]
  Evidence --> Report["Report V2"]
```

## User Roles

| Role | Product Focus | Visible Capabilities |
| --- | --- | --- |
| User | Operations execution | Dashboard, device profile, AI risk events, diagnosis reports, maintenance records |
| Admin | Platform governance | All User capabilities plus diagnosis execution, knowledge management, risk scanning, system settings |

The backend remains compatible with legacy `viewer` and `engineer` records. The frontend normalizes them into the simpler User/Admin product model for enterprise demonstrations.

## Deployment Topology

```mermaid
flowchart TD
  subgraph Docker Compose
    Frontend["frontend: nginx"]
    Backend["backend: FastAPI"]
    Chroma["chromadb"]
    Postgres[("postgres")]
    Data[("uploads / logs / models")]
  end
  Frontend --> Backend
  Backend --> Postgres
  Backend --> Chroma
  Backend --> Data
  Backend --> Provider["OpenAI-compatible API or Ollama"]
```

## Demo Story

1. User opens Dashboard and sees abnormal devices and pending alarms.
2. User opens Device Detail Center for `DEV-003` and sees current E101 alarm, health trend, diagnosis history, knowledge links, and maintenance memory.
3. User opens AI Operations Center and sees proactive risk events for temperature, vibration, and communication risks.
4. User opens Smart Service Reports and reviews a Report V2 diagnosis with facts, causes, verification steps, actions, and knowledge citations.
5. Admin uploads or refreshes maintenance manuals in Knowledge Center.
6. Admin triggers diagnosis/risk scanning and saves field handling results in Maintenance Loop.
7. The saved maintenance result becomes future device context and improves the next diagnosis.
