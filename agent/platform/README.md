# Platform Backend

本目录是项目正式平台后端入口。

当前第一版后端使用：

- FastAPI
- WebSocket
- 内存存储骨架

后续会逐步替换为真实数据库与 Agent 编排实现。

## 运行方式

```bash
cd agent/platform
uv sync
./run_dev.sh
```

如果你只想手动启动，而不是走脚本，也可以这样运行：

```bash
cd agent/platform
uv run python -m uvicorn app.main:app --host 127.0.0.1 --port 9010
```

启动后接口根路径：

```text
http://localhost:9010/api
```
