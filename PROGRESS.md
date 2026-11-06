
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
