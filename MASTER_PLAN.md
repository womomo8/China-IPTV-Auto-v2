# China-IPTV-Auto V3

# MASTER_PLAN.md — 完整施工计划

## 文件定位

本文件负责把 `CORE_FLOW.md` 规定的总流程、技术架构、模块职责和验收标准，拆解为具体施工任务、施工顺序、模块接口、测试方法和里程碑。

**最高依据：`CORE_FLOW.md`**

本文件不是第二套总流程，也不是独立的技术架构设计。

所有施工任务必须遵循以下规则：

1. `CORE_FLOW.md` 是唯一总流程依据和最高技术施工规范。
2. 本文件只负责展开施工任务和验收安排。
3. 本文件不得自行增加业务阶段、业务入口、正式工作流或发布路径。
4. 本文件不得改变 `CORE_FLOW.md` 已经确定的模块职责、调用方向、数据接口和安全规则。
5. 两份文件出现冲突时，以 `CORE_FLOW.md` 为准，修订本文件后才能继续施工。
6. README.md 负责项目介绍和使用说明，不得另行定义业务流程。

**实施状态说明：**

本文件描述目标施工方案，不代表程序已经全部创建、功能已经实现或测试已经通过。

架构确定不等于代码完成。

配置存在不等于安全隔离已经生效。

测试文件存在不等于测试已经通过。

每项功能必须有对应代码、实际测试结果和验收证据，才能标记完成。

---

# 一、项目施工目标

## 1.1 项目目标

建设一套自动化、轻量化、可持续运行的 IPTV 直播源筛选系统。

从多个来源发现直播地址，经过数据整理、IPv4 准入、快速筛选和深度媒体验证，最终只发布通过全部必要检查的线路。

项目第一目标是线路质量，不是线路数量。

例如：

- 收集 1000 条，最终 20 条通过，就发布 20 条。
- 收集 1000 条，最终 5 条通过，就发布 5 条。
- 没有合格线路，不发布不合格线路。
- 本轮关键检测无法可靠完成时，保留上一份正式订阅。
- 不为了让订阅看起来更丰富而降低检测标准。
- 不使用未验证线路补足数量。

不建设复杂评分体系。

不建立复杂线路历史关系。

不建设相互依赖的多层评分机制。

不建立不必要的长期线路历史数据库。

本轮候选数据、检测结果和统计信息由 pipeline.py 在本轮流程中统一管理，不为同一批候选建立多个互相竞争的数据存储。

## 1.2 核心原则

1. 只有一个业务入口：`pipeline.py`。
2. 只有一个正式工作流：`.github/workflows/main.yml`。
3. 固定五个业务阶段。
4. 只有一个正式订阅文件：`output/iptv.m3u`。
5. 统一配置、统一数据结构、统一状态规则。
6. 不建设复杂评分体系。
7. 不建立不必要的线路历史数据库。
8. 不擅自增加自动黑名单系统。
9. 不允许未验证线路进入正式订阅。
10. 不允许 FFmpeg 直接连接公网媒体地址。
11. 不允许安全测试失败后绕过隔离继续正式验证。
12. 不把云端检测结果宣传为所有地区和运营商的播放保证。
13. 不把设计方案冒充已经实现的程序。
14. 不把模拟测试冒充实际安全验收。
15. 不使用旧线路补充本轮结果。
16. 不设置没有实际依据的最低发布线路数量。
17. 所有正式发布结果必须来自本轮完整检测结果。

## 1.3 固定业务流程

前置工程准备不属于业务阶段。

五阶段业务流程固定为：

    第一阶段：广泛发现
              |
              v
    第二阶段：数据整理
              |
              v
    第三阶段：快速筛选
              |
              v
    第四阶段：深度验证
              |
              v
    第五阶段：安全发布

完整工作流：

    .github/workflows/main.yml
              |
              v
         pipeline.py
              |
              v
        广泛发现
              |
              v
        数据整理
              |
              v
        快速筛选
              |
              v
        深度验证
              |
              v
        安全发布
              |
              v
         publisher.py
              |
              v
        本轮临时发布产物
              |
              v
       pipeline Job 校验
              |
              v
        上传本轮 Artifact
              |
              v
       GitHub Actions publish Job
              |
              v
       核验当前运行的 Artifact
              |
              v
       更新唯一正式订阅
              |
              v
        output/iptv.m3u

固定要求：

- 五个业务阶段由 pipeline.py 按顺序组织和调度。
- publisher.py 只生成和校验本轮临时发布产物。
- pipeline Job 负责生成、核验并上传本轮 Artifact。
- publish Job 负责核验当前运行的产物并更新正式订阅。
- pipeline Job 不得直接提交正式订阅。
- publish Job 不得重新执行五阶段业务。
- 前置工程准备不计入五个业务阶段。
- 测试、安全检查和变更控制贯穿整个施工过程，不另设业务阶段。

---

# 二、最终目标文件结构与模块职责

## 2.1 目标目录结构

V3 目标结构如下：

    China-IPTV-Auto-v3/
    |
    |-- .github/
    |   `-- workflows/
    |       `-- main.yml
    |
    |-- tests/
    |   |-- test_network_guard.py
    |   |-- test_discovery.py
    |   |-- test_normalize.py
    |   |-- test_media_gateway.py
    |   |-- test_network_isolation.py
    |   |-- test_validator.py
    |   |-- test_publisher.py
    |   `-- test_pipeline.py
    |
    |-- settings.py
    |-- sources.txt
    |-- network_guard.py
    |-- discovery.py
    |-- normalize.py
    |-- media_gateway.py
    |-- validator.py
    |-- publisher.py
    |-- pipeline.py
    |
    |-- Dockerfile.gateway
    |-- Dockerfile.validator
    |-- compose.yaml
    |
    |-- requirements.txt
    |
    |-- output/
    |   `-- iptv.m3u
    |
    |-- README.md
    |-- MASTER_PLAN.md
    `-- CORE_FLOW.md

以上是目标结构，不代表所有文件已经创建或实现。

实际施工前必须核对仓库当前目录。

不得为了形式完整而随意增加文件。

不得保留已经失去用途的旧入口、重复配置、重复数据存储或重复发布文件。

新增、删除或重命名文件，必须先检查实际依赖、调用关系、配置引用、工作流引用和测试引用。

## 2.2 文件唯一职责

| 文件 | 唯一施工职责 |
|---|---|
| main.yml | GitHub Actions 调度、运行环境准备、权限控制、Artifact 交接和正式 Git 提交 |
| pipeline.py | 唯一业务入口，按固定顺序组织五阶段 |
| settings.py | 统一运行参数、超时、并发、资源预算和安全配置 |
| sources.txt | 人工维护公开来源地址 |
| discovery.py | 读取来源、获取原始内容、汇总原始候选 |
| normalize.py | 播放列表解析、字段规范化、组合去重和候选准入 |
| network_guard.py | 统一 URL、DNS、IP、重定向和实际网络访问安全控制 |
| media_gateway.py | 接收受控媒体请求，代理外部媒体资源，处理受支持的 HLS 子资源 |
| validator.py | 快速筛选、调用 FFprobe 和隔离环境中的 FFmpeg |
| publisher.py | 发布资格检查、临时 M3U 生成、校验和本轮发布产物准备 |
| Dockerfile.gateway | 构建媒体网关容器 |
| Dockerfile.validator | 构建 FFmpeg/FFprobe 环境和必要的防火墙启动工具 |
| compose.yaml | 定义容器、固定地址、Docker 网络和权限关系 |
| requirements.txt | Python 项目依赖 |
| tests/ | 模块、接口、流程和安全测试 |
| output/iptv.m3u | 唯一正式订阅 |

注意：

1. `network_guard.py` 是共享安全策略模块，不是业务入口。
2. `media_gateway.py` 是受控媒体访问服务，不是第二个业务入口。
3. `validator.py` 负责快速筛选和深度验证，但内部必须保持明确的先后顺序。
4. `publisher.py` 不负责 Git push，不直接更新 GitHub 正式订阅。
5. Dockerfile 不负责业务调度。
6. main.yml 不负责复制 Python 模块的业务逻辑。

## 2.3 唯一调用关系

唯一业务主流程：

    main.yml
       |
       v
    pipeline.py
       |
       v
    discovery.py
       |
       v
    normalize.py
       |
       v
    validator.py
       |
       +--> 快速筛选
       |
       +--> 深度验证
       |
       v
    publisher.py
       |
       v
    本轮发布产物
       |
       v
    pipeline Job
       |
       v
    GitHub Actions publish Job
       |
       v
    output/iptv.m3u

网络安全辅助关系：

    discovery.py --------+
                         |
    normalize.py --------+----> network_guard.py
                         |
    validator.py --------+
                         |
    media_gateway.py ----+

说明：

- discovery.py 在访问来源前执行安全检查。
- normalize.py 只使用适用的静态 URL 和地址规则，不在数据整理阶段自行发起外部网络请求。
- validator.py 的网络检查必须使用统一安全规则。
- media_gateway.py 在实际代理外部媒体请求时执行统一安全检查。
- Dockerfile.gateway 使用仓库同一份 network_guard.py。
- network_guard.py 不负责采集、去重、媒体质量判断或发布。
- network_guard.py 不反向调用业务模块。

深度媒体验证关系：

    pipeline.py
        |
        v
    validator.py
        |
        v
    Docker Compose
        |
        +-----------------------------+
        |                             |
        v                             v
    FFmpeg 验证容器               media_gateway
        |                             |
        |                             v
        |                       network_guard.py
        |                             |
        +------受控媒体请求------------+
                                      |
                                      v
                                  外部媒体源

固定依赖方向：

- pipeline.py 调度业务模块。
- 业务模块调用共享安全模块。
- validator.py 通过 Docker 管理隔离验证任务。
- media_gateway.py 调用 network_guard.py。
- GitHub Actions 调度 pipeline.py 并处理本轮发布产物。

禁止反向调用和循环依赖。

## 2.4 明确禁止的结构

- 不建立 main.py 作为第二个业务入口。
- 不建立第二个正式工作流。
- 不让 discovery.py 调用 validator.py。
- 不让 validator.py 调用 normalize.py 重新整理数据。
- 不让 publisher.py 自行重新采集线路。
- 不让 publisher.py 自行运行 FFprobe 或 FFmpeg。
- 不让 publisher.py 自行执行 Git push。
- 不让 validator.py 直接访问外部媒体服务器。
- 不让 FFmpeg 直接访问公网媒体地址。
- 不让 FFmpeg 容器连接外部出口网络。
- 不让 media_gateway.py 成为开放公网代理。
- 不让 network_guard.py 反向调用业务模块。
- 不在 main.yml 中编写线路筛选业务逻辑。
- 不让多个模块分别定义不同的安全策略。
- 不让多个模块分别定义互相冲突的状态。
- 不让多个模块重复维护同一个参数。
- 不建立循环依赖。
- 不建立重复数据存储。
- 不建立重复正式订阅。
- 不让旧 Artifact 或其他运行批次产物混入本轮发布。

---

# 三、前置工程准备：M0 安全隔离可行性验证

## 3.1 目标

在正式开发 FFmpeg 深度验证功能之前，先完成 Docker 双网络架构和端口级网络隔离的可行性验证。

M0 是前置工程准备，不属于五阶段业务流程。

M0 必须按照 CORE_FLOW 已经确定的固定架构施工。

不把 FFmpeg 直接联网作为备用实现。

不把取消网络隔离作为临时降级方案。

不把安全测试失败后继续深度验证作为可选路径。

## 3.2 固定目标架构

运行环境：

- GitHub-hosted 标准 Ubuntu Runner。
- Docker Engine。
- Docker Compose。
- 独立媒体网关容器。
- 独立 FFmpeg/FFprobe 验证容器。
- Docker 双网络。
- validator 容器内部 nftables 防火墙。

网络关系：

    GitHub Actions Runner
              |
              v
         Docker Compose
              |
       +------+----------------+
       |                       |
       v                       v
  validator_net          gateway_egress
  internal: true         普通受控 bridge
       |                       |
       v                       |
  validator 容器               |
       |                       |
       +----内部访问------------+
                               |
                               v
                       media-gateway
                               |
                               v
                         外部媒体源

固定要求：

1. validator 只加入 validator_net。
2. validator_net 设置 internal: true。
3. validator_net 禁用 IPv6。
4. validator 不加入 gateway_egress。
5. media-gateway 同时加入 validator_net 和 gateway_egress。
6. gateway_egress 只连接 media-gateway。
7. FFmpeg 只能访问媒体网关内部地址和 TCP 8080 端口。
8. 网关负责全部受控外部媒体请求。
9. network_guard.py 负责外部目标的统一安全检查。
10. 不开放不必要的宿主机端口。
11. 不使用 host 网络模式。
12. 不使用 privileged 模式。
13. 不挂载 Docker Socket。

## 3.3 固定网络名称、地址和端口

网络名称：

    validator_net
    gateway_egress

validator_net：

- Docker bridge 网络。
- internal: true。
- 固定 IPv4 子网。
- 禁用 IPv6。
- 不提供外部默认出口。

gateway_egress：

- 普通受控 bridge 网络。
- 只连接 media-gateway。
- 禁用 IPv6。
- 不连接 validator。

固定内部地址：

| 项目 | 固定值 |
|---|---|
| validator_net 子网 | 172.30.10.0/24 |
| media-gateway | 172.30.10.2 |
| validator | 172.30.10.3 |
| 网关服务名 | media-gateway |
| 网关内部端口 | TCP 8080 |

FFmpeg 使用以下内部服务地址：

    http://media-gateway:8080

服务名、固定地址、监听地址、端口和 Compose 配置必须保持一致。

网关必须绑定 validator_net 的内部地址和 8080 端口。

不得将网关管理接口或内部管理端口暴露到公网。

不得通过宿主机端口映射完成 FFmpeg 与网关之间的通信。

如果 Runner 环境发生子网冲突，必须统一修改 settings.py、compose.yaml、防火墙规则和测试用例，不得只修改其中一处。

## 3.4 validator 容器内部 nftables 规则

validator 容器必须在自己的网络命名空间内建立 nftables 防火墙规则。

默认策略：

- OUTPUT 默认 DROP。
- INPUT 默认 DROP。

允许：

- loopback。
- 已建立或关联的返回流量。
- Docker 内部 DNS：127.0.0.11 UDP 53。
- Docker 内部 DNS：127.0.0.11 TCP 53。
- media-gateway：172.30.10.2 TCP 8080。

禁止：

- 其他 IPv4 出站。
- 其他 IPv6 出站。
- 访问宿主机网关。
- 访问其他容器。
- 访问网关其他端口。
- 直接访问外部媒体源。
- 通过 DNS、重定向或其他网络方式绕过网关。

防火墙必须在 FFmpeg/FFprobe 进程启动之前完成加载。

规则缺失或加载失败时，validator 容器不得进入正常验证状态。

## 3.5 防火墙初始化与权限降级

Dockerfile.validator 必须提供：

- FFmpeg。
- FFprobe。
- nftables。
- setpriv 所需工具。
- 固定 UID/GID 的非 root 验证用户。

启动顺序固定为：

1. validator 容器启动阶段以 root 身份运行初始化入口。
2. 必须先移除容器全部默认 Linux capabilities。
3. 启动阶段仅明确添加以下三项必要能力：
   - NET_ADMIN：仅用于加载本容器网络命名空间内的 nftables 规则。
   - SETUID：仅用于通过 setpriv 切换到固定非 root 用户。
   - SETGID：仅用于通过 setpriv 切换到固定非 root 用户组并清除附加组。
4. 加载 nftables 规则。
5. 检查防火墙规则确实存在。
6. 检查通过后，立即通过 setpriv 切换到固定 UID/GID 的非 root 用户。
7. setpriv 必须启用 no-new-privileges。
8. 权限切换后，常驻进程及其启动的 FFmpeg/FFprobe 必须以非 root 身份运行。
9. 常驻进程及 FFmpeg/FFprobe 的 CapEff 和 CapPrm 均不得包含 NET_ADMIN、SETUID、SETGID。
10. validator.py 执行 docker compose exec 时必须显式指定固定非 root 用户。

NET_ADMIN、SETUID 和 SETGID 只允许用于启动阶段的防火墙初始化及身份切换，不得作为 FFmpeg/FFprobe 的运行权限长期保留。

不得仅凭 setpriv 或 no-new-privileges 配置，就认定启动能力已经全部清除。

必须通过实际容器测试检查：

- 运行进程的 UID。
- 运行进程的 GID。
- /proc/self/status 中的 CapEff。
- /proc/self/status 中的 CapPrm。
- /proc/self/status 中的 NoNewPrivs。

必须确认：

- 进程以固定非 root 用户运行。
- CapEff 不包含 NET_ADMIN、SETUID、SETGID。
- CapPrm 不包含 NET_ADMIN、SETUID、SETGID。
- NoNewPrivs 为启用状态。

不得仅根据 Docker Compose 配置文本认定权限隔离已经成功。

不得让 FFmpeg/FFprobe 以 root 身份运行。

不得使用 privileged 或 host 网络模式。

不得挂载 Docker Socket。

防火墙加载失败、规则检查失败、权限降级失败或容器启动检查失败，均不得继续深度验证。

## 3.6 M0 施工任务

**M0-A：Runner 环境检查**

检查：

- 标准 Ubuntu Runner 能否正常运行。
- Docker Engine 是否可用。
- Docker Compose 是否可用。
- 两个镜像能否正常构建。
- internal 网络能否创建。
- 固定网络地址能否使用。
- 容器能否按要求启动和停止。
- 运行结束后能否清理资源。

**M0-B：Docker 网络隔离**

验证：

- validator 只加入 validator_net。
- validator_net 的 internal 属性有效。
- gateway_egress 只连接网关。
- 网关同时加入两个网络。
- FFmpeg 不能直接访问公网 IPv4。
- FFmpeg 不能直接访问公网 IPv6。
- FFmpeg 不能访问宿主机网关。
- FFmpeg 不能访问其他容器的非授权服务。

**M0-C：nftables 和权限降级**

验证：

- 默认拒绝规则有效。
- loopback 通信正常。
- Docker 内部 DNS 访问正常。
- 172.30.10.2:8080 可以访问。
- 网关其他端口无法访问。
- 防火墙规则缺失时容器不能正常启动。
- 防火墙加载失败时容器不能正常启动。
- validator 启动前已移除全部默认 Linux capabilities。
- 启动阶段仅保留 NET_ADMIN、SETUID、SETGID 三项必要能力。
- nftables 规则加载并检查通过。
- setpriv 成功切换到固定 UID/GID 的非 root 用户。
- 常驻进程及 FFmpeg/FFprobe 的 CapEff 不包含 NET_ADMIN、SETUID、SETGID。
- 常驻进程及 FFmpeg/FFprobe 的 CapPrm 不包含 NET_ADMIN、SETUID、SETGID。
- NoNewPrivs 为启用状态。
- FFmpeg/FFprobe 使用非 root 用户。

**M0-D：媒体网关外部访问**

验证：

- 网关能够访问允许的公网 IPv4。
- 网关拒绝私有地址。
- 网关拒绝回环地址。
- 网关拒绝链路本地地址。
- 网关拒绝其他特殊地址。
- 网关不能访问未授权内网。
- 网关不能成为任意 IP 转发器。

**M0-E：DNS 和重定向**

验证：

- 正常域名解析。
- DNS 解析到公网 IPv4。
- DNS 解析到私有地址。
- DNS 解析到回环地址。
- DNS 结果变化。
- DNS rebinding。
- DNS 检查与实际连接 IP 绑定。
- 重定向到其他公网地址。
- 重定向到私有地址。
- 重定向到 IPv6 地址。
- 连续重定向。
- 重定向循环。

**M0-F：HLS 请求链**

使用本地模拟媒体服务构造测试数据。

至少测试：

- 主播放列表。
- 子播放列表。
- 视频分片。
- 音频分片。
- 加密密钥。
- 初始化片段。
- URI 属性。
- 相对 URL。
- 查询参数。
- 字节范围。
- 不支持的标签和 URI 形式。

预期：

所有受支持外部资源请求都经过网关。

无法安全解析的资源必须拒绝，不得让 FFmpeg 直接访问原始外部地址。

## 3.7 M0 验收标准

以下项目全部通过，才允许标记 M0 完成：

- Runner Docker 环境正常。
- Compose 能正常编排两个容器。
- 双网络关系符合固定设计。
- FFmpeg 不能直接访问公网 IPv4。
- FFmpeg 不能直接访问公网 IPv6。
- FFmpeg 只能访问网关 8080。
- 网关其他端口不能被访问。
- nftables 默认拒绝规则有效。
- nftables 规则加载失败时容器不能继续运行。
- validator 已移除全部默认 Linux capabilities。
- 启动阶段仅使用 NET_ADMIN、SETUID、SETGID 三项必要能力。
- setpriv 成功切换到固定非 root 用户。
- 常驻进程及 FFmpeg/FFprobe 的 CapEff、CapPrm 均不包含上述三项启动能力。
- NoNewPrivs 为启用状态。
- FFmpeg/FFprobe 使用非 root 用户。
- 网关不能被用作任意 IP 转发器。
- DNS 检查与实际连接目标绑定有效。
- 重定向逐跳检查有效。
- HLS 受支持子资源经过网关。
- 关键绕行测试全部通过。

## 3.8 M0 交付物

- Dockerfile.gateway
- Dockerfile.validator
- compose.yaml
- tests/test_network_isolation.py
- M0 实际测试记录

以上交付物只有在实际创建并测试后才能标记完成。

---

# 四、基础工程施工：M1

## 4.1 目标

建立统一配置、唯一业务入口、统一数据结构、统一状态规则和基础测试框架。

M1 不得提前建立第二套业务流程。

M1 不得实现与五阶段职责冲突的业务逻辑。

## 4.2 settings.py

settings.py 是所有运行参数的统一读取入口。

必须集中管理以下配置类别。

**来源发现：**

- source_timeout
- source_max_bytes
- max_source_count
- source_retry
- discovery_total_timeout
- discovery_concurrency

**快速筛选：**

- quick_connect_timeout
- quick_read_timeout
- quick_total_timeout
- quick_concurrency

**深度验证：**

- ffprobe_timeout
- ffmpeg_timeout
- max_media_bytes
- max_media_duration
- max_validation_jobs

**媒体网关：**

- gateway_request_timeout
- gateway_max_response_bytes
- gateway_max_redirect_hops

**网关映射：**

- gateway_mapping_ttl_seconds
- gateway_max_mappings_per_task
- gateway_resource_id_bytes

**请求头：**

- gateway_max_header_count
- gateway_max_header_value_bytes
- gateway_max_header_total_bytes

**HLS：**

- hls_max_resources
- hls_max_depth
- hls_max_playlist_bytes
- hls_max_resource_bytes
- hls_max_total_bytes
- hls_max_total_requests
- hls_max_concurrent_requests
- hls_max_request_timeout
- hls_max_mapping_count
- hls_max_redirect_hops
- hls_max_header_total_bytes

**Docker：**

- validator_cpu_limit
- validator_memory_limit
- validator_pids_limit
- gateway_cpu_limit
- gateway_memory_limit

**网络安全：**

- allowed_schemes
- allowed_ports
- IPv4 强制策略
- 禁止访问的地址范围
- validator_net 子网
- media-gateway 固定内部地址
- 网关内部端口

**运行控制：**

- run_mode
- 运行级总超时
- 任务清理超时

要求：

1. 所有实际参数统一从 settings.py 读取。
2. 不同模块不得重复维护同一个参数。
3. Docker Compose 中的网络地址和端口必须与统一配置一致。
4. Docker 启动阶段需要的静态安全规则必须通过统一配置和固定接口管理。
5. 测试模式与正式模式必须明确区分。
6. 敏感凭证不得写入公开配置文件。
7. 初始参数必须保守。
8. 需要 Runner 实测的参数标记为待校准。
9. 不得把未经实际运行验证的参数称为最佳值或最终值。

达到单线路资源预算后，根据实际证据返回 FAIL 或 UNKNOWN，不得影响其他独立线路继续验证。

## 4.3 pipeline.py

pipeline.py 是唯一业务入口。

负责：

1. 读取本轮运行模式。
2. 加载统一配置。
3. 检查基础运行环境。
4. 检查必要工具。
5. 检查本轮必要安全条件。
6. 按固定顺序调用五个业务阶段。
7. 接收各阶段执行结果。
8. 管理本轮候选数据和检测结果。
9. 控制阶段之间的数据传递。
10. 根据统一状态规则决定继续、跳过或停止。
11. 生成本轮运行报告。
12. 将合格结果交给 publisher.py。
13. 将本轮运行状态和发布资格交给 GitHub Actions。

不得在 pipeline.py 中重新实现采集、去重、媒体网关、安全检查或 M3U 生成细节。

不得由业务模块反向调用 pipeline.py。

不得启动第二套完整业务流程。

## 4.4 requirements.txt

要求：

- 只加入真正需要的 Python 依赖。
- 不引入没有实际用途的大型框架。
- 对关键依赖固定或约束版本。
- FFmpeg 和 FFprobe 的安装、版本检查单独处理。
- 安全相关依赖必须明确版本和用途。
- 不因为开发方便引入重复功能库。

## 4.5 统一数据和状态基础

所有模块使用 CORE_FLOW 规定的候选记录字段和四种统一状态。

不在不同模块中重复定义不同的数据结构。

不建立不必要的长期线路历史数据库。

本轮数据由 pipeline.py 统一管理。

## 4.6 M1 验收

- Python 环境正常。
- 统一配置能够正确读取。
- pipeline.py 能够启动。
- 只有一个业务入口。
- 五阶段调用顺序固定。
- 统一候选结构可用。
- PASS、FAIL、UNKNOWN、NODE_ERROR 能正确传递。
- 基础测试框架可运行。
- 缺少依赖时能够明确报告环境故障。
- 不存在循环依赖。
- 不存在重复配置。

---

# 五、第一阶段施工：广泛发现 M2

## 5.1 负责文件

discovery.py

## 5.2 输入

sources.txt。

每行一个公开来源地址。

规则：

- 空行忽略。
- 以 # 开头的注释行忽略。
- 每轮运行重新读取配置。
- 来源失败不自动从配置中删除。
- 不把密码、Token 或私密凭证写入公开仓库。
- 不支持的来源格式必须明确记录。

## 5.3 施工任务

discovery.py 按以下顺序执行：

1. 读取 sources.txt。
2. 检查来源配置格式。
3. 识别受支持的来源类型。
4. 对来源地址执行静态安全检查。
5. 请求前调用 network_guard.py。
6. 使用受安全约束的 HTTP/HTTPS 客户端获取原始内容。
7. 限制请求超时。
8. 限制响应体积。
9. 判断来源内容格式。
10. 获取原始播放列表内容。
11. 对单个来源执行有限重试。
12. 记录每个来源的执行状态。
13. 汇总成功来源的原始候选。
14. 将原始候选交给 pipeline.py。

## 5.4 职责边界

discovery.py 只负责来源访问和原始内容获取。

不负责：

- 频道名称最终规范化。
- 频道组合去重。
- IPv4 实际连接验证。
- FFprobe 或 FFmpeg。
- 最终 M3U 生成。
- 正式订阅替换。
- Git 提交和推送。

## 5.5 网络安全

来源地址访问前必须经过统一安全检查。

必须覆盖：

- URL 协议限制。
- URL 格式检查。
- DNS 目标检查。
- 实际连接 IP 约束。
- 私有和特殊地址拒绝。
- 重定向逐跳检查。
- 超时限制。
- 响应体积限制。

不能因为来源地址来自人工配置就跳过安全检查。

来源访问不能成为绕过 network_guard.py 的入口。

## 5.6 资源限制

使用 settings.py 中的统一配置：

- 单来源请求超时。
- 单来源最大响应字节数。
- 最大来源数量。
- 单来源重试次数。
- 全局发现总超时。
- 来源访问并发数。
- 响应读取限制。

不得无限等待或无限下载。

## 5.7 异常处理

| 情况 | 处理 |
|---|---|
| 单个来源成功 | 保存原始内容 |
| 单个来源失败 | 记录并继续 |
| 临时网络错误 | 有限重试 |
| 来源格式不支持 | 记录并跳过 |
| 所有来源失败 | 停止本轮，不发布 |
| 没有有效原始内容 | 停止本轮，不发布 |
| 全局安全组件故障 | NODE_ERROR |

## 5.8 M2 验收

- 来源配置读取正确。
- 支持来源能够获取原始内容。
- 单来源失败不会拖垮其他来源。
- 人工配置每轮重新读取。
- 超时和体积限制有效。
- 来源访问安全检查有效。
- 不支持的来源能够明确记录。
- 原始内容不会直接进入正式订阅。

---

# 六、第二阶段施工：数据整理 M3

## 6.1 负责文件

normalize.py

## 6.2 输入

第一阶段获取的原始播放列表内容和来源执行结果。

## 6.3 施工任务

1. 解析受支持的播放列表格式。
2. 提取频道名称。
3. 提取播放 URL。
4. 提取必要请求头。
5. 提取分组和频道元数据。
6. 规范化字段。
7. 检查记录完整性。
8. 检查 URL 格式和协议。
9. 执行 IPv4 准入。
10. 执行组合去重。
11. 保留必要来源信息。
12. 输出统一候选记录。

## 6.4 组合去重

唯一组合依据：

- 规范化频道名称。
- 规范化 URL。
- 规范化必要请求头。

规则：

| 情况 | 处理 |
|---|---|
| 同频道、同 URL、相同必要请求头 | 合并 |
| 同频道、不同 URL | 保留不同线路 |
| 不同频道、同 URL | 保留不同频道 |
| 请求头不同且影响播放 | 分别保留 |
| 地址格式错误 | 淘汰或隔离 |

不得只按频道名称去重。

不得只按 URL 去重后丢失影响播放的必要请求头。

不建立复杂历史关系，不进行长期线路评分。

## 6.5 IPv4 准入

检查：

- URL 是域名还是 IP。
- 域名是否有符合要求的 IPv4 A 记录。
- DNS 解析结果是否属于允许的公网 IPv4 范围。
- 是否包含私有、回环、链路本地、多播或特殊地址。
- 是否存在明确不支持的协议。
- 是否能够满足后续 IPv4 实际连接要求。

注意：

DNS A 记录存在，不等于实际连接一定使用 IPv4。

实际连接必须在后续网络请求阶段再次确认。

IPv4 准入通过不等于线路可播放。

## 6.6 媒体协议准入

首批实际支持范围：

- HTTP/HTTPS 直接媒体资源。
- HTTP/HTTPS 传输的 MPEG-TS 媒体资源。
- HTTP/HTTPS 传输的 MP4 媒体资源。
- HTTP/HTTPS HLS M3U8 播放列表。
- 通过受控 HLS 解析和改写访问的受支持子资源。

MPEG-TS 和 MP4 是媒体封装或资源格式，不是独立网络传输协议。

RTSP、RTP、UDP、RTMP、MMS 等不属于首批支持范围。

不支持的协议必须明确记录，不得伪装成已经支持的协议。

## 6.7 数据安全

不得：

- 把密码、Token 或 Cookie 输出到普通日志。
- 把私密请求头写入公开订阅。
- 把不完整记录伪装成有效候选。
- 静默删除影响播放的必要请求头。
- 把未知协议当成已支持协议。

如果候选缺少必要信息，根据实际证据淘汰或标记 UNKNOWN。

## 6.8 M3 验收

- 支持格式解析正确。
- 必要请求头保留正确。
- 组合去重正确。
- 同频道不同线路不会被误删。
- 同 URL 不同频道不会被误删。
- IPv4 准入有效。
- 不支持协议能够明确识别。
- 不合格记录有明确原因。
- 输出数据结构统一。
- 私密凭证不会泄漏。

---

# 七、第三阶段施工：快速筛选 M4

## 7.1 负责文件

validator.py

快速筛选和深度验证由同一个 validator.py 管理，但必须保持清晰的内部职责边界。

## 7.2 输入

第二阶段完成整理、IPv4 准入和去重的候选记录。

## 7.3 施工任务

快速筛选按以下顺序执行：

1. 接收规范化候选。
2. 检查 URL 和必要请求头。
3. 调用 network_guard.py 执行适用的安全检查。
4. 检查 DNS 解析结果。
5. 通过 IPv4 建立实际连接。
6. 检查实际连接目标是否与安全检查结果一致。
7. 检查连接建立情况。
8. 检查基础 HTTP 或协议响应。
9. 记录必要响应信息。
10. 根据明确规则判定 PASS、FAIL 或 UNKNOWN。
11. 将 PASS 候选交给深度验证。

## 7.4 快速筛选原则

快速筛选重点是低资源消耗地淘汰明显无效线路。

检查项目保持轻量：

- 基础连接是否建立。
- 请求是否获得合理响应。
- 是否满足当前支持协议的基本要求。
- 是否存在明确错误。
- 是否在规定时间内获得有效响应。

不得加入复杂线路质量评分系统。

不得使用多层评分相互决定是否通过。

不得为了排序而引入不必要的历史数据。

TCP 连接成功不等于直播可播放。

HTTP 返回成功不等于媒体能够解码。

## 7.5 超时和错误处理

必须区分：

- 目标明确无效：FAIL。
- 单条线路暂时超时、证据不足：UNKNOWN。
- 网络安全模块或共享网络基础设施异常：NODE_ERROR。

不能所有 timeout 一律 FAIL。

不能所有 timeout 一律 UNKNOWN。

必须结合错误来源和实际证据判断。

DNS 分类统一遵循第十一章。

## 7.6 资源控制

统一从 settings.py 读取：

- 连接超时。
- 读取超时。
- 单线路总超时。
- 快速筛选并发数。
- 必要重试次数。
- 本轮快速筛选资源预算。

不得在多个模块重复定义不同的超时和并发参数。

## 7.7 输出

第三阶段输出：

- 快速筛选 PASS 候选。
- FAIL 候选及原因。
- UNKNOWN 候选及原因。
- 快速筛选统计。
- 本阶段执行状态。

只有 PASS 候选可以进入深度验证。

## 7.8 M4 验收

- 快速筛选资源消耗受控。
- DNS 和实际连接符合 IPv4 要求。
- 实际连接目标经过安全检查。
- 单条线路失败不影响其他线路。
- PASS、FAIL、UNKNOWN 和 NODE_ERROR 区分正确。
- UNKNOWN 不进入深度验证。
- 未通过快速筛选的线路不能进入深度验证。
- 快速筛选通过不等于具备发布资格。
- 不存在复杂评分和历史关系依赖。

---

# 八、第四阶段施工：深度验证 M5

## 8.1 负责文件

- validator.py
- media_gateway.py
- network_guard.py
- Dockerfile.gateway
- Dockerfile.validator
- compose.yaml
- settings.py

## 8.2 输入

第三阶段快速筛选 PASS 的候选记录。

## 8.3 固定执行架构

    pipeline.py
        |
        v
    validator.py
        |
        v
    Docker Compose
        |
        +-----------------------------+
        |                             |
        v                             v
    FFmpeg 验证容器               media_gateway
        |                             |
        |                             v
        |                       network_guard
        |                             |
        +------内部受控请求------------+
                                      |
                                      v
                                  外部媒体源

固定职责：

- validator.py 管理深度验证任务。
- FFmpeg/FFprobe 只在隔离网络中运行。
- media_gateway.py 是访问外部媒体资源的唯一业务入口。
- network_guard.py 负责实际外部请求的安全约束。
- validator.py 不直接访问外部媒体服务器。
- FFmpeg 不得通过其他网络路径绕过网关。

## 8.4 validator.py 施工任务

1. 接收快速筛选通过的线路。
2. 检查本轮 Docker 环境。
3. 检查媒体网关状态。
4. 检查网络隔离安全关卡。
5. 为线路创建独立验证任务。
6. 将原始媒体 URL 和必要请求头交给媒体网关建立受控映射。
7. 获取当前任务专用的内部网关访问地址。
8. 将内部网关地址交给隔离环境中的 FFprobe。
9. 执行 FFprobe 媒体探测。
10. 根据结果执行 FFmpeg 实际读取或解码验证。
11. 记录执行结果、错误和资源消耗。
12. 销毁或失效当前任务的网关资源映射。
13. 输出统一验证结果。
14. 区分线路级故障和环境级故障。
15. 将深度验证结果交给 pipeline.py。

不得将原始公网 URL 直接交给 FFmpeg。

不得让 FFmpeg 自行访问 HLS 原始子资源地址。

## 8.5 media_gateway.py 施工任务

1. 接收内部验证任务。
2. 验证任务标识和请求参数。
3. 取得原始媒体地址。
4. 调用 network_guard.py 检查目标。
5. 使用受约束的 HTTP/HTTPS 客户端请求外部资源。
6. 每次重定向重新检查。
7. 检查实际连接 IP。
8. 保留必要 Host、TLS SNI 和证书验证行为。
9. 处理支持的媒体响应。
10. 解析和改写受支持的 HLS 资源地址。
11. 将子资源地址改写为网关内部地址。
12. 记录必要请求结果。
13. 任务结束后清理临时映射。
14. 映射过期后拒绝访问。
15. 网关异常时拒绝继续代理。

网关不能成为任意公网代理或任意内网访问工具。

不得允许 FFmpeg 通过网关进行任意 IP 转发。

## 8.6 network_guard.py 施工任务

network_guard.py 是唯一共享网络安全策略实现。

负责：

- URL 格式检查。
- 允许协议检查。
- DNS 解析和地址检查。
- 公网 IPv4 准入。
- 私有、回环、链路本地和特殊地址拒绝。
- DNS 检查与实际连接 IP 绑定。
- DNS rebinding 防护。
- TOCTOU 防护。
- 重定向逐跳检查。
- 实际 IPv4 连接约束。
- 不允许 IPv6 fallback。
- 请求超时和响应限制。
- 必要的网络安全记录。

依赖关系：

    discovery.py ------+
    normalize.py ------+----> network_guard.py
    validator.py ------+
    media_gateway.py --+

说明：

- normalize.py 只使用适用的静态规则，不在数据整理阶段自行发起外部网络请求。
- discovery.py 使用统一规则访问来源。
- validator.py 使用统一规则执行快速筛选和适用的网络检查。
- media_gateway.py 使用统一规则执行实际媒体外部请求。
- network_guard.py 不调用任何业务模块。

不得让各个模块复制一套互相不一致的 DNS 和 IP 安全规则。

## 8.7 DNS 与实际连接绑定

不能只在请求前解析 DNS 并检查一次，然后让底层 HTTP 客户端重新解析域名并自行选择连接地址。

必须保证：

1. 先取得 DNS 解析结果。
2. 对解析得到的所有目标地址执行安全检查。
3. 只选择符合规则的 IPv4 地址。
4. 实际 socket 连接使用已经检查过的 IPv4 地址。
5. 连接失败时不得自动回退到未经检查的 IPv6 地址。
6. HTTPS 保留正确 Host。
7. HTTPS 保留正确 TLS SNI。
8. HTTPS 证书验证不能关闭。
9. DNS 结果变化时重新检查。

实现必须使用能够固定连接目标地址的安全 HTTP 传输方式，或经过测试的等效实现。

不得出现检查时是安全 IP、实际连接时又被客户端重新解析到其他 IP 的情况。

## 8.8 重定向

每一跳重定向都必须：

1. 解析 Location。
2. 正确处理相对 Location。
3. 检查新 URL。
4. 重新解析 DNS。
5. 重新检查 IP。
6. 重新绑定实际 IPv4 连接目标。
7. 检查协议和端口。
8. 检查重定向次数。
9. 防止重定向循环。

重定向不得绕过 network_guard.py。

禁止无限重定向。

## 8.9 Docker 网络隔离施工任务

compose.yaml 必须实现：

- validator 只加入 validator_net。
- validator_net 使用 internal: true。
- validator_net 禁用 IPv6。
- validator 使用固定内部地址 172.30.10.3。
- media-gateway 同时加入 validator_net 和 gateway_egress。
- media-gateway 在 validator_net 使用固定地址 172.30.10.2。
- gateway_egress 只连接 media-gateway。
- FFmpeg 没有公网出口。
- 网关只提供内部 TCP 8080 服务。
- 不开放不必要的宿主机端口。
- 不使用 host 网络模式。
- 不使用 privileged 模式。
- 不挂载 Docker Socket。
- 使用非 root 用户运行 FFmpeg/FFprobe。
- 设置 CPU、内存和进程数量限制。
- 限制临时文件和缓存占用。

Docker internal 网络只是隔离基础，必须结合 validator 容器内部 nftables 端口级限制。

必须通过真实绕行测试确认实际效果。

## 8.10 HLS 施工任务

HLS 必须形成完整的网关解析和改写闭环。

首批必须处理：

- Master Playlist。
- Media Playlist。
- 子播放列表。
- 视频分片。
- 音频分片。
- TS、M4S 等媒体分片。
- 加密密钥 URI。
- 初始化片段。
- EXT-X-STREAM-INF 后续 URI。
- EXT-X-MEDIA URI。
- EXT-X-I-FRAME-STREAM-INF URI。
- EXT-X-KEY URI。
- EXT-X-MAP URI。
- 普通 URI 行。
- 相对 URL。
- 绝对 URL。
- 查询参数。
- HTTP Range。
- EXT-X-BYTERANGE。

首批加密密钥只支持能够由当前 FFmpeg 环境安全处理的 AES-128 方式。

首批不支持：

- EXT-X-SESSION-KEY URI 属性。
- DRM。
- SAMPLE-AES。
- Low-Latency HLS 的 PART、PRELOAD-HINT 等资源引用。
- Content Steering。
- 尚未实现的其他 URI 扩展标签。
- 无法安全处理的特殊密钥格式。

对于上述不支持的资源，必须拒绝请求或标记 UNKNOWN，不得静默忽略，不得原样交给 FFmpeg 访问。

处理顺序：

1. 接收当前任务的播放列表请求。
2. 检查任务映射和访问权限。
3. 通过 network_guard.py 获取播放列表。
4. 判断 Master Playlist 或 Media Playlist。
5. 解析已支持的标签和 URI。
6. 正确处理相对 URI。
7. 解析普通 URI 行。
8. 解析 URI 属性中的子资源。
9. 为子资源建立当前任务专用映射。
10. 将外部 URI 改写为内部网关 URI。
11. 将改写后的播放列表返回 FFmpeg。
12. FFmpeg 请求子资源时重新验证任务映射。
13. 网关按映射中的原始目标和必要请求头访问外部资源。
14. 每次重定向继续执行安全检查。

不得只代理主播放列表。

不得只改写普通 URI 行而遗漏 URI 属性。

不得将原始 HLS 内容原样交给 FFmpeg，再依赖 FFmpeg 自行访问外部子资源。

对于无法安全解析或尚未支持的资源引用：

- 不得绕过网关。
- 不得让 FFmpeg 直接访问外部地址。
- 应拒绝请求或标记 UNKNOWN。
- 不得静默忽略。
- 必须记录具体原因。

## 8.11 HLS Range 和请求头

对于受支持的 HLS 资源，正确处理 HTTP Range。

检查：

- Range 请求头。
- Content-Range 响应。
- 206 Partial Content。
- 必要的 Content-Length。
- 请求范围是否超出允许资源边界。

不得把不完整范围响应伪装成完整媒体资源。

必要请求头、查询参数和资源映射必须保持一致。

如果某些请求头不能安全地跨子资源传递，必须明确拒绝或标记 UNKNOWN。

## 8.12 网关任务级资源映射

每条待验证线路建立独立任务级资源映射。

映射至少包含：

- 本轮运行标识。
- 验证任务标识。
- 原始媒体 URL。
- 必要请求头。
- 允许访问的资源类型。
- 映射创建时间。
- 映射过期时间。
- 当前任务状态。

固定规则：

1. 每个验证任务使用独立、不可预测的资源标识。
2. 资源标识使用安全随机数生成，至少具有 256 bit 随机强度。
3. 资源标识不得直接暴露原始目标 URL。
4. 资源标识同时承担内部访问授权凭证作用。
5. 映射绑定本轮运行标识和具体验证任务。
6. 不同任务之间不得共享可写入的映射状态。
7. 不允许通过修改 URL 参数访问任意外部目标。
8. 不允许客户端自行提交 URL 让网关代为访问。
9. 不允许通过修改资源 ID 访问其他任务资源。
10. 必要请求头必须绑定在映射中。
11. 映射必须有明确有效期。
12. 任务结束后必须使映射失效。
13. 异常退出时也必须清理映射。
14. 映射清理失败时必须阻止其被其他任务继续使用。
15. 授权标识不得写入普通日志。

映射只在当前网关进程内存中保存。

不建立第二套数据库。

不把任务授权映射持久化到公开文件。

网关必须在内部验证当前请求对应的有效任务映射。

## 8.13 请求头安全

必要请求头由 validator.py 创建任务时交给网关。

网关必须根据任务映射使用对应请求头。

不得允许 FFmpeg 任意覆盖：

- Host。
- Authorization。
- Cookie。
- 其他影响目标访问和安全边界的请求头。

普通请求头必须有明确允许规则。

不同任务的请求头不得互相传递。

请求头必须设置：

- 最大数量。
- 单字段最大字节数。
- 总字节数上限。

超过限制时拒绝创建映射。

## 8.14 首批媒体协议支持范围

首批只支持 HTTP 或 HTTPS 传输的媒体资源。

具体支持：

1. HTTP/HTTPS 直接媒体资源。
2. HTTP/HTTPS 传输的 MPEG-TS 媒体资源。
3. HTTP/HTTPS 传输的 MP4 媒体资源。
4. HTTP/HTTPS HLS M3U8 播放列表。
5. 通过受控 HLS 解析和改写访问的子播放列表、媒体分片、初始化分片和受支持的加密密钥资源。

MPEG-TS 和 MP4 是媒体封装或资源格式，不是独立网络传输协议。

首批 HLS 必须明确支持并测试：

- Master Playlist。
- Media Playlist。
- EXT-X-STREAM-INF 后续 URI。
- EXT-X-MEDIA 的 URI 属性。
- EXT-X-I-FRAME-STREAM-INF 的 URI 属性。
- 普通媒体分片 URI。
- EXT-X-KEY 的受支持密钥 URI。
- EXT-X-MAP 的初始化分片 URI。
- EXT-X-BYTERANGE。
- 相对 URI。
- 查询参数。
- 嵌套播放列表。
- HTTP Range 请求。

加密密钥首批只支持能够由当前 FFmpeg 环境安全处理的 AES-128 方式。

不支持：

- DRM。
- SAMPLE-AES。
- RTSP。
- RTP。
- UDP 组播或单播媒体流。
- RTMP。
- MMS。
- 未明确实现并通过安全测试的其他协议。
- Low-Latency HLS 的 PART、PRELOAD-HINT 等资源引用。
- Content Steering。
- 尚未实现的其他 URI 扩展标签。
- 无法安全处理的特殊密钥格式。

不支持的协议或资源：

1. normalize.py 必须识别并记录不支持原因。
2. 不得把不支持的协议伪装成 HTTP/HTTPS。
3. 不得尝试通过 FFmpeg 直接访问原始外部地址。
4. 不得绕过媒体网关。
5. 可以在数据整理阶段明确淘汰，也可以在运行时标记 UNKNOWN。
6. 不支持的线路不得进入正式订阅。

以后增加协议或 HLS 功能，必须先修改 CORE_FLOW.md、统一接口和安全测试范围，再修改程序。

## 8.15 HLS 和网关资源预算

所有网关和 HLS 参数必须由 settings.py 统一管理。

网关通用限制和 HLS 专用限制必须同时生效，不允许某个模块只执行其中一套限制。

### A. 网关映射预算

至少包括：

- gateway_mapping_ttl_seconds：任务映射有效期。
- gateway_max_mappings_per_task：单任务全部资源映射的最大数量。
- gateway_resource_id_bytes：资源标识随机字节数。
- gateway_request_timeout：普通网关请求超时。
- gateway_max_response_bytes：普通网关响应最大字节数。
- gateway_max_redirect_hops：普通网关请求最大重定向跳数。
- gateway_max_header_count：允许的最大请求头数量。
- gateway_max_header_value_bytes：单个请求头最大字节数。
- gateway_max_header_total_bytes：请求头总字节数上限。

gateway_max_mappings_per_task 统计当前任务全部有效映射，包括：

1. 原始媒体入口映射。
2. HLS 子播放列表映射。
3. HLS 媒体分片映射。
4. HLS 初始化分片映射。
5. HLS 密钥映射。
6. 其他已经明确支持的 HLS 子资源映射。

所有映射共用同一个任务级总数量上限。

### B. HLS 专用预算

至少包括：

- hls_max_resources：单个播放列表允许解析的最大子资源 URI 条目数。
- hls_max_depth：最大嵌套播放列表深度。
- hls_max_playlist_bytes：单个 HLS 播放列表最大读取字节数。
- hls_max_resource_bytes：单个 HLS 子资源最大响应字节数。
- hls_max_total_bytes：单个 HLS 验证任务所有 HLS 资源的总读取字节数上限。
- hls_max_total_requests：单个 HLS 验证任务最大请求次数。
- hls_max_concurrent_requests：单个 HLS 验证任务最大并发子资源请求数。
- hls_max_request_timeout：单个 HLS 子资源请求超时。
- hls_max_mapping_count：单个 HLS 验证任务累计创建的 HLS 子资源映射最大数量。
- hls_max_redirect_hops：HLS 子资源请求最大重定向跳数。
- hls_max_header_total_bytes：HLS 请求头总字节数上限。

以下三个数量限制必须明确区分：

- hls_max_resources：限制单个播放列表中解析的子资源 URI 条目数量。
- hls_max_mapping_count：限制整个验证任务累计创建的 HLS 子资源映射数量。
- gateway_max_mappings_per_task：限制整个验证任务全部资源映射数量，包括原始媒体入口映射和 HLS 子资源映射。

重复 URI 可以按规范化后的资源身份复用已有映射，但不得因此绕过请求次数、实际读取字节数和播放列表 URI 条目数限制。

HLS 子资源映射必须同时满足：

1. 不超过 hls_max_mapping_count。
2. 不超过 gateway_max_mappings_per_task。
3. 不超过其他适用的单任务资源预算。

任何一项达到上限，都必须停止当前任务继续创建相应映射。

### C. 通用限制与 HLS 专用限制的关系

通用网关限制和 HLS 专用限制必须同时生效。

同一项资源使用多个上限时，实际生效值采用其中更严格的限制。

具体规则：

| 限制项目 | 实际生效规则 |
|---|---|
| HLS 请求超时 | min(gateway_request_timeout, hls_max_request_timeout) |
| HLS 重定向跳数 | min(gateway_max_redirect_hops, hls_max_redirect_hops) |
| HLS 请求头总字节数 | min(gateway_max_header_total_bytes, hls_max_header_total_bytes) |
| HLS 子资源响应字节数 | min(gateway_max_response_bytes, hls_max_resource_bytes) |
| HLS 播放列表字节数 | min(gateway_max_response_bytes, hls_max_resource_bytes, hls_max_playlist_bytes) |
| HLS 全部映射数量 | 同时受 hls_max_mapping_count 和 gateway_max_mappings_per_task 限制 |
| HLS 单任务总读取字节数 | 同时受 hls_max_total_bytes 和适用的 max_media_bytes 限制 |

这里的 min 表示取所有适用限制中的最小值。

普通媒体资源不适用 HLS 专用限制，但仍必须遵守通用网关和单线路预算。

如果其他通用单线路预算比 HLS 专用预算更严格，也必须优先执行更严格的限制。

不得因为 HLS 有单独配置，就绕过通用资源上限。

### D. 任务级累计预算

所有任务级资源预算必须在整个验证任务范围内累计。

至少包括：

- 外部请求次数。
- 重定向请求次数。
- 实际读取字节数。
- HLS 子资源 URI 条目数量。
- HLS 映射数量。
- 当前并发请求数量。
- 当前任务创建的全部映射数量。

重定向产生的每一次实际外部请求都必须计入请求次数。

同一个任务内的并发请求必须共享同一份预算。

预算检查和累计必须具备并发安全性，不能因多个请求同时执行而突破上限。

不得只限制单个分片大小，却允许大量分片使整个任务无限下载。

达到总资源预算后，必须停止当前任务的进一步资源请求，并根据故障证据标记 UNKNOWN。

不得因为一条线路达到资源上限而影响其他独立线路继续验证。

### E. 映射生命周期

- 映射创建时记录创建时间和固定过期时间。
- 映射不得超过 settings.py 规定的有效期。
- 映射有效期不得因后续请求自动无限延长。
- 任务正常结束后立即清理。
- 任务异常退出时执行清理。
- 网关必须定期清理已经过期的映射。
- 清理失败的映射必须立即禁止继续授权。
- 不得因为清理失败而让其他任务继续使用当前任务映射。
- 不得让已过期或已结束任务的资源标识重新生效。

### F. 初始值和校准

可以在首次施工时设置保守初始值。

但初始值必须标记为待 Runner 实测校准。

不得把未经实际运行验证的参数称为最佳值、最终值或已验证值。

参数调整必须说明原因，并检查是否影响其他模块。

达到单线路预算时，应根据实际情况返回 FAIL 或 UNKNOWN，不得影响其他独立线路继续验证。

## 8.16 FFprobe 与 FFmpeg 验证规则

FFprobe 负责：

- 探测媒体格式。
- 识别媒体流。
- 获取视频和音频流信息。
- 识别时长、编码和其他可获得的媒体元数据。
- 提供后续验证参考信息。

FFmpeg 负责：

- 实际读取媒体数据。
- 在指定条件下执行媒体解码。
- 检查媒体数据是否能够持续读取到规定的测试边界。
- 记录读取和解码过程中的错误。

必须区分：

- FFprobe 成功：媒体信息探测成功。
- FFmpeg 读取成功：媒体数据能够被读取。
- FFmpeg 解码成功：在指定测试条件下完成对应解码。
- 检测未完成：UNKNOWN。
- 验证工具无法正常启动：根据故障范围判定 NODE_ERROR。

不能把 FFprobe 成功直接当成最终播放成功。

不能把 HTTP 请求成功直接当成媒体解码成功。

不能把一次短时间读取成功描述为长期稳定。

不能因为 FFmpeg 超时就一律判定线路无效。

必须区分线路响应问题、媒体读取问题和检测环境故障。

## 8.17 广告和占位内容识别边界

可以研究和实现明显广告片段、占位内容或异常媒体的辅助识别。

但必须遵守：

- 不得仅凭 FFprobe 成功就宣称已经识别广告。
- 不得仅凭媒体格式判断内容是否为真实频道。
- 没有可靠检测依据时，不得把广告识别描述成确定结论。
- 无法确定的情况应记录为 UNKNOWN 或辅助观察结果。
- 广告识别不得取代 FFprobe 和 FFmpeg 的实际媒体检查。
- 不得因为识别不确定就伪造线路失败结论。

## 8.18 M5 验收

必须全部满足：

- Docker 环境正常。
- Docker Compose 服务关系正确。
- FFmpeg 容器只连接隔离内部网络。
- 媒体网关同时连接内部网络和受控外部网络。
- validator 内部 nftables 规则成功加载。
- FFmpeg 运行进程不具备 NET_ADMIN。
- FFmpeg 使用非 root 用户。
- FFmpeg 不能绕过网关访问外部媒体源。
- FFmpeg 只能访问网关 TCP 8080。
- IPv4 和 IPv6 隔离测试有效。
- 宿主机网关和其他容器访问受到阻断。
- DNS rebinding 和 TOCTOU 防护经过测试。
- 重定向逐跳检查有效。
- 实际连接目标与安全检查目标一致。
- HTTPS Host、TLS SNI 和证书验证正确。
- 网关任务级映射有效。
- 不同验证任务之间不能互相访问资源。
- 任务结束后映射能够失效。
- 映射过期后不能继续访问。
- HLS 已声明支持的子资源全部经过网关。
- HLS 相对 URI、URI 属性、密钥和分片处理正确。
- Range 和 Byte Range 行为经过测试。
- 未支持的媒体请求不会回退直连。
- 网关故障不会使 FFmpeg 获得直接联网能力。
- FFprobe 和 FFmpeg 结果区分清楚。
- 单条线路失败不会导致所有线路中断。
- 全局环境故障能够正确返回 NODE_ERROR。
- 网络隔离未通过时不会进入正式发布。

---

# 九、第五阶段施工：安全发布 M6

## 9.1 负责文件

- publisher.py
- pipeline.py
- .github/workflows/main.yml

## 9.2 输入

第四阶段完整深度验证结果。

输入必须包含：

- 候选线路记录。
- 数据整理结果。
- IPv4 准入结果。
- 快速筛选结果。
- 深度验证结果。
- 必要频道元数据。
- 必要播放请求头。
- 本轮阶段执行状态。
- 安全关卡执行结果。
- 本轮运行标识。
- 本轮运行模式。

## 9.3 发布资格

每条线路必须同时满足：

1. 数据整理阶段通过。
2. IPv4 准入通过。
3. 快速筛选通过。
4. 深度验证通过。
5. 必要请求头能够安全处理。
6. 不包含不允许公开的私密凭证。
7. 线路记录完整且格式有效。
8. 本轮所有必要检测均已完成。

只有满足全部条件的线路才能进入正式订阅。

FAIL、UNKNOWN 和未完成验证的线路不得发布。

不得以其他线路的检测结果替代本线路结果。

不得因为某条线路数量少、来源少或频道名称重要而放宽发布资格。

## 9.4 publisher.py 施工任务

publisher.py 按以下顺序执行：

1. 检查本轮运行模式。
2. 检查本轮运行状态。
3. 检查各阶段是否可靠完成。
4. 检查 Docker 网络安全关卡是否通过。
5. 检查媒体网关是否正常。
6. 检查线路是否全部满足发布资格。
7. 过滤所有 FAIL、UNKNOWN 和未完成验证的线路。
8. 生成本轮临时 M3U。
9. 检查文件格式和内容。
10. 检查是否存在未通过验证的线路。
11. 检查是否包含敏感凭证。
12. 检查临时文件完整性。
13. 生成本轮 Manifest 和文件摘要。
14. 返回本轮发布产物和发布资格给 pipeline.py。

publisher.py 只负责生成和校验本轮发布产物。

publisher.py 不负责：

- 正式订阅文件替换。
- Git add。
- Git commit。
- Git push。
- GitHub 远端文件更新。

## 9.5 唯一正式订阅

唯一正式订阅路径：

    output/iptv.m3u

不得生成多个互相竞争的正式订阅文件。

临时文件只用于本轮生成、校验和安全交接，不是第二份正式订阅。

本轮临时 Artifact 不是第二个长期订阅地址。

正式订阅必须符合 M3U 格式要求。

发布结果必须只包含本轮完整通过检测的线路。

首次正式发布成功前，不得宣称订阅已经可用。

## 9.6 发布产物和 Manifest

Artifact 至少包含：

- 本轮生成的 M3U 文件。
- 本轮 manifest.json。

Manifest 至少记录：

- workflow_run_id。
- commit_sha。
- run_mode。
- pipeline_status。
- publish_eligible。
- artifact_file。
- artifact_sha256。
- 生成时间。
- 必要的阶段完成状态。

Manifest 不得包含：

- 密码。
- Token。
- Cookie。
- Authorization。
- 私密请求头。

M3U 文件摘要必须与 Manifest 中记录的 SHA-256 一致。

Artifact 必须来自当前 workflow run。

Artifact 名称必须包含本轮唯一运行标识。

不得使用固定旧文件代替本轮产物。

Artifact 保留时间必须明确设置，并覆盖正常 Job 交接时间。

## 9.7 publish Job 发布职责

正式文件更新由 GitHub Actions 的独立 publish Job 完成。

publish Job 负责：

1. 确认当前模式为 PRODUCTION。
2. 确认 pipeline Job 成功。
3. 确认发布资格为 true。
4. 下载当前 workflow run 的 Artifact。
5. 核对 workflow_run_id。
6. 核对 commit_sha。
7. 核对运行模式。
8. 核对 pipeline_status。
9. 核对 publish_eligible。
10. 校验 M3U 文件 SHA-256。
11. 检查 M3U 格式和内容。
12. 检查是否只有完整通过验证的线路。
13. 检查是否存在敏感凭证。
14. 将校验通过的文件安全替换到 output/iptv.m3u。
15. 检查 Git 变更范围。
16. 只提交规定的正式订阅文件。
17. 推送到仓库。
18. 确认远端文件确实更新。

publish Job 不得重新执行五阶段业务。

publish Job 不得重新采集、整理、筛选、FFprobe 或 FFmpeg 验证。

publish Job 只接受当前运行的产物。

正式文件替换必须先完成全部校验。

替换失败不得破坏旧文件。

Git 提交或推送失败，不得报告正式发布成功。

## 9.8 发布保护

以下情况不得更新正式文件：

- 所有来源失败。
- 没有有效候选数据。
- 没有任何线路通过深度验证。
- 关键阶段发生 NODE_ERROR。
- Docker 网络隔离关卡未通过。
- nftables 端口限制未通过。
- validator 权限降级失败。
- 媒体网关无法正常工作。
- 本轮关键检测未可靠完成。
- 临时 M3U 文件校验失败。
- 发现未验证线路混入。
- 发现敏感凭证泄漏。
- Artifact 缺失。
- Artifact 与当前运行标识不匹配。
- commit SHA 不匹配。
- M3U 摘要与 Manifest 不匹配。
- 正式文件替换失败。
- 当前运行模式为 TEST。
- 正式 Git 提交或推送失败。

出现以上情况时，保留上一份正式订阅。

## 9.9 数量与发布原则

线路数量只反映本轮真实通过检测的结果。

必须遵守：

- 不设置没有跑测依据的最低线路数。
- 不因数量减少而降低检测标准。
- 不使用旧线路补充本轮结果。
- 不建立复杂评分或线路历史关系。
- 不以历史数量替代本轮验证结果。
- 不因发布数量少而自动放宽检测条件。
- 不为了凑数保留 FAIL 或 UNKNOWN 线路。

本轮有多少条线路完整通过，就发布多少条。

本轮没有线路通过，就保留上一份正式订阅，不发布不合格线路。

## 9.10 M6 验收

- 临时文件生成正常。
- M3U 格式检查正确。
- 只有完整通过的线路能够发布。
- UNKNOWN 不会进入订阅。
- 敏感凭证不会泄露。
- Manifest 与本轮运行绑定。
- Artifact 不能跨运行混用。
- 空结果不覆盖旧订阅。
- 全局错误不覆盖旧订阅。
- TEST 模式不修改正式订阅。
- publisher.py 不执行 Git push。
- publish Job 能够安全替换正式文件。
- Git 失败不会报告正式发布成功。
- 远端文件更新能够得到确认。

---

# 十、GitHub Actions 自动运行 M7

## 10.1 负责文件

唯一正式工作流：

    .github/workflows/main.yml

不得为相同业务建立第二套正式工作流。

## 10.2 唯一工作流职责

GitHub Actions 负责：

1. 准备标准 Ubuntu Runner。
2. 检查 Python 环境。
3. 检查 Docker 和 Docker Compose。
4. 安装 Python 依赖。
5. 检查 FFmpeg、FFprobe 和必要工具。
6. 构建网关和验证镜像。
7. 准备 Docker 网络。
8. 执行必要的安全测试。
9. 调用唯一业务入口 pipeline.py。
10. 生成和上传本轮 Artifact。
11. 根据发布条件执行独立 publish Job。
12. 输出运行结果。

不得在 YAML 中编写频道解析、线路筛选、去重、媒体验证或发布资格判断的重复业务逻辑。

## 10.3 运行环境准备

使用标准 GitHub-hosted Ubuntu Runner。

不把用户个人电脑作为自动运行服务器。

用户电脑不需要为了 GitHub Actions 定时任务持续开机。

每次运行都必须检查：

- Python。
- Docker Engine。
- Docker Compose。
- FFprobe。
- FFmpeg。
- nftables。
- setpriv。
- 项目依赖。
- 网关镜像构建条件。
- 验证镜像构建条件。
- Docker 网络创建条件。
- validator 防火墙加载条件。
- validator 非 root 运行条件。

不能假设 Runner 已经预装所有项目依赖。

## 10.4 触发事件

正式工作流只使用：

- workflow_dispatch
- schedule

不使用 pull_request 作为正式发布工作流触发事件。

手动运行默认 TEST。

定时运行固定采用 PRODUCTION。

定时表达式使用 UTC。

必须在文件注释中说明 UTC 时间与预期运行时间的换算关系。

## 10.5 两 Job 权限隔离

正式工作流必须采用两个 Job。

两个 Job 使用同一个 main.yml。

不得建立第二套正式工作流。

### pipeline Job

职责：

- 检出当前提交。
- 准备 Python 环境。
- 安装项目依赖。
- 检查 Docker 和 Docker Compose。
- 检查 FFprobe、FFmpeg 和必要工具。
- 构建网关和验证容器。
- 准备 Docker 网络。
- 加载 validator 容器网络防火墙。
- 检查 validator 权限降级状态。
- 执行必要的网络隔离安全测试。
- 启动唯一业务入口 pipeline.py。
- 完成五阶段业务流程。
- 生成本轮运行报告。
- 生成本轮 M3U 和 Manifest。
- 校验本轮产物。
- 上传本轮 Artifact。
- 输出运行状态和发布资格。

权限固定为：

    permissions:
      contents: read

pipeline Job 不得拥有 contents: write。

pipeline Job 不得直接推送正式订阅。

### publish Job

依赖：

    needs: pipeline

只有同时满足以下条件才允许执行：

- 当前模式为 PRODUCTION。
- pipeline Job 成功。
- pipeline 输出发布资格为 true。
- 当前运行 Artifact 存在。
- Artifact 校验通过。

权限固定为：

    permissions:
      contents: write

publish Job 只负责：

- 下载当前 workflow run 的 Artifact。
- 校验 Manifest。
- 校验运行标识。
- 校验 commit SHA。
- 校验文件摘要。
- 检查 M3U。
- 更新 output/iptv.m3u。
- 提交并推送正式订阅。

publish Job 不重新执行五阶段业务流程。

TEST 模式不得进入正式发布步骤。

### 权限边界

工作流默认权限必须保持最小化。

pipeline Job 只拥有读取权限。

只有满足发布条件的 publish Job 才拥有仓库写权限。

不得在整个 workflow 顶层无条件授予 contents: write。

不得让普通测试任务拥有正式仓库写权限。

## 10.6 Artifact 交接规则

pipeline Job 与 publish Job 之间使用 GitHub Actions Artifact 交接。

必须满足：

1. Artifact 由当前 pipeline Job 上传。
2. Artifact 名称包含当前 run_id。
3. Artifact 包含 M3U 和 Manifest。
4. Artifact 保留时间明确设置。
5. publish Job 只下载当前 workflow run 的 Artifact。
6. 不允许从其他运行批次下载旧产物。
7. 不允许使用固定旧文件代替本轮产物。
8. 下载后必须校验 Manifest。
9. 必须核对 run_id。
10. 必须核对 commit_sha。
11. 必须核对运行模式。
12. 必须核对发布资格。
13. 必须核对 M3U SHA-256。
14. 校验失败立即停止发布。

Artifact 过期、缺失或无法下载时，必须停止发布并保留旧订阅。

不得为了完成发布而跳过 Artifact 校验。

第三方 Artifact Actions 必须固定到完整提交 SHA。

## 10.7 运行模式

固定使用两种运行模式：

| 模式 | 触发方式 | 用途 | 正式订阅写入 |
|---|---|---|---|
| TEST | 手动运行 | 检查程序、测试流程、验证运行结果 | 禁止 |
| PRODUCTION | 定时运行 | 正式执行完整流程并发布合格订阅 | 满足全部条件后允许 |

固定规则：

1. 手动触发默认 TEST。
2. 定时任务采用 PRODUCTION。
3. 手动运行不得默认执行正式发布。
4. TEST 模式不得提交或推送正式订阅。
5. PRODUCTION 模式仍必须通过全部发布保护条件。
6. PRODUCTION 运行失败时保留上一份正式订阅。
7. 不得因为运行模式为 PRODUCTION 就跳过测试或安全检查。
8. TEST 和 PRODUCTION 使用相同五阶段业务流程。
9. TEST 的运行结果不能当作正式发布结果。

## 10.8 固定并发控制

PRODUCTION 并发组：

    iptv-production

TEST 并发组：

    iptv-test

两个运行模式必须使用不同并发组。

两个并发组均采用：

    queue: max
    cancel-in-progress: false

固定要求：

1. 同一时间，同一个并发组最多运行一个工作流。
2. 同一并发组的后续任务进入等待队列。
3. 不允许新任务取消正在运行的任务。
4. 不允许新任务替换同组已经排队的任务。
5. TEST 和 PRODUCTION 互不取消。
6. TEST 不得取消 PRODUCTION。
7. PRODUCTION 不得取消 TEST。
8. 两个组可以分别运行，不互相占用同一个并发锁。
9. 正式任务按平台实际队列顺序逐个处理。
10. TEST 任务按自己的队列顺序逐个处理。

GitHub Actions concurrency 的 queue: max 最多允许 100 个待执行任务。

队列达到平台上限时，新的任务可能无法进入队列。

不得假称无限排队。

队列顺序以任务实际进入等待队列的时间为准，不得宣称一定等同于定时触发时间或严格 FIFO 调度时间。

不得使用默认只保留一个 pending 的策略。

不得让 TEST 和 PRODUCTION 共用一个并发组。

不得设置 cancel-in-progress: true。

并发控制不能替代正式发布校验。

每次 PRODUCTION 发布仍必须核对当前 workflow run、Artifact、commit SHA、Manifest 和文件摘要。

## 10.9 第三方 Actions

第三方 GitHub Actions 必须固定到完整提交 SHA。

不得使用未经固定的浮动版本作为正式依赖。

必须尽量减少第三方 Actions 数量。

能使用 GitHub Actions 原生能力完成的工作，不额外引入没有必要的第三方 Action。

更新第三方 Action 时，必须核对其来源、版本和完整提交 SHA。

不得编造未经核对的 Action SHA。

## 10.10 深度验证启动顺序

pipeline Job 中的深度验证准备顺序：

1. 检查 Runner 环境。
2. 检查 Docker。
3. 检查 Compose。
4. 检查 nftables 和 setpriv。
5. 构建网关镜像。
6. 构建 FFmpeg 验证镜像。
7. 创建 validator_net 和 gateway_egress。
8. 启动媒体网关。
9. 检查网关健康状态。
10. 启动 validator 容器。
11. 加载 validator 内部 nftables 防火墙。
12. 检查 NET_ADMIN 已移除。
13. 检查非 root 运行状态。
14. 执行必要网络隔离测试。
15. 执行 DNS 和重定向测试。
16. 执行 HLS 子资源测试。
17. 确认关键安全关卡通过。
18. 开始深度验证。
19. 结束后停止容器并清理临时资源。

任何关键安全步骤失败，不得继续正式深度验证。

## 10.11 工作流执行顺序

### pipeline Job

1. 根据触发方式确定运行模式。
2. 检出当前提交。
3. 准备 Python 环境。
4. 安装项目依赖。
5. 检查 Docker 和 Docker Compose。
6. 检查 FFprobe、FFmpeg 及必要工具。
7. 构建媒体网关和验证容器。
8. 准备 Docker 网络。
9. 加载 validator 容器网络防火墙。
10. 检查 validator 容器降权状态。
11. 执行必要的网络隔离安全测试。
12. 启动 pipeline.py。
13. 执行五阶段业务流程。
14. 生成本轮运行报告。
15. 生成本轮 M3U 和 Manifest。
16. 校验本轮产物。
17. 上传本轮 Artifact。
18. 输出本轮运行状态和发布资格。

### publish Job

1. 等待 pipeline Job 成功。
2. 判断当前模式是否为 PRODUCTION。
3. 检查发布资格。
4. 下载当前 workflow run 的 Artifact。
5. 核对 Manifest。
6. 核对运行标识和 commit SHA。
7. 校验 M3U 文件摘要。
8. 校验 M3U 文件内容。
9. 检查发布资格和敏感信息。
10. 更新唯一正式订阅文件。
11. 检查 Git 变更范围。
12. 提交 output/iptv.m3u。
13. 推送到仓库。
14. 确认远端正式订阅文件更新。

main.yml 只负责编排和执行，不得复制 Python 业务模块的筛选、去重或验证逻辑。

publish Job 不得重新执行五阶段业务。

## 10.12 M7 验收

- 手动 TEST 运行正常。
- 定时 PRODUCTION 运行正常。
- pipeline Job 只有读取权限。
- publish Job 按条件获得写权限。
- Docker 镜像构建正常。
- 安全关卡正常执行。
- 失败任务不会提交正式文件。
- Artifact 只使用当前运行产物。
- Manifest 和 SHA-256 校验有效。
- 正式提交和推送正常。
- 远端订阅文件能够实际读取。
- 两个并发组互相隔离。
- 队列规则符合固定要求。
- 运行报告准确。

---

# 十一、统一数据结构与状态

## 11.1 候选记录

所有业务模块使用统一字段含义。

每条候选至少包含：

| 字段 | 必要性 | 含义 |
|---|---|---|
| channel_name | 必须 | 规范化频道名称 |
| url | 必须 | 直播地址 |
| headers | 可选 | 播放所需请求头 |
| source_id | 必须 | 来源标识 |
| group_title | 可选 | 频道分组 |
| tvg_id | 可选 | 频道 ID |
| tvg_logo | 可选 | 频道图标 |
| source_metadata | 可选 | 必要来源补充信息 |

具体程序可以使用字典或等效结构实现，但字段含义不得改变。

必要请求头必须在发现、整理、验证和发布环节之间正确传递。

如果请求头包含不能公开的凭证，必须在日志和公开输出中进行安全处理。

如果必要凭证无法安全传递给最终订阅使用者，该线路不得进入公开订阅。

不得把完整运行报告、检测历史和大量无关数据塞进候选记录。

## 11.2 统一检测结果

每个阶段必须返回明确的执行结果。

至少包含：

- 阶段名称。
- 阶段执行状态。
- 输入数量。
- 通过数量。
- 失败数量。
- 未确定数量。
- 输出数据。
- 必要错误信息。
- 本阶段是否完整执行。
- 是否存在影响后续流程的全局故障。

运行报告至少保留：

- 本轮运行标识。
- 运行模式。
- 代码提交 SHA。
- 各阶段完成情况。

错误信息不得包含密码、Token、Cookie、Authorization 或私密请求头。

每条线路的检测结果必须能够对应到该线路的候选记录。

不得只返回总数量而丢失单条线路的检测状态。

## 11.3 四种统一状态

| 状态 | 含义 | 后续处理 |
|---|---|---|
| PASS | 当前检查完整通过 | 可以进入下一项检查 |
| FAIL | 已确认不符合当前检查要求 | 淘汰该记录 |
| UNKNOWN | 检查未完成或无法确定 | 不得发布，可隔离其他记录继续 |
| NODE_ERROR | 检测环境或全局工具发生故障 | 阻止依赖该环境的后续检测和正式发布 |

状态必须区分适用范围：

- 来源级错误。
- 线路级错误。
- 阶段级错误。
- 运行级错误。

不能把单条线路失败当成全局故障。

不能把 FFmpeg 工具无法启动误判成所有线路失效。

不能把 UNKNOWN 当成 PASS。

## 11.4 FAIL 判定边界

只有取得足够证据，确认目标本身不符合当前检查要求时，才判定 FAIL。

可以判定 FAIL 的情况包括：

- URL 格式明确无效。
- 地址明确不符合 IPv4 准入规则。
- DNS 明确返回 NXDOMAIN。
- DNS 查询成功，但域名没有可用 IPv4 A 记录。
- DNS 结果明确包含不允许访问的目标地址。
- 目标明确返回不支持的资源或协议。
- 目标明确不存在。
- 明确拒绝响应能够证明当前资源不可用。
- 媒体内容明确不是有效媒体数据。
- 媒体流明确不满足既定检测条件。

不能仅因为一次网络超时就直接判定线路永久无效。

## 11.5 UNKNOWN 判定边界

以下情况通常应判定 UNKNOWN：

- 单条线路暂时超时，无法取得充分结论。
- 单条线路连接暂时失败，但无法确认目标永久失效。
- DNS 单次查询超时。
- DNS 临时 SERVFAIL 或其他暂时解析异常。
- 响应不完整。
- 证据不足。
- 检测达到单线路资源预算，但无法确认线路本身无效。
- 媒体读取没有完成规定的检测边界。
- HLS 出现无法安全处理或尚未支持的资源引用。

UNKNOWN 不得进入正式订阅。

## 11.6 NODE_ERROR 判定边界

以下情况属于检测环境或共享基础设施故障，应按影响范围判定 NODE_ERROR：

- FFprobe 或 FFmpeg 未安装、无法启动或工具本身崩溃。
- Docker daemon 不可用。
- Docker Compose 无法正常工作。
- nftables 无法加载规定的隔离规则。
- validator 容器无法完成降权启动。
- 网络安全模块发生异常，无法可靠执行安全检查。
- 媒体网关整体故障。
- Docker 网络隔离测试失败。
- 共享 DNS、网络或容器基础设施发生影响全局检测的故障。
- 测试环境本身无法提供可靠检测条件。
- 本轮关键阶段因系统故障无法完整执行。

不能把一个来源失败直接等同于全局 NODE_ERROR。

不能把 FFmpeg 程序本身无法正常启动误判为某条线路 FAIL。

如果共享工具、网络安全模块、Docker 环境或关键验证服务发生全局故障，必须根据影响范围判定 NODE_ERROR。

## 11.7 DNS 故障统一分类

| DNS 情况 | 状态 | 处理 |
|---|---|---|
| 明确 NXDOMAIN | FAIL | 当前域名不存在，淘汰候选 |
| 查询成功但没有 IPv4 A 记录 | FAIL | 不符合 IPv4 准入要求 |
| 查询成功且存在不允许的目标地址 | FAIL | 拒绝目标，不得尝试绕过 |
| 单次 DNS timeout | UNKNOWN | 有限重试，不能直接认定域名失效 |
| 临时 SERVFAIL 或解析异常 | UNKNOWN | 记录原因，按有限重试处理 |
| 共享 DNS 服务整体不可用 | NODE_ERROR | 停止依赖该 DNS 的检测并阻止发布 |
| 大量不同域名同时出现相同 DNS 故障 | 先检查共享环境 | 确认公共解析环境故障时判 NODE_ERROR |

不得把 DNS 临时故障批量记为线路 FAIL。

不得把明确 NXDOMAIN 无限重试。

不得在 DNS 解析异常时改用未经检查的备用地址。

## 11.8 阶段传递规则

第一阶段只交付原始候选和来源执行结果。

第二阶段只交付完成解析、规范化、安全准入和去重的候选。

第三阶段只交付通过快速连接检查的候选。

第四阶段只交付通过深度媒体验证的候选及其检测结果。

第五阶段只接受完整验证结果，并根据统一发布条件决定是否生成本轮发布产物。

任何阶段不得绕过下游检查，把未验证数据交给发布模块。

---

# 十二、测试施工计划

## 12.1 四层测试

测试固定分为四层。

**第一层：基础检查**

检查：

- Python 环境。
- 依赖安装。
- Docker 环境。
- Docker Compose。
- FFprobe 和 FFmpeg。
- nftables。
- setpriv。
- 配置文件格式。
- 必要目录和文件。
- Docker 镜像构建。
- 网关启动条件。
- 验证容器启动条件。
- validator 防火墙加载条件。
- validator 非 root 运行条件。
- GitHub Actions 工作流语法。

**第二层：模块测试**

至少测试：

- network_guard.py
- discovery.py
- normalize.py
- media_gateway.py
- validator.py
- publisher.py
- pipeline.py

每个模块只测试自己负责的功能。

不得在多个测试文件中重复维护互相矛盾的业务规则。

模块测试覆盖正常输入、异常输入、边界输入和失败处理。

**第三层：接口和流程联调**

必须验证：

- pipeline.py 能按固定顺序调度五个阶段。
- 上游数据能正确交给下游。
- 统一字段和状态能够正确传递。
- 快速筛选 PASS 才能进入深度验证。
- 深度验证 PASS 才能进入发布资格检查。
- publisher.py 不能绕过验证阶段。
- network_guard.py 没有循环依赖。
- FFmpeg 的媒体请求确实经过网关。
- publisher.py 不负责 Git push。
- main.yml 不包含重复业务筛选逻辑。
- TEST 模式不能触发正式订阅提交。
- PRODUCTION 模式必须经过全部发布保护。
- pipeline Job 没有仓库写权限。
- publish Job 只有满足条件时才执行。
- publish Job 只使用当前 workflow run 的 Artifact。
- Artifact Manifest 和 SHA-256 校验有效。
- publish Job 不重新运行五阶段业务。
- validator 容器启动时先加载 nftables。
- validator 防火墙加载失败时容器不能进入正常验证状态。
- FFmpeg/FFprobe 以非 root 用户运行。
- FFmpeg/FFprobe 进程不具备 NET_ADMIN。
- validator.py 调用 docker compose exec 时明确使用非 root 用户。
- TEST 与 PRODUCTION 使用不同并发组。
- TEST 不会取消正在运行的 PRODUCTION。

**第四层：回归测试**

涉及以下内容的修改，必须执行受影响范围的回归测试：

- 模块职责。
- 数据结构。
- 配置参数。
- URL 和 DNS 处理。
- Docker 网络。
- HLS 解析。
- 状态判断。
- 发布保护。
- GitHub Actions 权限。
- Artifact 格式。
- 并发规则。

## 12.2 网络地址和 DNS 安全测试

至少覆盖：

- 私网地址访问拦截。
- 回环地址访问拦截。
- 链路本地地址访问拦截。
- 特殊 IP 地址访问拦截。
- NXDOMAIN 判定测试。
- 无 IPv4 A 记录判定测试。
- DNS timeout 的 UNKNOWN 判定测试。
- DNS SERVFAIL 的 UNKNOWN 判定测试。
- 共享 DNS 故障的 NODE_ERROR 判定测试。
- DNS rebinding 测试。
- DNS 检查与实际连接绑定测试。
- DNS 变化后的目标重新检查。
- 重定向逐跳检查。
- IPv4 实际连接测试。
- IPv6 禁止回退测试。
- HTTPS Host 和 TLS SNI 保留测试。
- HTTPS 证书验证测试。

## 12.3 Docker 网络隔离测试

至少覆盖：

- FFmpeg 容器公网 IPv4 访问阻断。
- FFmpeg 容器公网 IPv6 访问阻断。
- FFmpeg 容器宿主机网关访问阻断。
- FFmpeg 容器网络绕行。
- FFmpeg 容器只能访问网关 8080。
- FFmpeg 容器非网关端口访问阻断。
- FFmpeg 容器其他容器访问阻断。
- 网关故障时禁止直连。
- nftables 规则缺失时禁止启动。
- nftables 规则加载失败时禁止启动。
- NET_ADMIN 能力移除。
- 非 root 用户运行。
- 宿主机路由绕行。
- 其他容器访问路径。
- IPv6 绕行。
- DNS 绕行。

不能只检查 compose.yaml 中是否写了 internal: true。

必须验证真实容器网络行为。

## 12.4 网关和任务映射测试

至少覆盖：

- 任意目标注入。
- 非法资源 ID。
- 跨任务访问。
- 过期映射访问。
- 任务结束后的映射失效。
- 映射数量上限。
- 映射有效期。
- 必要请求头隔离。
- 请求头大小上限。
- 重定向目标安全。
- 网关开放代理风险。
- 网关异常时拒绝代理。
- 资源授权标识不进入普通日志。

## 12.5 HLS 安全测试

至少覆盖：

- HLS 子播放列表请求。
- HLS 媒体分片请求。
- HLS 密钥 URI 请求。
- HLS URI 属性处理。
- HLS 相对 URI 处理。
- HLS 嵌套播放列表处理。
- HLS 字节范围请求。
- HLS 查询参数保留。
- HLS 必要请求头传递。
- HLS 总资源预算。
- HLS 最大资源数量。
- HLS 最大嵌套深度。
- HLS 最大请求次数。
- HLS 未支持语法拒绝。
- HLS 子资源不会回退外部直连。

## 12.6 媒体协议范围测试

至少覆盖：

- HTTP 媒体资源。
- HTTPS 媒体资源。
- HTTP/HTTPS HLS。
- MPEG-TS 资源。
- MP4 资源。
- RTSP 拒绝。
- RTP/UDP 拒绝。
- RTMP 拒绝。
- 未知协议拒绝。
- 不支持协议不能绕过网关。

## 12.7 凭证和日志测试

至少覆盖：

- 私密请求头泄漏。
- Token 和 Cookie 泄漏。
- 公开订阅敏感信息检查。
- Actions 日志敏感信息检查。
- 网关资源授权标识日志泄漏。

## 12.8 异常测试

至少覆盖：

1. 单个来源失败。
2. 所有来源失败。
3. 来源格式错误。
4. 空候选结果。
5. 重复记录。
6. 同频道不同 URL。
7. 同 URL 不同频道。
8. 请求头不同的记录。
9. IPv6-only 地址。
10. 私有地址。
11. DNS 解析异常。
12. DNS 解析结果变化。
13. 重定向到危险地址。
14. HLS 子资源访问异常。
15. HLS 不支持的形式。
16. 单线路连接超时。
17. FFprobe 失败。
18. FFmpeg 失败。
19. FFmpeg 工具环境故障。
20. Docker 无法启动。
21. Docker 隔离失效。
22. FFmpeg 尝试直接联网。
23. UNKNOWN 不得发布。
24. NODE_ERROR 阻止发布。
25. 空结果不覆盖旧订阅。
26. 临时文件校验失败。
27. 敏感凭证泄露检查。
28. Git 推送失败。
29. TEST 不得修改正式文件。
30. Artifact 缺失。
31. Manifest 不匹配。
32. Artifact 摘要错误。
33. 旧 Artifact 不得代替当前产物。
34. pipeline Job 失败时 publish Job 不得执行。
35. nftables 加载失败时 FFmpeg 不得继续运行。
36. 网关故障时 FFmpeg 不得直接联网。

## 12.9 测试证据

每项关键功能必须记录：

- 测试对象。
- 测试环境。
- 测试方法。
- 实际结果。
- 通过或失败。
- 未解决问题。

必须区分：

- 配置检查。
- 模拟测试。
- 单元测试。
- 真实容器网络测试。
- GitHub Actions 实际运行测试。

文档中写了功能，不等于程序已经实现。

程序已经实现，不等于测试已经通过。

模拟测试通过，不等于真实网络隔离测试通过。

## 12.10 测试完成标准

一项功能只有同时满足以下条件，才能标记完成：

1. 对应程序代码已经存在。
2. 模块职责符合 CORE_FLOW。
3. 接口符合统一数据规范。
4. 对应测试已经编写。
5. 对应测试已经实际运行。
6. 测试结果有记录。
7. 必要安全测试已经通过。
8. 不存在绕过流程的备用路径。
9. 不与其他文档和模块冲突。
10. 对应功能在实际运行环境中符合预期。

---

# 十三、异常处理与发布保护

## 13.1 来源和线路隔离

单来源失败：

- 记录来源错误。
- 有限重试。
- 继续处理其他来源。

单线路失败：

- 记录线路失败。
- 隔离该线路。
- 继续处理其他线路。

单线路 UNKNOWN：

- 记录不确定原因。
- 不进入正式订阅。
- 不影响其他线路继续检测。

不能让一个普通来源或线路错误中断整个任务。

## 13.2 全局环境故障

以下情况属于 NODE_ERROR：

- Python 关键依赖无法使用。
- Docker 无法正常运行。
- Docker Compose 无法正常运行。
- FFprobe 或 FFmpeg 工具无法启动。
- nftables 无法加载规定规则。
- validator 无法完成权限降级。
- 媒体网关整体不可用。
- network_guard.py 无法可靠执行安全检查。
- 隔离网络安全测试失败。
- 共享 DNS 或网络基础设施发生影响全局检测的故障。

出现 NODE_ERROR，必须阻止依赖该环境的后续检测和正式发布。

不得把全局环境故障伪装成大量线路 FAIL。

## 13.3 DNS 故障处理

严格按照第十一章的 DNS 状态分类处理。

- 明确 NXDOMAIN：FAIL。
- 查询成功但无 IPv4 A 记录：FAIL。
- 单次 timeout：UNKNOWN。
- 临时 SERVFAIL：UNKNOWN。
- 共享 DNS 服务整体不可用：NODE_ERROR。

不得把临时 DNS 故障批量记为线路永久失效。

## 13.4 旧订阅保护

以下情况必须保留上一份正式订阅：

- 所有来源失败。
- 本轮没有有效候选。
- 本轮没有合格线路。
- 全局环境故障。
- Docker 网络安全测试失败。
- nftables 端口限制测试失败。
- validator 权限降级失败。
- 媒体网关不可用。
- HLS 受控访问关键功能未通过测试。
- 本轮关键检测未可靠完成。
- 临时 M3U 校验失败。
- 敏感信息检查失败。
- Artifact 缺失或校验失败。
- Manifest 不匹配。
- 正式文件替换失败。
- Git 提交或推送失败。

不得通过旧线路补数。

不得把未验证线路重新混入正式订阅。

## 13.5 正式发布保护

正式发布必须同时通过：

- pipeline Job 成功。
- 当前运行模式为 PRODUCTION。
- 本轮发布资格为 true。
- 当前运行 Artifact 存在。
- workflow_run_id 匹配。
- commit_sha 匹配。
- Manifest 校验通过。
- M3U SHA-256 校验通过。
- M3U 内容检查通过。
- 敏感凭证检查通过。
- 正式替换和 Git 推送成功。

任何必要条件不满足，均停止发布。

---

# 十四、运行报告

每轮运行通过 GitHub Actions Summary 输出简明报告。

至少记录：

- 运行模式。
- workflow_run_id。
- commit SHA。
- 开始和结束时间。
- Runner 环境。
- Python 环境。
- Docker 和 Compose 检查结果。
- nftables 防火墙检查结果。
- validator 降权检查结果。
- 网络隔离测试结果。
- 来源总数。
- 来源成功数。
- 来源失败数。
- 原始采集数量。
- 规范化后数量。
- IPv4 准入数量。
- 快速筛选通过数量。
- FFprobe 通过数量。
- FFmpeg 深度验证通过数量。
- FAIL 数量。
- UNKNOWN 数量。
- NODE_ERROR 情况。
- 最终发布候选数量。
- 各阶段执行状态。
- 主要失败原因。
- Artifact 是否生成。
- Artifact 校验结果。
- Manifest 校验结果。
- 正式订阅是否更新。
- Git 推送是否成功。
- 远端文件是否确认更新。

不得在日志和运行报告中打印：

- Token。
- 密码。
- Cookie。
- Authorization。
- 私密请求头。
- 其他敏感凭证。
- 网关任务授权标识。

报告必须以本轮实际运行结果为准。

不得引用未执行的检测结果。

不建立不必要的数据库。

如果需要保存本轮结构化 JSON 报告，必须保持轻量，不引入复杂线路历史关系。

---

# 十五、里程碑与施工顺序

施工顺序固定如下：

| 里程碑 | 施工内容 | 完成条件 |
|---|---|---|
| M0 | Docker 双网络、nftables、权限降级和安全隔离可行性验证 | 固定架构和关键绕行测试通过 |
| M1 | 基础工程、统一配置、统一数据结构和唯一入口 | pipeline 能按固定顺序组织业务流程 |
| M2 | 广泛发现 | 支持来源能够获取原始数据，单来源失败隔离 |
| M3 | 数据整理 | 解析、规范化、组合去重和 IPv4 准入正确 |
| M4 | 快速筛选 | 基础连接和实际 IPv4 检查有效 |
| M5 | 深度验证 | 网关、FFprobe、FFmpeg、HLS 和隔离安全测试通过 |
| M6 | 安全发布 | 临时产物、Manifest、资格检查和发布保护有效 |
| M7 | GitHub Actions 自动运行 | 双 Job、Artifact、权限、并发和正式发布流程正常 |

M0 是前置工程准备，不属于五个业务阶段。

M1 是基础工程施工，不属于五个业务阶段。

M2—M6 按照五阶段业务流程顺序实施。

M7 负责将统一业务流程交给 GitHub Actions 自动运行。

## 15.1 里程碑完成规则

每个里程碑必须：

1. 完成规定施工任务。
2. 执行对应测试。
3. 检查上游和下游接口。
4. 检查模块职责和依赖方向。
5. 检查与 CORE_FLOW 的一致性。
6. 记录测试证据。
7. 明确剩余问题。
8. 确认没有绕过安全要求。

没有实际证据，不得标记完成。

## 15.2 施工阻断规则

- M0 未通过，不进入正式深度验证施工。
- M1 未通过，不开始正式业务流程联调。
- 任一业务阶段必要接口未通过，不得把未验证数据交给后续阶段。
- M5 安全关卡未通过，不得进入依赖该能力的正式发布。
- M6 发布保护未通过，不得开放正式 Git 写入。
- M7 权限和 Artifact 交接未通过，不得开放自动正式发布。

## 15.3 不允许跳过里程碑验收

不得因为某个模块已经写出代码就直接进入下一阶段。

不得把模拟结果当作 Runner 实测结果。

不得把工作区文件替换成功当作远端发布成功。

不得把某个单项测试通过扩大解释为整个系统已经完成。

---

# 十六、施工纪律与变更管理

## 16.1 每次施工前

每次修改文档、代码、配置或工作流前，必须先核对：

1. 当前仓库最新版本的 CORE_FLOW.md。
2. 当前仓库最新版本的 MASTER_PLAN.md。
3. 当前仓库最新版本的 README.md。
4. 仓库真实目录和文件结构。
5. 本次目标文件的完整现有内容。
6. 上下游模块接口和调用关系。
7. 当前里程碑及其验收状态。
8. 当前已经确定的实施细则。
9. 当前尚未解决的问题。
10. 受影响的测试、工作流和安全配置。

必须记录本次施工所依据的相关文件版本和 Git Commit SHA。

不得使用旧版本文件、过期代码片段或不完整聊天记录代替仓库当前版本。

不得只看目标文件而忽略调用它的模块。

不得在没有读取完整目标文件的情况下直接重写或替换。

## 16.2 修改前说明

每次修改必须先明确：

- 发现的问题。
- 问题所在文件。
- 问题原因及依据。
- 修改目标。
- 本次已经确定的具体要求。
- 必须保留的原有有效内容。
- 涉及文件。
- 上游影响。
- 下游影响。
- 数据接口是否变化。
- 模块职责是否变化。
- 安全边界是否变化。
- 需要同步的其他文档。
- 测试范围。
- 验收标准。

没有明确施工目标，不开始随意修改。

如果发现 CORE_FLOW.md 本身存在问题，必须先按照统一变更流程修订 CORE_FLOW.md，再同步其他文件。

不得通过修改 MASTER_PLAN.md 或 README.md 绕过 CORE_FLOW.md 的规定。

## 16.3 修改后的多轮检查

每次修改完成后，必须进行多轮复核。

**第一轮：原文件内容完整性检查**

- 是否保留原文件中仍然有效的章节。
- 是否保留已经确定的具体实施细则。
- 是否遗漏本次要求。
- 是否为了缩短文件而删减有效内容。
- 是否改变原有章节结构和必要说明。
- 是否存在不必要的重复内容。

**第二轮：流程检查**

- 是否符合 CORE_FLOW。
- 是否仍然只有五个业务阶段。
- 是否改变唯一业务入口。
- 是否改变唯一正式工作流。
- 是否改变正式发布路径。
- 是否把前置工程准备误写为业务阶段。
- 是否把测试、安全和变更控制误写为新的业务阶段。

**第三轮：职责和依赖检查**

- 是否破坏模块唯一职责。
- 是否新增重复功能。
- 是否产生循环依赖。
- 是否产生模块之间的反向调用。
- 是否让业务逻辑进入 YAML 或 Dockerfile。
- 是否产生重复配置、重复数据存储或重复入口。

**第四轮：数据和状态检查**

- 是否改变统一数据字段含义。
- 是否产生重复配置。
- 是否影响 PASS、FAIL、UNKNOWN、NODE_ERROR。
- 是否破坏上游和下游数据传递。
- 是否遗漏已经确定的 DNS 分类和错误处理规则。

**第五轮：安全检查**

- 是否影响 IPv4 准入。
- 是否影响 DNS 检查和实际连接绑定。
- 是否影响重定向逐跳检查。
- 是否影响 Docker 双网络隔离。
- 是否影响 nftables。
- 是否影响权限降级。
- 是否影响 HLS 子资源安全。
- 是否影响网关任务映射。
- 是否出现安全要求被弱化或绕过的情况。

**第六轮：发布检查**

- 是否影响 publisher.py 职责。
- 是否影响 Manifest。
- 是否影响 Artifact。
- 是否影响 pipeline Job 权限。
- 是否影响 publish Job 权限。
- 是否影响正式订阅保护。
- 是否影响 TEST 和 PRODUCTION 隔离。
- 是否影响并发队列规则。
- 是否可能让旧运行产物覆盖新运行产物。

**第七轮：跨文件一致性检查**

- 是否与最新 CORE_FLOW.md 一致。
- 是否与 README.md 的项目说明一致。
- 是否与相关代码和配置文件的实际职责一致。
- 三份文档的五阶段名称、顺序和职责是否一致。
- 模块名称、唯一职责和调用方向是否一致。
- Docker 网络、地址、端口和安全规则是否一致。
- 媒体协议支持范围是否一致。
- 参数、状态、发布资格和验收标准是否一致。
- 是否遗漏已经确定但尚未落实到相关文件的实施细则。

**第八轮：测试和交付检查**

- 是否需要更新测试。
- 是否需要执行回归测试。
- 哪些检查已经实际执行。
- 哪些测试尚未执行。
- 是否存在未经验证的完成声明。
- 是否存在尚未解决的问题。
- 最终交付内容是否与最后一次复核的版本完全一致。

发现问题必须先修正，再重新执行受影响的检查。

如果修正导致其他文件、模块、接口或测试受到影响，必须扩大复核范围。

不得把尚未解决的问题留到文件交付以后再处理。

只有完成适用的检查，才能交付修改结果。

## 16.4 文件新增、删除和重命名

新增文件前，必须说明：

- 新增原因。
- 唯一职责。
- 调用者。
- 依赖项。
- 是否与现有功能重复。
- 是否符合总流程。
- 是否需要同步其他文档和测试。

删除或重命名文件前，必须检查：

- 所有调用。
- 配置引用。
- 工作流引用。
- 测试引用。
- 文档引用。
- Docker 构建上下文。
- 上下游接口。

不得为了整理目录而破坏现有功能。

不得保留没有用途的旧入口或重复模块。

不得擅自删除仍然承担已确定职责的文件。

## 16.5 防止无休止诊断

发现问题后按固定顺序处理：

1. 定位问题。
2. 确认原因。
3. 确认影响范围。
4. 对照 CORE_FLOW 确认正确实施方式。
5. 制定修复方案。
6. 执行修改。
7. 执行能够实际执行的测试。
8. 多轮复核。
9. 更新进度。
10. 记录仍未解决的问题。

每轮只处理一个最高优先级目标。

每批施工必须有明确结束条件。

不得不断扩大检查范围，产生没有结论的反复诊断。

发现的问题必须记录并落实修复，不得在后续施工中遗忘。

## 16.6 代码交付纪律

今后所有代码、配置和工作流文件都必须遵循：

1. 先核对最新 CORE_FLOW。
2. 再核对最新 MASTER_PLAN。
3. 检查目标文件完整内容。
4. 检查上下游模块。
5. 确定唯一职责和接口。
6. 保留已经确定且仍然有效的实施细则。
7. 编写完整文件。
8. 检查是否重复实现。
9. 检查是否产生循环依赖。
10. 检查统一配置和状态规则。
11. 检查网络安全和发布边界。
12. 执行能够实际执行的测试。
13. 根据测试结果修正问题。
14. 多轮复核。
15. 确认没有文档冲突和实施细则遗漏后再交付。

不能写完代码就直接发给用户。

不能把没有运行过的代码说成已经测试通过。

不能把静态检查说成完整功能验收。

不能为了让代码看起来完整而增加未经确定的架构。

设计确定不等于代码完成。

代码存在不等于测试通过。

测试通过也不等于未经测试的安全能力已经验收。

## 16.7 施工交付规则

每次向用户交付文件或代码时：

- 一次只交付一个明确文件或任务。
- 提供完整、可直接替换的文件内容，不要求用户自行拼接零散片段。
- 明确 Git Commit 提交说明。
- 说明需要上传或替换的准确路径。
- 明确哪些测试已经实际执行。
- 明确哪些测试尚未执行。
- 明确哪些项目仍然待验收。
- 不宣称未经验证的功能已经完成。
- 不在交付后再把本应事先发现的问题留给用户排查。

交付前必须确认：

1. 本次提出的修改要求已经全部落实。
2. 已经确定的实施细则没有遗漏。
3. 文件内部没有明显矛盾。
4. 与 CORE_FLOW.md 没有流程、职责和技术规范冲突。
5. 与 README.md 及其他相关文件没有冲突。
6. 原文件中仍然有效的内容没有被无故删减。
7. 最终交付内容与最后一次复核的版本完全一致。

未达到以上条件，不得声称文件已经确认无误。

用户上传后，再核对仓库实际版本、Git Commit SHA 和提交结果。

# 十七、最终完成标准

V3 只有同时满足以下条件，才能认定整体完成。

## 17.1 工程结构

- [ ] 唯一入口为 pipeline.py。
- [ ] 唯一正式工作流为 main.yml。
- [ ] 统一配置为 settings.py。
- [ ] 统一安全策略为 network_guard.py。
- [ ] 五阶段职责明确。
- [ ] 没有循环依赖。
- [ ] Docker 网关和验证容器职责明确。
- [ ] 不存在重复业务入口。
- [ ] 不存在重复正式订阅。
- [ ] 不存在不必要的重复数据存储。

## 17.2 业务流程

- [ ] 多来源发现正常。
- [ ] 数据整理和组合去重正确。
- [ ] IPv4 准入正确。
- [ ] 快速筛选有效。
- [ ] FFprobe 探测有效。
- [ ] FFmpeg 实际读取和解码有效。
- [ ] 只有完整通过的线路能够发布。
- [ ] UNKNOWN 不进入正式订阅。
- [ ] 不使用旧线路补数。

## 17.3 网络安全

- [ ] validator 只连接 validator_net。
- [ ] media-gateway 同时连接两个指定网络。
- [ ] validator_net internal 隔离有效。
- [ ] nftables 端口级限制有效。
- [ ] NET_ADMIN 在启动后移除。
- [ ] FFmpeg/FFprobe 使用非 root 用户。
- [ ] FFmpeg 不能直接访问公网。
- [ ] FFmpeg 只能访问媒体网关 TCP 8080。
- [ ] 网关不能成为任意 IP 转发器。
- [ ] DNS 检查和实际连接 IP 一致。
- [ ] 重定向逐跳检查有效。
- [ ] HLS 子资源受到安全约束。
- [ ] IPv4 限制贯穿实际媒体请求。
- [ ] 网络绕行测试通过。
- [ ] 未支持协议不能绕过网关。

## 17.4 发布与自动运行

- [ ] publisher.py 只生成本轮临时发布产物。
- [ ] pipeline Job 只有读取权限。
- [ ] publish Job 按条件获得写权限。
- [ ] Artifact 只使用当前运行产物。
- [ ] Manifest 校验有效。
- [ ] SHA-256 校验有效。
- [ ] UNKNOWN 不会发布。
- [ ] NODE_ERROR 阻止正式发布。
- [ ] 空结果不覆盖旧订阅。
- [ ] 敏感信息不泄露。
- [ ] TEST 和 PRODUCTION 权限隔离。
- [ ] 两种模式使用独立并发组。
- [ ] 两个并发组采用固定排队策略。
- [ ] Git 提交和推送正常。
- [ ] 远端订阅文件能够实际读取。
- [ ] 运行报告准确。
- [ ] 四层测试完成。
- [ ] 必要安全测试全部通过。

以上项目必须有实际测试证据。

没有证据的项目保持待验收状态。

---

# 十八、长期施工总原则

1. CORE_FLOW.md 是唯一总流程依据和最高技术施工规范。
2. MASTER_PLAN.md 只负责施工计划、任务拆解和验收。
3. README.md 只负责项目介绍、使用说明和真实状态。
4. 不得增加第二套业务流程。
5. 不得增加第二个业务入口。
6. 不得增加第二个正式工作流。
7. 不得绕过网络安全关卡。
8. 不得让 FFmpeg 直接联网。
9. 不得让 HLS 子资源绕过媒体网关。
10. 不得让媒体网关成为开放公网代理。
11. 不得让不同验证任务互相访问资源。
12. 不得让不支持的协议绕过网关。
13. 不得把计划中的功能写成已经实现。
14. 不得把模拟测试冒充实际安全验收。
15. 不得把工作区文件更新冒充远端正式发布。
16. 不得让旧 Artifact 代替本轮发布产物。
17. 不得让 TEST 模式执行正式提交。
18. 不得在全局环境故障时继续正式发布。
19. 不得把未验证线路混入正式订阅。
20. 不得为了线路数量降低质量标准。
21. 不得用复杂评分和历史数据库增加维护负担。
22. 不得在不同文档中定义互相冲突的参数和状态。
23. 不得因为某个实现复杂就擅自取消已经确定的安全要求。
24. 不得为了让文件变短而删掉已经确定的实施规则。
25. 每个里程碑必须有实际测试证据。
26. 每次代码修改必须检查上下游影响。
27. 每次交付前必须对照 CORE_FLOW 多轮复核。
28. 没有实际运行证据，不得宣称测试通过。
29. 发现冲突必须先修正文档和接口，再继续施工。
30. 所有实现、修改、测试、维护和发布都必须遵循 CORE_FLOW.md。

施工总原则：

先完成前置工程和安全隔离可行性验证，再建立统一基础工程；按照固定五阶段顺序逐步实施；每个阶段先完成代码，再执行对应测试和验收；通过必要安全关卡后，才允许进入下一步；最终只有本轮完整通过检测的线路，才能通过当前运行的 Artifact 和独立 publish Job 更新唯一正式订阅。

CORE_FLOW.md 决定系统怎么工作。

MASTER_PLAN.md 决定按照什么顺序施工、每一步如何验收。

README.md 负责说明项目是什么、如何使用以及当前真实状态。

三份文件必须始终保持一致。
