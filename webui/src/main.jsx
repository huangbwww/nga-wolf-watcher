import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  Bot,
  Check,
  ChevronDown,
  CircleStop,
  Database,
  FolderOpen,
  MessageSquare,
  Play,
  QrCode,
  RefreshCw,
  Save,
  Settings,
  ShieldCheck,
  TerminalSquare,
} from "lucide-react";
import "./styles.css";

const api = () => window.pywebview?.api;

const fieldGroups = {
  common: [
    ["nga_cookie", "NGA Cookie", "textarea"],
    ["watch_mode", "监听模式", "select", ["author", "thread_author", "both"]],
    ["thread_watch_tail_count", "帖内扫描条数", "number"],
    ["thread_watch_interval", "帖内扫描间隔秒", "number"],
  ],
  feishu: [
    ["feishu_app_id", "App ID", "text"],
    ["feishu_app_secret", "App Secret", "password"],
    ["feishu_receive_id", "Receive ID", "text"],
  ],
  wechat: [
    ["wechat_bot_token", "Token", "password"],
    ["wechat_bot_base_url", "Base URL", "text"],
    ["wechat_bot_cdn_base_url", "CDN Base URL", "text"],
    ["wechat_bot_target_user_id", "目标用户 ID", "text"],
    ["wechat_bot_allowed_user_ids", "允许用户 ID", "text"],
    ["wechat_bot_account_id", "账号标识", "text"],
  ],
  ai: [
    ["ai_enabled", "启用 AI", "checkbox"],
    ["ai_provider", "Provider", "select", ["codex", "claude", "custom"]],
    ["ai_auto_analyze_new_post", "新帖自动分析", "checkbox"],
    ["ai_work_dir", "AI 工作目录", "text"],
    ["ai_auto_analysis_prompt", "自动分析提示词", "textarea"],
    ["ai_schedule_enabled", "定时分析", "checkbox"],
    ["ai_schedule_interval_minutes", "定时间隔分钟", "number"],
    ["ai_schedule_windows", "定时时间窗口", "text"],
    ["ai_schedule_prompt", "定时提示词", "textarea"],
  ],
  runtime: [
    ["interval", "轮询间隔秒", "number"],
    ["jitter", "随机抖动秒", "number"],
    ["retries", "重试次数", "number"],
    ["retry_initial_delay", "重试初始等待秒", "number"],
    ["retry_delay", "重试递增秒", "number"],
    ["nga_request_min_interval", "NGA 请求最小间隔秒", "number"],
    ["quiet_hours_enabled", "免打扰", "checkbox"],
    ["quiet_policy", "免打扰策略", "select", ["ignore", "defer"]],
    ["quiet_start_time", "免打扰开始", "text"],
    ["quiet_end_time", "免打扰结束", "text"],
  ],
};

function normalizeConfig(config = {}, defaults = {}) {
  return { ...defaults, ...config };
}

function parseJsonList(raw) {
  if (Array.isArray(raw)) return raw.filter((item) => item && typeof item === "object");
  try {
    const value = JSON.parse(String(raw || "[]"));
    return Array.isArray(value) ? value.filter((item) => item && typeof item === "object") : [];
  } catch {
    return [];
  }
}

function formatJsonList(rows) {
  return JSON.stringify(rows, null, 2);
}

function ensureId(prefix, row) {
  if (String(row.id || "").trim()) return String(row.id).trim();
  return `${prefix}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 7)}`;
}

function profileLabel(profile, fallback) {
  const label = String(profile.label || "").trim();
  const id = String(profile.id || "").trim();
  return label && id ? `${label} (${id})` : label || id || fallback;
}

function chatLabel(chat) {
  const id = String(chat.chat_id || chat.id || "").trim();
  const name = String(chat.name || chat.title || "").trim();
  return name && id ? `${name} (${id})` : id || name;
}

function targetLabel(target) {
  const channel = target.channel === "wechat" ? "微信" : "飞书";
  const name = String(target.label || target.id || target.receive_id || "").trim();
  const receive = String(target.receive_id || "").trim();
  return `${channel} / ${name}${receive ? ` -> ${receive}` : ""}`;
}

function channelTitle(channel) {
  return channel === "wechat" ? "微信" : "飞书";
}

function parseProfiles(config, key, legacy = {}) {
  const rows = parseJsonList(config[key]).map((row) => ({ ...row, id: ensureId(key.includes("feishu") ? "feishu" : "wechat", row) }));
  if (rows.length) return rows;
  if (key === "feishu_bot_profiles" && (config.feishu_app_id || config.feishu_app_secret)) {
    return [{ id: "default", label: "默认飞书", app_id: config.feishu_app_id || "", app_secret: config.feishu_app_secret || "", id_type: config.feishu_id_type || "chat_id", chats: [] }];
  }
  if (key === "wechat_bot_profiles" && config.wechat_bot_token) {
    return [{
      id: "default",
      label: "默认微信",
      token: config.wechat_bot_token || "",
      base_url: config.wechat_bot_base_url || "https://ilinkai.weixin.qq.com",
      cdn_base_url: config.wechat_bot_cdn_base_url || "https://novac2c.cdn.weixin.qq.com/c2c",
      target_user_id: config.wechat_bot_target_user_id || "",
      allowed_user_ids: config.wechat_bot_allowed_user_ids || "",
      poll_timeout_ms: config.wechat_bot_poll_timeout_ms || "35000",
      account_id: config.wechat_bot_account_id || "default",
      route_tag: config.wechat_bot_route_tag || "",
    }];
  }
  return legacy.rows || [];
}

function parsePushTargets(config, feishuProfiles, wechatProfiles) {
  const rows = parseJsonList(config.push_targets).map((row) => ({ ...row, id: ensureId("target", row), channel: row.channel || "feishu", id_type: row.id_type || "chat_id" }));
  if (rows.length) return rows;
  const fallback = [];
  if (feishuProfiles.length && config.feishu_receive_id) {
    fallback.push({ id: "default_feishu", label: "默认飞书群", channel: "feishu", profile_id: feishuProfiles[0].id, receive_id: config.feishu_receive_id, id_type: config.feishu_id_type || "chat_id", default_author_id: config.default_author_id || "", default_tid: config.default_tid || "" });
  }
  if (wechatProfiles.length && config.wechat_bot_target_user_id) {
    fallback.push({ id: "default_wechat", label: "默认微信", channel: "wechat", profile_id: wechatProfiles[0].id, receive_id: config.wechat_bot_target_user_id, id_type: "user_id", default_author_id: config.default_author_id || "", default_tid: config.default_tid || "" });
  }
  return fallback;
}

function parseListenRules(config) {
  return parseJsonList(config.listen_rules).map((row) => ({
    ...row,
    id: ensureId("rule", row),
    mode: row.mode || "thread_author",
    target_ids: Array.isArray(row.target_ids) ? row.target_ids : String(row.target_ids || "").split(/[,，;；\s]+/).filter(Boolean),
  }));
}

function applyStructuredConfig(config, { feishuProfiles, wechatProfiles, pushTargets, listenRules }) {
  const next = {
    ...config,
    feishu_bot_profiles: formatJsonList(feishuProfiles),
    wechat_bot_profiles: formatJsonList(wechatProfiles),
    push_targets: formatJsonList(pushTargets),
    listen_rules: formatJsonList(listenRules),
  };
  if (feishuProfiles[0]) {
    next.feishu_app_id = feishuProfiles[0].app_id || "";
    next.feishu_app_secret = feishuProfiles[0].app_secret || "";
    next.feishu_id_type = feishuProfiles[0].id_type || "chat_id";
  }
  if (wechatProfiles[0]) {
    next.wechat_bot_token = wechatProfiles[0].token || "";
    next.wechat_bot_base_url = wechatProfiles[0].base_url || "https://ilinkai.weixin.qq.com";
    next.wechat_bot_cdn_base_url = wechatProfiles[0].cdn_base_url || "https://novac2c.cdn.weixin.qq.com/c2c";
    next.wechat_bot_target_user_id = wechatProfiles[0].target_user_id || "";
    next.wechat_bot_allowed_user_ids = wechatProfiles[0].allowed_user_ids || "";
    next.wechat_bot_poll_timeout_ms = wechatProfiles[0].poll_timeout_ms || "35000";
    next.wechat_bot_account_id = wechatProfiles[0].account_id || "default";
    next.wechat_bot_route_tag = wechatProfiles[0].route_tag || "";
  }
  const modes = new Set(listenRules.map((rule) => rule.mode || "thread_author"));
  if (modes.size === 2) next.watch_mode = "both";
  else if (modes.has("author")) next.watch_mode = "author";
  else if (modes.has("thread_author")) next.watch_mode = "thread_author";
  return next;
}

function parseTargetList(raw = "", fallback = "") {
  const text = String(raw || "").trim();
  const rows = [];
  const seen = new Set();
  const items = text ? text.split(/[\r\n,，;；]+/) : [];
  if (!items.length && fallback) items.push(String(fallback));
  for (const item of items) {
    const part = item.trim();
    if (!part) continue;
    const [idPart, ...labelParts] = part.split("=");
    const id = idPart.trim();
    if (!id || seen.has(id)) continue;
    seen.add(id);
    rows.push({ id, label: labelParts.join("=").trim() });
  }
  return rows;
}

function formatTargetList(rows) {
  return rows
    .filter((row) => String(row.id || "").trim())
    .map((row) => {
      const id = String(row.id || "").trim();
      const label = String(row.label || "").trim();
      return label ? `${id}=${label}` : id;
    })
    .join("\n");
}

function parseThreadAuthorWatches(raw = "") {
  return String(raw || "")
    .split(/[\r\n]+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const [mainPart, ...routeParts] = line.split("|").map((part) => part.trim());
      const [pairPart, ...labelParts] = mainPart.split("=");
      const [tid = "", authorId = ""] = pairPart.split(":");
      const row = {
        tid: tid.trim(),
        authorId: authorId.trim(),
        label: labelParts.join("=").trim(),
        receiveId: "",
        appId: "",
        appSecret: "",
        idType: "chat_id",
      };
      for (const part of routeParts) {
        if (!part) continue;
        const [rawKey, ...valueParts] = part.split("=");
        const key = rawKey.trim().toLowerCase().replaceAll("-", "_");
        const value = valueParts.join("=").trim();
        if (key === "receive_id" || key === "feishu_receive_id") row.receiveId = value;
        if (key === "app_id" || key === "feishu_app_id") row.appId = value;
        if (key === "app_secret" || key === "feishu_app_secret") row.appSecret = value;
        if (key === "id_type" || key === "receive_id_type" || key === "feishu_id_type") row.idType = value || "chat_id";
      }
      return row;
    });
}

function formatThreadAuthorWatches(rows) {
  return rows
    .filter((row) => String(row.tid || "").trim() && String(row.authorId || "").trim())
    .map((row) => {
      let line = `${String(row.tid).trim()}:${String(row.authorId).trim()}`;
      const label = String(row.label || "").trim();
      if (label) line += `=${label}`;
      const receiveId = String(row.receiveId || "").trim();
      const appId = String(row.appId || "").trim();
      const appSecret = String(row.appSecret || "").trim();
      const idType = String(row.idType || "chat_id").trim();
      if (receiveId) line += `|receive_id=${receiveId}`;
      if (appId) line += `|app_id=${appId}`;
      if (appSecret) line += `|app_secret=${appSecret}`;
      if (idType && idType !== "chat_id") line += `|id_type=${idType}`;
      return line;
    })
    .join("\n");
}

function Field({ config, setConfig, spec }) {
  const [key, label, type, options] = spec;
  const value = config[key] ?? "";
  const update = (next) => setConfig((current) => ({ ...current, [key]: next }));
  if (type === "textarea") {
    return (
      <label className="field field-wide">
        <span>{label}</span>
        <textarea value={value || ""} onChange={(event) => update(event.target.value)} rows={key === "nga_cookie" ? 4 : 3} />
      </label>
    );
  }
  if (type === "select") {
    return (
      <label className="field">
        <span>{label}</span>
        <select value={value || options[0]} onChange={(event) => update(event.target.value)}>
          {options.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </label>
    );
  }
  if (type === "checkbox") {
    return (
      <label className="switch-row">
        <span>{label}</span>
        <input type="checkbox" checked={Boolean(value)} onChange={(event) => update(event.target.checked)} />
      </label>
    );
  }
  return (
    <label className="field">
      <span>{label}</span>
      <input type={type || "text"} value={value || ""} onChange={(event) => update(event.target.value)} />
    </label>
  );
}

function Section({ icon: Icon, title, description, children, defaultOpen = true }) {
  return (
    <details className="section" open={defaultOpen}>
      <summary>
        <div className="section-title">
          <Icon size={18} />
          <div>
            <h2>{title}</h2>
            <p>{description}</p>
          </div>
        </div>
        <ChevronDown size={18} />
      </summary>
      <div className="section-body">{children}</div>
    </details>
  );
}

function ActionButton({ icon: Icon, children, onClick, kind = "secondary", disabled = false }) {
  return (
    <button className={`btn ${kind}`} onClick={onClick} disabled={disabled}>
      <Icon size={16} />
      {children}
    </button>
  );
}

function Notice({ message, kind = "info" }) {
  if (!message) return null;
  return <div className={`notice ${kind}`}>{message}</div>;
}

function ChannelPicker({ config, setConfig }) {
  return (
    <label className="field">
      <span>当前配置通道</span>
      <select
        value={config.bot_channel || "feishu"}
        onChange={(event) => setConfig((current) => ({ ...current, bot_channel: event.target.value }))}
      >
        <option value="feishu">飞书</option>
        <option value="wechat">微信</option>
      </select>
    </label>
  );
}

function TargetListEditor({ config, setConfig, configKey, fallbackKey, title, idLabel }) {
  const rows = parseTargetList(config[configKey], config[fallbackKey]);
  const updateRows = (nextRows) => setConfig((current) => ({ ...current, [configKey]: formatTargetList(nextRows) }));
  const updateRow = (index, patch) => updateRows(rows.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)));
  const addRow = () => updateRows([...rows, { id: "", label: "" }]);
  const deleteRow = (index) => updateRows(rows.filter((_, rowIndex) => rowIndex !== index));
  return (
    <div className="editor-card field-wide">
      <div className="editor-header">
        <div>
          <h3>{title}</h3>
          <p>ID 和备注分开填写，保存时会自动转成兼容旧版的配置格式。</p>
        </div>
        <button className="small-btn primary" type="button" onClick={addRow}>
          +
        </button>
      </div>
      <div className="row-list">
        {rows.length ? (
          rows.map((row, index) => (
            <div className="config-row" key={`${configKey}-${index}`}>
              <label>
                <span>{idLabel}</span>
                <input value={row.id || ""} onChange={(event) => updateRow(index, { id: event.target.value })} />
              </label>
              <label>
                <span>备注</span>
                <input value={row.label || ""} onChange={(event) => updateRow(index, { label: event.target.value })} />
              </label>
              <button className="small-btn" type="button" onClick={() => deleteRow(index)}>
                -
              </button>
            </div>
          ))
        ) : (
          <div className="empty-row">暂无条目，点击 + 添加。</div>
        )}
      </div>
    </div>
  );
}

function ProfileGroupEditor({ title, kind, rows, setRows, busy, onQueryChats }) {
  const [chatQueries, setChatQueries] = useState({});
  const addRow = () => setRows([...rows, kind === "feishu"
    ? { id: ensureId("feishu", {}), label: "", app_id: "", app_secret: "", id_type: "chat_id", chats: [] }
    : { id: ensureId("wechat", {}), label: "", token: "", base_url: "https://ilinkai.weixin.qq.com", cdn_base_url: "https://novac2c.cdn.weixin.qq.com/c2c", target_user_id: "", allowed_user_ids: "", poll_timeout_ms: "35000", account_id: "default", route_tag: "" }]);
  const updateRow = (index, patch) => setRows(rows.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)));
  const deleteRow = (index) => setRows(rows.filter((_, rowIndex) => rowIndex !== index));
  return (
    <div className="editor-card field-wide">
      <div className="editor-header">
        <div>
          <h3>{title}</h3>
          <p>{kind === "feishu" ? "每组 App ID / Secret 独立缓存可见群组。" : "每组微信 Token 独立保存目标用户和账号标识。"}</p>
        </div>
        <button className="small-btn primary" type="button" onClick={addRow}>+</button>
      </div>
      <div className="row-list">
        {rows.length ? rows.map((row, index) => (
          <div className={kind === "feishu" ? "profile-row feishu" : "profile-row"} key={`${kind}-${row.id || index}`}>
            <label><span>备注</span><input value={row.label || ""} onChange={(event) => updateRow(index, { label: event.target.value })} /></label>
            {kind === "feishu" ? (
              <>
                <label><span>App ID</span><input value={row.app_id || ""} onChange={(event) => updateRow(index, { app_id: event.target.value })} /></label>
                <label><span>App Secret</span><input type="password" value={row.app_secret || ""} onChange={(event) => updateRow(index, { app_secret: event.target.value })} /></label>
                <label><span>搜索群名</span><input placeholder="新群没出现时输入群名" value={chatQueries[row.id] || ""} onChange={(event) => setChatQueries((current) => ({ ...current, [row.id]: event.target.value }))} /></label>
                <button className="btn slim" type="button" disabled={busy} onClick={() => onQueryChats(row.id, chatQueries[row.id] || "")}>查询群组</button>
                <span className="row-meta">{Array.isArray(row.chats) ? row.chats.length : 0} 个群</span>
              </>
            ) : (
              <>
                <label><span>Token</span><input type="password" value={row.token || ""} onChange={(event) => updateRow(index, { token: event.target.value })} /></label>
                <label><span>目标用户 ID</span><input value={row.target_user_id || ""} onChange={(event) => updateRow(index, { target_user_id: event.target.value })} /></label>
                <label><span>账号标识</span><input value={row.account_id || ""} onChange={(event) => updateRow(index, { account_id: event.target.value })} /></label>
              </>
            )}
            <button className="small-btn" type="button" onClick={() => deleteRow(index)}>-</button>
          </div>
        )) : <div className="empty-row">暂无配置组，点击 + 添加。</div>}
      </div>
    </div>
  );
}

function ListenRuleEditor({ rows, setRows, authorRows, threadRows, pushTargets, feishuProfiles, wechatProfiles, onEnsureRouteTarget }) {
  const [draft, setDraft] = useState(null);
  const addRow = () => setRows([...rows, { id: ensureId("rule", {}), label: "", mode: "thread_author", author_id: authorRows[0]?.id || "", tid: threadRows[0]?.id || "", target_ids: pushTargets[0]?.id ? [pushTargets[0].id] : [] }]);
  const updateRow = (index, patch) => setRows(rows.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)));
  const deleteRow = (index) => setRows(rows.filter((_, rowIndex) => rowIndex !== index));
  const selectedTargets = (row) => (Array.isArray(row.target_ids) ? row.target_ids : []).filter(Boolean);
  const removeTarget = (rowIndex, targetIndex) => {
    const row = rows[rowIndex];
    updateRow(rowIndex, { target_ids: selectedTargets(row).filter((_, index) => index !== targetIndex) });
  };
  const openTargetDraft = (rowIndex) => {
    const channel = feishuProfiles.length || !wechatProfiles.length ? "feishu" : "wechat";
    const profile = channel === "wechat" ? wechatProfiles[0] : feishuProfiles[0];
    const chats = channel === "feishu" && profile && Array.isArray(profile.chats) ? profile.chats : [];
    setDraft({ rowIndex, channel, profile_id: profile?.id || "", receive_id: chats[0]?.chat_id || "" });
  };
  const draftProfile = draft?.channel === "wechat"
    ? wechatProfiles.find((profile) => profile.id === draft.profile_id) || wechatProfiles[0]
    : feishuProfiles.find((profile) => profile.id === draft?.profile_id) || feishuProfiles[0];
  const draftChats = draft?.channel === "feishu" && draftProfile && Array.isArray(draftProfile.chats) ? draftProfile.chats : [];
  const confirmDraft = () => {
    if (!draft) return;
    const targetId = onEnsureRouteTarget(draft);
    if (!targetId) return;
    const row = rows[draft.rowIndex];
    const nextIds = selectedTargets(row);
    if (!nextIds.includes(targetId)) nextIds.push(targetId);
    updateRow(draft.rowIndex, { target_ids: nextIds });
    setDraft(null);
  };
  return (
    <div className="editor-card field-wide">
      <div className="editor-header">
        <div>
          <h3>监听规则</h3>
          <p>规则决定监听什么内容，并直接选择飞书群或微信账号。</p>
        </div>
        <button className="small-btn primary" type="button" onClick={addRow}>+</button>
      </div>
      <div className="row-list">
        {rows.length ? rows.map((row, index) => (
          <div className="rule-row" key={row.id || index}>
            <label><span>备注</span><input value={row.label || ""} onChange={(event) => updateRow(index, { label: event.target.value })} /></label>
            <label><span>监听方式</span><select value={row.mode || "thread_author"} onChange={(event) => updateRow(index, { mode: event.target.value })}><option value="thread_author">固定帖子筛选用户</option><option value="author">用户主页监听</option></select></label>
            <label><span>用户</span><select value={row.author_id || ""} onChange={(event) => updateRow(index, { author_id: event.target.value })}>{authorRows.map((item) => <option key={item.id} value={item.id}>{item.label ? `${item.label} (${item.id})` : item.id}</option>)}</select></label>
            <label><span>帖子</span><select disabled={row.mode === "author"} value={row.tid || ""} onChange={(event) => updateRow(index, { tid: event.target.value })}>{threadRows.map((item) => <option key={item.id} value={item.id}>{item.label ? `${item.label} (${item.id})` : item.id}</option>)}</select></label>
            <div className="inline-targets">
              <div className="inline-target-header">
                <span>发送目标</span>
                <button className="small-btn primary" type="button" onClick={() => openTargetDraft(index)}>+</button>
              </div>
              {selectedTargets(row).length ? selectedTargets(row).map((targetId, targetIndex) => {
                const target = pushTargets.find((item) => item.id === targetId);
                return (
                  <div className="inline-target-row" key={`${row.id}-${targetId}-${targetIndex}`}>
                    <span>{target ? targetLabel(target) : targetId}</span>
                    <button className="small-btn" type="button" onClick={() => removeTarget(index, targetIndex)}>-</button>
                  </div>
                );
              }) : <span className="empty-inline">点击 + 添加飞书群或微信账号。</span>}
            </div>
            <button className="small-btn" type="button" onClick={() => deleteRow(index)}>-</button>
          </div>
        )) : <div className="empty-row">暂无监听规则。点击 + 添加监听内容和发送目标。</div>}
      </div>
      {draft ? (
        <div className="modal-backdrop">
          <div className="modal-card">
            <div className="editor-header">
              <div>
                <h3>新增规则发送目标</h3>
                <p>飞书选择配置组和群；微信只选择配置组。</p>
              </div>
              <button className="small-btn" type="button" onClick={() => setDraft(null)}>×</button>
            </div>
            <div className="grid compact-form">
              <label className="field">
                <span>通道</span>
                <select value={draft.channel} onChange={(event) => {
                  const channel = event.target.value;
                  const profile = channel === "wechat" ? wechatProfiles[0] : feishuProfiles[0];
                  const chats = channel === "feishu" && profile && Array.isArray(profile.chats) ? profile.chats : [];
                  setDraft((current) => ({ ...current, channel, profile_id: profile?.id || "", receive_id: chats[0]?.chat_id || "" }));
                }}>
                  <option value="feishu">飞书</option>
                  <option value="wechat">微信</option>
                </select>
              </label>
              {draft.channel === "feishu" ? (
                <>
                  <label className="field">
                    <span>飞书配置</span>
                    <select value={draft.profile_id} onChange={(event) => {
                      const profile = feishuProfiles.find((item) => item.id === event.target.value);
                      const chats = profile && Array.isArray(profile.chats) ? profile.chats : [];
                      setDraft((current) => ({ ...current, profile_id: event.target.value, receive_id: chats[0]?.chat_id || "" }));
                    }}>
                      {feishuProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profileLabel(profile, "feishu")}</option>)}
                    </select>
                  </label>
                  <label className="field">
                    <span>飞书群 / chat_id</span>
                    <input list="rule-feishu-chats" value={draft.receive_id || ""} onChange={(event) => setDraft((current) => ({ ...current, receive_id: event.target.value }))} placeholder="选择或粘贴 chat_id" />
                    <datalist id="rule-feishu-chats">
                      {draftChats.map((chat) => <option key={chat.chat_id} value={chat.chat_id}>{chatLabel(chat)}</option>)}
                    </datalist>
                  </label>
                </>
              ) : (
                <label className="field">
                  <span>微信配置</span>
                  <select value={draft.profile_id} onChange={(event) => setDraft((current) => ({ ...current, profile_id: event.target.value }))}>
                    {wechatProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profileLabel(profile, "wechat")}</option>)}
                  </select>
                </label>
              )}
            </div>
            <div className="inline-actions">
              <button className="btn" type="button" onClick={() => setDraft(null)}>取消</button>
              <button className="btn primary" type="button" onClick={confirmDraft}>确认</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function ThreadAuthorEditor({ config, setConfig }) {
  const rows = parseThreadAuthorWatches(config.thread_author_watches);
  const updateRows = (nextRows) => setConfig((current) => ({ ...current, thread_author_watches: formatThreadAuthorWatches(nextRows) }));
  const updateRow = (index, patch) => updateRows(rows.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)));
  const addRow = () =>
    updateRows([
      ...rows,
      {
        tid: config.default_tid || "",
        authorId: config.default_author_id || "",
        label: "",
        receiveId: "",
        appId: "",
        appSecret: "",
        idType: "chat_id",
      },
    ]);
  const deleteRow = (index) => updateRows(rows.filter((_, rowIndex) => rowIndex !== index));
  return (
    <div className="editor-card field-wide">
      <div className="editor-header">
        <div>
          <h3>帖内作者监听</h3>
          <p>拉取固定帖子新回复后按作者过滤；可为每个组合指定飞书群或独立机器人。</p>
        </div>
        <button className="small-btn primary" type="button" onClick={addRow}>
          +
        </button>
      </div>
      <div className="row-list">
        {rows.length ? (
          rows.map((row, index) => (
            <div className="thread-row" key={`thread-author-${index}`}>
              <label>
                <span>帖子 ID</span>
                <input value={row.tid || ""} onChange={(event) => updateRow(index, { tid: event.target.value })} />
              </label>
              <label>
                <span>作者 UID</span>
                <input value={row.authorId || ""} onChange={(event) => updateRow(index, { authorId: event.target.value })} />
              </label>
              <label>
                <span>备注</span>
                <input value={row.label || ""} onChange={(event) => updateRow(index, { label: event.target.value })} />
              </label>
              <label>
                <span>推送群 Receive ID</span>
                <input value={row.receiveId || ""} onChange={(event) => updateRow(index, { receiveId: event.target.value })} />
              </label>
              <label>
                <span>单独机器人 App ID</span>
                <input value={row.appId || ""} onChange={(event) => updateRow(index, { appId: event.target.value })} />
              </label>
              <label>
                <span>单独机器人 Secret</span>
                <input type="password" value={row.appSecret || ""} onChange={(event) => updateRow(index, { appSecret: event.target.value })} />
              </label>
              <label>
                <span>ID 类型</span>
                <select value={row.idType || "chat_id"} onChange={(event) => updateRow(index, { idType: event.target.value })}>
                  {["chat_id", "open_id", "union_id", "user_id"].map((option) => (
                    <option key={option} value={option}>
                      {option}
                    </option>
                  ))}
                </select>
              </label>
              <button className="small-btn" type="button" onClick={() => deleteRow(index)}>
                -
              </button>
            </div>
          ))
        ) : (
          <div className="empty-row">暂无条目。使用 thread_author 或 both 模式时，点击 + 添加帖子和作者。</div>
        )}
      </div>
    </div>
  );
}

function AiModelControls({ config, setConfig, options }) {
  const provider = config.ai_provider || "codex";
  const update = (key, value) => setConfig((current) => ({ ...current, [key]: value }));
  const modelOptions = options.aiModels?.[provider] || ["default", "auto"];
  const reasoningOptions = options.aiReasoning?.[provider] || ["default"];
  if (provider === "custom") {
    return (
      <>
        <Field config={config} setConfig={setConfig} spec={["ai_model", "模型", "text"]} />
        <Field config={config} setConfig={setConfig} spec={["ai_reasoning_effort", "思考强度", "text"]} />
      </>
    );
  }
  const modelValue = modelOptions.includes(config.ai_model) ? config.ai_model : "default";
  const reasoningValue = reasoningOptions.includes(config.ai_reasoning_effort) ? config.ai_reasoning_effort : "default";
  return (
    <>
      <label className="field">
        <span>模型</span>
        <select value={modelValue} onChange={(event) => update("ai_model", event.target.value)}>
          {modelOptions.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </label>
      <label className="field">
        <span>思考强度</span>
        <select value={reasoningValue} onChange={(event) => update("ai_reasoning_effort", event.target.value)}>
          {reasoningOptions.map((option) => (
            <option key={option} value={option}>
              {option}
            </option>
          ))}
        </select>
      </label>
    </>
  );
}

function AiScheduleTargets({ config, setConfig, pushTargets, feishuProfiles, wechatProfiles, onCreateScheduleTarget }) {
  const [draft, setDraft] = useState(null);
  const rawTargetIds = String(config.ai_schedule_target_ids || "").trim();
  const allTargetIds = pushTargets.map((target) => target.id).filter(Boolean);
  const selectedIds = rawTargetIds.toLowerCase() === "__none__"
    ? []
    : rawTargetIds
      ? rawTargetIds.split(/[,，;；\s]+/).filter(Boolean)
      : (allTargetIds[0] ? [allTargetIds[0]] : []);
  const saveSelected = (targetIds) => {
    setConfig((current) => ({ ...current, ai_schedule_target_ids: targetIds.length ? targetIds.join(",") : "__none__" }));
  };
  const removeAt = (index) => {
    saveSelected(selectedIds.filter((_, itemIndex) => itemIndex !== index));
  };
  const openAdd = () => {
    const channel = feishuProfiles.length || !wechatProfiles.length ? "feishu" : "wechat";
    const profile = channel === "wechat" ? wechatProfiles[0] : feishuProfiles[0];
    const chats = channel === "feishu" && profile && Array.isArray(profile.chats) ? profile.chats : [];
    setDraft({ channel, profile_id: profile?.id || "", receive_id: chats[0]?.chat_id || "" });
  };
  const draftProfile = draft?.channel === "wechat"
    ? wechatProfiles.find((profile) => profile.id === draft.profile_id) || wechatProfiles[0]
    : feishuProfiles.find((profile) => profile.id === draft?.profile_id) || feishuProfiles[0];
  const draftChats = draft?.channel === "feishu" && draftProfile && Array.isArray(draftProfile.chats) ? draftProfile.chats : [];
  const confirmDraft = () => {
    if (!draft) return;
    onCreateScheduleTarget(draft);
    setDraft(null);
  };
  return (
    <div className="editor-card field-wide">
      <div className="editor-header">
        <div>
          <h3>定时分析发送目标</h3>
          <p>定时分析只跑一次，结果发送到下面这些目标。</p>
        </div>
        <div className="button-row compact">
          <button className="small-btn primary" type="button" onClick={openAdd}>+</button>
          <button className="small-btn" type="button" onClick={() => saveSelected(selectedIds.slice(0, -1))}>-</button>
        </div>
      </div>
      <div className="schedule-target-list">
        {selectedIds.length ? selectedIds.map((targetId, index) => {
          const target = pushTargets.find((item) => item.id === targetId);
          return (
            <div className="schedule-target-row" key={`${targetId}-${index}`}>
              <span>{target ? targetLabel(target) : targetId}</span>
              <button className="small-btn" type="button" onClick={() => removeAt(index)}>-</button>
            </div>
          );
        }) : <span className="empty-inline">暂无定时发送目标，点击 + 添加。</span>}
      </div>
      {draft ? (
        <div className="modal-backdrop">
          <div className="modal-card">
            <div className="editor-header">
              <div>
                <h3>新增定时发送目标</h3>
                <p>飞书选择配置组和群；微信只选择配置组。</p>
              </div>
              <button className="small-btn" type="button" onClick={() => setDraft(null)}>×</button>
            </div>
            <div className="grid compact-form">
              <label className="field">
                <span>通道</span>
                <select value={draft.channel} onChange={(event) => {
                  const channel = event.target.value;
                  const profile = channel === "wechat" ? wechatProfiles[0] : feishuProfiles[0];
                  const chats = channel === "feishu" && profile && Array.isArray(profile.chats) ? profile.chats : [];
                  setDraft({ channel, profile_id: profile?.id || "", receive_id: chats[0]?.chat_id || "" });
                }}>
                  <option value="feishu">飞书</option>
                  <option value="wechat">微信</option>
                </select>
              </label>
              {draft.channel === "feishu" ? (
                <>
                  <label className="field">
                    <span>飞书配置</span>
                    <select value={draft.profile_id} onChange={(event) => {
                      const profile = feishuProfiles.find((item) => item.id === event.target.value);
                      const chats = profile && Array.isArray(profile.chats) ? profile.chats : [];
                      setDraft((current) => ({ ...current, profile_id: event.target.value, receive_id: chats[0]?.chat_id || "" }));
                    }}>
                      {feishuProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profileLabel(profile, "feishu")}</option>)}
                    </select>
                  </label>
                  <label className="field">
                    <span>飞书群 / chat_id</span>
                    <input list="schedule-feishu-chats" value={draft.receive_id || ""} onChange={(event) => setDraft((current) => ({ ...current, receive_id: event.target.value }))} placeholder="选择或粘贴 chat_id" />
                    <datalist id="schedule-feishu-chats">
                      {draftChats.map((chat) => <option key={chat.chat_id} value={chat.chat_id}>{chatLabel(chat)}</option>)}
                    </datalist>
                  </label>
                </>
              ) : (
                <label className="field">
                  <span>微信配置</span>
                  <select value={draft.profile_id} onChange={(event) => setDraft((current) => ({ ...current, profile_id: event.target.value }))}>
                    {wechatProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profileLabel(profile, "wechat")}</option>)}
                  </select>
                </label>
              )}
            </div>
            <div className="inline-actions">
              <button className="btn" type="button" onClick={() => setDraft(null)}>取消</button>
              <button className="btn primary" type="button" onClick={confirmDraft}>确认</button>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function App() {
  const [config, setConfig] = useState({});
  const [defaults, setDefaults] = useState({});
  const [options, setOptions] = useState({});
  const [status, setStatus] = useState({ running: false, pids: [] });
  const [logs, setLogs] = useState("");
  const [logOffset, setLogOffset] = useState(0);
  const [message, setMessage] = useState("");
  const [messageKind, setMessageKind] = useState("info");
  const [busy, setBusy] = useState(false);
  const [advancedJson, setAdvancedJson] = useState("");

  const channel = config.bot_channel || "feishu";
  const feishuProfiles = useMemo(() => parseProfiles(config, "feishu_bot_profiles"), [config]);
  const wechatProfiles = useMemo(() => parseProfiles(config, "wechat_bot_profiles"), [config]);
  const pushTargets = useMemo(() => parsePushTargets(config, feishuProfiles, wechatProfiles), [config, feishuProfiles, wechatProfiles]);
  const listenRules = useMemo(() => parseListenRules(config), [config]);
  const authorRows = useMemo(() => parseTargetList(config.watch_author_ids, config.default_author_id), [config.watch_author_ids, config.default_author_id]);
  const threadRows = useMemo(() => parseTargetList(config.preset_thread_ids, config.default_tid), [config.preset_thread_ids, config.default_tid]);
  const setStructured = (patch) => {
    setConfig((current) => {
      const currentFeishu = parseProfiles(current, "feishu_bot_profiles");
      const currentWechat = parseProfiles(current, "wechat_bot_profiles");
      const currentTargets = parsePushTargets(current, currentFeishu, currentWechat);
      const currentRules = parseListenRules(current);
      return applyStructuredConfig(current, {
        feishuProfiles: patch.feishuProfiles ?? currentFeishu,
        wechatProfiles: patch.wechatProfiles ?? currentWechat,
        pushTargets: patch.pushTargets ?? currentTargets,
        listenRules: patch.listenRules ?? currentRules,
      });
    });
  };
  const ensureRouteTarget = (draft) => {
    const channelValue = draft.channel === "wechat" ? "wechat" : "feishu";
    const profile = channelValue === "wechat"
      ? wechatProfiles.find((item) => item.id === draft.profile_id) || wechatProfiles[0]
      : feishuProfiles.find((item) => item.id === draft.profile_id) || feishuProfiles[0];
    const profileId = profile?.id || "";
    const receiveId = channelValue === "wechat" ? String(profile?.target_user_id || "").trim() : String(draft.receive_id || "").trim();
    if (!profileId || !receiveId) {
      setMessage(channelValue === "wechat" ? "微信配置缺少目标用户 ID" : "请选择飞书配置和飞书群");
      setMessageKind("error");
      return "";
    }
    let target = pushTargets.find((item) => (item.channel || "feishu") === channelValue && item.profile_id === profileId && item.receive_id === receiveId);
    const nextTargets = [...pushTargets];
    if (!target) {
      const chat = channelValue === "feishu" && Array.isArray(profile?.chats)
        ? profile.chats.find((item) => String(item.chat_id || item.id || "") === receiveId)
        : null;
      target = {
        id: ensureId("target", {}),
        label: channelValue === "feishu" ? String(chat?.name || chat?.title || receiveId) : profileLabel(profile, "wechat"),
        channel: channelValue,
        profile_id: profileId,
        receive_id: receiveId,
        id_type: channelValue === "wechat" ? "user_id" : profile?.id_type || "chat_id",
        default_author_id: config.default_author_id || "",
        default_tid: config.default_tid || "",
      };
      nextTargets.push(target);
      setStructured({ pushTargets: nextTargets });
    }
    return target.id;
  };
  const createScheduleTarget = (draft) => {
    setConfig((current) => {
      const currentFeishu = parseProfiles(current, "feishu_bot_profiles");
      const currentWechat = parseProfiles(current, "wechat_bot_profiles");
      const currentTargets = parsePushTargets(current, currentFeishu, currentWechat);
      const currentRules = parseListenRules(current);
      const channelValue = draft.channel === "wechat" ? "wechat" : "feishu";
      const profile = channelValue === "wechat"
        ? currentWechat.find((item) => item.id === draft.profile_id) || currentWechat[0]
        : currentFeishu.find((item) => item.id === draft.profile_id) || currentFeishu[0];
      const profileId = profile?.id || "";
      const receiveId = channelValue === "wechat" ? String(profile?.target_user_id || "").trim() : String(draft.receive_id || "").trim();
      if (!profileId || !receiveId) {
        setMessage(channelValue === "wechat" ? "微信配置缺少目标用户 ID" : "请选择飞书配置和飞书群");
        setMessageKind("error");
        return current;
      }
      let target = currentTargets.find((item) => (item.channel || "feishu") === channelValue && item.profile_id === profileId && item.receive_id === receiveId);
      const nextTargets = [...currentTargets];
      if (!target) {
        const chat = channelValue === "feishu" && Array.isArray(profile?.chats)
          ? profile.chats.find((item) => String(item.chat_id || item.id || "") === receiveId)
          : null;
        target = {
          id: ensureId("target", {}),
          label: channelValue === "feishu" ? String(chat?.name || chat?.title || receiveId) : profileLabel(profile, "wechat"),
          channel: channelValue,
          profile_id: profileId,
          receive_id: receiveId,
          id_type: channelValue === "wechat" ? "user_id" : profile?.id_type || "chat_id",
          default_author_id: current.default_author_id || "",
          default_tid: current.default_tid || "",
        };
        nextTargets.push(target);
      }
      const raw = String(current.ai_schedule_target_ids || "").trim();
      const selected = raw && raw.toLowerCase() !== "__none__"
        ? raw.split(/[,，;；\s]+/).filter(Boolean)
        : (!raw && currentTargets[0]?.id ? [currentTargets[0].id] : []);
      if (!selected.includes(target.id)) selected.push(target.id);
      const next = applyStructuredConfig(current, {
        feishuProfiles: currentFeishu,
        wechatProfiles: currentWechat,
        pushTargets: nextTargets,
        listenRules: currentRules,
      });
      setMessage("已添加定时发送目标");
      setMessageKind("success");
      return { ...next, ai_schedule_target_ids: selected.join(",") };
    });
  };
  const runningText = status.running ? `运行中 PID ${status.pids?.join(", ")}` : "未启动";

  const refresh = async () => {
    if (!api()) return;
    const boot = await api().bootstrap();
    const merged = normalizeConfig(boot.config, boot.defaults);
    setConfig(merged);
    setDefaults(boot.defaults);
    setOptions(boot.options || {});
    setStatus(boot.status);
    setLogs(boot.logs?.text || "");
    setLogOffset(boot.logs?.offset || 0);
    setAdvancedJson(JSON.stringify(merged, null, 2));
  };

  useEffect(() => {
    refresh();
    window.addEventListener("pywebviewready", refresh);
    const timer = window.setInterval(async () => {
      if (!api()) return;
      if (!Object.keys(defaults).length) {
        await refresh();
        return;
      }
      const stat = await api().status();
      if (stat?.status) setStatus(stat.status);
      const next = await api().read_logs(logOffset);
      if (next?.text) {
        setLogs((current) => `${current}${next.text}`.slice(-60000));
        setLogOffset(next.offset || 0);
      } else if (next?.offset !== undefined) {
        setLogOffset(next.offset);
      }
    }, 1200);
    return () => {
      window.removeEventListener("pywebviewready", refresh);
      window.clearInterval(timer);
    };
  }, [logOffset, defaults]);

  const run = async (label, fn) => {
    if (!api()) {
      setMessage("pywebview API 未就绪");
      setMessageKind("error");
      return;
    }
    setBusy(true);
    setMessage(`${label}中...`);
    setMessageKind("info");
    try {
      const result = await fn();
      if (!result?.ok) {
        setMessage((result?.errors || [result?.error || `${label}失败`]).join("\n"));
        setMessageKind("error");
      } else {
        setMessage(`${label}完成`);
        setMessageKind("success");
        if (result.config) {
          setConfig(normalizeConfig(result.config, defaults));
          setAdvancedJson(JSON.stringify(normalizeConfig(result.config, defaults), null, 2));
        }
        if (result.status) setStatus(result.status);
      }
    } catch (error) {
      setMessage(String(error?.message || error));
      setMessageKind("error");
    } finally {
      setBusy(false);
    }
  };

  const applyJson = () => {
    try {
      const parsed = JSON.parse(advancedJson);
      setConfig(normalizeConfig(parsed, defaults));
      setMessage("已应用高级 JSON，保存后生效");
      setMessageKind("success");
    } catch (error) {
      setMessage(`JSON 格式错误：${error.message}`);
      setMessageKind("error");
    }
  };

  const threadHelp = useMemo(
    () => [
      "先选择要配置的通道，再补齐机器人配置、NGA Cookie、用户/帖子和监听规则。",
      "监听规则里直接选择飞书群或微信账号；手动查询可以使用所有已保存的用户和帖子。",
      "飞书和微信配置会保留，切换下拉只影响当前展示和默认消息入口。",
    ],
    []
  );
  const queryChats = (profileId, searchQuery = "") => run("查询飞书群组", () => api().query_feishu_chats(config, profileId, searchQuery));
  return (
    <main>
      <aside>
        <div className="brand">
          <div className="logo">N</div>
          <div>
            <strong>NGA Wolf Watcher</strong>
            <span>Preview UI</span>
          </div>
        </div>
        <div className={`status ${status.running ? "online" : ""}`}>
          <Activity size={16} />
          <span>{runningText}</span>
        </div>
        <nav>
          <a href="#quick">快速开始</a>
          <a href="#channel">消息通道</a>
          <a href="#ai">AI 分析</a>
          <a href="#runtime">运行参数</a>
          <a href="#advanced">高级配置</a>
          <a href="#logs">日志</a>
        </nav>
      </aside>

      <section className="content">
        <header>
          <div>
            <h1>监听配置</h1>
            <p>旧版 GUI 仍可使用；这里是更简洁的 pywebview 预览版。</p>
          </div>
          <div className="actions">
            <ActionButton icon={Save} kind="primary" disabled={busy} onClick={() => run("保存配置", () => api().save_config(config))}>
              保存
            </ActionButton>
            <ActionButton icon={Play} kind="primary" disabled={busy || status.running} onClick={() => run("启动监听", () => api().start(config))}>
              启动
            </ActionButton>
            <ActionButton icon={CircleStop} disabled={busy || !status.running} onClick={() => run("停止监听", () => api().stop())}>
              停止
            </ActionButton>
          </div>
        </header>

        <Notice message={message} kind={messageKind} />

        <Section icon={ShieldCheck} title="快速开始" description="首次使用按顺序完成：通道配置、NGA Cookie、用户/帖子、监听规则。" defaultOpen>
          <div id="quick" className="grid">
            <ChannelPicker config={config} setConfig={setConfig} />
            {channel === "wechat" ? (
              <ProfileGroupEditor title="微信机器人配置组" kind="wechat" rows={wechatProfiles} setRows={(rows) => setStructured({ wechatProfiles: rows })} busy={busy} onQueryChats={queryChats} />
            ) : (
              <ProfileGroupEditor title="飞书机器人配置组" kind="feishu" rows={feishuProfiles} setRows={(rows) => setStructured({ feishuProfiles: rows })} busy={busy} onQueryChats={queryChats} />
            )}
            <Field config={config} setConfig={setConfig} spec={["default_author_id", "默认用户 ID", "text"]} />
            <Field config={config} setConfig={setConfig} spec={["default_tid", "默认帖子 ID", "text"]} />
            <Field config={config} setConfig={setConfig} spec={["nga_cookie", "NGA Cookie", "textarea"]} />
            <Field config={config} setConfig={setConfig} spec={["thread_watch_tail_count", "帖内扫描条数", "number"]} />
            <Field config={config} setConfig={setConfig} spec={["thread_watch_interval", "帖内扫描间隔秒", "number"]} />
            <TargetListEditor config={config} setConfig={setConfig} configKey="watch_author_ids" fallbackKey="default_author_id" title="用户 ID 列表" idLabel="用户 UID" />
            <TargetListEditor config={config} setConfig={setConfig} configKey="preset_thread_ids" fallbackKey="default_tid" title="帖子预设" idLabel="帖子 ID" />
            <ListenRuleEditor rows={listenRules} setRows={(rows) => setStructured({ listenRules: rows })} authorRows={authorRows} threadRows={threadRows} pushTargets={pushTargets} feishuProfiles={feishuProfiles} wechatProfiles={wechatProfiles} onEnsureRouteTarget={ensureRouteTarget} />
          </div>
          <div className="hint-list">
            {threadHelp.map((line) => (
              <span key={line}>{line}</span>
            ))}
          </div>
        </Section>

        <Section
          icon={MessageSquare}
          title="消息通道"
          description={`当前展示：${channelTitle(channel)}。切换快速开始里的通道下拉即可编辑另一种机器人配置。`}
          defaultOpen={false}
        >
          <div id="channel" className="grid">
            <ChannelPicker config={config} setConfig={setConfig} />
            {channel === "wechat" ? (
              <ProfileGroupEditor title="微信机器人配置组" kind="wechat" rows={wechatProfiles} setRows={(rows) => setStructured({ wechatProfiles: rows })} busy={busy} onQueryChats={queryChats} />
            ) : (
              <ProfileGroupEditor title="飞书机器人配置组" kind="feishu" rows={feishuProfiles} setRows={(rows) => setStructured({ feishuProfiles: rows })} busy={busy} onQueryChats={queryChats} />
            )}
          </div>
          <div className="inline-actions">
            <ActionButton icon={Database} disabled={busy} onClick={() => run("初始化已读", () => api().mark_seen(config))}>
              初始化已读
            </ActionButton>
            <ActionButton icon={QrCode} disabled={busy} onClick={() => run("微信扫码绑定", () => api().bind_wechat(config))}>
              微信扫码绑定
            </ActionButton>
          </div>
        </Section>

        <Section icon={Bot} title="AI 分析" description="AI 是公共配置，结果跟随当前消息通道发送。" defaultOpen={false}>
          <div id="ai" className="grid">
            {fieldGroups.ai.map((spec) => (
              <Field key={spec[0]} config={config} setConfig={setConfig} spec={spec} />
            ))}
            <AiModelControls config={config} setConfig={setConfig} options={options} />
            <AiScheduleTargets config={config} setConfig={setConfig} pushTargets={pushTargets} feishuProfiles={feishuProfiles} wechatProfiles={wechatProfiles} onCreateScheduleTarget={createScheduleTarget} />
          </div>
        </Section>

        <Section icon={Settings} title="运行参数" description="轮询、重试、免打扰等低频配置收在这里。" defaultOpen={false}>
          <div id="runtime" className="grid">
            {fieldGroups.runtime.map((spec) => (
              <Field key={spec[0]} config={config} setConfig={setConfig} spec={spec} />
            ))}
          </div>
        </Section>

        <Section icon={TerminalSquare} title="高级配置" description="保留全部旧配置字段，适合排查或迁移。" defaultOpen={false}>
          <div id="advanced" className="json-panel">
            <textarea value={advancedJson} onChange={(event) => setAdvancedJson(event.target.value)} rows={18} />
            <div className="inline-actions">
              <ActionButton icon={Check} onClick={applyJson}>
                应用 JSON
              </ActionButton>
              <ActionButton icon={RefreshCw} onClick={refresh}>
                重新读取
              </ActionButton>
              <ActionButton icon={FolderOpen} onClick={() => run("打开数据目录", () => api().open_data_dir())}>
                数据目录
              </ActionButton>
            </div>
          </div>
        </Section>

        <Section icon={TerminalSquare} title="日志" description={status.logPath || ""} defaultOpen>
          <pre id="logs" className="logs">{logs || "暂无日志"}</pre>
        </Section>
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
