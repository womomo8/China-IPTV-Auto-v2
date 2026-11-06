China-IPTV-Auto V3

自动发现、筛选和验证 IPv4 IPTV 直播源，只发布通过规定检测的线路。

项目目标

以线路质量为第一目标，不追求数量，不使用未经验证的线路凑数。

核心流程

广泛发现 → 数据整理 → 快速筛选 → 深度验证 → 安全发布

检测说明

目前以 GitHub Actions Runner 所在网络环境的检测结果作为依据。

云端检测通过不代表所有地区、运营商和用户家庭网络都能正常播放。

订阅地址

预期地址：

https://raw.githubusercontent.com/womomo8/China-IPTV-Auto-v3/main/output/iptv.m3u

首次正式发布成功、远端文件生成后才能使用。

项目文档

- "CORE_FLOW.md"：总流程依据和技术施工规范，日常确认流程优先看这里。
- "MASTER_PLAN.md"：施工任务、开发顺序和验收计划。
- "README.md"：项目简介和基本说明。

当前状态

项目目前处于 V3 建设阶段。文档描述的是目标方案，不代表程序和自动化工作流已经完成。实际完成情况以代码、测试记录和 GitHub Actions 运行结果为准。
