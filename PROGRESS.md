PROGRESS

1. 项目目标

自动筛选通过规定验证的 IPv4 IPTV 线路，持续生成：

"output/iptv.m3u"

2. 已锁定架构

固定五步：

1. 广泛发现
2. 数据整理
3. 快速筛选
4. 深度验证
5. 安全发布

固定六个核心程序：

- "config.py"：统一配置。
- "models.py"：统一数据结构。
- "security.py"：唯一 IPTV 公网访问入口，负责媒体获取和资源清单。
- "sources.py"：来源读取、解析和去重。
- "validator.py"：快速筛选、深度验证编排和线路状态判定。
- "pipeline.py"：唯一业务入口和发布资格判断。

固定深度验证链：

"security.py → 本轮媒体暂存和资源清单 → 宿主机校验 → 任务专属快照 → 一次性无网络验证容器 → 结构化 JSON → 宿主机校验 → validator.py"

宿主机控制器由 GitHub Actions 受限步骤承担，不新增第七个业务程序。

3. 已确定的关键规则

- 验证容器使用 "--network none"。
- 验证容器不连接 security.py，不访问公网和外部 DNS。
- 验证容器只读当前任务媒体快照。
- 验证容器使用非 root 用户运行。
- 验证容器移除全部 Linux capabilities。
- 宿主机校验任务身份、媒体清单、实际大小和 SHA-256。
- 宿主机校验验证结果身份和结构后，才交给 validator.py。
- 线路状态为 PASS、FAIL、UNKNOWN、NODE_ERROR。
- 单条线路失败不能拖垮整轮任务。
- 只有本轮 PASS 线路可以进入正式订阅。
- 零 PASS、关键故障、测试运行或发布检查失败时，不得覆盖正式订阅。
- 不使用线路评分，不引入持久化线路数据库，不随意增加程序或业务入口。
- 正式订阅路径为 "output/iptv.m3u"。
- 目标运行方式为每天北京时间 06:00 自动运行，并支持手动正式和手动测试运行。

4. 文档状态

以下四份文档已存在于仓库 main 分支：

- "CORE_FLOW.md"
- "MASTER_PLAN.md"
- "README.md"
- "PROGRESS.md"

5. 当前仓库实际文件状态

截至本次检查，仓库 main 分支中与核心实现有关的文件如下：

- "models.py"：文件已经存在，尚待独立验收。
- "config.py"：尚未创建。
- "security.py"：尚未创建。
- "sources.py"：尚未创建。
- "validator.py"：尚未创建。
- "pipeline.py"：尚未创建。
- ".github/workflows/main.yml"：已存在，目前是手动触发的验证容器安全预检工作流，不是完整业务工作流。
- "Dockerfile.validator"：已存在，能够构建验证镜像。

已有真实运行证据

GitHub Actions：

- 工作流："Validator Network-None Security Precheck"
- Run ID："42348126781"
- Run 编号：第 13 次运行
- Job ID："128330223009"
- 运行结论："success"
- Job 内 7 个步骤全部成功。

本次预检实际覆盖：

- 验证镜像构建。
- Docker "--network none"。
- 只读 root filesystem。
- 非 root 身份。
- Linux capabilities 全部为零。
- "NoNewPrivs"。
- CPU、内存和 PID 限制。
- 任务快照只读挂载及 SHA-256 一致性。
- 临时目录可写。
- 仅存在 loopback 网络接口。
- 无默认网络路由。
- 公网 IPv4、外部域名和安全入口不可达。
- FFmpeg 和 FFprobe 可执行。

预检结论边界

上述成功只证明当前预检工作流所覆盖的容器基础隔离和运行环境检查通过。

它不代表：

- 六个核心程序已经完成。
- 宿主机任务控制器已经实现。
- 真实媒体任务已经进入验证容器。
- 真实 HLS 媒体验证已经通过。
- S01—S26 全部通过。
- 完整业务流程或正式订阅发布已经可用。

6. 下一步施工顺序

1. 独立检查并验收仓库现有 "models.py"，确认数据结构、字段、身份、完整性和状态判定契约。
2. "models.py" 验收通过后，实现并验收 "config.py"。
3. 按已锁定架构实现并验收 "security.py"。
4. 实现并验收 "sources.py"。
5. 实现并验收 "validator.py"。
6. 落实 GitHub Actions 宿主机控制器：任务身份、资源清单、媒体文件、SHA-256、任务快照、容器创建销毁和结构化结果交接。
7. 实现并验收 "pipeline.py"，串联完整五步流程。
8. 将当前手动预检工作流逐步落实为完整自动、手动正式和手动测试工作流。
9. 完成 S01—S26 真实安全测试。
10. 完成业务集成、异常恢复、发布保护和正式订阅生成测试。

前置程序未通过验收，不进入依赖阶段。

7. 验收纪律

每次更新记录实际改动、测试环境、操作、证据、结论和未验证事项。

静态检查、模拟测试和真实运行测试必须明确区分。

没有实际证据不得标记为完成。
