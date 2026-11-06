
# China-IPTV-Auto V3 项目进度与交接记录

> 本文件用于记录已经核实的项目状态、重要决策、问题结论和下一步工作，供后续 ChatGPT 或开发者接手。
>
> 本文件是进度记录，不替代 CORE_FLOW.md。技术规则以 CORE_FLOW.md 为准；施工任务和验收顺序以 MASTER_PLAN.md 为准。若本文件与权威文档冲突，以权威文档为准。

## 一、最近核对基线

- 核对日期：2026-11-06
- 仓库：womomo8/China-IPTV-Auto-v3
- 默认分支：main
- 核对时最新提交：6c7e44ace7f6c23309ba088bb1b566db161b8d40
- 最新提交说明：fix: prevent SIGPIPE in validator log checks
- 当前状态：V3 建设中，M0 尚未完成完整验收。

注意：接手时必须重新检查远程仓库最新提交，不能把这里的 SHA 当成永远最新的版本。

## 二、项目目标与基本原则

1. 自动发现并筛选真正能在中国大陆网络环境播放的 IPv4 IPTV 直播源。
2. 质量优先，不以线路数量为目标；未通过验证的线路不得为了凑数而发布。
3. CORE_FLOW.md 是权威流程和技术规范。
4. MASTER_PLAN.md 是施工任务、依赖顺序和验收计划。
5. 不为追求 GitHub Actions 变绿而降低验收标准。
6. 不得用临时占位容器的测试结果冒充正式架构验收。
7. 未经确认的想法不能直接写成权威技术规则。
8. 未经实际测试的功能不能标记为完成。

## 三、当前仓库文件状态

以 6c7e44a 为核对基线：

| 文件 | 状态 |
|---|---|
| CORE_FLOW.md | 已存在 |
| MASTER_PLAN.md | 已存在 |
| README.md | 已存在 |
| .github/workflows/main.yml | 已存在 |
| Dockerfile.validator | 已存在 |
| Dockerfile.gateway | 未发现 |
| compose.yaml | 未发现 |
| network_guard.py | 未发现 |
| media_gateway.py | 未发现 |
| pipeline.py | 未发现 |
| tests/ | 未发现 |

接手时必须重新检查文件树，确认是否有新提交。

## 四、M0 当前进度

**总状态：未完成，不得标记 M0 PASS。**

### M0-A：运行环境与正式编排

- 当前 workflow 检查 Ubuntu Runner、Docker Engine 和 Docker Compose 命令。
- 正式 Dockerfile.gateway 和 compose.yaml 尚未建立。
- 当前没有通过正式 Compose 文件构建并启动正式双容器架构。
- 结论：未完成。

### M0-B：网络隔离

- 当前 workflow 使用临时 Docker networks、Alpine 和 nginx 占位容器进行部分网络测试。
- 已覆盖部分网络成员关系、固定 IPv4、IPv6 禁用配置、gateway 8080 可达、公网 IPv4 拒绝及另一个测试容器拒绝。
- 这些测试不能代表正式 Compose 架构的完整验收。
- 宿主机网关、IPv6 外连及其他网络边界仍需按流程规范完整验证。
- 结论：未完成。

### M0-C：防火墙与权限

- 当前 workflow 会构建并运行 Dockerfile.validator，检查防火墙加载日志及部分运行身份、能力状态。
- 最近核对的 Actions Run #10：ID 42220291969，Job ID 127900353036，结果失败。
- 失败日志出现：
  - Firewall loaded and verified.
  - Switching to unprivileged validator user...
- 后续未及时捕获预期成功标记。

已确认的 workflow 问题：

容器状态变成 Running，不代表 entrypoint 已完成初始化。当前只等待 Running 后读取一次日志，存在启动时序竞态。

修复方向：

- 轮询启动日志，直到出现成功标记。
- 同时检测容器退出和超时。
- 避免 grep -q 管道造成 SIGPIPE。

注意：修复这个竞态不代表 M0-C 完成。仍需完整验证正式网络环境、防火墙规则、运行进程身份及能力状态。

### M0-D：网关访问控制

尚未完成完整验收。

需要验证：

- 允许符合规则的公网 IPv4 访问。
- 拒绝 private、loopback、link-local、special-use 和未授权内网地址。
- 不得成为任意 IP 转发代理。

### M0-E：DNS 与重定向安全

尚未完成完整验收。

需要验证：

- DNS 正常解析。
- 私有及 loopback 地址拒绝。
- DNS 变化和 rebinding 防护。
- 实际连接 IP 绑定。
- 每一跳 redirect 检查。
- 重定向循环处理。

### M0-F：HLS 子资源安全

尚未完成完整验收。

需要验证：

- 主、子播放列表。
- 音视频分片。
- 密钥和初始化段。
- URI 属性和相对 URL。
- query 和 byte range。
- 不支持的形式必须拒绝。
- 所有媒体资源必须经网关，禁止回退直连。

## 五、已确认的重要技术结论

1. validator 与 media-gateway 必须遵循 CORE_FLOW.md 的双网络设计。
2. validator 只加入 internal 的 validator_net。
3. gateway 同时连接 validator_net 和受控的 gateway_egress。
4. FFmpeg / FFprobe 只能通过 http://media-gateway:8080 访问媒体资源，不得直接连接外部媒体地址。
5. network_guard.py 是统一网络安全实现，不能让不同模块各自实现互相冲突的安全规则。
6. 不能仅凭 setpriv --no-new-privs 推断 capabilities 已清零，必须检查真实运行进程状态。
7. 不得通过随意增加启动能力来绕过能力边界。
8. 正式验收必须针对正式镜像和正式 Compose 网络拓扑。

## 六、当前施工顺序

按模块依赖关系施工，不按 Actions 报错顺序东补一块、西补一块。

1. 重新核对最新仓库版本。
2. 完整核对 CORE_FLOW.md 中网络安全、网关接口、DNS、redirect、HLS 要求。
3. 核对 MASTER_PLAN.md 的 M0-D、M0-E、M0-F。
4. 明确 network_guard.py 的职责、输入输出和调用接口。
5. 实现并检查完整的 network_guard.py。
6. 实现 media_gateway.py 和 Dockerfile.gateway。
7. 建立正式 compose.yaml，落实双网络和固定地址。
8. 补齐正式架构的网络隔离、权限、防火墙、DNS、redirect、HLS 测试。
9. 按 M0-A 至 M0-F 顺序完整验收。
10. 全部通过后，才能将 M0 标记为完成。

**当前下一项工作：**

先完成第 1 至第 3 项规范和接口核对。核对清楚之前，不要直接编写 network_guard.py。

## 七、进度保存制度

出现以下情况，必须更新本文件：

1. 正式决定重大技术方向或架构方案。
2. 发现流程图存在重大缺陷，并决定修改。
3. 查明重要故障的根本原因。
4. 完成重要施工阶段。
5. 验收通过、失败或验收范围发生变化。
6. 改变施工顺序、模块接口或安全边界。
7. 准备结束当前对话或交给新的 ChatGPT 接手。

记录必须区分：

- 已决定：已经确认采用的方案。
- 待确认：尚未决定的想法或规范缺口。
- 已完成：有代码和检查证据支持。
- 未通过：已经执行但失败。
- 未验证：尚未执行，或证据不足。

聊天记录负责讨论，GitHub 文档负责保存最终决定和可交接进度。

## 八、新接手者必须先做什么

1. 检查 GitHub 默认分支最新 commit SHA 和文件树。
2. 阅读 CORE_FLOW.md、MASTER_PLAN.md 和本文件。
3. 核对本文件记录是否与最新代码、测试日志一致。
4. 发现进度变化时先更新记录。
5. 严格按照权威流程和依赖顺序继续施工。
6. 修改文件前读取最新版本及上下游接口。
7. 交付完整文件，并先完成可行的静态检查和测试。
8. 不重复已经有证据的工作，不把未验证事项说成完成。
## 九、2026-11-06 最新核对补充

### 9.1 最新仓库基线

- 核对日期：2026-11-06
- 仓库：womomo8/China-IPTV-Auto-v3
- 默认分支：main

本次连续完成并核验了以下两个文档提交：

1. CORE_FLOW.md：
   - 提交 SHA：ffa1ef3827ba34021cd7a334004df1c4f79a7605
   - 提交说明：docs: clarify gateway and HLS resource budget rules
   - 更新内容：第 7.11 节和第 7.14 节。

2. MASTER_PLAN.md：
   - 提交 SHA：766a1ee1ed81eb3a53dece2da3fbe8f545e1541f
   - 提交说明：docs: align master plan with HLS resource budget rules
   - 更新内容：第 8.15 节。

以上两个提交均已从 GitHub 远端文件重新读取并核验。

最新提交 SHA：
766a1ee1ed81eb3a53dece2da3fbe8f545e1541f

### 9.2 当前文件和实现状态

最近一次目录核对确认，仓库已有基础文档和工作流文件：

- CORE_FLOW.md
- MASTER_PLAN.md
- README.md
- PROGRESS.md
- Dockerfile.validator
- .github/workflows/main.yml

最近两次提交只涉及文档，没有实现业务代码。

以下正式业务模块和配置仍属于待建设内容：

- network_guard.py
- media_gateway.py
- Dockerfile.gateway
- compose.yaml
- pipeline.py
- settings.py
- discovery.py
- normalize.py
- validator.py
- publisher.py
- tests/

开始代码施工前，必须重新读取最新仓库目录，确认实际文件状态。

### 9.3 HLS 首批支持范围和资源预算

状态：文档规范已对齐，程序实现和安全测试尚未完成。

首批 HLS 支持范围：

1. 支持符合规定的 EXT-X-KEY AES-128 密钥 URI。
2. 不支持 EXT-X-SESSION-KEY URI。
3. 不支持 DRM、SAMPLE-AES。
4. 不支持尚未实现的 Low-Latency HLS 资源引用。
5. 不支持 Content Steering。
6. 不支持无法安全解析的特殊资源引用。
7. 不得静默忽略未支持的资源。
8. 不得将原始外部 URI 交给 FFmpeg 绕过网关。

资源预算已经在 CORE_FLOW.md 第 7.11、7.14 节和 MASTER_PLAN.md 第 8.15 节完成同步。

三个数量限制已经明确区分：

- hls_max_resources：单个播放列表中解析的子资源 URI 条目数量。
- hls_max_mapping_count：单个验证任务累计创建的 HLS 子资源映射数量。
- gateway_max_mappings_per_task：单个验证任务全部资源映射数量，包括原始媒体入口和 HLS 子资源。

已经明确：

1. HLS 子资源映射同时受 HLS 专用映射数量和网关任务总映射数量限制。
2. 重复 URI 可以按规范化后的资源身份复用映射，但不能绕过请求次数、读取字节数和 URI 条目数量限制。
3. 通用网关限制与 HLS 专用限制同时执行。
4. 同一项目存在多个上限时，执行更严格的限制。
5. HLS 总读取字节数同时受 hls_max_total_bytes 和适用的 max_media_bytes 限制。
6. 任务级请求次数、读取字节数、映射数量和并发请求数量必须累计管理。
7. 并发预算必须具备并发安全性。
8. 映射必须具有固定有效期，任务结束或异常退出后必须清理。
9. 清理失败的映射不得继续授权。
10. 预算初始值必须等待 GitHub Runner 实际运行校准。

注意：

以上是已经确定的设计规范，不代表资源预算代码已经实现，也不代表参数初始值已经通过实际测试。

### 9.4 网关任务控制接口契约

状态：控制面和媒体面接口设计已在 CORE_FLOW.md 第 7.8 节明确。

已经确定的调用关系：

Runner
→ pipeline.py
→ validator.py
→ docker compose exec -T
→ media-gateway 容器内 media_gateway.py --control
→ Unix Domain Socket
→ 正在运行的 media_gateway.py 服务进程。

已经确定：

1. 控制接口采用 Docker Compose exec + Unix Domain Socket。
2. 不新增 gateway_client.py、worker_server.py 等重复模块。
3. 不向 validator 容器挂载 Docker Socket。
4. 不向 validator 容器挂载控制 Socket。
5. 控制接口只允许 create_task 和 delete_task 两种操作。
6. 控制请求通过标准输入传递 JSON。
7. 不通过命令行参数、环境变量或临时公开文件传递原始 URL 和敏感请求头。
8. Socket 目录权限为 0700。
9. Socket 文件权限为 0600。
10. 网关服务和控制客户端使用固定非 root UID/GID。
11. 服务端检查连接进程 UID。
12. 网关生成至少 256 bit 随机强度的资源标识。
13. 资源映射只保存在网关进程内存中。
14. FFmpeg 只取得当前任务专用 resource_url。
15. FFmpeg 不得取得原始外部 URL 或任务管理权限。
16. 媒体接口只允许 GET/HEAD /v1/resources/{resource_id}。
17. 媒体服务固定绑定 172.30.10.2:8080。
18. 任务正常结束、超时和异常退出时都必须执行清理。
19. 清理失败必须阻止映射继续授权。
20. 清理失败时由映射 TTL 机制兜底，但不得因此重新授权。

固定调用顺序：

1. validator.py 创建唯一 task_id。
2. 通过 Docker Compose exec 调用网关控制客户端。
3. 控制客户端通过 Unix Domain Socket 请求创建任务。
4. 网关创建任务级资源映射。
5. 网关返回当前任务专用 resource_url。
6. validator.py 将 resource_url 交给 FFprobe。
7. 根据 FFprobe 结果执行 FFmpeg 验证。
8. validator.py 收集检测结果和资源消耗。
9. validator.py 请求清理任务。
10. 网关立即使当前任务映射失效。
11. validator.py 输出统一验证结果。

以上接口设计已经写入 CORE_FLOW.md。

但尚未有实际程序实现，不能标记为运行通过。

### 9.5 仍待定义的具体程序接口

虽然网关任务控制和媒体访问接口已经确定，但 network_guard.py 的具体 Python 调用契约仍需在编码前明确。

必须先确定：

1. network_guard.py 对外提供的函数名称和参数。
2. URL 检查、DNS 解析和实际连接之间的统一调用方式。
3. 如何确保检查后的 IPv4 地址与实际连接目标绑定。
4. 如何统一处理普通小响应和媒体流式响应。
5. 如何逐跳检查重定向。
6. 如何保留 HTTPS Host、TLS SNI 和证书验证。
7. 如何统一处理请求超时、响应字节数和错误。
8. media_gateway.py 如何调用 network_guard.py。
9. HLS 子资源如何创建映射并返回改写后的播放列表。
10. 任务级预算如何在并发请求之间安全共享。
11. 如何将安全拒绝、资源不支持、线路网络异常和节点故障区分开。
12. 如何通过测试确认网关不是开放代理。

不得让 network_guard.py、media_gateway.py 和 validator.py 各自创造互不兼容的调用方式。

接口契约确定前，不得直接堆叠程序代码。

### 9.6 更新后的施工顺序

1. 已完成：核对最新 CORE_FLOW.md 和 MASTER_PLAN.md。
2. 已完成：统一 HLS 首批支持范围。
3. 已完成：统一网关和 HLS 资源预算定义。
4. 已完成：明确网关任务控制和媒体访问接口。
5. 当前任务：定义 network_guard.py 的具体 Python 函数接口和统一返回结构。
6. 随后：核对 network_guard.py 与 media_gateway.py 的调用关系。
7. 随后：确定 HLS 资源解析、映射和 URI 改写的内部接口。
8. 检查所有接口是否符合 CORE_FLOW.md 和 MASTER_PLAN.md。
9. 必要时先修订权威文档，再开始代码施工。
10. 实现 network_guard.py。
11. 实现 media_gateway.py 和 Dockerfile.gateway。
12. 建立正式 compose.yaml。
13. 完成网络隔离、DNS、重定向、任务映射、HLS 和资源预算测试。
14. 按 M0-A 至 M0-F 完整验收。

任何步骤不得绕过前置接口和安全验收要求。

### 9.7 当前验收状态

- 五阶段总流程：文档已确定。
- HLS 首批支持范围：文档已对齐。
- HLS 和网关资源预算：文档已对齐。
- 网关任务控制接口：文档已定义。
- 网关媒体访问接口：文档已定义。
- network_guard.py 具体函数接口：待定义。
- network_guard.py：未实现。
- media_gateway.py：未实现。
- Dockerfile.gateway：未实现。
- compose.yaml：未实现。
- pipeline.py：未实现。
- settings.py：未实现。
- 正式业务流程：尚未实现。
- M0-A 至 M0-F：尚未完成全部验收。
- M0 总体验收：未通过，不能标记 PASS。

文档设计完成不能替代程序实现。

程序实现完成不能替代实际测试。

模拟测试通过不能替代真实容器网络隔离测试。

只有取得相应运行证据，才能更新对应验收状态。

### 9.8 本次交接重点

下一位接手者必须先阅读：

1. CORE_FLOW.md：总流程和最高技术规范。
2. MASTER_PLAN.md：施工顺序和验收要求。
3. PROGRESS.md：本次进度和未完成任务。

本次已经确定的资源预算规则和网关控制接口，不得重新设计或擅自简化。

下一步不是直接编写 media_gateway.py，也不是先搭建一套临时代理。

必须先完成 network_guard.py 的具体调用接口、返回结构和安全闭环设计，再进行代码施工。

用户没有国内网络实测条件，因此国内网络实测不是 V3 的硬性验收门槛。当前检测依据仍是 GitHub-hosted Ubuntu Runner，不能宣称能够保证所有国内运营商和家庭网络均可播放。

