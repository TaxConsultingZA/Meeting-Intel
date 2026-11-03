# Admin 显示修复与线上截图验收 · 2026-11-03

只改两个显示区域：审计事件的宽度/换行/滚动，以及监控 job 区域的一排高度/滚动。没有改审计写入、计量、权限、分页接口或数据库。

## 发布版本

- 前端提交：7b082d5523f48c8b8639a5c8e1e57ddbbefb9331，已推送 main 和 feature/processing-audit-monitoring。
- Vercel：dpl_E67Xpb49qNPBmmtXPG1fe2nk9zFR，READY；原地址 https://meeting-intel-staging.vercel.app/admin/audit-logs 。版本地址 https://meeting-intel-staging-bvhdystzg-team-22c0.vercel.app 。
- API 保持 1ac9a4b6-a644-498b-bd80-5cc3d3091b44 / SUCCESS；worker 保持 38f8cb63-daec-4b87-b3e0-ee40bb1c1b26 / SUCCESS。本次未重发、未重启、未修改它们。
- worker SSH 实查 RECORDING_PROCESSING_ENABLED=true、EMAILS_ENABLED=false、BUSINESSAI_ENABLED=false。API health=200，两个审计接口未登录均 401。

## 真实线上验收

使用既有 Wei Jiuyang 管理员会话和线上原有记录。默认 7 天得到 29 条事件、7 个 job；没有添加、修改或触发任务、邮件、供应商事件。数据库只读检查迁移 head=92d6a10f4e72，事件分类计数与原发布后相同，active_jobs=0。

- 修复前：桌面 Details 列超出可视宽度；390px 窄屏表内横向溢出 781px；7 个 job 直接展开，页面很长。
- 修复后桌面 1280×900：页面、事件区、job 区横向溢出均 0。六列标题完整，资源 ID 不省略。事件区 870px，前七行加表头约 869px；内部可滚动。job 区 241px，首排两张卡片约 241.33px，内部可滚动。
- 桌面键盘：job 区 Page Down 后 scrollTop=210 且保持焦点；事件区 scrollTop≈760.67，表头相对区域顶部偏移 0。
- 修复后手机 390×844：三个横向溢出均 0；事件卡片保留 Time/Actor/Action/Resource/Outcome/Details，29 个详情按钮存在，完整资源 ID 保留。事件区 633px，job 区 305px、首排一张约 305.33px，均可内部纵向滚动。事件区键盘滚动 554px，固定标题偏移 0。
- 桌面及手机真实失败事件的详情弹窗均打开成功，时间与失败阶段存在；手机弹窗完全在视口内。
- failed 筛选实际返回 1 个失败 job、3 条事件；View job events 自动应用 job，仍返回该 job 的 3 条事件。没有执行 Retry 或 Reprocess。
- 当前全部 29 条在第一页，Previous/Next 均正确禁用，计数保留；没有下一页样本，不能称线上翻页遍历已实测。有下一页时的 Previous/Next 已由本地浏览器和单元测试验证。
- 47 项受影响 Admin 前端测试通过，tsc --noEmit 通过；本地 desktop/narrow 浏览器检查通过。生产前端构建 READY。未重跑后端套件。

## 截图与隐私

修复前：[桌面](before-desktop.png)、[390px 窄屏](before-mobile.png)。修复后：[桌面](after-desktop.png)、[390px 窄屏](after-mobile.png)。均由真实线上页面截图，邮箱和内部 ID 用不透明块脱敏；遮挡可能覆盖其邻近行的少量文字，不是产品裁切。未对真实页面 DOM 隐藏列/内容，没有使用 AI 生成截图。

使用浏览器明确的 1280×900 / 390×844 视口。截图像素宽度不含浏览器自身滚动条，因此文件宽度为 1264 / 374；产品与区域宽度测量仍按实际 DOM 记录。浏览器临时尺寸覆盖已恢复。

带 metrics/check 名的 JSON 是对应的线上测量/交互布尔结果。database-postflight.json 仅包含聚合及安全配置。../processing-audit-layout/ 是本地合成布局证据，不能与此处真实线上截图混用。

## 大任务完成度与待做

已完成：已有录音用户动作、处理过程、摘要 extraction 事件可按时间/操作者/类型/结果/job/录音/当前状态查询；失败可钻取详情；本次两个显示问题及管理员真实页面交互已验收。功能通俗说明及亲自检查步骤见 ../../docs/admin-audit-usage.md 。

已有线上样本：import 6、retry 3、reprocess 1、cancel 6、cancelled 6、started 5、processing 成功 3 / 失败 2、AI requested/completed 各 3（全库聚合，不等于默认七天页面条数）。

代码上线等待自然事件：created、新 provider 各阶段、AI 失败/返回用量、人工编辑/审核、邮件与访问历史。真实 provider 引用是接受证据，但不伪造 provider.submitted 事件；AI extraction 历史事件也不证明真实 AI 供应商调用。所有无证据的费用/总次数/用量继续 Unknown。

仍未线上验收：普通用户 API 403、切换真实账号清除旧管理员数据；这两项按用户授权保留“本地通过，线上普通用户会话未验收”。线上下一页遍历、加载失败重试暂无对应真实样本；本地测试通过。

后续待做：用正常业务自然产生的事件补齐样本，再安排真实普通用户验收；是否扩展列表/搜索、音频片段、登录失败及其他账号管理日志另行定范围。不为覆盖率制造录音、邮件或供应商事件。
