China-IPTV-Auto-v3

自动发现、筛选和验证 IPv4 IPTV 直播源，生成 M3U 订阅。

正式订阅

文件路径：

"output/iptv.m3u"

订阅地址：

https://raw.githubusercontent.com/womomo8/China-IPTV-Auto-v3/main/output/iptv.m3u

首次成功生成并发布文件后，订阅地址才可使用。

运行方式

项目目标支持：

- 每天北京时间 06:00 自动更新。
- 手动正式运行。
- 手动测试运行，测试运行不覆盖正式订阅。

具体运行状态以 GitHub Actions 实际结果为准。

验证方式

项目采用安全入口获取媒体、宿主机校验媒体资料、一次性无网络验证容器执行媒体检测的方式。

订阅只收录本轮实际通过项目验证条件的线路。

检测通过不代表所有地区、运营商和设备都能保证播放。

项目文档

- "CORE_FLOW.md"：总流程、架构和安全规则。
- "MASTER_PLAN.md"：施工顺序、接口和验收标准。
- "PROGRESS.md"：实际进度、测试证据和待办事项。

文档中的目标不代表程序已经完成。项目是否可用，以真实代码、测试证据和 GitHub Actions 发布结果为准。
