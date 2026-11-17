# 实验委托模型拆解册

南麓材料实验室（9人）把委托单上的业务依赖整理为可验证的3NF关系，并保留候选键、闭包、最小覆盖和无损校验证据。

## 业务工作流

原先设计员在Excel里堆叠委托号、客户、检测项、方法与结果，再手工画表结构。痛点：依赖口径难确认、复合键容易漏判、拆表后无法证明无损。上游为委托单和已确认业务规则，本项目承接关系草案登记、函数依赖编辑、3NF合成、验证报告导出，下游为实验数据录入系统的数据库设计人员。

核心实体：关系草案 Relation、函数依赖 Dependency、委托样本 Sample、分解报告 Report。5业务页和独立登录页；管理员另有审计页。业务规则不执行为SQL，属性名是纯数据。

## 函数依赖的样本规则核验

函数依赖不再只凭人工登记：登记后到「规则核验」页用真实委托样本佐证。

- **样本可增改移除**：样本按关系归集，定位标签同关系唯一；取值为 属性→值，留空以 `null` 保存。
- **空值语义**：`null` 表示“未知”而不是一个可比较的值。决定项任一属性为空则该样本不参与同决定项分组；被决定项一侧为空的属性跳过判定。只有两条样本决定项全部已知且逐项相等、某被决定项属性两边都已知却取值不同时，才形成反例。
- **按指定依赖检查全体样本**：核验枚举该关系全部样本对，冲突返回可定位反例行（双方样本 id/标签、冲突属性、各自取值与决定项取值）。
- **四种状态**：待核验 `pending`、可采纳 `adoptable`、冲突 `conflict`、已采纳 `adopted`。无反例只表示“当前样本支持”，不证明依赖恒真；**空样本不允许采纳（422）**。
- **源数据变化使旧结论失效**：每次样本增改移除都递增 `sample_version`；核验结论记录所依据版本，版本落后即标记“结论已失效”，采纳时在锁内重算，发现冲突或空样本则拒绝采纳。
- **采纳即正式规则**：采纳后规则约束后续样本写入（单条与批量），写入后对完整样本集重放全部已采纳规则，任一违反给出反例并**整批拒绝回滚**；重复采纳幂等，不重复登记审计。
- **并发正确性**：样本写入与采纳在事务内对关系行 `SELECT ... FOR UPDATE` 互斥，提交即释放，采纳与并发更正交错后只可能出现“采纳成功且冲突写入被拒”或“更正先提交且采纳被拒并转为冲突”，不会留下规则与样本互相矛盾的状态。
- 核验期间允许继续更正样本；已采纳依赖的决定项/被决定项锁定不可改，避免规则被静默篡改。

接口：`GET /relations/{id}/samples`、`POST/PUT/DELETE /samples`、`POST /relations/{id}/samples/batch`、`GET /verifications`、`POST /dependencies/{id}/verify`、`POST /dependencies/{id}/adopt`。后端测试见 `backend/tests`（`pip install -r requirements-dev.txt` 后 `pytest`），覆盖空决定项、复合决定项、移除反例、空样本拒绝、失效拒绝与并发更正。

## 快速启动

```sh
cp .env.example .env
docker compose up -d --build
docker compose exec -T backend python -m scripts.seed_demo
```

前端 http://localhost:18243 ，后端 http://localhost:19243/docs ，MySQL localhost:17743。

|角色|账号|密码|权限|
|---|---|---|---|
|admin|admin@nanlu.test|Demo2026!|草案/依赖写入、运行、审计|
|operator|operator@nanlu.test|Demo2026!|草案/依赖写入、运行、导出|
|viewer|viewer@nanlu.test|Demo2026!|只读与导出，写API403|

## 一天的工作剧本

09:00 operator登录；09:05打开 `NL-1117-A` 材料检测委托单；09:10查看五属性 `委托号,客户,检测项,方法,结果`；09:15确认 `委托号→客户`、`检测项→方法`、`委托号,检测项→结果`；09:20执行 `shift-20261117` 分解任务；09:25候选键为 `{委托号,检测项}`，拆出委托客户、检测项方法、委托检测结果3个关系；09:30导出 `report-1.json`；09:40 viewer复核3NF/依赖保持/无损均通过；10:00 admin审计。

另有 `NL-1117-B` 的循环依赖 A→B/B→A与独立属性C，候选键AC/BC；`NL-1117-C` 没有确认依赖，完整属性集作为唯一候选键，不凭空猜测业务规则。

## 算法说明

Python真算，MySQL保存草案/依赖与结果，Redis传递任务，独立worker执行。

1. 属性闭包：迭代应用所有X→a，直到不再增加属性。
2. 候选键：先取不出现在RHS的必需属性，再按大小枚举其余属性子集；若闭包覆盖全集且不含已知候选键，加入结果。**最多10个属性/64条依赖**，最多1024个子集；超限API422/算法ValueError，避免指数搜索失控。
3. 最小覆盖：RHS拆成单属性，去平凡依赖；逐一删除左侧多余属性、移除冗余依赖。
4. 3NF合成：按最小覆盖左侧分组，删除被包含关系；若无关系含候选键，补入候选键关系。无依赖时保留全属性关系。
5. 验证：精确生成F+在各分解关系上的投影，枚举局部候选键，逐非平凡投影依赖检查3NF；所有原始依赖须可由投影并集推出。tableau追赶法依据FD合并符号，出现全a符号行则无损，报告包含见证行、合并步骤与最终表。

复合、循环、空决定项、无依赖均支持。不在任何RHS中的属性强制进入候选键。输入入队时冻结快照，后续修改不会改变已有报告。结果JSON含SHA256，固定输入应有固定输出。失败态包括引用关系外属性、重复/空属性、属性超过10、依赖超过64、队列错误；页面可恢复并重新执行。

这是小型关系模型设计辅助工具，FD由人工登记并经委托样本核验（样本只用于佐证/反例，不从脏数据自动推断业务规则）；不连接生产数据或自动执行DDL。精确投影在10属性内有界，仍可能随依赖复杂度增加耗时。单worker串行队列，不带生产任务重试/崩溃续跑。

## 工程结构

|服务|技术|职责|
|---|---|---|
|frontend|原生HTML/CSS/JS + Nginx|5业务页、登录、共享业务表格、报告与核验组件|
|backend|Python3.11/FastAPI/SQLAlchemy/PyJWT|校验、权限、审计、样本核验、快照与导出|
|worker|Python3.11|闭包、候选键、3NF与chase|
|db|MySQL8.0|JSON属性与依赖、任务报告|
|redis|Redis7|持久任务队列|

目录：`frontend/src/{api,stores,types,components/common,hooks,pages,router,utils,constants}`；`backend/src/{routes,controllers,services,models,schemas,middlewares,utils,constants,config}`；`backend/scripts/seed_demo.py`；`backend/migrations/001_initial.sql`；`backend/tests`。每核心实体贯穿模型/schema/service/route/API/store/page。组件table/badge/frame复用，hooks/session/feedback和utils/forms/html共用；request_id/errors双后端中间件。核验逻辑集中在 `services/verification.py`（纯判定 `find_counterexamples/evaluate` + 事务性 verify/adopt），样本写入约束在 `services/samples.py`。

枚举：角色admin/operator/viewer、任务queued/running/completed/failed；前后端定义位于 `backend/src/constants/enums.py` 和 `frontend/src/constants/enums.js`，security/reports、frame/badge消费；worker持久化状态。

环境变量见.env.example：COMPOSE_PROJECT_NAME、FRONTEND_PORT/BACKEND_PORT/DB_PORT、DB_PASSWORD、JWT_SECRET、SEED_DEMO。默认密码仅本地演示，JWT8小时。seed按自然键只补缺失关系及初始依赖，不覆盖用户修改。schema由SQLAlchemy metadata.create_all初始化，无在线迁移引擎。

本地开发：Python3.11安装backend/requirements.txt，配置DATABASE_URL/REDIS_URL后从backend运行 `uvicorn src.main:app --reload`、`python -m src.worker`；前端用Nginx同源代理/api。5服务均有健康检查和健康依赖，数据库/Redis/worker产物为独立命名卷。停止清空：`docker compose down -v --remove-orphans`。

UI为酒红档案册，双字体由Google Fonts加载，离线有回退且业务不依赖字体网络。

## License

MIT。真实测试脚本、截图与结果保存在源码外 `../../test-artifacts/gb-4104/`。
