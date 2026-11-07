China-IPTV-Auto-v3

自动发现、筛选和验证 IPv4 IPTV 直播源，生成 M3U 订阅。

订阅

正式文件："output/iptv.m3u"

订阅地址：

https://raw.githubusercontent.com/womomo8/China-IPTV-Auto-v3/main/output/iptv.m3u

首次成功生成并发布文件后，订阅地址才可正常使用。

运行方式

计划支持：

- 每天北京时间 06:00 自动更新。
- 手动正式运行。
- 手动测试运行（不覆盖正式订阅）。

具体可用状态以 GitHub Actions 实际运行结果为准。

检测说明

订阅只收录本轮通过项目规定验证的线路。

检测通过不代表所有地区、运营商和播放设备都能保证播放。线路状态和检测环境可能影响实际效果。

项目文档

- "CORE_FLOW.md"：项目总规则、架构和安全要求。
- "MASTER_PLAN.md"：施工顺序和验收标准。
- "PROGRESS.md"：实际进度、测试证据和待办事项。

项目状态

文档中的目标和计划不代表程序已经完成。项目是否可用，以实际代码、测试证据和 GitHub Actions 发布结果为准。
