# T6 / T7：离线验证与资源申请清单

本轮只修改本地代码：未启动真实 Worker、未连接数据库、未执行迁移，未调用真实
Graph / OneDrive / AssemblyAI / Gemini / OpenAI，未发送邮件，未部署或创建资源。
本文件是代码说明和申请清单，不是已经完成云端联调的证明。

## 现有实现与本轮补齐

复用 `app.queue.worker`、`RecordingJob`、`ProcessedItem`、`process_recording`、
`Extractor` 和 `RichExtractionResult`，没有新增另一套队列或 AI Provider 框架。

- 启动入口仍是 `python -m app.queue.worker`。API 只入队，独立 Worker 执行 pipeline。
- 状态沿用 pending → processing → completed；失败退回 pending，达到上限 failed。
  每次 claim 增加 attempts，默认最多 3 次；退避为 15、30…秒，上限 300 秒。
- claim 使用 PostgreSQL `FOR UPDATE SKIP LOCKED`；每次领取生成 lease_token，续租与
  完成均校验它，旧 Worker 不能覆盖新租约。
- locked_at 现在是最近心跳时间。只回收过期或缺失心跳的 processing 任务；不会在
  每次启动时把其他 Worker 的所有 processing 任务重置。
- 中断/失败时同步更新未完成会议的失败状态，防止页面永久停在处理中；不会覆盖
  awaiting_review / approved / sent 的人工审核流程。
- 同一录音继续使用 drive_item_id 作为既有身份；活动任务部分唯一索引防止并行重复入队。
  retry insert 使用 ON CONFLICT DO NOTHING，原始发现仍复用 ProcessedItem 唯一账本。
- 处理期间持有录音级 PostgreSQL session advisory lock。即使心跳延迟，仍在执行的
  Worker 也不会被过期回收抢走；失去租约时取消本进程的 pipeline。
- Ctrl+C / SIGTERM 停止新 claim，默认等待当前任务 30 秒，超时取消并按重试预算处理。
  强制 kill 无法跑清理逻辑，交给数据库连接释放与过期回收。
- 空队列和队列故障等待轮询间隔，不进行忙循环。
- Mock 固定返回 summary、speaker_highlights.key_points、action_items、risks、next_steps。
  Mock 是明确的测试样例，不是真实会议内容分析。
- Gemini 扩展现有 Extractor，复用 httpx，不增加 SDK。默认禁用，无默认型号、无仓库 Key。
  空转写、缺少 Key / model、空响应、截断响应、非法 JSON、错误结构均报错。
- pipeline 在 AI 前提交原始转写和 Speaker 时间戳，AI 重试复用转写；结构化输出通过
  Pydantic 与非空摘要校验。成功停在 awaiting_review，ActionItem.approved=false。
  awaiting_review / approved / sent 的重复任务直接返回，不覆盖人工结果。
- EMAILS_ENABLED=false 时包括通知在内的邮件均不发送。设为 true 后原有处理通知仍可能发送；
  这不等于自动批准或自动发送会议纪要。离线验证务必保持 false。

## 配置与迁移注意事项

只更新了 `.env.example` 的占位说明，没有修改真实 `.env` 或云端设置。

| 配置 | 默认 / 用途 |
| --- | --- |
| EXTRACTOR_IMPL | transcript_only；离线测试用 mock；获批后才允许 gemini |
| GEMINI_ENABLED | false；第二道显式外部调用开关 |
| GEMINI_API_KEY | 空；仅来自环境配置 / 密钥管理，不进 Git |
| GEMINI_MODEL | 空；必须显式指定管理员批准的型号 |
| WORKER_POLL_SECONDS | 3 |
| WORKER_LEASE_SECONDS | 120 |
| WORKER_HEARTBEAT_SECONDS | 20，必须小于 lease |
| WORKER_SHUTDOWN_SECONDS | 30 |

新迁移 `7b2d9e4c6a10_recording_job_leases.py` 依赖已有未提交迁移
`3f7a2b61c9d4_add_meeting_email_audits.py`。迁移只生成，未执行。以后需由管理员：

1. 先备份并选定隔离的 PostgreSQL 验证库，绝不能误连生产库。
2. 停止旧版本 Worker，再审核并执行完整迁移链。
3. 若有重复的 pending / processing 行，迁移主动失败；人工调查，不自动删除任务。
4. Worker 使用直连或 session pooling 的 DATABASE_URL；不能使用 transaction pooling。
   每个活动 Worker 需要考虑锁连接、pipeline 连接及心跳连接的并发占用。
5. 完成下面的真实 PostgreSQL 测试后才考虑多副本。当前建议先单副本。

队列是至少一次执行，不声称跨数据库和外部服务“严格恰好一次”。例如转写供应商成功、
但本地尚未提交转写时进程崩溃，后续重试仍可能再次调用供应商。该问题需后续供应商级
任务 ID / 幂等设计，不应把 Mock 测试理解为消除了所有重复计费风险。

## 本轮可复现的零网络验证

使用现有已安装依赖，不运行 pip/npm 安装，不启动服务，不执行数据库迁移。

在仓库根目录 PowerShell：

```powershell
$testTemp = Join-Path $env:TEMP ('meeting-offline-' + [guid]::NewGuid())
.\.venv\Scripts\python.exe -m pytest --basetemp $testTemp -p no:cacheprovider -q
.\.venv\Scripts\python.exe -m compileall -q app alembic
```

`app/tests/conftest.py` 在收集测试之前替换数据库 URL 和密钥为测试值，并阻止真实
socket、DNS、asyncio 网络连接；只放行 Windows 标准库内部用于 asyncio 的本机 socketpair。
Graph、AI HTTP、邮件和数据库均使用 Mock。不能靠“默认配置大概是 mock”来保障费用。

前端在**单独的临时 PowerShell 会话**中运行，结束后关闭该会话：

```powershell
Set-Location C:\Users\93547\project\Meeting-Intel\frontend
$env:NODE_OPTIONS='--require=C:\Users\93547\project\Meeting-Intel\scripts\offline-node.cjs'
node node_modules/vitest/vitest.mjs run
node node_modules/eslint/bin/eslint.js .
node node_modules/next/dist/bin/next build --webpack
```

预加载文件关闭 telemetry、覆盖测试进程中的 DB/Auth 参数并阻止真实 TCP/TLS/DNS/UDP/fetch；
仅允许本机进程间管道通信。Vitest 的 fetch 使用测试 Mock。使用 Webpack 构建便于限制
在 Node 网络隔离范围内，没有改项目默认 bundler 配置。构建产物包含测试用 API 地址，
**不能发布此离线构建产物**。不会修改 `.env.local`。

自动化覆盖：领取与锁 SQL、成功、重试退避、最大失败、过期回收、旧租约拒绝完成、
活动任务唯一索引 / retry 插入冲突、session lock 排斥与释放、心跳丢失取消、空队列等待、
停止信号和宽限期、模拟新 Session 恢复、Mock 输出、Gemini 配置与假 HTTP 响应、
AI 错误传至 job retry/failed、原始转写保留、成功后的审核门槛，以及原有 T2/T3/T4 回归。

本轮结果：后端 **241 passed**；前端 **37 passed**；ESLint、Python compileall、
Next.js `build --webpack` 均通过；git diff --check 通过。后端有一个既有的
Starlette/httpx 弃用警告。没有运行真实数据库/云端端到端测试。

## 未验证 / 人工验收清单

**这个测试必须 PostgreSQL 才能完整验证。** SQL 编译断言和 fake Session 不证明实际锁行为。
本轮没有使用 SQLite 冒充 PostgreSQL，也没有连接任何真实数据库。

- 在隔离 PostgreSQL 库应用迁移，确认重复活动任务的迁移失败策略。
- 同时启动两个 Worker，提交同一任务，验证只有一个真实 claim 和一个 pipeline。
- 同时发两次原始入队 / retry 请求，验证只有一个活动任务，失败事务不遗留错误账本。
- 强制终止处理进程，再启动 Worker；数据库行仍存在，过期后恢复，达到上限后 failed。
- 保持 Worker A 活跃，启动 Worker B；B 不应回收 A 的任务。模拟心跳延迟与连接断开。
- 在 pipeline 各个提交点 kill，确认原始转写已提交后的重试不再下载/转写；审核后重放不覆盖。
- 在目标 Linux 容器上测试 SIGTERM、平台停止宽限期与连接池模式。Mock 信号测试不替代它。
- 隔离前端 / 测试身份显示结构化内容、人工审核与权限按钮。真实 Entra 登录和真实音频试听
  需要公司授权的测试身份、Graph 权限和测试录音；本轮未做真实登录或播放。
- Gemini 实际模型支持、配额、数据驻留、超长转写上下文限制、响应格式兼容性未联调。

## Railway 资源申请（不执行部署）

- 一个独立常驻 Worker service，复用现有代码 / Dockerfile，覆盖默认 API CMD 为
  `python -m app.queue.worker`；不把它作为 FastAPI 请求后台任务。
- 不需要公网端口、域名或 HTTP ingress；需要到 PostgreSQL 及将来获批供应商的出站连接。
  不要给无 HTTP listener 的 Worker 配置 HTTP 健康检查。
- DATABASE_URL：同一业务库的直连/session-pooling URL；确认连接数、SSL、备份和网络策略。
- 必需配置名：DATABASE_URL、TENANT_ID、CLIENT_ID、CLIENT_SECRET、GRAPH_IMPL、
  TRANSCRIBER_IMPL、EXTRACTOR_IMPL、EMAILS_ENABLED、WORKER_*。
  现有 AUTH_MICROSOFT_ENTRA_ID_* 别名可复用，但不用重复填写两套冲突值。
- 获批真实转写才提供 ASSEMBLYAI_API_KEY；获批 Gemini 才提供 GEMINI_*；
  保持 EMAILS_ENABLED=false、AUTO_SEND_EMAIL=false、ENABLE_AUTO_RECONCILE=false。
  以后允许通知才审核 MAIL_SENDER_UPN、POPIA_NOTICE_ENABLED、APP_URL。
- 工程起步建议（不是平台硬性最低配置，也未实测）：单并发约 1 vCPU / 2 GiB RAM。
  当前 AssemblyAI 上传会读入整个文件，超大录音需更高内存；按最大录音大小做隔离压测。
  公司允许的资源档位、真实最低可用规格：**需要管理员确认**。
- 不要求持久录音磁盘；pipeline 使用临时目录，队列 / 转写 / 结果保存在 PostgreSQL。
  临时磁盘至少容纳最大录音及处理余量；异常 kill 后临时目录可能残留，需宿主回收策略。
- 可能计费项目：服务计划、Worker CPU/RAM、数据库 CPU/存储/备份、网络出站、
  可选 volume、构建与日志，以及未来转写/AI供应商用量。实际收费项目与价格：
  **需要管理员确认**，本轮未查价、未申请或创建服务。

## Azure 资源申请（只作架构适配判断）

| 方案 | 与当前代码的适配 | 需要确认 |
| --- | --- | --- |
| Azure Container Apps 常驻容器 | 最匹配现有 Docker + 无限轮询 Worker；独立应用，无 ingress，至少保持一个副本 | 区域、配额、非 HTTP 扩缩容、资源档位、终止宽限期、网络、日志、费用均需管理员确认 |
| App Service / continuous WebJob | 若公司已有受支持的常驻 App Service 计划可评估复用 | Python/OS/WebJob 支持组合、Always On、后台资源配额、重启策略与费用需要管理员确认 |
| Azure Functions | 当前不是短生命周期触发函数；直接搬入无限轮询/长音频处理不匹配 | 若选用需改触发方式、拆分长任务或做耐久编排；计划超时和成本需要管理员确认 |

优先建议 Container Apps 常驻服务，而非现有 README 的定时 reconcile Job；reconcile 是
发现/入队，不是本次录音消费 Worker。需申请受控订阅/资源组、镜像仓库权限、容器环境、
PostgreSQL/网络访问、密钥管理、日志和预算告警。无 GPU / 本地模型需求。所有云平台
功能与计费判断仅基于架构适配，未查询当前官方产品规格，具体可用性需管理员确认。

## Gemini 资源申请

- 公司拥有并管理的 Google Cloud / Gemini 项目，API Key 属于该项目，不用个人项目 Key。
  需要项目 ID、负责人、授权使用范围和密钥注入/轮换渠道。
- 当前 adapter 指向 Gemini Developer API 的 `generativelanguage.googleapis.com`
  （Generative Language API）。管理员需确认项目是否获准启用该 API，以及 Key 限制策略。
  如果公司只批准 Vertex AI，本 adapter 不能直接当 Vertex AI 使用；需另行适配 IAM/端点。
- 是否必须绑定 Billing、是否允许免费层、支付归属、配额/RPM/TPM、预算和告警：
  **需要管理员确认**。不能从“有 API Key”推断可免费使用，也不能承诺零费用。
- 推荐配置哪个型号：仓库无法证明公司当前可用型号，不猜具体 model ID。
  请管理员确认一个允许处理会议文本、支持 JSON 输出、上下文足够且成本合适的稳定型号；
  将确认的准确 ID 填入 GEMINI_MODEL，先使用合成文本进行获批的小样本验收。
- 代码配置：EXTRACTOR_IMPL=gemini、GEMINI_API_KEY、GEMINI_MODEL；只有获批真实
  调用后才设 GEMINI_ENABLED=true。当前仍保持禁用，绝不在 Git 中提交 Key。
- 数据处理协议、POPIA/公司合规、数据驻留、保留/训练用途、模型可用地区和服务等级：
  **需要管理员确认**。本轮未实际验证模型输出或连接。
