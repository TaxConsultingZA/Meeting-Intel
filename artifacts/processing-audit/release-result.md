# 管理员审计发布结果 · 2026-11-03

应用已上线既有 staging 项目的 production 环境；不是部署到其他未指定系统。

- API/worker 代码：222cf86ebbdf4098a2ffd58a781a29e8b41957ac。
- 前端 7 行滚动补发：76e7e0d9a780b454480d1c3a4439e1c26d9c86b7。
- API：1ac9a4b6-a644-498b-bd80-5cc3d3091b44，SUCCESS。worker 暂停版 87e70a7c-4b38-4a9c-bc90-506f4b83c7d9，恢复原配置后的当前版 38f8cb63-daec-4b87-b3e0-ee40bb1c1b26，SUCCESS。
- 前端：dpl_FbDeV88PeJM4v5aj7vAS1jSUwhUX，READY，原域名 https://meeting-intel-staging.vercel.app 已绑定。
- API 的 admin.py、reviews.py、processing_monitor.py，以及 worker 的 transcription_submission.py、ai_audit.py 容器 SHA256 与本地发布源一致。无 migration；数据库 head 仍为 92d6a10f4e72。

## 原任务五类事件的状态

- **user actions：已上线且验收（已有动作的只读核验）**。既有 import 6、retry 3、reprocess 1、cancel 6，管理员两个接口成功读取。新增人工 decisions/action item/transcript/speaker 编辑已实现并上线，但无线上事件样本，待观察。
- **processing events：已上线且验收（已有处理事件的只读核验）**。started 5、processing succeeded 3 / failed 2、cancelled 6。新 created、供应商 reserved/submitted/submission_unknown/completed/failed/poll_unknown 无线上样本，已实现并上线、待观察。不能将此标为真实供应商验收通过。
- **summary generation：已上线且验收（已有生成事件的只读核验）**。extraction_requested 3、extraction_completed 3。失败事件及供应商 token 新增计量无线上样本；历史事件不能证明真实 AI 调用或费用，仍 Unknown。
- **email approvals：代码已实现但无线上样本**。批准请求/批准/发送保留，补邮件预览及个人副本审计，Admin 可按新事件类型查询；邮件保持关闭，不为验收发送、批准或预览制造事件。
- **access history：代码已实现但无线上样本**。新增授权会议查看、权限请求、批准/拒绝、分享/撤销，Admin 可按事件与操作者查询。没有通过打开真实会议制造样本，不回填历史权限。

## 线上权限和页面验收的边界

用户打开 Wei Jiuyang 管理员会话页面后，Railway 访问日志 2026-11-03 06:54:42 UTC 分别记录 GET /admin/audit-events=200、GET /admin/processing-monitor=200。这里只保存时间、路径、状态，不保存认证头、查询值或用户数据，见 live-api-requests.json。

未登录直接请求两个 API 均 401，health=200。Next 前端返回 HTTP 200 的流式登录重定向，HTML 含 /login redirect 且无 Audit Logs 标题；不将这个 200 当作获得审计页面权限。见 unsigned-live-check.json。普通用户 403、切换身份清除旧管理员数据按用户明确许可沿用已有本地合成测试，**本地通过，线上普通用户会话未验收**；未创建账号或修改权限。

管理员页面线上筛选、失败详情、加载失败重试和最终 7 行滚动的视觉交互仍未完成验收：浏览器扩展连接失败，Windows Computer Use 因不能可靠确认当前 URL 而停止；用户恢复页面后工具仍拒绝读取。没有绕过该限制。两个管理员 API 的 200 不等于全部页面交互通过。

7 行滚动、固定表头、页数/计数及 Previous/Next 在实际 Admin 组件的 desktop 1280×900 / narrow 390×844 合成浏览器检查通过；区域 804px、前七行加表头 803.5px、内部滚动 545px、表头位移 0.5px，见 ../processing-audit-scroll/browser-results.json。此目录三个截图均为合成数据，不能冒充线上截图。新增相关检查 121 后端、1 页面、tsc 通过，沿用原 193/46/Webpack 结果，线上两次前端生产构建 READY。

## worker 恢复与剩余缺口

按用户补充要求恢复原 RECORDING_PROCESSING_ENABLED=true；配置恢复部署成功后 SSH printenv 实查 true。EMAILS_ENABLED=false、BUSINESSAI_ENABLED=false，保持原值。仅为恢复该配置由 Railway 重建 worker 运行实例；没有因前端 UI 补丁重发 API/worker 源码。

发布前后只读数据库聚合相同，active_jobs=0，事件键无重复，必填字段完整；没有人工触发录音、供应商、AI、邮件，也没有重置提交预留。对正常自动处理的恢复不等于制造验收样本。

尚未覆盖所有列表/搜索、音频片段访问、登录失败和全部账号管理行为；这不是全站安全访问日志。历史无证据的提交、费用、用量、时长仍 Unknown。线上供应商新事件、邮件、权限/人工编辑样本及管理员完整视觉交互继续待观察/待验收。
