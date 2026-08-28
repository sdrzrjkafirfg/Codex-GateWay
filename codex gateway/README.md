# Codex Priority Gateway

为 Codex 提供一个本地 OpenAI 兼容网关，在多个 API 中转线路之间自动选择和故障切换。

它解决三个实际痛点：线路价格不同、单个供应商不稳定、切换线路需要反复修改 Codex 配置。

核心能力：

- 自动选择价格最低且健康的线路
- 上游故障时自动切换，避免请求直接失败
- 线路恢复后自动切回，无需重启 Codex
- 通过管理页面实时调整供应商、价格、优先级和路由策略
- API key 保存在本地 `.env`，不会写入供应商配置或状态接口

## Run

1. Create `.env` from `.env.example` and fill in the secrets. Use different
   values for `GATEWAY_API_KEY` and `GATEWAY_ADMIN_API_KEY`.
2. Create `providers.yaml` from `providers.example.yaml` and set each upstream URL,
   price multiplier, and priority. Codex selects the model and the gateway forwards
   it unchanged.
3. Install and start the gateway:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -e ".[dev]"
   Copy-Item .env.example .env
   Copy-Item providers.example.yaml providers.yaml
   uvicorn app.main:create_app --factory --env-file .env --host 127.0.0.1 --port 4000
   ```

4. Point Codex at `http://127.0.0.1:4000/v1` and use the value of
   `GATEWAY_API_KEY` as its API key.

To launch the gateway and open the local management page in your browser:

```powershell
.\Start-Gateway.ps1
```

The page is available at `http://127.0.0.1:4000/admin/ui`. It is served by the
same local FastAPI process and does not require Tauri, Electron, Node.js, or a
desktop WebView shell.

Use the key button in the page's upper-right corner to set `GATEWAY_API_KEY`.
The value takes effect immediately for new Codex requests and is saved only in
the local `.env` file; it is never shown again in the UI.

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

## Behavior

- Providers are ordered by `price_multiplier`, then `priority`.
- Only configured recoverable status codes and transport errors trigger fallback.
- Three consecutive failures (configurable) open a provider circuit.
- An open circuit is not used for normal requests. After its cooldown, the
  background checker requires consecutive successful minimal `POST /responses` probes before
  recovery. It starts with `gpt-5.4-mini` and falls back to `gpt-5.4`, `gpt-5.5`,
  and `gpt-5.6-terra` only when the upstream reports that the probe model is unsupported.
  Failed recovery probes retry after 60 seconds; after the first success, the confirmation
  probe runs 20 seconds later.
  the provider becomes eligible again.
- Circuit-breaker state is stored in SQLite (`gateway.state_database_path`) so a
  restart does not immediately retry a provider that was already known to be bad.
- The inbound request, including its model field, is forwarded unchanged.
- Each individual request body is limited to 128 MiB. Non-streaming responses are
  also limited to 128 MiB; streaming SSE responses are forwarded incrementally.
- Streaming responses are byte-for-byte proxied after the upstream returns a 2xx
  status. A stream that fails after it starts cannot be safely transferred to a
  different upstream.

The first release deliberately has no Redis, load balancing, or response cache.
Use the management UI or API for live changes; direct edits to `providers.yaml`
take effect after a process restart.

An upstream URL may be either its root URL (for example `https://provider.example`)
or an existing `/v1` URL. The gateway forwards Codex's requested `/v1/...` path
unchanged and avoids adding a second `/v1` when the configured URL already has it.

`gateway-state.db` contains only runtime health state: failure counts, circuit
deadlines, recent errors, and success timestamps. It does not contain provider
keys. Keep it beside `providers.yaml` and do not delete it during normal restarts.

## Management API

The proxy uses `Authorization: Bearer <GATEWAY_API_KEY>`. Management endpoints
use the separate `Authorization: Bearer <GATEWAY_ADMIN_API_KEY>` header. Changes
are written to `providers.yaml` and apply to new requests immediately.

```text
GET    /admin/status
GET    /admin/config
PUT    /admin/routing
POST   /admin/providers
PUT    /admin/providers/{name}
POST   /admin/providers/{name}/enable
POST   /admin/providers/{name}/disable
DELETE /admin/providers/{name}
```

Create and update requests accept this shape. `api_key` is required on create;
on update, omit it to keep the existing key. The API response never includes the
key.

```json
{
  "alias": "relay-a",
  "base_url": "https://provider.example/v1",
  "api_key": "sk-...",
  "price_multiplier": 0.17,
  "priority": 1,
  "enabled": true
}
```

The gateway writes `api_key` to `.env` under a generated provider-specific
environment variable, while `providers.yaml` stores only that variable name.

`routing.mode` may be `auto` or `manual`. In `auto` mode, enabled healthy
providers are ordered by price multiplier and then priority. Manual routing uses
`priority_failover`, `failure_transfer`, or `pinned_provider`; the latter requires
a provider name. `failure_transfer` starts with the priority-selected provider and
only after a recoverable request failure tries other healthy providers by the
lowest price multiplier. A pinned provider never fails over to another upstream,
including after it has been disabled or deleted.
