# Meeting-Intel 项目状态与后续任务

> 状态日期：2026-09-10。
> 本次更新依据已明确验证的最新 commit、push、staging 部署及验收观察；不是重新运行测试或部署。
> “已实现”不等于“已通过所有真实 E2E”。已完成的真实双用户验收与仍待验证的链路在下文分别记录。

## Current Deployment Status — 2026-09-07

### Git

- Retry/Reprocess 已完成两个 commit：
  - `1f77af274d0f83abd4b4172a494c609b21ca3e3e`：Separate recording processing and review statuses。
  - `f60b3a1c484f42566e7e0bd8f96a3e080f6a2570`：Add retry and safe recording reprocessing。
- 两个 commit 均已 push 到 `origin/main`。
- Participants / Attendees 修复 commit `2148887006cb144b03927fda67a3393f45877abc` 已 push、部署并通过真实 staging 验证。
- T5 MVP commit `caafe365d1e80dd7b1fea106154090c4ef29d8de` 已 push 并部署到 staging。
- `backup-20260828` 保留为备份。
- 未提交 secret、API key、数据库凭据或本地测试媒体。

### Staging

本次部署已成功完成，使用现有资源，未创建新的云项目或 service：

- Frontend：Vercel。
- Backend API：Railway。
- Background Worker：Railway，独立于 API 运行。
- Database：现有 PostgreSQL / Neon。
- Staging URL：[Meeting Intel staging](https://meeting-intel-staging.vercel.app)。
- Worker deployment `767942ef-d3e6-4c8b-aaa7-1c3a5d57ebca`：SUCCESS。
- API deployment `64729e0a-9498-4f11-bc14-ac6948a92fb5`：SUCCESS。
- Frontend deployment：[Vercel deployment](https://meeting-intel-staging-k35k2ux7j-team-22c0.vercel.app)：READY；已确认生成完整 Next.js routes，不只是部署状态为 READY。
- Staging alias：[meeting-intel-staging.vercel.app](https://meeting-intel-staging.vercel.app)。
- Railway API health check 通过。
- Worker 已部署，并确认连接 PostgreSQL。
- 真实付费录音／AI 处理保持禁用，避免现有排队任务意外调用外部 API。
- `RECORDING_PROCESSING_ENABLED=false`、`GEMINI_ENABLED=false`、`EMAILS_ENABLED=false`。
- 本次未调用真实 Gemini、Cloudflare、AssemblyAI，未发送真实邮件。

这证明 staging 服务已上线，不表示真实 AI 处理已达到 production-ready 状态。

### Database migrations

staging 从 `f81c4a7d2e10` 成功升级，依次执行：

1. `3f7a2b61c9d4`：邮件审计记录。
2. `7b2d9e4c6a10`：Worker 租约及 active job 去重索引。
3. `8e31a4c2d907`：已保留代码所需的取消字段及状态。

迁移后实际版本为 `8e31a4c2d907`，schema/version 已复核。现有 meeting/job 数据保留；2 条会议、5 个任务仍在，其中 3 个 pending 任务未被消费。会议、参会者及行动项数据校验值未变。

### Timezone Fix

真实南非用户反馈会议时间显示不正确。

根因：Microsoft Graph 分别返回 `dateTime` 和 `timeZone`，但部分处理路径丢失了时区信息；部分无时区 datetime 又被错误解释为浏览器本地时间或直接视为 UTC。

当前修复：

- 正确解析 Graph `dateTime` / `timeZone`，已有显式 UTC/offset 的值不重复转换。
- 后端统一以明确的 UTC 时间处理和输出，数据库可保存 canonical UTC。
- 前端按用户／浏览器的 IANA 时区渲染，不使用写死的 `+2` / `+8`。
- 当前没有可靠持久化的用户 mailbox/profile 时区，实际显示采用浏览器 IANA 时区，不使用 Vercel 服务器时区。
- Dashboard、Upcoming Meetings、Old Meetings、录音匹配／导入展示及 meeting detail 使用统一的时间处理。
- 南非 `Africa/Johannesburg`、中国 `Asia/Shanghai`、显式 offset 和跨日期转换已有自动化测试覆盖。

已读取的真实 Graph 示例：`2026-08-28T13:00:00.0000000` + `timeZone=UTC`，`originalStartTimeZone=South Africa Standard Time`。归一化为 `13:00Z`，南非应显示 15:00，中国应显示 21:00；实际用户页面仍待人工验收。

### Recording Matching Fix

已修复 recording matching 的函数参数不一致及返回值处理错误：

- `recording_datetime` 正确接收录音文件名和 Graph metadata。
- `match_calendar_event` 正确接收文件名、录音时间及候选会议。
- `event_people` 的邮箱列表／姓名映射返回值按实际结构处理。
- 使用有可靠时区的 Graph 时间，避免把无时区文件名时间戳直接当作 UTC。

这些问题此前导致或促成 meeting date、attendee data、meeting metadata 无法正确补全。修复仅针对现有逻辑，不代表 T5 跨用户录音处理已完成；正确匹配真实会议仍需 staging 用户验证。

### Validation

以下为刚完成部署时的自动化验证结果，本次文档更新未重新执行：

- Backend：282 tests passed。
- Frontend：55 tests passed。
- ESLint：passed。
- Python compileall：passed。
- Next.js production build：passed；Vercel 云端构建及部署成功。

Retry/Reprocess 的最新定向验证结果：

- Targeted backend tests：73 passed。
- Frontend targeted tests：16 passed。
- ESLint：passed。
- Code implemented、committed、pushed，并已部署到 staging。
- Retry / Reprocess 的人工 staging 状态链路已验收，当前阶段完成；这不代表真实 transcription Worker E2E 已完成或 production ready。

只读上线检查：API health、前端到 API 的 CORS、Microsoft 登录页及 OIDC 配置、Graph 日历读取、已部署的 Speaker 试听／映射及编辑申请接口均已确认。完整 Microsoft 登录及登录后 UI 交互未被标记为验收通过。

### Manual staging validation status

真实公司用户 staging 验证状态：

- [ ] 1. Microsoft login 可完成登录并返回 staging。
- [ ] 2. 能看到该用户的真实 Outlook meetings。
- [ ] 3. Meeting title、organiser、attendees、date、time 正确；南非／中国本地显示及跨日期场景正确。
- [ ] 4. Recording 匹配到正确的会议，而非同时间附近的其他会议。
- [ ] 5. 有审核权限时 Speaker audio preview 出现且可播放。
- [ ] 6. Speaker dropdown 包含正确的 Outlook attendees，映射保存后显示正确。
- [x] 7. Attendee edit-request workflow 正常，申请仅限本人参加的会议。
- [x] 8. Organiser 可 approve/reject；批准前不可编辑，批准后仅可编辑获授权会议。
- [ ] 9. 获批参会者仍不能批准最终 meeting notes，不能指定任意收件人；仅允许向本人发送副本。

本轮人工验证不得启用真实付费转写／AI，也不得发送真实邮件。涉及处理的场景使用已完成转写的现有会议；依赖新的真实处理结果的验收保持待验证，不为验收临时解除安全开关。

## Feature Status

### Completed / implemented

以下能力已实现或部署；不代表每项都已通过真实多人验收：

- Microsoft company login。
- Outlook meeting/calendar reading。
- OneDrive recording discovery。
- Recording-to-meeting matching logic（T1，参数及时间处理 bug 已修复，真实匹配待验收）。
- Transcript/review workflow。
- Speaker A/B/C detection。
- Speaker audio preview（T2，已实现并部署，真实试听待验收）。
- Speaker-to-Outlook-attendee mapping。
- Attendee edit-access request（T4，真实双用户 staging E2E 已通过）。
- Organiser approve/reject edit request（真实双用户 staging E2E 已通过）。
- Approved attendee transcript/action-item/speaker editing（真实双用户 staging E2E 已通过）。
- Attendee self-copy email restriction（T3，前后端权限限制已实现，真实角色验收待完成）。
- PostgreSQL job queue。
- Independent background Worker。
- retry/backoff infrastructure。
- job lease/heartbeat。
- stale-job recovery。
- worker shutdown handling。
- staging Worker deployment。
- staging API deployment。
- staging frontend deployment。

### T5 — Cross-user recording processing

**Status: MVP IMPLEMENTED、COMMITTED、PUSHED、DEPLOYED TO STAGING；REAL CROSS-USER E2E NOT COMPLETE。**

业务规则：T5 不允许未参加会议的人申请。当前用户必须是该会议的 organizer 或 attendee。如果当前用户参加过会议，但 recording 存储在另一个已注册／opt-in 用户的 OneDrive，当前用户可以 Request Processing；Recording Owner Approve/Deny 后，系统才允许处理该 recording。

T5 MVP 当前事实：

- 已实现、commit、push，并部署到 staging。
- Commit：`caafe365d1e80dd7b1fea106154090c4ef29d8de`。
- Migration：`ae52c790b316`。
- Backend targeted tests：39 passed。
- Frontend targeted tests：11 passed。
- Recent Meetings 已在真实 staging 显示过去 7 天会议。
- processed meeting 可显示 View。
- Request Processing 的 frontend、backend、model 与 approval flow 已实现。

但 T5 real cross-user E2E 尚未完成。真实页面中，一些应该属于跨用户场景的会议仍显示 `No recording found` 或 `No reliable recording found`。因此以下真实链路尚未验证成功：

`cross-user OneDrive discovery/matching -> Request Processing -> owner approve -> queued`

T5 不能标记为 fully validated。

### Background sync

Pilot proposal，尚未通过 production 验证：

- 大约每 15 分钟 polling；这是试点方案，不是已确认启用的生产调度。
- 优先合理使用资源，避免不必要的同步和外部请求。
- Opt-out 应停止未来同步和 AI 处理。
- 已有历史 Meeting Intel 数据继续可访问，不因退出而删除。

### T6 — AI meeting insights

- Gemini adapter / provider abstraction 已存在。
- Mock/offline processing 已存在。
- 公司真实 AI 凭据尚未接入使用，真实 AI 处理未验收。
- 计划输出：Summary、Key points、Action items、Risks、Next steps。
- Gemini 仍是首选 meeting-insights provider。
- 正式 transcription provider 尚未最终选定。
- 候选包括 Gemini Transcribe，以及 Cloudflare Whisper 等较低成本转写服务。
- 最终选择必须依据真实公司会议的准确率和成本测试；这些候选不代表已接入或获准调用。

### T7 — Worker

**Current status: DEPLOYED TO STAGING。** 不再描述为“未部署”。

已实现 PostgreSQL queue、retry/backoff、deduplication、lease/heartbeat、stale recovery、graceful shutdown，并完成 Railway staging 部署及 PostgreSQL 连接验证。

真实付费 AI／transcription execution 有意保持禁用。服务已上线不等于真实转写消费、异常恢复及多人流程已完成生产验收。

### Processing status / Retry / Reprocess / Cancel

**Status: IMPLEMENTED、COMMITTED、PUSHED、DEPLOYED TO STAGING；CURRENT PHASE COMPLETE。**

用户提出导入／转写／处理阶段更清晰的进度展示、失败任务 Retry，以及 queued/running 任务 Cancel。

Retry/Reprocess 已分两个 commit 完成；processing status 与 review status 已拆分，并加入 Retry 与安全 Reprocess。定向验证为 backend 73 passed、frontend 16 passed、ESLint passed；代码已 committed、pushed，并已部署到 staging。

当前 staging UI 已观察到：

- Processing / Review 已分列。
- Cancelled job 显示 Retry。
- Approved Completed 显示 View-only。
- clean Awaiting Review Completed 可显示 Reprocess + View。
- 某些 Awaiting Review Completed 只有 View，表示 `can_reprocess=false`。

已人工验证真实 staging UI 状态链路：`Reprocess -> Queued -> Cancel -> Cancelled -> Retry`。Retry / Reprocess 当前阶段视为完成。

该验收不代表真实 transcription Worker E2E 已完成，也不代表真实付费处理已达到 production ready。`RECORDING_PROCESSING_ENABLED=false` 仍保持不变，自动处理没有开启。

### Participants / Attendees

**Status: FIXED、COMMITTED、DEPLOYED、VALIDATED ON REAL STAGING；COMPLETE。**

- Dashboard participant count 正确。
- Meeting Detail attendees 正确。
- Commit：`2148887006cb144b03927fda67a3393f45877abc`。

### Multi-user Edit Access

**Status: REAL TWO-USER STAGING E2E PASSED；COMPLETE。**

已通过 attendee Request Edit Access、organizer approve、attendee edit、Save speaker names 的真实双用户 staging E2E。CORS 问题已修复；Sphesihle 实际复测回复 “works”。

### Performance Optimization

**Status: CORE DASHBOARD PATHS OPTIMIZED；FINAL VALIDATION PARTIALLY PENDING。**

已完成：

- Dashboard initial render optimization：
  - 首屏不再等待全部慢 API。
  - 页面框架先显示，数据异步加载。
- Recent Meetings optimization：
  - `/calendar/recent` 优先读取 `synced_calendar_events`。
  - 页面请求不再实时扫描 Microsoft Graph / OneDrive。
- Upcoming Meetings optimization：
  - `/calendar/upcoming` 优先读取同步数据。
- Process Past Recording optimization：
  - `/recordings/available` 使用同步数据。
  - 页面请求不再扫描 OneDrive。
- Recording Processing Requests optimization：
  - 修复 N+1 查询。
  - 减少重复请求。
  - 保持 approval flow 不变。
- Reviews optimization：
  - `/reviews/all` 减少列表响应大小。
  - 不加载 `transcript` / `extracted_json` 等详情字段。
- Historical Access optimization：
  - SQL 提前过滤 attendees。
  - 减少 Meeting 字段加载。
  - 当前 PostgreSQL JSONB 类型兼容问题已修复，等待最终验证。

当前页面请求架构：

优化前：

```text
Frontend request
→ API
→ Microsoft Graph
→ OneDrive
→ Database
→ Response
```

优化后：

```text
Frontend request
→ API
→ Persisted synced data
→ Database
→ Response
```

页面请求路径已减少对 Microsoft Graph / OneDrive 的实时依赖。

### Remaining Performance Items

- Meeting Detail：
  - 需要验证首屏加载时间。
  - 可能存在 `transcript` / `extracted_json` 大字段影响 SSR。
- Historical Access：
  - 已优化。
  - 需要 staging 最终验证。

### Remaining known gaps

- T5 real cross-user recording discovery E2E。
- Meeting Detail 首屏性能验证。
- Historical Access staging 最终验证。
- Background sync。
- Admin override/control。
- Real transcription / Gemini / email E2E。
- Teams native transcript。
- Nested OneDrive discovery real-user acceptance。

### T8 — Email workflow validation

邮件预览、权限限制及审计相关实现已保留；真实邮件发送、失败恢复及不重复发送仍需单独授权后的验证。本轮不发送真实邮件，不因状态为 approved 就宣称邮件已送达。

### T9 — Teams native transcripts

**Status: PLANNED。**

存在 Teams 原生 transcript 时优先导入，避免付费 MP4 重复转写；MP4 transcription 作为 fallback。原生 transcript 获取权限、说话人／时间戳、与 MP4 路线的去重均待实现或验收，不标为已完成。

### T10 — Full multi-user E2E validation

**Status: PENDING。** 需真实组织者及参会者完成全链路、角色权限与异常恢复验证，才能宣称多人端到端稳定。当前部署、单元测试和只读检查不能替代该验收。

## Immediate Next Step

Retry / Reprocess、Participants / Attendees、Multi-user Edit Access 与核心 Dashboard 性能优化当前任务均已完成。剩余性能事项仅为 Meeting Detail 首屏加载时间验证，以及已优化的 Historical Access staging 最终验证。其他后续重要工作保持为：T5 real cross-user recording discovery E2E 与 background sync；另有 Admin override/control、real transcription / Gemini / email E2E、Teams native transcript，以及 nested OneDrive discovery real-user acceptance。T5 MVP 已部署，但在真实跨用户发现、匹配、申请、owner 审批并 queued 的整条链路成功前，不标记为 fully validated。

继续遵守安全边界：secret 和本地测试媒体不进入 Git；真实付费 AI 和邮件发送保持关闭，直至获得明确授权。staging 不等同于正式生产环境。
