const translations = {
  en: { localGateway: "LOCAL GATEWAY", switchLanguage: "Switch language", connected: "Connected", notConnected: "Not connected", adminAccess: "ADMIN ACCESS", connectTitle: "Connect to local gateway", connectHelp: "Enter the administrator key configured for this gateway.", adminKey: "Administrator key", connect: "Connect", mode: "Mode", nextProvider: "Next provider", enabled: "Enabled", unavailable: "Unavailable", gateway: "GATEWAY", gatewaySummary: "Gateway summary", configureGatewayKey: "Configure Codex API key", gatewayApiKey: "Gateway API key", gatewayKeyHelp: "Codex must use this same value when connecting to the local gateway.", updateGatewayKey: "Update key", gatewayKeyUpdated: "Gateway API key updated", showKey: "Show key", hideKey: "Hide key", copyKey: "Copy key", keyCopied: "Key copied", enterGatewayKey: "Enter a key to copy", routing: "ROUTING", routeSelection: "Route selection", routingMode: "Routing mode", saveRouting: "Save routing", automatic: "Automatic", manual: "Manual", manualStrategy: "Manual strategy", priorityFailover: "Priority failover", fixedProvider: "Fixed provider", upstreams: "UPSTREAMS", upstream: "UPSTREAM", providers: "Providers", addProvider: "Add provider", provider: "Provider", multiplier: "Multiplier", priority: "Priority", status: "Status", alias: "Alias", priceMultiplier: "Price multiplier", apiAddress: "API address", apiKey: "API key", apiKeyHelp: "Required when adding; blank keeps the current key", discoverModels: "Discover models", modelChoice: "Model choice remains with Codex.", cancel: "Cancel", saveProvider: "Save provider", addProviderTitle: "Add provider", editProviderTitle: "Edit provider", ready: "Ready", circuitOpen: "Circuit open", disabled: "Disabled", autoHelp: "Uses the enabled, healthy provider with the lowest price multiplier.", manualHelp: "Manual mode follows your chosen routing strategy.", providerSaved: "Provider saved", providerDeleted: "Provider deleted", routingUpdated: "Routing updated", enterApiAddress: "Enter an API address first", noModels: "No models returned by this provider.", edit: "Edit", delete: "Delete", enable: "Enable", disable: "Disable", close: "Close", clearSession: "Clear admin session", refreshStatus: "Refresh status", configureGatewayKeyTitle: "Configure Codex API key", providerEnabled: "Provider enabled", providerDisabled: "Provider disabled", noProvider: "None" },
  zh: { localGateway: "本地网关", switchLanguage: "切换语言", connected: "已连接", notConnected: "未连接", adminAccess: "管理访问", connectTitle: "连接本地网关", connectHelp: "输入此网关配置的管理员密钥。", adminKey: "管理员密钥", connect: "连接", mode: "模式", nextProvider: "下一供应商", enabled: "已启用", unavailable: "不可用", gateway: "网关", gatewaySummary: "网关概览", configureGatewayKey: "设置 Codex API 密钥", gatewayApiKey: "网关 API 密钥", gatewayKeyHelp: "Codex 连接本地网关时必须使用相同的值。", updateGatewayKey: "更新密钥", gatewayKeyUpdated: "网关 API 密钥已更新", showKey: "显示密钥", hideKey: "隐藏密钥", copyKey: "复制密钥", keyCopied: "密钥已复制", enterGatewayKey: "请先输入密钥", routing: "路由", routeSelection: "路由选择", routingMode: "路由模式", saveRouting: "保存路由", automatic: "自动", manual: "手动", manualStrategy: "手动策略", priorityFailover: "按优先级切换", fixedProvider: "固定供应商", upstreams: "上游", upstream: "上游", providers: "供应商", addProvider: "添加供应商", provider: "供应商", multiplier: "倍率", priority: "优先级", status: "状态", alias: "别名", priceMultiplier: "价格倍率", apiAddress: "API 地址", apiKey: "API 密钥", apiKeyHelp: "新增时必填；留空则保留现有密钥", discoverModels: "发现模型", modelChoice: "模型由 Codex 自行选择。", cancel: "取消", saveProvider: "保存供应商", addProviderTitle: "添加供应商", editProviderTitle: "编辑供应商", ready: "正常", circuitOpen: "熔断中", disabled: "已禁用", autoHelp: "在已启用且健康的供应商中，使用价格倍率最低的线路。", manualHelp: "手动模式会遵循所选的路由策略。", providerSaved: "供应商已保存", providerDeleted: "供应商已删除", routingUpdated: "路由已更新", enterApiAddress: "请先输入 API 地址", noModels: "该供应商没有返回模型。", edit: "编辑", delete: "删除", enable: "启用", disable: "禁用", close: "关闭", clearSession: "清除管理员会话", refreshStatus: "刷新状态", configureGatewayKeyTitle: "设置 Codex API 密钥", providerEnabled: "供应商已启用", providerDisabled: "供应商已禁用", noProvider: "无" }
};
translations.en.failureTransfer = "Failure transfer";
translations.zh.failureTransfer = "失败转移";
const state = { config: null, status: null, mode: "auto", strategy: "priority_failover", pinned: null, editing: null, language: localStorage.getItem("gatewayUiLanguage") || "en" };
const $ = (selector) => document.querySelector(selector);
const apiKey = () => sessionStorage.getItem("gatewayAdminKey") || "";
const t = (key) => translations[state.language][key] || key;

function applyTranslations() {
  document.documentElement.lang = state.language === "zh" ? "zh-CN" : "en";
  document.title = state.language === "zh" ? "Codex 网关" : "Codex Gateway";
  document.querySelectorAll("[data-i18n]").forEach((element) => { element.textContent = t(element.dataset.i18n); });
  document.querySelectorAll("[data-i18n-aria]").forEach((element) => { element.setAttribute("aria-label", t(element.dataset.i18nAria)); });
  document.querySelectorAll("[data-i18n-placeholder]").forEach((element) => { element.placeholder = t(element.dataset.i18nPlaceholder); });
  $("#language-button").textContent = state.language === "en" ? "中文" : "EN";
  $("#language-button").title = t("switchLanguage"); $("#language-button").setAttribute("aria-label", t("switchLanguage"));
  $("#refresh-button").title = t("refreshStatus"); $("#refresh-button").setAttribute("aria-label", t("refreshStatus"));
  $("#lock-button").title = t("clearSession"); $("#lock-button").setAttribute("aria-label", t("clearSession"));
  $("#gateway-key-button").title = t("configureGatewayKeyTitle"); $("#gateway-key-button").setAttribute("aria-label", t("configureGatewayKeyTitle"));
  $("#close-dialog").title = t("close"); $("#close-dialog").setAttribute("aria-label", t("close"));
  $("#close-gateway-key-dialog").title = t("close"); $("#close-gateway-key-dialog").setAttribute("aria-label", t("close"));
  $("#toggle-gateway-api-key").title = $("#gateway-api-key").type === "password" ? t("showKey") : t("hideKey"); $("#toggle-gateway-api-key").setAttribute("aria-label", $("#toggle-gateway-api-key").title);
  $("#copy-gateway-api-key").title = t("copyKey"); $("#copy-gateway-api-key").setAttribute("aria-label", t("copyKey"));
  setConnection(Boolean(apiKey()) && $("#dashboard").hidden === false);
}

function headers() { return { "Authorization": `Bearer ${apiKey()}`, "Content-Type": "application/json" }; }
async function api(path, options = {}) {
  const response = await fetch(path, { ...options, headers: { ...headers(), ...(options.headers || {}) } });
  if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(formatError(data.detail, response.status)); }
  return response.status === 204 ? null : response.json();
}
function formatError(detail, status) { if (Array.isArray(detail)) return detail.map((item) => `${item.loc?.slice(-1)[0] || "field"}: ${item.msg || "invalid value"}`).join("; "); if (typeof detail === "string") return detail; return `Request failed (${status})`; }
function toast(message, isError = false) { const element = $("#toast"); element.textContent = message; element.className = `show${isError ? " error" : ""}`; window.clearTimeout(toast.timer); toast.timer = window.setTimeout(() => { element.className = ""; }, 3200); }
function humanStatus(provider) { if (!provider.enabled) return ["disabled", t("disabled")]; if (provider.recovery_successes) return ["open", `${t("circuitOpen")} (${provider.recovery_successes}/2)`]; if (provider.circuit_open_until) return ["open", t("circuitOpen")]; return ["healthy", t("ready")]; }
function setConnection(live) { const element = $("#connection"); element.textContent = live ? t("connected") : t("notConnected"); element.classList.toggle("live", live); }

async function refresh() {
  if (!apiKey()) return;
  try {
    const [config, status] = await Promise.all([api("/admin/config"), api("/admin/status")]);
    state.config = config; state.status = status; state.mode = status.routing.mode; state.strategy = status.routing.manual_strategy; state.pinned = status.routing.pinned_provider;
    render(); setConnection(true); $("#auth-panel").hidden = true; $("#dashboard").hidden = false;
  } catch (error) { setConnection(false); $("#auth-panel").hidden = false; $("#dashboard").hidden = true; toast(error.message, true); }
}
function render() {
  const providers = state.config.providers; const providerStates = state.status.providers;
  const unavailable = providers.filter((provider) => !provider.enabled || providerStates[provider.name]?.circuit_open_until).length;
  $("#summary-mode").textContent = state.mode === "auto" ? t("automatic") : t("manual");
  $("#summary-next").textContent = state.status.next_provider || t("noProvider");
  $("#summary-enabled").textContent = providers.filter((provider) => provider.enabled).length;
  $("#summary-unavailable").textContent = unavailable;
  document.querySelectorAll("[data-mode]").forEach((button) => button.classList.toggle("active", button.dataset.mode === state.mode));
  document.querySelectorAll("[data-strategy]").forEach((button) => button.classList.toggle("active", button.dataset.strategy === state.strategy));
  $("#manual-controls").hidden = state.mode !== "manual";
  $("#pinned-field").hidden = state.strategy !== "pinned_provider";
  $("#mode-description").textContent = state.mode === "auto" ? t("autoHelp") : t("manualHelp");
  $("#pinned-provider").innerHTML = providers.map((provider) => `<option value="${escapeHtml(provider.name)}" ${provider.name === state.pinned ? "selected" : ""}>${escapeHtml(provider.name)}</option>`).join("");
  $("#providers-body").innerHTML = providers.map((provider) => providerRow(provider, providerStates[provider.name] || {})).join("");
}
function providerRow(provider, health) {
  const [statusClass, statusText] = humanStatus({ ...provider, ...health });
  return `<tr><td data-label="${t("provider")}"><div class="provider-name">${escapeHtml(provider.name)}<span class="provider-url">${escapeHtml(provider.base_url)}</span></div></td><td data-label="${t("multiplier")}">${provider.price_multiplier}</td><td data-label="${t("priority")}">${provider.priority}</td><td data-label="${t("status")}"><span class="status ${statusClass}">${statusText}</span></td><td data-label="${t("enabled")}"><label class="switch" title="${t(provider.enabled ? "disable" : "enable")} ${escapeHtml(provider.name)}"><input type="checkbox" data-toggle="${escapeHtml(provider.name)}" ${provider.enabled ? "checked" : ""}><span class="slider"></span></label></td><td data-label="${t("status")}"><div class="row-actions"><button class="icon-button" data-edit="${escapeHtml(provider.name)}" title="${t("edit")} ${escapeHtml(provider.name)}" aria-label="${t("edit")} ${escapeHtml(provider.name)}">&#9998;</button><button class="icon-button danger" data-delete="${escapeHtml(provider.name)}" title="${t("delete")} ${escapeHtml(provider.name)}" aria-label="${t("delete")} ${escapeHtml(provider.name)}">&#128465;</button></div></td></tr>`;
}
function escapeHtml(value) { return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]); }
function openProvider(provider = null) { state.editing = provider?.name || null; $("#provider-dialog-title").textContent = provider ? t("editProviderTitle") : t("addProviderTitle"); $("#provider-alias").value = provider?.name || ""; $("#provider-url").value = provider?.base_url || ""; $("#provider-key").value = ""; $("#provider-key").required = !provider; $("#provider-multiplier").value = provider?.price_multiplier ?? ""; $("#provider-priority").value = provider?.priority ?? 100; $("#provider-enabled").checked = provider?.enabled ?? true; $("#discovered-models").textContent = t("modelChoice"); $("#provider-dialog").showModal(); }
async function discoverModels() { const baseUrl = $("#provider-url").value.trim(); const key = $("#provider-key").value; if (!baseUrl) { toast(t("enterApiAddress"), true); return; } try { const result = await api("/admin/providers/discover-models", { method: "POST", body: JSON.stringify({ base_url: baseUrl, api_key: key || undefined, provider_alias: state.editing || undefined }) }); $("#discovered-models").innerHTML = result.models.length ? `<span class="model-list">${result.models.map(escapeHtml).join(", ")}</span>` : t("noModels"); } catch (error) { toast(error.message, true); } }
async function saveProvider(event) { event.preventDefault(); const payload = { alias: $("#provider-alias").value.trim(), base_url: $("#provider-url").value.trim(), price_multiplier: Number($("#provider-multiplier").value), priority: Number($("#provider-priority").value), enabled: $("#provider-enabled").checked }; const key = $("#provider-key").value; if (key) payload.api_key = key; try { await api(state.editing ? `/admin/providers/${encodeURIComponent(state.editing)}` : "/admin/providers", { method: state.editing ? "PUT" : "POST", body: JSON.stringify(payload) }); $("#provider-dialog").close(); toast(t("providerSaved")); await refresh(); } catch (error) { toast(error.message, true); } }
async function saveRouting() { const payload = { mode: state.mode, manual_strategy: state.strategy, pinned_provider: state.strategy === "pinned_provider" ? $("#pinned-provider").value : null }; try { await api("/admin/routing", { method: "PUT", body: JSON.stringify(payload) }); toast(t("routingUpdated")); await refresh(); } catch (error) { toast(error.message, true); } }
async function saveGatewayKey(event) { event.preventDefault(); try { await api("/admin/gateway/api-key", { method: "PUT", body: JSON.stringify({ api_key: $("#gateway-api-key").value }) }); $("#gateway-key-dialog").close(); $("#gateway-api-key").value = ""; toast(t("gatewayKeyUpdated")); } catch (error) { toast(error.message, true); } }
function toggleGatewayKeyVisibility() { const input = $("#gateway-api-key"); input.type = input.type === "password" ? "text" : "password"; applyTranslations(); }
async function copyGatewayKey() { const value = $("#gateway-api-key").value; if (!value) { toast(t("enterGatewayKey"), true); return; } try { await navigator.clipboard.writeText(value); toast(t("keyCopied")); } catch { toast(t("copyKey"), true); } }

$("#auth-form").addEventListener("submit", async (event) => { event.preventDefault(); sessionStorage.setItem("gatewayAdminKey", $("#admin-key").value); await refresh(); });
$("#refresh-button").addEventListener("click", refresh); $("#lock-button").addEventListener("click", () => { sessionStorage.removeItem("gatewayAdminKey"); setConnection(false); $("#dashboard").hidden = true; $("#auth-panel").hidden = false; });
$("#language-button").addEventListener("click", () => { state.language = state.language === "en" ? "zh" : "en"; localStorage.setItem("gatewayUiLanguage", state.language); applyTranslations(); if (state.config) render(); });
$("#gateway-key-button").addEventListener("click", () => { $("#gateway-api-key").value = ""; $("#gateway-key-dialog").showModal(); });
$("#close-gateway-key-dialog").addEventListener("click", () => $("#gateway-key-dialog").close()); $("#cancel-gateway-key").addEventListener("click", () => $("#gateway-key-dialog").close()); $("#gateway-key-form").addEventListener("submit", saveGatewayKey);
$("#toggle-gateway-api-key").addEventListener("click", toggleGatewayKeyVisibility); $("#copy-gateway-api-key").addEventListener("click", copyGatewayKey);
$("#add-provider").addEventListener("click", () => openProvider()); $("#close-dialog").addEventListener("click", () => $("#provider-dialog").close()); $("#cancel-provider").addEventListener("click", () => $("#provider-dialog").close()); $("#provider-form").addEventListener("submit", saveProvider); $("#discover-models").addEventListener("click", discoverModels); $("#save-routing").addEventListener("click", saveRouting);
document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => { state.mode = button.dataset.mode; render(); })); document.querySelectorAll("[data-strategy]").forEach((button) => button.addEventListener("click", () => { state.strategy = button.dataset.strategy; render(); }));
$("#providers-body").addEventListener("click", async (event) => { const edit = event.target.closest("[data-edit]"); const remove = event.target.closest("[data-delete]"); if (edit) openProvider(state.config.providers.find((provider) => provider.name === edit.dataset.edit)); if (remove && window.confirm(`${t("delete")} ${remove.dataset.delete}?`)) { try { await api(`/admin/providers/${encodeURIComponent(remove.dataset.delete)}`, { method: "DELETE" }); toast(t("providerDeleted")); await refresh(); } catch (error) { toast(error.message, true); } } });
$("#providers-body").addEventListener("change", async (event) => { const alias = event.target.dataset.toggle; if (!alias) return; try { await api(`/admin/providers/${encodeURIComponent(alias)}/${event.target.checked ? "enable" : "disable"}`, { method: "POST" }); toast(t(event.target.checked ? "providerEnabled" : "providerDisabled")); await refresh(); } catch (error) { toast(error.message, true); } });
applyTranslations(); if (apiKey()) refresh(); window.setInterval(refresh, 10000);
