China-IPTV-Auto V3

自动发现、筛选和验证 IPv4 IPTV 直播源，持续生成符合检测标准的 IPTV 订阅。

本项目以线路质量为第一目标，不追求线路数量。收集 1000 条，最终只有 20 条通过检测，就只发布这 20 条；不使用未经验证的线路凑数。

«项目状态说明： 本仓库目前以 V3 设计规范和施工计划为依据逐步建设。文档描述的是目标架构，不代表所有程序已经实现，也不代表 Docker 网络隔离、媒体网关或线路检测已经通过实际测试。具体完成情况以代码、测试记录和 GitHub Actions 运行结果为准。»

---

一、项目目标与检测边界

系统计划通过 GitHub Actions 云端运行，从多个来源发现 IPTV 直播地址，经过数据整理、快速筛选、深度媒体验证和安全发布，生成一份持续更新的 IPTV 订阅。

必须区分以下检测能力：

1. 地址符合 IPv4 准入要求。
2. DNS 解析存在符合要求的 IPv4 目标。
3. 实际网络连接确实使用 IPv4。
4. FFprobe 能够正确探测媒体流。
5. FFmpeg 能够通过受控访问通道读取或解码媒体流。
6. 线路在本轮规定的检测条件下通过验证。
7. 用户实际使用环境能够正常播放。

以上检查具有不同含义，不能相互替代。

本项目当前以 GitHub Runner 所在网络环境的检测结果作为本轮检测依据。

云端检测通过，仅表示线路在本轮 Runner 所处网络环境和规定检测条件下通过，不能保证其他地区、其他运营商或用户家庭网络一定能够正常播放。

本项目不把云端检测结果宣传为国内所有网络环境的播放保证。

---

二、统一业务流程

V3 固定采用五个业务阶段：

GitHub Actions
       |
       v
  pipeline.py
       |
       v
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
       |
       v
生成本轮临时发布产物
       |
       v
pipeline Job 校验并上传 Artifact
       |
       v
publish Job 核验当前运行的 Artifact
       |
       v
更新唯一正式订阅
       |
       v
output/iptv.m3u

各阶段职责：

1. 广泛发现： 从配置的公开来源获取原始直播数据。
2. 数据整理： 解析播放列表、规范化记录、组合去重并执行 IPv4 准入。
3. 快速筛选： 通过基础连接检查淘汰明显无效的线路。
4. 深度验证： 通过受控媒体网关调用 FFprobe 和 FFmpeg 检查媒体流。
5. 安全发布： 检查发布资格，生成并校验临时 M3U，再通过独立 publish Job 更新正式订阅。

Docker 网络隔离的可行性验证属于正式业务流程开始前的工程准备，不属于第六个业务阶段。

必须先通过安全隔离测试，才能开展正式深度验证。

详细流程、模块职责、接口和验收标准以 "CORE_FLOW.md" 为准。

---

三、技术架构

3.1 运行环境

目标运行环境：

- GitHub-hosted 标准 Ubuntu Runner。
- GitHub Actions 自动调度。
- Docker Engine 和 Docker Compose。
- 独立 FFmpeg 验证容器。
- 独立媒体网关容器。

系统不依赖用户自己的电脑持续开机。

3.2 媒体访问安全架构

目标结构：

GitHub Actions
       |
       v
  pipeline.py
       |
       v
  validator.py
       |
       v
 Docker Compose
       |
       +----------------------+
       |                      |
       v                      v
FFmpeg 验证容器             媒体网关
       |                      |
       |                      v
       |                network_guard.py
       |                      |
       +----受控请求----------+
                              |
                              v
                         外部媒体源

核心要求：

- FFmpeg 验证容器不能直接访问公网。
- FFmpeg 只能通过媒体网关访问外部媒体资源。
- 媒体网关必须执行统一网络安全检查。
- DNS 检查结果必须与实际连接目标绑定。
- 每次重定向都必须重新检查。
- HLS 主播放列表及受支持的子资源请求必须经过网关。
- 不支持或无法安全处理的媒体请求必须拒绝，不能绕过网关直接访问。

重要：

Docker "internal: true" 是网络隔离的基础，不是隔离成功的证明。

必须通过 GitHub Actions 实际安全测试，确认 IPv4、IPv6 和其他网络绕行方式均受到限制。

未通过安全关卡，不得让 FFmpeg 直接联网作为替代方案。

---

四、主要文件结构

以下是 V3 的目标目录结构，不代表所有文件已经创建：

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

以上为目标结构，实际文件增删必须遵循 "CORE_FLOW.md" 和变更控制规则。

文件职责

文件| 唯一职责
main.yml| GitHub Actions 调度、运行环境准备、权限控制、Artifact 交接和正式 Git 提交
pipeline.py| 唯一业务入口，按顺序调度五个阶段
settings.py| 统一管理运行参数和资源限制
sources.txt| 人工维护公开来源配置
discovery.py| 获取来源原始内容
normalize.py| 数据解析、规范化、组合去重和 IPv4 准入
network_guard.py| 统一网络安全策略和受控外部访问
media_gateway.py| 受控代理媒体请求并处理支持的 HLS 子资源
validator.py| 快速筛选、FFprobe 和隔离容器中的 FFmpeg 验证
publisher.py| 发布资格检查、临时 M3U 生成、校验和本轮发布产物准备
Dockerfile.gateway| 构建媒体网关镜像
Dockerfile.validator| 构建 FFmpeg 验证镜像
compose.yaml| 定义容器服务和网络隔离关系
requirements.txt| Python 项目依赖
tests/| 模块、接口、流程和安全测试
output/iptv.m3u| 唯一正式订阅文件

注意：

- 不设置第二个业务入口。
- 不设置第二套正式发布程序。
- 不建立不必要的数据库和复杂线路历史关系。
- "publisher.py" 不直接提交或更新正式订阅。
- 正式订阅由 GitHub Actions 的 publish Job 更新。

---

五、统一状态规则

系统统一使用四种状态：

状态| 含义| 处理方式
PASS| 当前检查完整通过| 可以进入下一项检查
FAIL| 已确认不符合当前要求| 淘汰该记录
UNKNOWN| 检查未完成或无法确定| 不得发布
NODE_ERROR| 检测环境或全局工具故障| 阻止依赖该环境的后续检测和正式发布

单个来源失败或单条线路失败，不应轻易导致整个任务中断。

检测工具无法启动，不能误判为所有线路失效；检测未完成，也不能当作通过。

---

六、自动运行与发布

计划使用 GitHub Actions 执行统一业务流程。

运行规则：

- 手动运行默认采用 TEST 模式。
- 定时任务采用 PRODUCTION 模式。
- 两种模式共用同一套业务流程。
- TEST 模式不得修改正式订阅。
- 只有正式发布任务才开放必要的仓库写入权限。
- 正式任务必须避免并发覆盖。
- Git 提交或推送失败，不得报告正式发布成功。

正式发布采用两个 Job：

pipeline Job

1. 执行五阶段业务流程。
2. 生成本轮临时发布产物。
3. 校验发布产物和 Manifest。
4. 上传当前运行的 Artifact。

publish Job

1. 核验当前运行对应的 Artifact。
2. 检查发布条件。
3. 更新唯一正式订阅。
4. 执行 Git 提交和推送。
5. 确认正式发布结果。

出现空结果、全局环境故障、关键安全测试失败或临时文件校验失败时，必须保留上一份正式订阅。

---

七、正式订阅

唯一正式订阅文件：

output/iptv.m3u

预期订阅地址：

https://raw.githubusercontent.com/womomo8/China-IPTV-Auto-v3/main/output/iptv.m3u

该地址只有在首次正式发布成功、远端文件实际生成后才可使用。在此之前不能保证订阅可用。

---

八、项目文档

三份文档分工固定：

- CORE_FLOW.md： 唯一总流程依据和最高技术施工规范。日常确认流程、模块职责、安全边界和技术规则，优先看这份。
- MASTER_PLAN.md： 根据总流程拆解施工任务、开发顺序、测试方法和验收标准。实际施工、检查进度时看这份。
- README.md： 项目简介、技术架构、能力边界和基本使用说明。了解项目整体情况时看这份。

三份文档必须保持一致。

出现冲突时，以 "CORE_FLOW.md" 为最高依据，先修正文档和接口，再继续施工。

---

九、项目建设原则

1. 质量优先，不以线路数量为目标。
2. 只发布通过全部必要检查的线路。
3. 不用未经验证的线路凑数。
4. 如实说明云端检测结果的适用范围，不将其视为所有用户网络的播放保证。
5. 不建设不必要的复杂评分、数据库和历史关系系统。
6. 保持一个业务入口、一套配置、一条业务流程和一个正式订阅。
7. 不允许 FFmpeg 绕过媒体网关直接联网。
8. 不允许关键安全测试失败后继续正式深度验证。
9. 单个来源或线路失败应尽量隔离处理。
10. 全局环境故障时保护上一份正式订阅。
11. 未经实际测试和验收，不宣称功能已经完成。

最终原则：

先验证工程和网络安全方案，再按照固定五阶段逐步建设。每个里程碑都必须有实际测试证据；只有必要检查全部通过，才允许正式发布。
