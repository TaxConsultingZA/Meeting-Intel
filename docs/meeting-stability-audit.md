# Meeting Intelligence 稳定性审计

> 审计目的：记录当前已完成的性能稳定性优化、已检查但暂不修改的问题，以及后续验证和治理计划。
>
> 适用范围：Worker、后端查询、Dashboard、前端轮询与 speaker mapping 渲染路径。
>
> 约束：本次审计只创建文档，不修改业务代码、API、数据库或部署配置；不执行 deploy，不执行 migration。

## 1. 已完成修复

以下项目已完成代码层面的优化记录。它们需要在 Neon 额度恢复后按本文件的计划进行线上指标和回归验证；“已完成”不等于所有生产负载场景均已验收。

### 1.1 Worker idle query

- 优化 Worker 空闲状态下的查询路径，减少无任务时的重复轮询和无效数据库访问。
- 目标是降低空闲连接的查询频率、数据库消耗和 Worker 噪声，同时保留及时领取新任务的能力。
- 验证重点：空闲时查询次数、领取延迟、连接池使用率，以及从 idle 到有任务状态的恢复时间。

### 1.2 Reconcile duplicate task

- 完成 reconcile 流程中的重复任务处理优化，避免同一业务任务被重复识别、重复排队或重复处理。
- 验证重点：重复任务检测结果、reconcile 幂等性、任务状态转换，以及异常重试不会扩大重复数量。

### 1.3 Recording jobs eager loading

- 对 recording jobs 查询补充必要的 eager loading，减少逐条访问关联 meeting、user 等对象时产生的额外查询。
- 验证重点：单次列表请求的 SQL 数量、响应时间、返回数据一致性，以及较大任务列表下的内存使用。

### 1.4 RegisteredUser query reuse

- 复用已取得的 RegisteredUser 查询结果，避免同一请求链路重复查询相同用户记录。
- 验证重点：同请求内重复查询是否消失、用户权限和关联数据是否保持一致，以及未命中用户时的行为。

### 1.5 Dashboard processing requests optimization

- 优化 Dashboard processing requests 的读取路径，减少重复过滤、重复加载和不必要的请求数据处理。
- 验证重点：Dashboard 首屏耗时、processing requests 查询数量、分页或限制条件下的数据完整性，以及空数据状态。

### 1.6 Dashboard recording jobs optimization

- 优化 Dashboard recording jobs 的查询与组装，降低列表加载的数据库开销和序列化开销。
- 验证重点：不同任务状态组合、较多 recording jobs、失败或重试任务，以及前端展示字段是否完整。

### 1.7 Frontend polling optimization

- 优化前端轮询策略，避免在不可见页面、无相关任务或不需要刷新时持续请求。
- 验证重点：页面可见性切换、轮询间隔、请求取消、组件卸载后的清理，以及状态最终一致性。

### 1.8 Speaker mapping render optimization

- 优化 speaker mapping 的渲染计算和组件更新，减少无关状态变化导致的重复渲染。
- 验证重点：speaker 数量较多时的交互响应、映射编辑和保存后的显示一致性，以及重新加载或切换会议时的状态隔离。

## 2. 已检查但暂不修改的问题

以下问题已完成初步检查，目前保留现状。暂不修改的原因是需要更多真实负载、产品使用数据或额度恢复后的可重复基线；避免在缺乏证据时扩大变更范围。

### 2.1 `reviews/all` pagination

- 已检查该列表的分页现状和潜在查询成本。
- 当前暂不修改，先确认真实数据规模、常见筛选方式、用户是否需要深分页，以及现有响应是否已满足使用场景。
- 后续若确认需要，优先评估稳定排序、服务端分页边界、总数统计成本和索引使用情况。

### 2.2 Meeting detail large response

- 已检查 Meeting detail 返回内容可能偏大的问题，包括会议关联数据、转写/分析结果及嵌套字段。
- 当前暂不修改，避免未经产品确认就拆分响应或改变客户端依赖。
- 后续先测量 payload 大小、序列化耗时、首屏实际使用字段和缓存命中情况，再决定字段裁剪、分段加载或按需展开。

### 2.3 Calendar recent `extracted_json`

- 已检查 calendar recent 数据中 `extracted_json` 的体积和读取路径。
- 当前暂不修改，因为需要确认调用方真实使用的字段，以及裁剪后是否会影响匹配、展示或审计信息。
- 后续以字段使用清单和响应体测量为依据，评估投影查询、延迟解析或独立详情读取。

### 2.4 N+1 query 检查

- 已对主要列表和详情路径进行 N+1 风险检查。
- 当前不做全局性重构；已识别的高价值路径优先通过已有 eager loading、query reuse 和请求级优化处理。
- 后续在代表性数据量和真实权限组合下采集 SQL 计数，再按证据逐条处理，避免为了理论上的 N+1 改变稳定行为。

## 3. Neon 额度恢复后的验证计划

额度恢复后，按以下顺序进行只读或受控验证；每一步记录时间窗口、数据规模、请求样本和前后对比结果。

1. **建立基线**：记录 Worker idle 查询频率、任务领取延迟、数据库连接池使用率、Dashboard 和 meeting detail 的 p50/p95 延迟、响应体大小及前端轮询请求量。
2. **Worker 验证**：在无任务、单任务、并发任务、重复任务和失败重试场景下验证 idle query 与 reconcile duplicate task；确认幂等性和任务状态不回退。
3. **Recording jobs 验证**：对 recording jobs 列表及 Dashboard recording jobs 采集 SQL 数量、总耗时、序列化耗时和内存趋势；对比 eager loading 前后的结果一致性。
4. **用户查询复用验证**：在涉及权限、关联用户和空用户结果的请求中确认 RegisteredUser query reuse 不改变授权判断和返回内容。
5. **Dashboard 验证**：分别测试 processing requests、recording jobs 为空、少量、较多和混合状态的场景，记录首屏和刷新耗时。
6. **前端验证**：检查页面隐藏/恢复、路由切换、组件卸载、网络失败和长时间空闲下的 polling 行为；确认无请求泄漏且最终状态可收敛。
7. **Speaker mapping 验证**：使用少量和较多 speaker 的会议进行编辑、保存、切换和重新进入，确认渲染减少但交互和数据一致性不变。
8. **暂不修改项复测**：测量 `reviews/all`、Meeting detail、calendar recent `extracted_json` 和关键 N+1 路径的真实成本，再决定是否进入开发队列。
9. **验收记录**：将指标、SQL 样本、异常、回滚触发条件和结论写入后续验证记录；本审计文档只记录计划和结论摘要。

验证期间保持现有安全开关和数据边界，不因性能验证启用不必要的付费处理或扩大数据写入范围。

## 4. Admin 权限审计计划

Admin 权限审计与性能验证分开进行，重点确认最小权限、对象级授权和不可越权行为。

1. **权限矩阵**：列出普通用户、会议组织者、获授权参会者、reviewer、admin 等角色，对每个 API 和页面动作标注允许、拒绝或仅本人可见。
2. **对象级检查**：验证 meeting、recording、review、speaker mapping、processing request 等资源不能通过猜测 ID、修改筛选条件或重放请求越权访问。
3. **列表与详情一致性**：比较列表接口、详情接口、导出/下载路径的权限结果，防止列表隐藏但详情泄露，或前端隐藏但后端仍接受未授权操作。
4. **写操作审计**：重点检查 approve/reject、重试、重新处理、speaker mapping 保存、收件人设置和管理动作；确认每项操作均有服务端授权和审计记录。
5. **会话与角色变化**：验证角色变更、过期会话、撤销授权和多标签页状态，不依赖前端缓存作为权限依据。
6. **负向测试**：为每个拒绝项准备未登录、错误用户、错误组织、过期授权和篡改参数样例，记录 HTTP 状态、响应内容和日志行为。
7. **审计输出**：按严重度记录发现、复现条件、影响范围、修复建议和复测结果；未完成审计前不宣称 Admin 权限审计通过。

### Admin Audit 记录

- 已确认 Admin 权限基于注册用户的 `is_admin` 标记，并由后端依赖和对象级授权共同保护。
- 已补充 Last Admin Protection：不能删除最后一个 Admin，也不能撤销最后一个 Admin 的 Admin 权限。
- Admin Audit 仍需覆盖完整的负向测试矩阵、跨用户内容访问审计和异常状态处理；这些属于后续审计工作，不在本次稳定性文档变更中展开。

### Business Unit — Product Decision Item

当前事实：

- 用户通过 Microsoft Entra 登录。
- 首次登录不要求选择 Business Unit。
- 当前系统存在 Business Unit 字段和 Admin 分配能力。
- 当前尚未确认 Business Unit 的业务用途。

这不是当前安全问题。Business Unit 目前只作为已有用户管理数据和分配能力存在，不改变现有登录或权限模型。

未来可能用途：

- Department analytics
- Organization management
- Permission grouping

状态：**Pending product decision**。

在产品决策明确前，不删除 Business Unit，不修改 Business Unit API，也不修改数据库字段。

## 5. Future optimization backlog

按证据和收益排序，后续可考虑：

- 为 `reviews/all` 引入经过产品确认的服务端分页和稳定排序，并评估总数统计成本。
- 对 Meeting detail 进行字段使用分析，必要时拆分摘要与详情响应或按需加载大字段。
- 评估 calendar recent `extracted_json` 的投影读取、延迟解析或缓存策略。
- 为高频列表补充统一的 SQL 计数、慢查询和响应体观测，形成可重复基线。
- 继续检查边界路径中的 N+1，包括权限过滤、关联对象序列化和异常分支。
- 评估 Worker 退避、任务领取批量大小、连接池参数和长时间运行时的资源回收。
- 评估 Dashboard 数据缓存、请求合并和可见性驱动刷新策略的进一步简化。
- 评估前端大列表的虚拟化、结果分段渲染和错误重试上限。
- 为 speaker mapping 和 meeting detail 增加面向真实数据量的性能样本，而不是只依据小样本本地测量。
- 建立性能回归门槛：关键接口 p95、SQL 数量、响应体大小、前端请求数和 Worker 空闲查询均需有可接受范围。

## 审计边界与变更确认

本文件创建过程中：

- 未修改业务代码。
- 未修改 API 契约或路由。
- 未修改数据库 schema、数据或 migration。
- 未执行 deploy。
- 未执行 migration。

后续任何 backlog 项目进入实施前，需单独评估影响范围、验证方案和回滚方式。

## Error Handling Audit

本次已完成小范围 Error Handling 修复：

- Graph / OneDrive 外部异常在 API 边界完成净化，客户端不再收到原始 exception、上游响应、内部 URL 或 stack trace；完整异常仅记录在服务端日志。
- 增加全局未捕获异常处理，统一返回 `{"error": "Internal server error"}`，并记录 exception、traceback、HTTP method 和 request path。
- 前端 API 错误完成安全归一化，避免页面直接展示 SQL、Graph 或 traceback 等 backend 原始错误文本。

未修改、保留为未来优化：

- Calendar malformed data handling
- Database error classification
- Retry/backoff improvements

本次未修改：

- Microsoft Entra
- Authentication
- Permission logic
- Database schema
- Worker / reconcile
- Deployment

## Error Handling Validation

Completed:

- Graph exception sanitization
- Global API exception handling
- Frontend error normalization

Backend focused validation:

- `TestRecordingOwnership`: 3 passed
- The previously reported backend batch result was 106 passed, 5 failed, 1 error.

Known issues:

- `test_graph_client.py::TestLocalMockGraph::test_download_creates_local_marker_file` hit a Windows permission error while pytest attempted to clean `.pytest_tmp`; this is environment related.
- Three `test_recording_jobs.py` failures passed a FastAPI `Query` object directly to the endpoint helper instead of an integer limit; this is a test invocation/fixture issue.
- `test_cross_user_recordings.py::test_request_route_loads_contract_in_one_query` called an endpoint with its unresolved `Depends` default; this is a direct test invocation issue.
- `test_cross_user_recordings.py::test_approved_pipeline_preserves_calendar_access_without_emails` failed existing transcript/action-item grounding validation; it does not exercise the Error Handling changes.
- Frontend `getMe` account-state coverage currently expects the original `Not registered on the platform` response text. The new frontend normalization replaces it with a generic 404 message, so this test is directly affected by the normalization change and needs a compatibility decision before being considered green.

Status:

- Fixed: Graph exception sanitization
- Fixed: Global API exception handling
- Fixed: General frontend error normalization
- Pending: Preserve the explicit unregistered-user sentinel used by `getMe` while keeping other 404 errors sanitized
- Environment related: Windows pytest temporary-directory cleanup

The failures above do not indicate a change to Microsoft Entra, authentication, permission logic, database schema, worker, reconcile, or deployment behavior. No business code or tests were modified during this validation pass.
