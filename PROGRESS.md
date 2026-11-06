China-IPTV-Auto V3 项目进度与交接记录

«本文件用于记录已经核实的项目状态、重要决策、问题结论和下一步工作，供后续 ChatGPT 或开发者接手。

本文件是进度记录，不替代 CORE_FLOW.md。技术规则以 CORE_FLOW.md 为准；施工任务和验收顺序以 MASTER_PLAN.md 为准。若本文件与权威文档冲突，以权威文档为准。»

一、最近核对基线

- 核对日期：2026-11-06
- 仓库：womomo8/China-IPTV-Auto-v3
- 默认分支：main
- 最近已核实的 MASTER_PLAN.md 文档同步提交：8e65c888ff7715fe8b65c023effc546ab543bcc2
- 提交说明：docs: sync network guard interface and request budgets
- 本次更新范围：同步 network_guard.py 接口契约、统一请求预算和当前施工进度。
- 当前状态：V3 建设中，M0 尚未完成完整验收。

注意：

1. 接手时必须重新检查远程仓库最新提交和文件树。
2. 上述 SHA 是已核实的文档提交，不代表它永远是仓库最新提交。
3. 文档接口定义完成，不代表对应程序已经实现。
4. 未实际执行的测试不得记录为通过。

二、项目目标与基本原则

1. 自动发现并筛选真正能够通过现有检测条件验证的 IPv4 IPTV 直播源。
2. 质量优先，不以线路数量为目标；未通过验证的线路不得为了凑数而发布。
3. CORE_FLOW.md 是权威流程和技术规范。
4. MASTER_PLAN.md 是施工任务、依赖顺序和验收计划。
5. PROGRESS.md 记录真实进度、重要决策和交接信息。
6. 不为追求 GitHub Actions 变绿而降低验收标准。
7. 不得用临时占位容器的测试结果冒充正式架构验收。
8. 未经确认的想法不能直接写成权威技术规则。
9. 未经实际测试的功能不能标记为完成。
10. 不使用复杂评分和线路历史数据库代替明确的验证规则。
11. 不得为了增加发布数量而加入未经验证的线路。
12. 用户没有国内网络实测条件，因此国内网络实测不是 V3 的硬性验收门槛。当前以 GitHub-hosted Ubuntu Runner 的可重复检测证据作为施工和验收依据，不得据此宣称保证所有国内运营商和家庭网络均可播放。

三、当前仓库文件状态

最近一次已记录的目录核对确认，仓库已有基础文档和工作流文件：

- CORE_FLOW.md
- MASTER_PLAN.md
- README.md
- PROGRESS.md
- Dockerfile.validator
- .github/workflows/main.yml

以下正式业务模块和配置仍属于待建设内容，开始施工前必须重新检查远程文件树：

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

注意：

1. 文件状态必须以接手时实际读取的 GitHub 远端文件树为准。
2. 不得仅凭本文件的历史记录判断文件现在仍然不存在。
3. 不得把临时测试代码或占位容器当成正式业务模块。

四、M0 当前进度

总状态：未完成，不得标记 M0 PASS。

M0-A：运行环境与正式编排

- 当前 workflow 会检查 Ubuntu Runner、Docker Engine 和 Docker Compose 命令。
- 正式 Dockerfile.gateway 和 compose.yaml 尚未完成建设。
- 尚无完整证据证明正式 Compose 文件已经构建并启动正式双容器架构。
- 结论：未完成，等待正式架构施工和验收。

M0-B：网络隔离

- 现有 workflow 曾使用临时 Docker networks、Alpine 和 nginx 占位容器进行部分网络测试。
- 已覆盖部分网络成员关系、固定 IPv4、IPv6 禁用配置、gateway 8080 可达、公网 IPv4 拒绝及另一个测试容器拒绝。
- 这些测试不能代表正式 Compose 架构的完整验收。
- 宿主机网关、IPv6 外连及其他网络边界仍需按流程规范完整验证。
- 结论：未完成。

M0-C：防火墙与权限

- 当前 workflow 曾构建并运行 Dockerfile.validator，检查防火墙加载日志及部分运行身份、能力状态。
- 历史 Actions Run #10：ID 42220291969，Job ID 127900353036，结果失败。
- 历史失败日志出现：
  - Firewall loaded and verified.
  - Switching to unprivileged validator user...
- 当时未及时捕获预期成功标记。

已经发现的 workflow 问题：

容器状态变成 Running，不代表 entrypoint 已完成初始化。只等待 Running 后读取一次日志，存在启动时序竞态。

修复方向：

- 轮询启动日志，直到出现成功标记。
- 同时检测容器退出和超时。
- 避免 grep -q 管道造成 SIGPIPE。

注意：

1. 上述是历史故障记录，不代表当前 workflow 一定仍存在相同问题。
2. 接手时必须重新检查最新 workflow 和 Actions 日志。
3. 修复启动竞态不代表 M0-C 完成。
4. 仍需完整验证正式网络环境、防火墙规则、运行进程身份及能力状态。

结论：未完成。

M0-D：网关访问控制

尚未完成完整验收。

需要验证：

- 允许符合规则的公网 IPv4 访问。
- 拒绝 private、loopback、link-local、special-use 和未授权内网地址。
- 不得成为任意 IP 转发代理。
- 所有实际外部 HTTP/HTTPS 请求必须经过 network_guard.py。
- 网关不得允许 FFmpeg 绕过网关直连外部媒体地址。

结论：未完成。

M0-E：DNS 与重定向安全

尚未完成完整验收。

需要验证：

- DNS 正常解析。
- 私有及 loopback 地址拒绝。
- DNS 变化和 rebinding 防护。
- 实际连接 IP 绑定。
- 每一跳 redirect 检查。
- 重定向循环处理。
- HTTPS Host、TLS SNI 和证书验证。
- IPv6 fallback 阻断。

结论：未完成。

M0-F：HLS 子资源安全

尚未完成完整验收。

需要验证：

- 主、子播放列表。
- 音视频分片。
- AES-128 密钥和初始化段。
- URI 属性和相对 URL。
- query 和 byte range。
- 不支持的形式必须拒绝或按规范处理。
- 所有媒体资源必须经网关，禁止回退直连。
- 请求次数、读取字节数、映射数量和并发请求必须受到任务级预算控制。

结论：未完成。

五、已确认的重要技术结论

1. validator 与 media-gateway 必须遵循 CORE_FLOW.md 的双网络设计。
2. validator 只加入 internal 的 validator_net。
3. gateway 同时连接 validator_net 和受控的 gateway_egress。
4. FFmpeg / FFprobe 只能通过 "http://media-gateway:8080" 访问媒体资源，不得直接连接外部媒体地址。
5. network_guard.py 是唯一共享网络安全策略实现，不能让不同模块各自实现互相冲突的安全规则。
6. 不能仅凭 setpriv --no-new-privs 推断 capabilities 已清零，必须检查真实运行进程状态。
7. 不得通过随意增加启动能力来绕过能力边界。
8. 正式验收必须针对正式镜像和正式 Compose 网络拓扑。
9. 网关控制面使用 Docker Compose exec 和 Unix Domain Socket，不向 validator 容器挂载 Docker Socket 或控制 Socket。
10. 网关资源映射只保存在网关进程内存中，并且必须绑定任务生命周期。
11. network_guard.py 负责统一网络访问安全；media_gateway.py 负责 HLS 解析、URI 改写、资源映射和任务级预算持有。
12. 不得在 network_guard.py 中建立第二套任务数据库或映射存储。
13. 普通媒体请求和 HLS 请求必须使用统一预算接口，并通过 is_hls 明确区分。
14. 每次外部请求尝试、每次重定向和每次上层重试都必须计入相应任务预算。
15. 单次响应限制和任务级累计限制必须同时生效。

5.1 Docker 网络和权限边界

已确定的目标网络结构：

- validator_net：bridge、internal=true、IPv6 disabled，子网 172.30.10.0/24。
- media-gateway：固定地址 172.30.10.2，内部 TCP 8080。
- validator：固定地址 172.30.10.3，只加入 validator_net。
- gateway_egress：普通受控 bridge、IPv6 disabled，仅 gateway 连接。

validator 的防火墙和权限要求：

- nftables INPUT/OUTPUT 默认 DROP。
- 只允许 loopback、established/related、Docker DNS 和 gateway 172.30.10.2 TCP 8080。
- validator 容器以 root 启动并加载防火墙，随后降权至 UID/GID 10001。
- 设置 no-new-privileges。
- FFmpeg 不得以 root 身份运行。
- 必须核验实际进程能力集。

以上属于正式架构施工和验收要求，不代表全部已经实现或通过测试。

5.2 HLS 首批支持范围

状态：文档规范已确定，程序实现和安全测试尚未完成。

首批支持：

1. HTTP/HTTPS 直接媒体。
2. MPEG-TS。
3. 符合规范的 EXT-X-KEY AES-128 密钥 URI。
4. HLS 主播放列表和已明确支持的子资源。
5. 按规范处理相对 URI、资源映射和 URI 改写。

首批不支持：

1. EXT-X-SESSION-KEY URI。
2. DRM。
3. SAMPLE-AES。
4. 尚未实现的 Low-Latency HLS 资源引用。
5. Content Steering。
6. 无法安全解析的特殊资源引用。

不支持或无法安全解析的资源必须拒绝或按统一错误规则处理，不得静默忽略，更不得把原始外部 URI 交给 FFmpeg 绕过网关。

5.3 网关任务控制接口

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
16. 媒体接口只允许 GET/HEAD "/v1/resources/{resource_id}"。
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

以上是已确定的接口设计，不代表程序实现或运行验收通过。

5.4 network_guard.py 接口契约

<badge>接口文档已确定，程序未实现</badge>

权威依据：

- CORE_FLOW.md 第 7.15.1 节。
- MASTER_PLAN.md 第 8.6 节。
- CORE_FLOW.md 第 7.11、7.14 节。
- MASTER_PLAN.md 第 8.15 节。

已经确定的公开调用方式：

guard = NetworkGuard()

parsed = guard.parse_url(
    url,
    policy=policy,
)

with guard.open_url(
    url,
    method="GET",
    headers=headers,
    policy=policy,
    budget=task_budget,
    is_hls=True,
) as response:
    for chunk in response.iter_bytes():
        process(chunk)

已经确定：

1. NetworkGuard 是统一安全访问入口。
2. parse_url() 只执行静态 URL 检查，不执行 DNS 查询或网络连接。
3. parse_url() 返回 ParsedURL。
4. parse_url() 成功不代表目标已经通过 DNS 和实际连接检查。
5. open_url() 是唯一执行实际外部 HTTP/HTTPS 请求的公开接口。
6. open_url() 成功返回 GuardedResponse。
7. 不得把未经检查的原始 URL 交给其他 HTTP 客户端重新请求。
8. 首批只允许 GET 和 HEAD。
9. 所有请求头必须经过统一安全检查。
10. RequestPolicy 必须由调用方根据 settings.py 统一配置创建。
11. media_gateway.py 每次外部请求都必须传入当前任务的 budget。
12. HLS 主播放列表和全部 HLS 子资源请求必须设置 is_hls=True。
13. 普通媒体请求必须设置 is_hls=False。
14. discovery.py 和快速筛选也必须通过 open_url() 访问外部 HTTP/HTTPS 资源。

RequestPolicy 是不可变请求策略对象，至少包括：

- allowed_schemes
- allowed_ports
- connect_timeout_seconds
- read_timeout_seconds
- total_timeout_seconds
- max_response_bytes
- max_redirect_hops
- max_header_count
- max_header_value_bytes
- max_header_total_bytes

GuardedResponse 至少提供：

- status_code
- headers
- final_url
- peer_ip
- redirect_hops
- iter_bytes(chunk_size)
- read_all()
- close()

必须支持上下文管理器，不得向调用方暴露可绕过限制的原始 socket 或底层 HTTP Response 对象。

RequestBudget 固定方法：

begin_request(*, is_hls: bool) -> None

consume_bytes(
    byte_count: int,
    *,
    is_hls: bool,
) -> None

end_request(*, is_hls: bool) -> None

预算对象必须：

- 绑定唯一 run_id 和 task_id。
- 具备线程安全能力。
- 累计外部请求次数。
- 累计实际读取字节数。
- 管理当前并发请求数量。
- 超限时抛出明确的 BudgetExceeded 错误。
- 保证并发情况下不会突破预算。
- 记录当前任务的请求、字节和并发使用情况。

每次外部请求尝试、每次重定向和每次上层重试都必须计入对应预算。

DNS 查询不计入 HTTP 外部请求次数。

HLS 请求次数实际限制：

min(gateway_max_requests_per_task, hls_max_total_requests)

普通媒体请求遵守 gateway_max_requests_per_task。

GuardError 统一错误对象至少包含：

- code
- kind
- retryable

kind 固定区分：

- REJECTED
- TRANSIENT
- UNSUPPORTED
- BUDGET
- ENVIRONMENT

必须区分安全拒绝、临时网络异常、不支持的资源、预算超限和节点环境故障。不得把所有网络异常都判定为线路 FAIL。

以上接口契约已经同步到 CORE_FLOW.md 和 MASTER_PLAN.md，不得重新发明另一套接口。

重要状态区分：

- network_guard.py 接口契约：已定义。
- network_guard.py 程序：未实现。
- tests/test_network_guard.py：未完成。
- 真实网络安全验收：未完成。

六、当前施工顺序

按 CORE_FLOW.md 的总流程和 MASTER_PLAN.md 的模块依赖关系施工，不按 Actions 报错顺序东补一块、西补一块。

6.1 已完成的文档准备工作

1. 已核对 CORE_FLOW.md 的网络安全、网关接口、DNS、redirect 和 HLS 规范。
2. 已统一 HLS 首批支持范围。
3. 已统一网关和 HLS 资源预算定义。
4. 已明确网关任务控制和媒体访问接口。
5. 已确定 network_guard.py 的具体 Python 调用接口、返回结构、错误分类和任务级预算接口。
6. 已将 network_guard.py 接口契约同步到 CORE_FLOW.md 和 MASTER_PLAN.md。
7. 已将统一请求预算和 HLS 资源预算同步到 MASTER_PLAN.md。

6.2 后续施工顺序

1. 按 MASTER_PLAN.md 检查实现所需配置和模块依赖。
2. 实现 settings.py 中与统一请求策略、网关和 HLS 预算相关的配置。
3. 实现 network_guard.py，严格遵守已经确定的接口契约。
4. 建立并执行 tests/test_network_guard.py。
5. 实现 media_gateway.py 和 Dockerfile.gateway。
6. 建立正式 compose.yaml，落实双网络、固定地址和权限隔离。
7. 实现网关任务控制、媒体访问、HLS 解析、URI 改写和任务级资源预算。
8. 补齐正式架构的网络隔离、DNS rebinding、IPv4/IPv6、重定向、HLS 和资源预算测试。
9. 按 MASTER_PLAN.md 的 M0-A 至 M0-F 顺序完整验收。
10. 全部通过后，才能将 M0 标记为完成。

当前下一项工作：

进入程序施工准备和实现阶段。首先严格核对 CORE_FLOW.md 第 7.15.1 节、MASTER_PLAN.md 第 8.6 节、MASTER_PLAN.md 第 8.15 节及 settings.py 配置要求，然后按施工计划实现 network_guard.py。

不得重新发明已经确定的接口，不得绕过前置安全要求，也不得把接口文档完成当成程序实现完成。

七、进度保存制度

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

重大技术决策必须同步到权威文档，不能只写在聊天记录或本文件里。

八、新接手者必须先做什么

1. 检查 GitHub 默认分支最新 commit SHA 和文件树。
2. 阅读 CORE_FLOW.md、MASTER_PLAN.md 和本文件。
3. 核对本文件记录是否与最新代码、测试日志一致。
4. 发现进度变化时先更新记录。
5. 严格按照权威流程和依赖顺序继续施工。
6. 修改文件前读取最新版本及上下游接口。
7. 交付完整文件，并先完成可行的静态检查和测试。
8. 不重复已经有证据的工作，不把未验证事项说成完成。
9. 不能因为某个测试暂时失败就随意改变架构或降低安全要求。
10. 不能擅自恢复国内网络实测硬性门槛。
11. 用户是初学者，交付修改时必须明确文件路径、完整替换范围和单独的提交说明。
12. 如果文件修改点较多，优先提供完整文件替换内容，不要求用户在多个位置反复寻找和局部编辑。

九、2026-11-06 最新核对补充

9.1 network_guard.py 接口契约同步记录

状态：接口契约已经确定，并已同步到 CORE_FLOW.md 和 MASTER_PLAN.md。

已核实的 MASTER_PLAN.md 文档同步提交：

- 提交 SHA：8e65c888ff7715fe8b65c023effc546ab543bcc2
- 提交说明：docs: sync network guard interface and request budgets

本次同步内容：

1. settings.py 媒体网关配置清单加入 gateway_max_requests_per_task。
2. MASTER_PLAN.md 第 8.6 节明确 network_guard.py 的职责、公开 Python 接口、RequestPolicy、GuardedResponse、RequestBudget、GuardError、调用方职责和测试要求。
3. MASTER_PLAN.md 第 8.15 节明确网关通用预算、HLS 专用预算、请求次数累计、资源映射数量、并发和字节预算规则。
4. 统一请求预算与 HLS 预算必须同时生效，采用更严格的限制。
5. 文档同步完成不代表程序实现或安全验收完成。

接手时必须重新读取 GitHub 远端文件，确认这些内容仍然存在且没有被后续提交覆盖。

9.2 当前文件和实现状态

最近一次目录核对确认，仓库已有基础文档和工作流文件：

- CORE_FLOW.md
- MASTER_PLAN.md
- README.md
- PROGRESS.md
- Dockerfile.validator
- .github/workflows/main.yml

以下正式业务模块和配置仍属于待建设内容，接手时必须重新检查实际文件树：

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

9.3 资源预算规则

状态：文档规范已对齐，程序实现和安全测试尚未完成。

三个数量限制必须明确区分：

- hls_max_resources：单个播放列表中解析的子资源 URI 条目数量。
- hls_max_mapping_count：单个验证任务累计创建的 HLS 子资源映射数量。
- gateway_max_mappings_per_task：单个验证任务全部资源映射数量，包括原始媒体入口和 HLS 子资源。

已经明确：

1. HLS 子资源映射同时受 HLS 专用映射数量和网关任务总映射数量限制。
2. 重复 URI 可以复用已有映射，但不能绕过请求次数、读取字节数和 URI 条目数量限制。
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

9.4 网关任务控制接口状态

状态：控制面和媒体面接口设计已确定，程序尚未实现。

已经确定：

1. 控制接口采用 Docker Compose exec + Unix Domain Socket。
2. 不新增重复的客户端或服务端模块。
3. 不向 validator 容器挂载 Docker Socket 或控制 Socket。
4. 控制接口只允许 create_task 和 delete_task 两种操作。
5. 控制请求通过标准输入传递 JSON。
6. 不通过命令行参数、环境变量或临时公开文件传递原始 URL 和敏感请求头。
7. Socket 目录权限为 0700，Socket 文件权限为 0600。
8. 服务端检查连接进程 UID。
9. 资源映射只保存在网关进程内存中。
10. FFmpeg 只取得当前任务专用 resource_url。
11. 任务正常结束、超时和异常退出时都必须执行清理。
12. 清理失败必须阻止映射继续授权。

以上接口设计已经写入 CORE_FLOW.md，但尚无实际程序实现证据。

9.5 network_guard.py 具体程序接口契约

状态：接口契约已经确定，程序尚未实现。

权威依据：

- CORE_FLOW.md 第 7.15.1 节。
- MASTER_PLAN.md 第 8.6 节。
- CORE_FLOW.md 第 7.11、7.14 节。
- MASTER_PLAN.md 第 8.15 节。

已经确定的公开接口：

1. NetworkGuard 是唯一统一的外部 HTTP/HTTPS 安全访问入口。
2. parse_url(url, policy=policy) 负责静态 URL 检查，返回 ParsedURL，不执行 DNS 和网络连接。
3. open_url(...) 负责实际外部请求，返回 GuardedResponse。
4. RequestPolicy 是不可变请求策略对象，由调用方根据 settings.py 配置创建。
5. RequestBudget 是统一任务级资源预算接口。
6. GuardedResponse 负责受限制的流式读取和连接资源释放。
7. GuardError 负责统一网络错误分类。
8. discovery.py、快速筛选和 media_gateway.py 必须遵守统一网络访问接口。
9. media_gateway.py 创建并持有任务级预算对象，再传给 network_guard.py。
10. HLS 请求和普通媒体请求必须通过 is_hls 明确区分。
11. DNS 检查、实际 IPv4 连接绑定、TLS 证书验证、逐跳重定向检查不得被其他模块重复实现。
12. 不得将未经检查的原始外部 URL 交给其他 HTTP 客户端绕过安全入口。

RequestBudget 固定方法：

begin_request(*, is_hls: bool) -> None

consume_bytes(
    byte_count: int,
    *,
    is_hls: bool,
) -> None

end_request(*, is_hls: bool) -> None

预算必须具备线程安全能力，并累计请求次数、实际读取字节数和并发请求数量。

每次外部请求尝试、每次重定向和每次上层重试都必须计入对应预算。

HLS 请求次数实际限制：

min(gateway_max_requests_per_task, hls_max_total_requests)

普通媒体请求遵守 gateway_max_requests_per_task。

以上是已经确定的接口契约，不代表程序已经实现，也不代表安全测试已经通过。

9.6 更新后的施工顺序

1. 已完成：核对最新 CORE_FLOW.md 和 MASTER_PLAN.md。
2. 已完成：统一 HLS 首批支持范围。
3. 已完成：统一网关和 HLS 资源预算定义。
4. 已完成：明确网关任务控制和媒体访问接口。
5. 已完成：定义 network_guard.py 的具体 Python 函数接口和统一返回结构。
6. 已完成：将 network_guard.py 接口契约同步到 CORE_FLOW.md 和 MASTER_PLAN.md。
7. 当前阶段：按既定接口契约检查配置依赖，准备 network_guard.py 程序施工。
8. 随后：实现 network_guard.py 和对应单元测试。
9. 随后：实现 media_gateway.py 和 Dockerfile.gateway。
10. 随后：建立正式 compose.yaml。
11. 随后：完成网络隔离、DNS rebinding、IPv4/IPv6、重定向、HLS 和资源预算测试。
12. 最后：按 M0-A 至 M0-F 完整验收。

任何步骤不得绕过前置接口和安全验收要求。

不得因为程序实现遇到困难而擅自改变 CORE_FLOW.md 中已经确定的安全边界。

9.7 当前验收状态

- 五阶段总流程：文档已确定。
- HLS 首批支持范围：文档已对齐。
- HLS 和网关资源预算：文档已对齐。
- 网关任务控制接口：文档已定义。
- 网关媒体访问接口：文档已定义。
- network_guard.py 具体 Python 接口：已定义，已同步到权威文档。
- network_guard.py：未实现。
- network_guard.py 单元测试：未完成。
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

9.8 本次交接重点

下一位接手者必须先阅读：

1. CORE_FLOW.md：总流程和最高技术规范。
2. MASTER_PLAN.md：施工顺序和验收要求。
3. PROGRESS.md：当前进度和未完成任务。

本次已经确定的 network_guard.py 接口、网关控制接口、HLS 支持范围和资源预算规则，不得重新设计或擅自简化。

下一步不是重新讨论接口，也不是先搭建临时代理。

必须按照既定接口契约进入程序施工，并在实现过程中持续对照 CORE_FLOW.md 和 MASTER_PLAN.md。

用户没有国内网络实测条件，因此国内网络实测不是 V3 的硬性验收门槛。当前检测依据仍是 GitHub-hosted Ubuntu Runner，不能宣称能够保证所有国内运营商和家庭网络均可播放。
