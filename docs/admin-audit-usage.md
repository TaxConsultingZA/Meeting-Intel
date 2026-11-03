# 管理员审计日志：使用说明与完成度

这个功能帮助回答：谁在什么时候请求了处理、系统做到哪一步、哪里失败、是否有供应商接受证据。它把用户动作和系统处理事实连到 job，便于责任追溯；不是账单，也不能补造以前没有留下的记录。

## 怎么使用

1. 管理员打开 https://meeting-intel-staging.vercel.app/admin/audit-logs ，也可从 Admin 进入 Audit Logs。
2. 默认看最近 7 天。可按 Job ID、Recording item ID、Current job status、From/To、Event type、Outcome、Actor 筛选，点 Apply。Actor 是完整邮箱或 recording_worker/email_sender 等系统身份，精确匹配；时间按页面显示的 SAST 输入，To 不包含在窗口内，最大 90 天。
3. Processing monitoring 看当前 job 状态、attempts、已确认的转写接受证据、原音频时长、当前 attempt 时长、安全失败阶段/类别和已返回 token。桌面一排两张、手机一张，更多 job 在区域内向下滚动；Tab 聚焦后可用方向键或 Page Down。
4. 找到失败 job，点 View job events：页面自动按该 job 筛选。查看 started、processing failed/cancelled 等时间顺序，再点 View details，查看完整时间、身份、安全类别及恢复说明；展开 Technical details 查看完整资源、job、关联 ID。此按钮只查日志，不执行 Retry/Reprocess。
5. Audit Events 桌面保留六列，完整换行；手机每条记录按 Time/Actor/Action/Resource/Outcome/Details 展示。桌面约 5 条高、手机使用适合屏幕的有限高度，更多记录内部滚动。表头/手机列表标题位于滚动正文之外，保持可见且不遮挡正文；每页数量与 Previous/Next 分页保持原规则。Refresh 重读已应用条件，Reset 清空条件；加载失败可点 Retry。

注意：监控区时间按 job 创建时间，事件区时间按事件发生时间；当前状态筛选会作用于两个区，Actor/事件类型/结果只筛事件。监控最多 50 个 job，超过时缩小范围。

## 你可以亲自检查

- 桌面和约 390px 手机宽度打开页面，两个区都不应出现横向滚动；滚动 job 区只移动卡片，桌面一排两张、手机一张。
- 在事件列表里上下滚动，表头/手机标题保持可见，六类字段及 View details 都能找到；完整 ID 会换行，不省略。
- Current job status 选择 failed 后 Apply；点失败卡片 View job events，确认 Job ID 已应用，再打开事件详情。
- Reset 后查看每页计数；有下一页时用 Next/Previous。没有更多事件时按钮禁用是正常行为，不能为测分页制造事件。
- Unknown 就是没有可靠证据。attempts、预留、超时都不是实际接受次数；reserved、submitted、submission_unknown 是三种不同事实。实际费用、估算费用和账单证据仍 Unknown。

## 完成度（2026-11-03）

已上线并有既有线上样本：录音导入、Retry、Reprocess、取消请求/完成、worker 领取、处理成功/失败、摘要 extraction 请求/完成。可用真实管理员只读查询，未登录两个审计 API 为 401。

代码已上线，等待自然事件：recording.created；供应商 reserved/submitted/submission_unknown/completed/failed/poll_unknown 新审计；摘要失败与返回用量；人工编辑/审核补充；邮件预览、批准、发送/个人副本；会议查看与权限申请、批准/拒绝、分享/撤销。历史 provider 引用可证明至少一次接受，但不是新的 provider.submitted 审计样本。不能将这些项写成真实供应商、邮件或完整费用验收通过。

仍需真人普通用户线上验收：两个审计 API 应 403、直接打开页面被拒绝、切换账号后旧管理员数据不可见。目前这些是本地身份/权限测试通过，没有可用的线上普通用户会话；不创建账号、不修改管理员权限。

后续待做：观察自然事件补充覆盖证据；按实际需要扩展目前未全面记录的列表/搜索、音频片段访问、登录失败及其他账号管理行为。备份保留期限、生产规模查询性能和真实计费证据仍没有充分核实。

本次只修改 Admin 两个显示区域，不修改后端、数据库、供应商计量、权限或 worker 配置。线上修复前后截图和测量在 artifacts/processing-audit-layout-live/；本地合成布局证据在 artifacts/processing-audit-layout/，二者明确区分。前端部署版本与线上验收结果见该证据目录的 release-result.md。


本次显示修复已完成真实管理员桌面和 390px 线上截图验收，部署 dpl_E67Xpb49qNPBmmtXPG1fe2nk9zFR / 7b082d5。当前 29 条事件在第一页，分页按钮正确禁用；有下一页时的翻页遍历仅本地通过，不能写成线上已测。完整前后截图、测量和剩余验收项见 [本次发布验收报告](../artifacts/processing-audit-layout-live/release-result.md)。
