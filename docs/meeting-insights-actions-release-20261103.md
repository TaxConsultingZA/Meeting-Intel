# Meeting Insights 与 Action Items 发布候选审查

2026-11-03，UTC+8。实现、相关测试及本地开发服务器浏览器验收完成；生产服务器运行验收被环境策略阻止。没有提交、暂存、推送或部署。

## 工作树与来源

- 干净基线：`4d1d62ef90158624c0b17b1f05ded646b79ab25c`，包含最新审计布局 `7b082d5`。独立分支 `codex/insights-actions-release`，工作树 `C:/Users/93547/.codex/worktrees/insights-actions-release/Meeting-Intel`。
- 复用 `feature/meeting-insights-foundation` 实际未提交的草稿 API、mock、审核组件及 PostgreSQL/浏览器工具，而非只取该分支旧 HEAD `a1cd4cb`。已先读取两个 2026-11-02 审查报告。
- 应用主目录此前经过验收的 `audit-consumer.patch`，再逐块整合分析入口、确认接口日期补丁与状态字段。未复制混合主目录的配置、BusinessAI、整个 reviews/models/api/types 或 worker 文件。
- 未修改原主目录和 Insights 工作树的业务文件。

## 实际线上与迁移核对

认证 Vercel 查询当前域名，前端为 `7b082d5` / `dpl_E67Xpb49qNPBmmtXPG1fe2nk9zFR`，READY。Railway 活动 API 为 `1ac9a4b6-a644-498b-bd80-5cc3d3091b44`，worker 为 `38f8cb63-daec-4b87-b3e0-ee40bb1c1b26`，均 SUCCESS，与审计发布记录一致。

经既有 API 容器执行显式只读事务，仅查询 Alembic head、服务器版本及新表是否存在：实际 head 为 `92d6a10f4e72`，PostgreSQL `18.6 (4e5fd08)`，新草稿表不存在。未读取真实会议或逐字稿，未执行线上迁移、配置写入或 worker 操作。证据：`artifacts/meeting-insights/live-baseline.json`。

`62e9a3b8d014` 尚未发布，原父 revision 为旧分支 `51d8f2a7c903`。本候选将父 revision 接到实际 head `92d6a10f4e72`，单一新 head 为 `62e9a3b8d014`，无需 merge revision 或 stamp 线上数据库。若别的环境已提前应用旧分支的 62 revision，必须先核实其祖先与 schema，不能直接沿用本发布顺序。

本次在全新本机数据库完整重放历史链到 92，再使用真实 Alembic 命令执行 92 → 62 → 92 → head。旧合成会议、参与者、行动项快照不变，新表正确创建、删除、重建。

## 最终规则

保存的逐字稿经既有本地关键词 mock 生成独立待审核草稿；不会调用外部 AI。摘要、行动候选、决策候选可编辑，行动/决策原文证据不可改写。生成时所有候选均待确认，负责人和日期保持 null，不根据发言人或相对时间推断。

人工逐条确认的行动写入真实 ActionItem，服务端来源仍兼容 `mock_insight_human_confirmed`；待确认和拒绝候选不写入。确认后的候选锁定；摘要仍属于独立草稿，不替换会议原摘要。决策确认保留在独立分析草稿中，不自动覆盖已有 Meeting Decisions 面板。

任务列表与完成判断共用确认规则：独立人工确认可先于会议笔记批准，既有已批准纪要中的行动仍兼容。会议查看者可读，有任务管理权限的组织者/获准参会编辑者可完成和重开。owner 文本不授予权限；shared 编辑标记不绕过参会编辑规则；管理员也须有实际会议访问权才能管理任务。

有效、明确的人工 YYYY-MM-DD 同时保存为 deadline_iso；相对文字、时间戳、非法日期只保留原文。任务确认不等于未知 owner/deadline 已补齐，缺失字段不会被伪造，也不会产生提醒。

提醒仍仅本人完整 UPN、未完成、有效明确日期，按设备本地日历分组。完成立即消失，未忽略任务重开后恢复；当日忽略、关闭/恢复、ID 去重、焦点/分钟刷新及身份切换清除旧数据均保留。范围仍为当前页和筛选；开关/忽略仅当前页面会话。

## 逐文件冲突与取舍

- `app/api/reviews.py`：保留线上所有审计、邮件预览指纹及人工审批逻辑，只增加确认 helper 导入并改 can_complete_task。AST 检查其余全部函数不变。
- `app/api/action_items.py` / `app/services/action_review.py`：复用独立确认谓词，显式加载 raw，保留访问过滤、分页、mine 匹配及父会议 → 行动项锁顺序。新增两类状态字段，管理员撤权不绕过完成权限。
- `app/api/meeting_insights.py`：复用原生成/确认 API、父行锁、版本及逐字稿指纹校验；只叠加明确日期衔接，未接入真实 provider。
- `app/models.py`：只追加 MeetingInsightDraft，保留 AuditEvent 和 transcription admission 字段。`app/schemas.py` 只追加两项输出状态。
- `app/main.py`：只导入/注册分析 router；lifespan、定时同步、worker 行为不变。
- `alembic/versions/62e9a3b8d014_meeting_insight_drafts.py`：仅新表，父 revision 改为 92；无旧数据 backfill。
- `frontend/src/lib/api.ts`：在现有审计/监控方法之后追加原 Insights 类型和调用封装，沿用 apiFetch，不覆盖鉴权、超时或错误处理。`types.ts` 只添加可兼容的两项行动状态字段。
- 会议详情：只追加原审核组件，编辑权限使用服务端 can_edit，不用前端的 shared 编辑字段放大权限。
- `meeting-insights.tsx`：复用原交互；修复 React lint 发现的渲染时读取 ref，将“服务器已确认集合”改为 state。尚未保存的下拉确认仍不锁字段，成功保存后才锁定。
- Action Items 页面：保留线上 userKey、草稿保存、加载占位和 Try again；叠加提醒与“行动已确认 / 笔记未批准”标记。共享标题组件只改 Actions 说明。
- 测试保留原线上草稿/重试用例，只更新确认语义文案；相关详情测试仅增加新 API mock。未删除原回归覆盖。

`app/workers`、`app/pipeline`、`app/config.py`、既有审计/邮件服务及管理员界面 diff 均为空。没有调整正常自动转写、服务开关、admission 或外部连接。保留检查见 `preservation-check.json`。

## 本地验收

复用嵌入式 PostgreSQL 18.6 二进制，创建本工作树专属 data_directory，绑定 127.0.0.1:55483；只创建随机 `meeting_insights_*` 数据库。服务只监听本机，使用合成 example.test 身份、英文逐字稿和 JWT；测试工具禁止外部连接、邮件批准/发送、Reprocess 及 worker 路径。

- 相关后端 124 项通过，另迁入实际确认 → 列表 → 完成/重开用例 1 项通过，共 125 项。普通 pytest 全程禁止网络。
- 相关前端首次 147 项通过，恢复原线上额外用例后该文件 20 项通过，合计 148 项独立用例；React state 修复后相关 22 项复验通过。没有重跑无关全套。
- PostgreSQL 10 组检查通过：完整历史链到实际 head、新迁移升级/回退/再升级、并发生成一次、双审核者确认 200/409、重复提交不重复、真实行锁等待、锁超时回滚、权限/任务管理、失败重试、不批准纪要或发送邮件。
- 真实 Next 页面 → FastAPI → PostgreSQL 的 6 组浏览器检查通过：英文草稿、修改/逐条确认、保存网络失败保留编辑并重试、刷新持久化、原文证据、本人到期提醒、完成刷新与重开恢复、忽略/刷新/恢复、只读权限、390×844 窄屏无文档溢出。没有成功业务响应 stub。
- 浏览器 external=[]、errors=[]、无业务 API 5xx，无 approve/send-copy/reprocess 请求。API 头像仅本地 404；静态 chunk 如原工具取得完整字节原样转发，未改写业务响应。
- 最终 TypeScript、相关实现 ESLint、diff whitespace 与 Webpack 生产构建通过。发布预检脚本在正确本地 head 通过，错误 head 返回 exit 2，防止继续发布。
- 隔离库后检：新 head 62；自动批准 0、邮件 claim 0、recording jobs 0、重复确认任务会议 0，现有 meeting.viewed 审计成功记录 10 条。

证据位于 `artifacts/meeting-insights/`：`release-postgres-results.json`、`release-browser-results.json`、`release-api-requests.json`、`local-postflight.json`、`preservation-check.json`、`production-build.txt` 及提交前 diff 清单。

## 脱敏截图

所有截图仅有合成身份、合成 ID、合成英文会议内容，并标注 SYNTHETIC DATA ONLY，没有真实用户/会议内容。

- `page-generated-draft.png`：未知字段和待审核草稿。
- `page-save-failure-retains-draft.png`：保存失败保留编辑。
- `page-refreshed-confirmation.png`：刷新后确认/拒绝/待确认及决策修改。
- `page-action-items-open.png`：本人到期提示、行动确认、笔记未批准及原文。
- `page-viewer-readonly.png`、`page-viewer-action-items.png`：只读用户。
- `page-mobile-detail.png`、`page-mobile-action-items.png`：390px 页面。

## 限制与发布结论

这是可以交给发布审查的完整整合候选，不是已部署版本。生成仍是关键词 mock，只证明工作流，不宣称真实 AI 摘要质量。提醒不全量、不后台投递、不跨设备。已确认候选无法在草稿中重写；逐字稿改变会 409，尚无证据重新绑定 UI。新确认/完成路径未新增专属审计事件类型，既有审计写入保持不变。

自动审批拒绝以隐藏进程启动 next start，仅返回 blocked by policy，无更具体原因。没有修改审批或换方式重复启动生产服务器；浏览器验收使用获准的 next dev --webpack，生产编译/类型/静态生成通过，生产服务器运行验收未完成。这是剩余环境阻碍，应在允许的发布测试环境补做。

发布顺序及可执行命令见 `meeting-insights-actions-runbook.md`。未来授权发布前重新核实实际部署及 DB head；不能拿本次 head 快照替代届时检查。本轮未提交、推送、部署、修改线上数据库/配置/worker，未处理真实逐字稿、调用 BusinessAI 或 Reprocess。
