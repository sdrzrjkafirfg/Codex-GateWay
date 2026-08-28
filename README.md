## 中文使用教程

### 1. 准备配置

确认 Python 3.11 或更高版本已安装。编辑 `.env`，把其中的“示例”替换成你自己的两个不同密钥；再编辑 `providers.yaml`，填写上游地址、价格倍率、优先级和对应的环境变量名。

真实上游密钥只放在 `.env`，不要写入 `providers.yaml`。

### 2. 启动网关

在发布目录中双击 `Start-Gateway.ps1`，或在 PowerShell 执行：

```powershell
.\Start-Gateway.ps1
```

首次运行会自动创建 `.venv` 并安装依赖。管理页面地址为 `http://127.0.0.1:4000/admin/ui`。

### 3. 接入 Codex

将 Codex 的 API 地址设置为 `http://127.0.0.1:4000/v1`，API key 使用 `.env` 中的 `GATEWAY_API_KEY`。模型名称由 Codex 自己选择，网关会原样转发。

### 4. 管理线路

打开管理页面并输入 `GATEWAY_ADMIN_API_KEY`，即可新增、编辑、启用、禁用或删除供应商，并切换自动路由、优先级故障切换、失败转移和固定供应商模式。
