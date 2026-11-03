> 2026-11-03 发布执行补充见文末。前文的“未提交／不发布”是 11-02 与清单阶段记录；当前用户已授权本窗口提交、推送、部署及只读验收。

# 管理员审计与处理监控：实现前核查

基线：2026-11-02 拉取 origin/main，bcbb64c。独立 feature/processing-audit-monitoring 工作树。未读取线上凭据、数据库或触发供应商。

- 已有：audit_events（唯一 event_key、资源/会议/关联 ID 索引）；调用者事务内写入；审计查询严格元数据白名单；管理员依赖和 no-store；时间窗口/游标/身份筛选；Admin 审计列表、加载失败/Retry。
- 已有：录音创建、Retry、Reprocess、取消请求/完成、worker 领取及结果事件；现有租约与 admission_version 隔离旧任务。针对权限、事务、敏感内容和分页的测试。
- 部分具备：recording_jobs 的 attempts、submission_count、provider_status、provider_transcript_id、audio_duration_seconds。submission_count 在 HTTP 前预留，不能证明已发送/已接受。当前供应商 checkpoint 不写审计。
- 部分具备：BusinessAI 本地预算 SQLite 记录返回 token，但以输入 fingerprint 关联，无 durable job 外键；不能将历史预算预留当作该 job 实际用量。AI extraction requested/completed 不是供应商提交证明。
- 缺失：job/录音/当前状态关联筛选；管理员安全 job 指标；供应商接受/不确定结果审计及用量展示；费用证据。历史精确处理时长不能用 updated_at-created_at 代替。
- 保留：未发现 audit_events 自动清理/TTL；现有删除 job 无 audit FK 级联。数据库备份保留、平台运行日志保留期限未在仓库证实，仍为未知。不新增清理规则。
- 线上可用性：仓库具备以上实现，不等于线上已部署/迁移/实际写入。本轮禁止线上数据库/部署操作，因此线上实际可用性均未验证，不宣称上线完成。

补齐边界：复用原表及原页面，在既有租约事务中补供应商事件；只返回白名单及已核实数值，不回传原始 last_error、provider ID、正文或 key。不改转写决策、worker 开关和授权。

## 本轮交付与原有实现的边界

- 原有：audit_events / 唯一事件键 / 权限与 no-store / 审计列表与详情 / 时间、身份、事件类型与结果筛选。原有 recording.import、retry、reprocess、cancel、started、cancelled、processing 与 AI extraction 事件继续使用，不另建日志系统。
- 新增：在 jobs.py 的成功入队事务内统一写 recording.created，补齐非手工路径；既有手工事件仍表示用户动作，created 表示队列创建事实，不将二者计作两次提交。
- 新增：在原供应商 checkpoint 的行锁、租约、授权条件内写 provider.reserved / submitted / submission_unknown / completed / failed / poll_unknown。每 job、每阶段使用稳定唯一键；重复 checkpoint 在锁内检查原表，重复读/刷新不写指标。未更改供应商调用、重试或 worker 授权逻辑。
- 新增：原审计查询支持 job UUID、录音 drive_item_id、当前 job 状态。游标包含这些筛选的指纹；切换筛选不能挪用旧游标。按录音查询覆盖仍保留 job 的该录音各次处理；删除 job 后只能用保留的 job ID 查事件，录音归属无法重建时不猜测。
- 新增：/admin/processing-monitor 复用管理员依赖，返回最近 50 个匹配创建时间的 job，并从原审计表按 job 汇集证据。超过 50 提示缩小范围；事件列表沿用原有分页。状态筛选是当前状态，事件中的 previous/new_state 是历史状态。时间在监控区指 job 创建时间，在事件区指事件发生时间，页面有明确说明。
- 新增：在现有 AI bridge 将供应商实际返回且合法的 token 计数经 ContextVar 传给既有 extraction 成功/失败事件，沿用原 fenced commit。任务间隔离，取消后 reset；未写 prompt、逐字稿、响应正文、输入 fingerprint 或密钥。
- 新增：Admin 原页面显示当前状态、attempts、已证实转写接受次数及证据来源、供应商状态、报告的音频时长、AI token 明细、可配对的本次处理时长、安全失败阶段/类别、三种费用说明；新增监控区独立加载失败/重试，权限 token 更换立即隐藏旧结果，过期请求不能覆盖新结果。
- 补正测试：main 中两处旧断言仍要求失败自动回 pending；按 main 已有人工核对逻辑改为 failed/no automatic retry，没有改 worker。新增 created 事件后，原测试按对象类型/调用顺序检查 job 与审计同事务。

## 未知值与计量口径

- transcription submission_count 是 HTTP 前预留，本轮不直接展示为实际提交次数。submitted 审计或已有 provider_transcript_id 证明至少一次接受；现有每 job 至多一次付费 submit 协议下显示 1。只有预留、attempts、排队或超时无接受证据时显示 Unknown，不显示 0。供应商 ID 本身不返回页面。
- AI 返回用量可证明一次已返回计量的请求；显示去重后的“有返回用量的提交数”。这是有证据的下限，AI 总提交数仍 Unknown；预算预留、AI extraction_requested 和本地 mock 不算真实提交。历史本地预算账本没有 job 关联，不导入或回填。
- token 使用明细逐条显示原返回数值，不按刷新或事件列表分页累加。音频时长仅展示原 audio_duration_seconds，不拿处理墙钟时间充当计费时长。
- 处理时长只配对当前 attempt 唯一 started 与 terminal 事件；缺失/歧义/倒序即 Unknown。不是 updated_at-created_at，也不伪造队列耗时、历史 attempt 汇总或供应商耗时。
- 实际费用 Unknown：无发票/账单证据。估算费用 Unknown：无已核实费率、币种及计费模型，未引入价格表。未知费用单独明确标注，零费用也不能猜。
- 原始失败文本可能含个人信息或密钥，仅经既有 processing_failure_info 识别安全枚举，否则 Unknown / no record。
- 历史任务无事件、取消中断后未能持久化的响应、无 job 关联的供应商用量、已删除 job 的录音归属都不能完整恢复。新代码不能追溯补造它们。

## 脱敏验证证据

- 受影响后端：193 passed。涵盖原审计权限/筛选/事务/结果、AI bridge、入队、取消、Retry/Reprocess、清理；新增合成 job、重复事件、唯一约束、提交 checkpoint 锁、无身份/普通用户/管理员、未知用量和安全字段测试。conftest 全程禁用真实网络及供应商，使用内存 SQLite 验证已有审计唯一约束和 AI 用量事务。
- Admin：46 passed。新增 job/录音/状态筛选双接口一致性、未知费用、报告 token、刷新不累计、监控失败重试和 token 更换隐藏旧数据测试。
- TypeScript：node node_modules/typescript/bin/tsc --noEmit，exit 0。
- 必要生产构建：next build --webpack 成功，包含 /admin/audit-logs。默认 Turbopack 由于本地 node_modules junction 越出项目根目录而失败；复用已安装依赖未改 package/lock/Next 配置，webpack 构建通过。此结论不表示线上部署已验证。
- 浏览器：scripts/verify_processing_monitor_ui.mjs 渲染实际 Admin client 与原样式，仅使用合成 fixture；拦截非 loopback 网络，desktop 1280x900 / narrow 390x844，无页面整体溢出，事件表沿用局部横向滚动。筛选、错误脱敏、重试成功；无外部请求或浏览器异常。artifacts/processing-audit/browser-results.json 和三个截图为合成证据，完全不含真实用户/会议/供应商凭据。截图不代表登录流程或线上可用性验证。
- git diff --check 通过。未运行无关全量测试；未启动 worker、未转写、未实际调用供应商、未连接线上数据库、未改开关或部署，未提交/推送。

## 审查报告

- 权限：两个读取接口均使用原 _require_admin，原页面服务端管理员检查不变，普通用户/未注册用户/无认证分别验证拒绝。响应 no-store。前端权限变化、请求替换和异常不保留已失效身份的指标。
- 可靠性：提交预留与接受分开；provider 事件在原 job 行锁/租约/取消/授权校验内，与 checkpoint 同事务写入。唯一键是最终防线，去重不依赖浏览器。任务 created 与入队同事务；失败/回滚不能留下虚假成功事实。未改旧任务 admission 隔离。
- 数据最小化：无 key、prompt、逐字稿正文、原始异常、供应商响应/ID，未新增录音标题、参与者或 owner 信息。仅保留既有必要操作者身份和白名单计数。
- 兼容：无表/列变更，无迁移；既有事件键和 API 事件输出形状保留，新增筛选进入指纹，旧在途游标可能需 Refresh 开始新遍历。监控区刻意限制 50 jobs，数据多时需缩小筛选；暂不做跨 job 总费用或全部历史统计。
- 限制：未在线上验证实际部署、迁移状态、备份保留或生产规模查询性能。审计表现有 correlation 索引并非 job_id 专用索引，若生产记录规模导致查询慢，应先取只读执行计划再决定是否加索引；本轮不猜测生产规模并新增迁移。

## 独立工作树与整合（2026-11-03 复核）

分支 feature/processing-audit-monitoring，目录 C:/Users/93547/.codex/worktrees/processing-audit-monitoring/Meeting-Intel。HEAD 与本地 origin/main 均为 bcbb64c；本分支没有额外提交，交付全部在未提交 diff 和新文件中。主目录 main 为 d965b65，落后 origin/main 16 个提交且有其他未提交工作，不能作为本轮补丁基线。本次未 fetch，以上是本地引用快照，远端是否更新尚未核实。

- 相对 origin/main：18 个已跟踪文件变更，新增 2 个业务模块、1 个后端测试、1 个浏览器验证脚本、本文及 4 个合成证据文件（完整路径见下节）。业务范围仅为审计写入、只读监控接口和 Admin 原页面；没有 models/schema、依赖、配置、开关或迁移改动。
- 相对本地主目录 main：除上述本轮改动，还包含已经在 origin/main 的 16 个提交。runtime_bridge.py、jobs.py、transcription_submission.py、test_recording_jobs.py、frontend/src/lib/api.ts、types.ts 在这 16 个提交中也发生过变化。整合应以 bcbb64c 或其后继为基线，不能把 main..本工作树整体差异当作本功能提交，也不能整文件复制到旧 main。
- 会议分析/草稿工作树 feature/meeting-insights-foundation：HEAD a1cd4cb 已是 origin/main 祖先，没有独立待整合提交；其当前未提交改动与本轮真正同文件的是 frontend/src/lib/api.ts 和 frontend/src/lib/types.ts。保留其会议草稿 API/类型及本轮 getProcessingMonitor、AuditFilters、ProcessingMonitorJob/Page。它当前没有修改 runtime_bridge.py，旧说明中的该冲突点已纠正。它另有未跟踪迁移 62e9a3b8d014_meeting_insight_drafts.py，不属于本轮包。
- BusinessAI 集成工作树 feature/businessai-integration：HEAD 69ce893 已是 origin/main 祖先；当前新增 meeting_insights_adapter.py、对应测试和评估文档等，与本轮无同文件修改。既有 BusinessAI 适配器和预算逻辑已在共同基线内。本轮 runtime_bridge.py 只增加 capture_usage 导入及调用，读取既有 provider.reported_usage，缺失时保持未知。
- BusinessAI 证据/分析草稿工作树 codex/businessai-evidence：HEAD 5e2b58b，相对 origin/main 有 f2420a1、5e2b58b 两个独立提交。以共同祖先比较其新增提交，并叠加当前未提交文件后，与本轮同文件为 frontend/src/lib/api.ts 和 frontend/src/lib/types.ts；没有 runtime_bridge.py 的独立改动。保留 analysis draft API/类型和本轮监控 API/类型；禁止整文件覆盖。其 a710e9c2d004_analysis_drafts.py 迁移属于另一发布包。
- recording-loading-review 当前 HEAD 37710ab 的独立提交及未提交内容与本轮无同文件改动；旧说明中 api.ts/types.ts 的可能重叠在本次快照未出现。
- 主目录脏工作区另有 runtime_bridge.py、frontend/src/lib/api.ts、types.ts 与本轮重叠；这是独立未提交来源，不等于上述工作树已整合。单个整合窗口必须确认哪些主目录改动需要保留，不能用本轮文件覆盖它们。

同文件不等于必然产生 Git 冲突；目前没有执行合并。实际文本冲突以最终集成基线为准。今天只修正文档缺口，没有改变业务代码或重跑既有测试。

## 修改文件清单

- `app/ai/runtime_bridge.py`
- `app/api/admin.py`
- `app/services/ai_audit.py`
- `app/services/audit.py`
- `app/services/audit_queries.py`
- `app/services/jobs.py`
- `app/services/transcription_submission.py`
- `app/tests/test_ai_processing_audit.py`
- `app/tests/test_audit_query_api.py`
- `app/tests/test_job_controls.py`
- `app/tests/test_recording_action_audit.py`
- `app/tests/test_recording_jobs.py`
- `app/tests/test_recording_outcome_audit.py`
- `frontend/src/app/admin/audit-logs/__tests__/audit-logs.test.tsx`
- `frontend/src/app/admin/audit-logs/audit-display.tsx`
- `frontend/src/app/admin/audit-logs/audit-logs-client.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/lib/types.ts`
- `app/ai/audit_usage.py`
- `app/services/processing_monitor.py`
- `app/tests/test_processing_monitor.py`
- `artifacts/processing-audit/`
- `docs/processing-audit-monitoring.md`
- `scripts/verify_processing_monitor_ui.mjs`

## 可执行发布清单（交给单个整合窗口）

以下复选框均为未来操作，未代表本窗口已提交或发布。

### 1. 固定基线与提交边界

- [ ] 在整合窗口更新远端引用，记录最终 main SHA；确认 bcbb64c 是其祖先。若不成立，先核查基线，不将旧 main 的历史差异一并打包。
- [ ] 在本原工作树按下节分组逐路径暂存，禁止 git add .；检查 git diff --cached --name-status 与下面完整清单一致。提交前运行 git diff --cached --check，并确认未带入凭据、真实录音或其他工作树文件。
- [ ] 必须一起提交的 13 个业务文件：app/ai/audit_usage.py、app/ai/runtime_bridge.py、app/api/admin.py、app/services/ai_audit.py、app/services/audit.py、app/services/audit_queries.py、app/services/jobs.py、app/services/processing_monitor.py、app/services/transcription_submission.py、frontend/src/app/admin/audit-logs/audit-display.tsx、frontend/src/app/admin/audit-logs/audit-logs-client.tsx、frontend/src/lib/api.ts、frontend/src/lib/types.ts。
- [ ] 同包保留修改文件清单中的 7 个后端测试和 1 个 Admin 测试；保留本文、scripts/verify_processing_monitor_ui.mjs 及合成证据 artifacts/processing-audit/admin-390.png、admin-desktop.png、admin-error-390.png、browser-results.json。证据不参与应用运行。
- [ ] 先处理 api.ts/types.ts 的会议草稿与 BusinessAI 同文件整合；若纳入主目录改动，再逐段处理 runtime_bridge.py。保留本轮 ContextVar 交接，以及原供应商选择、准入、预算和调用路径。
- [ ] 沿用昨天后端 193、Admin 46、tsc 及 Webpack 构建通过的记录。仅当集成产生相关代码变化时检查受影响路径；不为本次文档交接重新跑这些套件。

### 2. 迁移与发布顺序

- [ ] 本功能新增 Alembic revision 数为 0，不运行本功能专属迁移，不回填历史事件或用量。仍依赖已存在的 audit_events 和 recording_jobs 供应商账本列；“无新迁移”不等于目标库已具备基线结构。
- [ ] 整合窗口在既有受控流程中核对目标库版本与最终集成代码的 Alembic heads。供应商账本列由既有 92d6a10f4e72 提供；会议草稿 62e9a3b8d014、BusinessAI 分析草稿 a710e9c2d004 如同时纳入，单独核对 revision 链和执行顺序，不在本包复制或另开迁移窗口。
- [ ] 先发布兼容本接口的后端，再发布 Admin 前端；确认 GET /admin/processing-monitor 可用后再验页面。沿用既有环境配置，不开启 worker、不授予处理权限、不安排真实供应商调用。
- [ ] 若回退，回退本包应用代码即可；本包无 schema downgrade。已写入的新事件保留，不清表，不因回退重试不确定提交。

### 3. 上线后只读验收：管理员

- [ ] 用已注册且 is_admin=true 的真实管理员登录 /admin/audit-logs；确认页面出现监控区。浏览器 Network 检查后端 GET /admin/audit-events 与 GET /admin/processing-monitor 均 200、Cache-Control: no-store。不要导出含认证头的 HAR 或复制 token 到证据。
- [ ] 用已存在且获准查看的 job UUID、drive_item_id、当前状态筛选；确认两个请求携带同一组 job/录音/状态条件。监控时间按 job 创建时间、事件列表按事件时间；默认 7 天，最长 90 天。超过 50 个 job 应提示缩小范围；切换筛选重新开始事件分页。
- [ ] 核对下列计量口径，只查看已有数据：provider.reserved / requested 仅代表 HTTP 前预留，不能增加 confirmed_submissions；provider.submitted / succeeded 才是接受证据（或历史已持久化 provider 引用），当前每 job 至多一次接受，显示 1；provider.submission_unknown / unknown 不单独增加接受次数，也不能显示为确定失败或 0。
- [ ] provider.poll_unknown 是接受后的轮询不确定，与提交不确定分开。已有接受证据的 job 即使后续结果不确定，接受次数仍为 1；这不证明完成或计费。completed 供应商事件也不等于会议结果已保存。
- [ ] 无接受证据的历史 job、只有 attempts/submission_count/预留或排队的 job，接受次数必须 Unknown；无可配对 start/terminal 的时长必须 Unknown；无用量事件的 AI 次数/token 必须 Unknown。不要从旧预算账本推导或回填。
- [ ] 如有既存 AI 用量，逐事件显示返回 token，重复刷新、翻页不能累加；AI 总提交数仍 Unknown。实际费用、估算费用、账单证据均 Unknown；音频时长仅展示供应商原值，缺失仍 Unknown。
- [ ] 列表与详情不得出现供应商 ID、原始异常、正文、prompt、key。可用浏览器阻止单个监控 GET 来验 Retry monitoring，解除阻止后重试应恢复，事件区不被监控错误覆盖。
- [ ] 没有上述某类既存事件时标记“线上样本缺失，计量验收待观察”，引用昨日合成证据作为本地依据；禁止为补样本点击导入、Retry、Reprocess、录音处理或触发供应商。

### 4. 上线后只读验收：普通用户及未登录

- [ ] 另用无管理员权限的已注册普通用户会话，直接访问 /admin/audit-logs 应跳回 /；普通用户本人 token 访问两个后端 GET 均 403，无监控/审计数据返回。仅隐藏导航不算权限验收通过。
- [ ] 未登录访问页面应转 /login；不带 Authorization 请求两个后端 GET 均 401。生产不能使用 mock token 绕过登录。
- [ ] 管理员退出后切换普通用户，确认旧监控结果不可见，迟到请求不能恢复管理员数据；刷新或直接输入页面 URL 仍被拒绝。
- [ ] 留存发布 SHA、环境、验收时间、角色（不记录 token/个人明细）、两个接口状态码、脱敏页面截图及每项通过/失败/样本缺失。权限泄漏、未知变成零或三类事件被混算均阻断验收，交整合窗口修复或回退。

今天完成：只读核对代码/工作树/本地引用及文档修订，git diff --check；未重跑昨日测试、未提交/推送、未部署、未连接线上数据库、未启动录音或供应商请求。上线状态仍未验证。

## 2026-11-03 五类审计复核与发布执行

远端 fetch 后 main 仍为 bcbb64c。所有改动从此基线逐段追加；没有合入会议草稿或 BusinessAI 分析草稿提交，没有新增 Alembic revision。目标 Railway 项目 meeting-intel-staging / production；Vercel 项目 meeting-intel-staging / production。这里 production 指既有服务环境名，不将 staging 域名描述为其他生产系统。

### 原任务五类覆盖

- user actions：原 recording.import/retry/reprocess/cancel 保留用户 UUID、UPN、job 和关联 ID。补会议人工 decisions_saved、action_item_edited、transcript_edited、speakers_edited；和业务写入同事务。审批事件沿用 email.approved。未更改内容、审批、编辑或查看权限。
- processing events：created 与入队同事务；started 与领取、processing/cancelled 与 fenced terminal 同事务；供应商 reserved/requested、submitted/succeeded、submission_unknown/unknown 与原 checkpoint 同事务，仍经 lease、admission、取消和行锁保护。completed/failed/poll_unknown 独立记录，不推断发送或计费。供应商每 job/阶段稳定唯一键，刷新不产生处理事件。
- summary generation：原 ai.extraction_requested/completed/failed 已覆盖摘要及 action extraction，沿用 fenced commit。只补供应商实际返回的合法 token，未启用真实 AI；历史 transcript_only 或无用量事件不被当作供应商提交。不能将历史 summary 内容反推生成时间或供应商用量。
- email approvals：原 approval_requested、approved、send 保留；补 email.previewed（仅预览，没有发送）及个人副本 copy_requested/copy_result。副本失败只存安全类别，未知接受结果为 unknown；两阶段共享关联 ID。发送关闭时只记录请求，不伪造已发事件。自动邮件、Graph 发送门禁均未开启。
- access history：原 participant 的当前权限和最近决定信息不是完整历史；补 access.requested/edit_requested/approved/denied/shared/revoked 与权限变更同事务；补已授权 meeting.viewed。查看和预览在成功响应前持久化。新增用户活动使用基于规范 UPN 的命名空间 UUID 和 UPN 快照，受影响用户只记录稳定 UUID，管理员可用 actor UPN 定位；不复制其邮箱到 metadata。

新增事件都使用既有 occurred_at 数据库时间、actor、动作、resource/meeting ID、outcome、correlation_id 和唯一 event_key。无 durable job 的会议活动 job_id 保持空，不伪造 job。Admin 新增 Manual review & viewing / Access history 事件筛选，详情展示完整资源和关联 ID；权限变更的 affected user reference 经前后端 UUID 白名单。

活动读取每次成功 HTTP 请求是一次查看事实；重复浏览可以留下多条查看事实，但不参与录音/AI 提交计量。人工编辑事件表示一次已提交动作，不将它们计为供应商调用。原审批重复提交沿用状态/指纹与锁阻止重复发送；分享已存在权限、已 pending 编辑请求等无新变更返回路径不补造事件。历史行为不回填。未全面审计列表浏览、搜索、音频片段读取、登录失败和所有管理账号操作；这不是完整安全访问日志，属于剩余范围，不宣称已完成。

### 新增改动、共享文件和验证

本次在上节原发布包之外新增业务 app/services/activity_audit.py，并增量修改 app/api/reviews.py、admin.py、audit.py、audit_queries.py 和 Admin 事件标签/筛选。reviews.py 与会议草稿工作树及主目录本地修改也重叠；只改既有路由的审计调用，没有复制草稿功能。api.ts/types.ts 仍仅追加审计必需字段和接口，其他工作树文件未修改。

新增 app/tests/test_activity_audit.py、修改 test_api_reviews.py 的 UUID/同步 add 夹具及新审计断言；test_meeting_decisions.py 的隔离库创建原有 audit_events，并将旧 head 断言更新为已发布 92d6a10f4e72，无迁移文件改动。新增 scripts/inspect_processing_audit_release.py 仅用只读事务输出 schema head、事件分类计数、字段/唯一性检查和安全开关。

沿用昨天 193 后端、46 Admin、Webpack 构建通过记录。今天仅受新增审计影响的检查：121 后端通过；新增页面筛选/脱敏检查 1 通过（原 46 未重复运行）；tsc --noEmit 通过。事务回滚无孤立审计、拒绝编辑不留下成功事件、预览不触发发送、三类供应商事件不混算均有针对性断言。另此前原邮件批准审计 23 项通过。git diff --check 通过。

### 数据库与发布门禁

只读实查 head=92d6a10f4e72，audit_events 存在；预检时无 pending/processing jobs。已有事件键无重复，时间、身份、资源、关联 ID 必填字段完整。已有 AI requested/completed、录音 import/retry/reprocess/cancel/cancelled/started/processing 成功和失败样本；新 provider 事件、邮件和访问历史样本在预检时不存在，不补造。

预检证据 artifacts/processing-audit/production-preflight.json；该文件只有聚合计数和安全配置，无录音内容、身份或凭据。没有运行迁移。worker 原 RECORDING_PROCESSING_ENABLED=true；本次更新 worker 必须以 false 启动，防止发布领取录音，暂停处理的状态在最终交付报告中明确说明，不自动恢复真实调用。

用户明确授权：线上仅 Wei Jiuyang 管理员会话及未登录验收；普通用户 403 与切换身份清除数据采用已有本地测试，报告为“本地通过，线上普通用户会话未验收”。不创建账号、不改任何人的管理员权限。

发布 SHA、部署 ID 与上线后只读验收结论另记 release-result.md / production-postflight.json；在取得证据前不标已验收。


### 前端独立补发：7 行内部滚动

用户在首轮部署完成后补充要求：保持每页数据量和分页，仅限制 Audit Events 的可视区域。新增可键盘聚焦的滚动区域，按当前表格前 7 条实际行高计算最大高度；横向滚动仍局限在表格，th 使用 sticky top-0。ResizeObserver 随列宽/字体变化重新测量并在卸载时清理，分页后回到表格顶部。没有改接口 limit 或分页游标。

验证 scripts/verify_audit_scroll_ui.mjs：12 条合成事件只显示 7 行高度，desktop/narrow 均测得区域 804px、前七行加表头 803.5px，内部可滚动 545px；滚动到底后表头位移 0.5px。Previous/Next、页数/每页计数、筛选、加载失败重试仍通过；无非 loopback 请求和浏览器异常。tsc --noEmit 通过。新证据在 artifacts/processing-audit-scroll/，旧合成证据保留。

首轮源代码 222cf86；API 部署 1ac9a4b6-a644-498b-bd80-5cc3d3091b44、worker 87e70a7c-4b38-4a9c-bc90-506f4b83c7d9、Vercel dpl_97eyD1Qcu38E6jwsvzSkRyPmwuss 均成功。API health=200；两个审计 API 无认证=401。API 容器 admin.py/reviews.py/processing_monitor.py SHA256 与发布源匹配。

用户补充要求恢复原自动处理：worker RECORDING_PROCESSING_ENABLED 已恢复 true；配置恢复部署 38f8cb63-daec-4b87-b3e0-ee40bb1c1b26 成功，SSH printenv 实查 true；仍为 222cf86 worker 代码。没有因前端补丁重新部署 API/worker，没有手工创建任务或调用录音、AI、邮件接口。邮件与 BusinessAI 开关保持关闭。

管理员线上页面验收暂未完成：浏览器扩展两次报告 Debugger unattached；窗口恢复工具因无法可靠识别 URL 而停止。已请用户将管理员 Chrome 页面恢复前台，不把数据库只读预检或本地截图冒充真实管理员页面验收。


### 最终发布与验收证据

前端补发 76e7e0d / dpl_FbDeV88PeJM4v5aj7vAS1jSUwhUX 已 READY 并绑定原域名，API 未再部署。用户实际打开管理员页面后，06:54:42 UTC 服务日志记录两个审计 GET 均 200；未认证两个 GET 均 401。证据只保留时间/路径/状态，详见 artifacts/processing-audit/live-api-requests.json、unsigned-live-check.json。普通用户与账号切换保持“本地通过，线上未验收”。浏览器工具仍无法可靠识别 URL，管理员完整视觉交互未验收，没有绕过工具限制。

worker 配置恢复部署 38f8cb63-daec-4b87-b3e0-ee40bb1c1b26 SUCCESS，容器实查 processing=true、emails=false、BusinessAI=false，源文件哈希仍匹配 222cf86。发布后数据库 head 不变，active_jobs=0，事件分类聚合与预检一致；不制造样本。

五类事件的逐项状态、真实线上证据与待观察项见 artifacts/processing-audit/release-result.md；机器可读部署版本见 deployment-result.json。新证据提交仅归档发布结果，不要求再次部署任何服务。
