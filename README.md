# China-IPTV-Auto-v2（第一批：基础层）

本批次建立新系统的基础，不导入旧仓库任何数据、订阅源、线路、黑名单或工作流。

## 本批次包含
- `config.yaml`：统一参数入口
- `requirements.txt`：基础依赖
- `iptv_auto/__init__.py`
- `iptv_auto/config.py`：配置读取与校验
- `iptv_auto/identity.py`：稳定线路/频道/来源身份
- `iptv_auto/playlist.py`：M3U/M3U8 解析、基础规范化和明显占位过滤
- `iptv_auto/database.py`：全新 SQLite 数据库结构、WAL、安全写入
- `tests/`：基础测试

## 重要说明
这只是第一批基础文件，**不是可直接运行的完整自动筛选系统**。自动发现、网络测速、FFmpeg/FFprobe 深度探测、评分、发布保护和 GitHub Actions 将在后续批次接入同一条管道。

首次完整运行必须等全部模块完成并审查后再进行。当前不会生成或覆盖正式 `output/result.m3u`。

## 环境
Python 3.11 或更新版本。

```bash
pip install -r requirements.txt
python -m unittest discover -s tests -v
```

## 数据库
默认数据库位置：`data/iptv_auto.sqlite3`。第一次运行会创建全新数据库。不要把旧仓库数据库复制过来。

## 配置
人工来源地址放在 `config.yaml` 的 `sources.manual` 中。此处默认留空，不预装任何旧仓库订阅源。
