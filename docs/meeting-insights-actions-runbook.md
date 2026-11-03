# Insights / Action Items 验收与发布顺序

本文件的发布命令为未来获得发布授权后的操作说明，本轮没有执行。所有命令从独立整合工作树根目录运行，不使用混合主目录。部署前将已审查变更形成单一明确提交/制品；本轮按用户要求保留未提交状态。

## 本地复验

使用 Python 环境 `C:/Users/93547/project/Meeting-Intel/.venv/Scripts/python.exe`、现有 frontend/node_modules 和 @embedded-postgres/windows-x64@18.6.0-beta.19 的 bin 目录。没有向库中提交依赖、PG runtime、data 或凭据。

本轮集群：`artifacts/meeting-insights/pg-data`，端口 55483；API 8976；Next 8975。PG 仅允许 loopback 的合成验收。新建集群时先 `initdb -D <绝对数据目录> -U postgres -A trust --no-locale --encoding=UTF8`；已有目录不要再次 initdb。使用该 runtime 的 pg_ctl 启动已有集群：

```powershell
& "$pgBin/pg_ctl.exe" -D "$PWD/artifacts/meeting-insights/pg-data" -l "$PWD/artifacts/meeting-insights/pg-server.log" -o '-p 55483 -h 127.0.0.1' start
python scripts/meeting_insights_local.py --prepare
python scripts/meeting_insights_local.py --serve
```

`--prepare` 每次创建新随机验收库、执行真实 Alembic 链及并发检查。工具拒绝其他 data_directory，不读取 .env，不启动 app.main/worker。`--new-ui` 只在当前隔离库新建一条合成页面会议，供组件改动后的页面复验。

另一个本地终端在 frontend 目录设置仅进程内合成配置：

```powershell
$env:DATABASE_URL='postgresql://postgres@localhost:55483/offline'
$env:AUTH_SECRET='synthetic-insights-local-session-only'
$env:AUTH_TRUST_HOST='true'
$env:AUTH_MICROSOFT_ENTRA_ID_TENANT_ID='synthetic'
$env:AUTH_MICROSOFT_ENTRA_ID_ID='synthetic'
$env:AUTH_MICROSOFT_ENTRA_ID_SECRET='synthetic'
$env:NEXT_PUBLIC_API_URL='http://127.0.0.1:8976'
$env:NEXT_TELEMETRY_DISABLED='1'
node --require ../scripts/meeting_insights_offline_guard.cjs node_modules/next/dist/bin/next dev --webpack --hostname 127.0.0.1 --port 8975
```

从根目录 `node scripts/meeting_insights_browser.mjs` 运行真实页面检查。仅使用合成 Cookie 和真实本地业务 API；不要改脚本指向线上。停止 dev 后使用同样的合成环境执行 `next build --webpack`。本轮 next start 被自动审批拒绝，不重复尝试或绕过；允许的测试环境需补生产运行验收。

相关 pytest 文件及前端文件见审查报告，不跑全套。UI/服务改动后只重跑受影响项；迁移或锁逻辑变化才重跑 PostgreSQL 验证。停止 API/Next 后用该 runtime 的 `pg_ctl -D <上述目录> -m fast stop` 关闭本机集群。

## 未来发布：固定顺序与停止条件

1. **固定来源。** 在这条独立分支审查提交前 diff 和新增文件清单。确认 worker/pipeline/config/admin 审计无改动；确认发布制品不含本机 PG data、临时日志或 .env；既有 .dockerignore 排除 artifacts。合成身份和验收服务器不得配置为生产入口，本地 API fixture 不能作为生产入口。
2. **再次只读预检。** 核对既有 Railway 项目 `059e3add-9746-4baa-90e1-58d4fa5f2559` 的 API/worker 部署，Vercel 项目 `prj_clw0nJfdfNmpFenJctjHIo5GrKDP` 及其当前域名。由批准的执行环境注入目标 DATABASE_URL 和既有应用迁移所需环境，不回显凭据，不加载其他工作树的 .env。
3. **备份与单次迁移。** 先按既有流程做好目标库备份。在包含新 migration 的明确源码/制品上，预检成功后只执行一次升级。不得在旧容器（没有 62 文件）直接调用不存在的 revision，也不得 stamp。

```powershell
python scripts/check_insights_release.py --expect-head 92d6a10f4e72 --draft-table absent
if ($LASTEXITCODE -ne 0) { throw 'Target schema differs; stop release' }
python -m alembic upgrade 62e9a3b8d014
if ($LASTEXITCODE -ne 0) { throw 'Migration failed; stop release' }
python scripts/check_insights_release.py --expect-head 62e9a3b8d014 --draft-table present
if ($LASTEXITCODE -ne 0) { throw 'Post-migration check failed; stop release' }
```

脚本仅读取显式 DATABASE_URL，事务为 READ ONLY，不打印连接异常细节；head/表状态不符合预期返回 2。若目标库已经是 62，先确认代码谱系和表结构，不能通过跳过预检来继续执行这个“尚未升级”流程。

4. **仅更新 API。** 使用已审查制品部署现有 API 服务，不新建服务/项目，不改运行配置。此加表迁移对旧 worker 向后兼容，不需要暂停、重启或重新部署 worker。

```powershell
railway up --project 059e3add-9746-4baa-90e1-58d4fa5f2559 --service meeting-intel-api --environment production --ci
if ($LASTEXITCODE -ne 0) { throw 'API deployment failed; do not publish frontend' }
```

只读确认 API 健康、旧审计接口权限和已部署源码；不拿真实会议生成草稿、不触发 Reprocess、邮件或供应商事件来制造样本。

5. **再更新前端。** 使用现有 Vercel 团队和项目，保持原域名及既有生产环境值；不要把本地 NEXT_PUBLIC_API_URL/合成 AUTH_SECRET 部署。用干净发布终端，不能沿用本地验收终端的环境。

```powershell
$env:VERCEL_ORG_ID='team_XujywMw2w5S41P4KwL6ys9rM'
$env:VERCEL_PROJECT_ID='prj_clw0nJfdfNmpFenJctjHIo5GrKDP'
vercel deploy --prod --scope team-22c0 --cwd frontend
if ($LASTEXITCODE -ne 0) { throw 'Frontend deployment failed' }
```

6. **发布后核对。** 明确记录部署 ID、源提交、迁移 head、旧审计布局和权限仍保留，worker 仍是原活动部署且其原有自动转写配置不变。当前 BusinessAI/邮件配置保持原值，不为本功能开启或关闭它们。真实用户验收及生产服务器运行检查须另有允许的环境与授权范围。

## 回退

默认先回退前端和 API 至各自原部署，保留新增表。原 worker 不动。新增表向后兼容，应用回退不要求删除草稿；独立确认 ActionItem 也不应删除。

数据库回退已在隔离库验证为 `python -m alembic downgrade 92d6a10f4e72`，它会删除草稿表并丢失其中人工审核记录。因此线上不自动执行：已有使用数据时先导出/备份并制定恢复方案，再决定是否需要 schema 回退。没有草稿数据的受控环境才可按已审核流程回退。删除草稿后重新生成可能再次创建行动项，不能把生产 downgrade/重生成当作去重或恢复策略。
