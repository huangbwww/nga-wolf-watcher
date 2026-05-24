import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
  AlertTriangle,
  Bot,
  Check,
  ChevronDown,
  CircleStop,
  Database,
  Edit3,
  FolderOpen,
  ListChecks,
  MessageSquare,
  Plus,
  Play,
  QrCode,
  RefreshCw,
  Save,
  Search,
  Settings,
  ShieldCheck,
  TerminalSquare,
  Trash2,
  Users,
  X,
} from "lucide-react";
import "./styles.css";

const api = () => window.pywebview?.api;
let closingFlag = false;
const isClosing = () => closingFlag;
const hasApiMethod = (method) => typeof api()?.[method] === "function";
const DEFAULT_AI_ANALYSIS_PROMPT = "根据最新的 NGA 回复历史、我目前的持仓信息和观察列表，并实时查询公开 A 股行情信息，分析盘面变化、机会与风险，给出接下来需要重点观察的方向和操作建议。";
const DEFAULT_SCHEDULE_WINDOWS = "weekday:09:30-11:30,13:00-15:00";
const WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"];
const QUIET_POLICY_OPTIONS = {
  ignore: "忽略新回复",
  defer: "暂存并在免打扰结束后汇总推送",
};

const fieldGroups = {
  common: [
    ["nga_cookie", "NGA Cookie", "textarea"],
    ["watch_mode", "监听模式", "select", ["author", "thread_author", "both"]],
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
    ["thread_watch_tail_count", "帖内扫描条数", "number"],
    ["thread_watch_interval", "帖内扫描间隔秒", "number"],
    ["interval", "轮询间隔秒", "number"],
    ["jitter", "用户回复随机抖动秒", "number"],
    ["retries", "重试次数", "number"],
    ["retry_initial_delay", "重试初始等待秒", "number"],
    ["retry_delay", "重试递增秒", "number"],
    ["nga_request_min_interval", "NGA 请求最小间隔秒", "number"],
  ],
  close: [
    ["web_close_behavior", "关闭按钮默认行为", "select", ["ask", "minimize", "exit"]],
  ],
};

function normalizeConfig(config = {}, defaults = {}) {
  const merged = { ...defaults, ...config };
  if (!String(merged.ai_auto_analysis_prompt || "").trim()) merged.ai_auto_analysis_prompt = DEFAULT_AI_ANALYSIS_PROMPT;
  if (!String(merged.ai_schedule_prompt || "").trim()) merged.ai_schedule_prompt = DEFAULT_AI_ANALYSIS_PROMPT;
  if (!String(merged.ai_schedule_windows || "").trim()) merged.ai_schedule_windows = DEFAULT_SCHEDULE_WINDOWS;
  if (!String(merged.web_close_behavior || "").trim()) merged.web_close_behavior = "ask";
  return merged;
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
  } else {
    next.feishu_app_id = "";
    next.feishu_app_secret = "";
    next.feishu_id_type = "chat_id";
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
  } else {
    next.wechat_bot_token = "";
    next.wechat_bot_base_url = "https://ilinkai.weixin.qq.com";
    next.wechat_bot_cdn_base_url = "https://novac2c.cdn.weixin.qq.com/c2c";
    next.wechat_bot_target_user_id = "";
    next.wechat_bot_allowed_user_ids = "";
    next.wechat_bot_poll_timeout_ms = "35000";
    next.wechat_bot_account_id = "default";
    next.wechat_bot_route_tag = "";
  }
  const firstFeishuTarget = pushTargets.find((target) => (target.channel || "feishu") === "feishu");
  next.feishu_receive_id = firstFeishuTarget?.receive_id || "";
  if (firstFeishuTarget?.id_type) next.feishu_id_type = firstFeishuTarget.id_type;
  const validTargetIds = new Set(pushTargets.map((target) => String(target.id || "").trim()).filter(Boolean));
  const rawScheduleTargetIds = String(next.ai_schedule_target_ids || "").trim();
  const scheduleTargetIds = rawScheduleTargetIds.toLowerCase() === "__none__" ? [] : rawScheduleTargetIds
    .split(/[,，;\s]+/)
    .map((item) => item.trim())
    .filter((item) => item && validTargetIds.has(item));
  next.ai_schedule_target_ids = rawScheduleTargetIds.toLowerCase() === "__none__" ? "__none__" : (scheduleTargetIds.length ? scheduleTargetIds.join(",") : (pushTargets.length ? "" : "__none__"));
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
  const splitLegacyTargets = (value) => {
    const lines = String(value || "").split(/[\r\n]+/).map((item) => item.trim()).filter(Boolean);
    if (lines.length > 1) return lines;
    const single = lines[0] || "";
    if (!single) return [];
    const legacyParts = single.split(/[,，;；]+/).map((item) => item.trim()).filter(Boolean);
    if (legacyParts.length <= 1) return [single];
    const looksLikeId = (item) => /^[A-Za-z]?\d+$/.test(String(item || "").split("=")[0].trim());
    return legacyParts.every(looksLikeId) ? legacyParts : [single];
  };
  const items = text ? splitLegacyTargets(text) : [];
  if (!items.length && fallback) items.push(String(fallback));
  for (const item of items) {
    const part = item.trim();
    if (!part) continue;
    const [visiblePart] = part.split("|");
    const [idPart, ...labelParts] = visiblePart.split("=");
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

function Field({ config, setConfig, spec, hint = null }) {
  const [key, label, type, options] = spec;
  let value = config[key] ?? "";
  if ((key === "ai_auto_analysis_prompt" || key === "ai_schedule_prompt") && !String(value || "").trim()) {
    value = DEFAULT_AI_ANALYSIS_PROMPT;
  }
  const update = (next) => setConfig((current) => ({ ...current, [key]: next }));
  if (key === "ai_schedule_windows") {
    return <ScheduleWindowField config={config} setConfig={setConfig} label={label} hint={hint} />;
  }
  const hintNode = hint ? <div className="field-alert">{hint}</div> : null;
  if (type === "textarea") {
    return (
      <label className={`field field-wide ${hint ? "validation-target-active" : ""}`} data-validation-target={key}>
        {hintNode}
        <span>{label}</span>
        <textarea value={value || ""} onChange={(event) => update(event.target.value)} rows={key === "nga_cookie" ? 4 : 3} />
      </label>
    );
  }
  if (type === "select") {
    const optionLabel = (option) => {
      if (key === "web_close_behavior") return { ask: "每次询问", minimize: "默认隐藏到托盘", exit: "默认退出程序" }[option] || option;
      return option;
    };
    return (
      <label className={`field ${hint ? "validation-target-active" : ""}`} data-validation-target={key}>
        {hintNode}
        <span>{label}</span>
        <select value={value || options[0]} onChange={(event) => update(event.target.value)}>
          {options.map((option) => (
            <option key={option} value={option}>
              {optionLabel(option)}
            </option>
          ))}
        </select>
      </label>
    );
  }
  if (type === "checkbox") {
    return (
      <label className={`switch-row ${hint ? "validation-target-active" : ""}`} data-validation-target={key}>
        {hintNode}
        <span>{label}</span>
        <input type="checkbox" checked={Boolean(value)} onChange={(event) => update(event.target.checked)} aria-label={label} />
      </label>
    );
  }
  return (
    <label className={`field ${hint ? "validation-target-active" : ""}`} data-validation-target={key}>
      {hintNode}
      <span>{label}</span>
      <input type={type || "text"} value={value || ""} onChange={(event) => update(event.target.value)} />
    </label>
  );
}

function ScheduleWindowField({ config, setConfig, label, hint = null }) {
  const parsed = parseScheduleWindows(config.ai_schedule_windows || DEFAULT_SCHEDULE_WINDOWS);
  const save = (nextDays, nextRanges) => {
    const expression = formatScheduleWindows(nextDays, nextRanges);
    setConfig((configCurrent) => ({
      ...configCurrent,
      ai_schedule_window_mode: "a_share",
      ai_schedule_windows: expression,
    }));
  };
  const toggleDay = (day) => {
    const days = parsed.days.includes(day) ? parsed.days.filter((item) => item !== day) : [...parsed.days, day].sort((a, b) => a - b);
    save(days, parsed.ranges);
  };
  const updateRange = (index, patch) => {
    const ranges = parsed.ranges.map((range, itemIndex) => (itemIndex === index ? { ...range, ...patch } : range));
    save(parsed.days, ranges);
  };
  const addRange = () => save(parsed.days, [...parsed.ranges, { start: "09:30", end: "10:30" }]);
  const removeRange = (index) => save(parsed.days, parsed.ranges.filter((_, itemIndex) => itemIndex !== index));
  return (
    <div className={`field field-wide schedule-window-picker ${hint ? "validation-target-active" : ""}`} data-validation-target="ai_schedule_windows">
      {hint ? <div className="field-alert">{hint}</div> : null}
      <span>{label}</span>
      <div className="weekday-picker">
        {WEEKDAYS.map((name, index) => (
          <label className="day-chip" key={name}>
            <input type="checkbox" checked={parsed.days.includes(index)} onChange={() => toggleDay(index)} />
            <span>{name}</span>
          </label>
        ))}
      </div>
      <div className="time-range-list">
        <div className="range-header">
          <strong>每天时间段</strong>
          <IconButton icon={Plus} label="添加时间段" kind="primary" onClick={addRange} />
        </div>
        {parsed.ranges.map((range, index) => (
          <div className="time-range-row" key={`${range.start}-${range.end}-${index}`}>
            <label>
              <span>开始</span>
              <input type="time" value={range.start} onChange={(event) => updateRange(index, { start: event.target.value })} />
            </label>
            <label>
              <span>结束</span>
              <input type="time" value={range.end} onChange={(event) => updateRange(index, { end: event.target.value })} />
            </label>
            <IconButton icon={Trash2} label="删除时间段" kind="danger" onClick={() => removeRange(index)} />
          </div>
        ))}
        {!parsed.ranges.length ? <div className="empty-row">暂无时间段，点击 + 添加。</div> : null}
      </div>
      <div className="window-preview">
        当前表达式：<code>{formatScheduleWindows(parsed.days, parsed.ranges)}</code>
      </div>
    </div>
  );
}

function NgaCookieField({ config, setConfig, hint = null, busy = false, status = null, onCheck }) {
  const update = (next) => setConfig((current) => ({ ...current, nga_cookie: next }));
  return (
    <div className={`field field-wide cookie-field ${hint ? "validation-target-active" : ""}`} data-validation-target="nga_cookie">
      {hint ? <div className="field-alert">{hint}</div> : null}
      <div className="field-header-row">
        <span>NGA Cookie</span>
        <button className="btn slim" type="button" disabled={busy} onClick={onCheck}>
          <Check size={15} />
          检测 Cookie
        </button>
      </div>
      <textarea value={config.nga_cookie || ""} onChange={(event) => update(event.target.value)} rows={4} />
      {status?.text ? <div className={`notice ${status.kind || "info"} compact`}>{status.text}</div> : null}
    </div>
  );
}

function parseDayExpr(raw) {
  const value = String(raw || "").trim().toLowerCase();
  if (["weekday", "weekdays", "mon-fri"].includes(value)) return [0, 1, 2, 3, 4];
  const names = { mon: 0, tue: 1, wed: 2, thu: 3, fri: 4, sat: 5, sun: 6 };
  const dayFrom = (item) => {
    if (names[item] !== undefined) return names[item];
    const number = Number.parseInt(item, 10);
    return Number.isFinite(number) ? Math.min(6, Math.max(0, number - 1)) : null;
  };
  if (value.includes("-")) {
    const [left, right] = value.split("-", 2).map((item) => item.trim());
    const start = dayFrom(left);
    const end = dayFrom(right);
    if (start === null || end === null) return [];
    const days = [];
    for (let day = start; day <= end; day += 1) days.push(day);
    return days;
  }
  const single = dayFrom(value);
  return single === null ? [] : [single];
}

function parseScheduleWindows(raw) {
  const text = String(raw || DEFAULT_SCHEDULE_WINDOWS).trim() || DEFAULT_SCHEDULE_WINDOWS;
  const days = new Set();
  const rangeMap = new Map();
  for (const block of text.split(";").map((item) => item.trim()).filter(Boolean)) {
    if (!block.includes(":")) continue;
    const [dayExpr, ...rangeParts] = block.split(":");
    for (const day of parseDayExpr(dayExpr)) days.add(day);
    for (const range of rangeParts.join(":").split(",").map((item) => item.trim()).filter(Boolean)) {
      const [start, end] = range.split("-", 2).map((item) => item.trim());
      if (/^\d{2}:\d{2}$/.test(start || "") && /^\d{2}:\d{2}$/.test(end || "")) {
        rangeMap.set(`${start}-${end}`, { start, end });
      }
    }
  }
  return {
    days: days.size ? [...days].sort((a, b) => a - b) : [0, 1, 2, 3, 4],
    ranges: rangeMap.size ? [...rangeMap.values()] : [{ start: "09:30", end: "11:30" }, { start: "13:00", end: "15:00" }],
  };
}

function formatDayExpression(days) {
  const normalized = [...new Set(days)].sort((a, b) => a - b);
  if (normalized.join(",") === "0,1,2,3,4") return "weekday";
  if (!normalized.length) return "weekday";
  const ranges = [];
  let start = normalized[0];
  let previous = normalized[0];
  for (let index = 1; index <= normalized.length; index += 1) {
    const current = normalized[index];
    if (current === previous + 1) {
      previous = current;
      continue;
    }
    ranges.push(start === previous ? String(start + 1) : `${start + 1}-${previous + 1}`);
    start = current;
    previous = current;
  }
  return ranges.join(";");
}

function formatScheduleWindows(days, ranges) {
  const rangeText = ranges
    .filter((range) => /^\d{2}:\d{2}$/.test(range.start || "") && /^\d{2}:\d{2}$/.test(range.end || ""))
    .map((range) => `${range.start}-${range.end}`)
    .join(",");
  const dayExpr = formatDayExpression(days);
  if (!rangeText) return `${dayExpr}:`;
  return dayExpr.split(";").map((day) => `${day}:${rangeText}`).join(";");
}

function QuietHoursControls({ config, setConfig, hint = null }) {
  const update = (patch) => setConfig((current) => ({ ...current, ...patch }));
  const startDay = String(config.quiet_start_day ?? "5");
  const endDay = String(config.quiet_end_day ?? "0");
  const policy = String(config.quiet_policy || "ignore");
  return (
    <div id="quiet" className={`grid ${hint ? "validation-target-active validation-panel" : ""}`} data-validation-target="quiet-hours">
      {hint ? <div className="field-alert field-wide">{hint}</div> : null}
      <Field config={config} setConfig={setConfig} spec={["quiet_hours_enabled", "启用免打扰", "checkbox"]} />
      <label className="field">
        <span>免打扰期间的新回复</span>
        <select value={policy} onChange={(event) => update({ quiet_policy: event.target.value })}>
          {Object.entries(QUIET_POLICY_OPTIONS).map(([value, label]) => (
            <option key={value} value={value}>{label}</option>
          ))}
        </select>
      </label>
      <div className="field field-wide quiet-window-card">
        <span>免打扰时段</span>
        <div className="quiet-time-grid">
          <label>
            <span>开始星期</span>
            <select value={startDay} onChange={(event) => update({ quiet_start_day: event.target.value })}>
              {WEEKDAYS.map((name, index) => <option key={name} value={String(index)}>{name}</option>)}
            </select>
          </label>
          <label>
            <span>开始时间</span>
            <input type="time" value={String(config.quiet_start_time || "00:00")} onChange={(event) => update({ quiet_start_time: event.target.value })} />
          </label>
          <label>
            <span>结束星期</span>
            <select value={endDay} onChange={(event) => update({ quiet_end_day: event.target.value })}>
              {WEEKDAYS.map((name, index) => <option key={name} value={String(index)}>{name}</option>)}
            </select>
          </label>
          <label>
            <span>结束时间</span>
            <input type="time" value={String(config.quiet_end_time || "00:00")} onChange={(event) => update({ quiet_end_time: event.target.value })} />
          </label>
        </div>
        <p className="field-hint">
          例如：周五 18:00 到周一 08:00。忽略表示免打扰期间新回复不推送；暂存表示免打扰结束后汇总推送。
        </p>
      </div>
    </div>
  );
}

function CloseConfirmModal({ step, request, setRequest, onCancel, onContinue, onSaveAndContinue, onFinish }) {
  if (!step || !request) return null;
  if (step === "background") {
    return (
      <div className="modal-backdrop">
        <div className="modal-card small">
          <div className="editor-header">
            <div>
              <h3>关闭窗口</h3>
              <p>可以把窗口隐藏到右下角托盘继续运行，也可以真正退出程序。</p>
            </div>
            <IconButton icon={X} label="取消关闭" onClick={onCancel} />
          </div>
          <label className="remember-row">
            <input type="checkbox" checked={Boolean(request.remember)} onChange={(event) => setRequest((current) => ({ ...current, remember: event.target.checked }))} />
            <span>记住这次选择，之后可在设置里修改</span>
          </label>
          <div className="inline-actions">
            <button className="btn" type="button" onClick={onCancel}>取消</button>
            <button className="btn" type="button" onClick={() => onContinue({ step: "dirty", action: "exit" })}>退出程序</button>
            <button className="btn primary" type="button" onClick={() => onFinish("minimize", Boolean(request.remember))}>隐藏到托盘</button>
          </div>
          <p className="field-hint">如果检测到监听仍在运行，会在退出前再次提醒你停止。</p>
        </div>
      </div>
    );
  }
  if (step === "dirty") {
    return (
      <div className="modal-backdrop">
        <div className="modal-card small">
          <div className="editor-header">
            <div>
              <h3>有未保存配置</h3>
              <p>退出前建议先保存当前配置。隐藏到托盘不会检查未保存配置。</p>
            </div>
            <IconButton icon={X} label="取消关闭" onClick={onCancel} />
          </div>
          <div className="inline-actions">
            <button className="btn" type="button" onClick={onCancel}>返回</button>
            <button className="btn" type="button" onClick={() => onContinue({ step: "running", dirty: false })}>放弃修改并继续</button>
            <button className="btn primary" type="button" onClick={onSaveAndContinue}>保存并继续</button>
          </div>
        </div>
      </div>
    );
  }
  if (step === "running") {
    const pids = Array.isArray(request.pids) && request.pids.length ? ` PID ${request.pids.join(", ")}` : "";
    return (
      <div className="modal-backdrop">
        <div className="modal-card small">
          <div className="editor-header">
            <div>
              <h3>监听仍在运行</h3>
              <p>检测到监听进程仍在运行{pids}。退出程序前需要先停止监听；隐藏到托盘会保持监听继续运行。</p>
            </div>
            <IconButton icon={X} label="取消关闭" onClick={onCancel} />
          </div>
          <div className="inline-actions">
            <button className="btn" type="button" onClick={onCancel}>返回</button>
            <button className="btn primary" type="button" onClick={() => onContinue({ step: "final", running: false, stopOnExit: true })}>停止监听并退出</button>
          </div>
        </div>
      </div>
    );
  }
  if (step === "final") {
    return null;
  }
  return null;
}

const FEISHU_ID_TYPE_OPTIONS = ["chat_id", "open_id", "user_id", "union_id"];
const CONFIG_SECTION_LABELS = {
  quick: "快速开始",
  channel: "消息通道",
  ai: "AI 分析",
  quiet: "免打扰",
  runtime: "运行参数",
  advanced: "高级配置",
};

function feishuIdTypeLabel(value) {
  return {
    chat_id: "群聊 chat_id（推荐）",
    open_id: "单个用户 open_id",
    user_id: "单个用户 user_id",
    union_id: "单个用户 union_id",
  }[value] || value;
}

function validationSectionForError(error) {
  const text = String(error || "");
  if (/AI|Codex|Claude|Custom|模型|思考|定时|飞书最大字符/.test(text)) return "ai";
  if (/免打扰/.test(text)) return "quiet";
  if (/轮询|重试|扫描|请求|缓存|超时|间隔|抖动|数字/.test(text)) return "runtime";
  if (/飞书|Feishu|Receive ID|chat_id|微信|WeChat|Bot Token|机器人|发送目标|通道/.test(text)) return "quick";
  if (/Cookie|NGA|监听|帖子|用户|作者|tid|uid|规则|ID/.test(text)) return "quick";
  return "quick";
}

function validationTargetForError(error) {
  const text = String(error || "");
  const runtimeMap = [
    ["轮询间隔", "interval"],
    ["用户回复随机抖动", "jitter"],
    ["重试次数", "retries"],
    ["重试初始等待", "retry_initial_delay"],
    ["重试延迟", "retry_delay"],
    ["NGA 请求最小间隔", "nga_request_min_interval"],
    ["NGA 短缓存", "nga_cache_ttl"],
    ["帖内扫描条数", "thread_watch_tail_count"],
    ["帖内扫描间隔", "thread_watch_interval"],
    ["请求超时", "timeout"],
    ["AI 超时", "ai_timeout"],
    ["AI 定时间隔", "ai_schedule_interval_minutes"],
    ["AI 飞书最大字符", "ai_max_feishu_chars"],
    ["微信长轮询超时", "wechat-profiles"],
  ];
  for (const [label, target] of runtimeMap) {
    if (text.includes(label)) return target;
  }
  if (/NGA Cookie/.test(text)) return "nga_cookie";
  if (/飞书配置|Feishu App ID|Feishu App Secret|飞书 App ID|飞书 App Secret|飞书机器人缺少 App ID|飞书机器人配置组/.test(text)) return "feishu-profiles";
  if (/微信Bot配置|微信 Bot 配置|微信 Bot Token|微信目标用户 ID|微信机器人缺少 Token|微信配置/.test(text)) return "wechat-profiles";
  if (/Receive ID|chat_id|发送目标|通道/.test(text)) return "listen-rules";
  if (/监听用户 ID 列表|配置一条用户 ID|用户 ID|用户主页/.test(text)) return "watch_author_ids";
  if (/帖子预设 ID 列表|配置一条帖子 ID|帖子预设|帖子/.test(text)) return "preset_thread_ids";
  if (/缺少可用的监听配置|监听规则|帖内作者|tid:uid|作者规则|至少需要选择一个发送目标/.test(text)) return "listen-rules";
  if (/免打扰/.test(text)) return "quiet-hours";
  if (/AI|Codex|Claude|Custom|模型|思考/.test(text)) return "ai-settings";
  if (/定时/.test(text)) return "ai-schedule-targets";
  return "quick-start";
}

function validationChannelForError(error) {
  const text = String(error || "");
  if (/微信|WeChat|wechat/.test(text)) return "wechat";
  if (/飞书|Feishu|Receive ID|chat_id|feishu/.test(text)) return "feishu";
  return "";
}

function Section({ icon: Icon, title, description, children, defaultOpen = true, sectionId = "", hint = null }) {
  return (
    <details className={`section ${hint ? "needs-attention" : ""}`} id={sectionId ? `section-${sectionId}` : undefined} open={defaultOpen || Boolean(hint)}>
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
      <div className="section-body">
        {hint ? <div className="inline-alert error">{hint}</div> : null}
        {children}
      </div>
    </details>
  );
}

function ActionButton({ icon: Icon, children, onClick, kind = "secondary", disabled = false }) {
  return (
    <button className={`btn ${kind}`} type="button" onClick={onClick} disabled={disabled}>
      <Icon size={16} />
      {children}
    </button>
  );
}

function IconButton({ icon: Icon, label, onClick, kind = "default", disabled = false }) {
  return (
    <button className={`icon-btn ${kind}`} type="button" onClick={onClick} disabled={disabled} title={label} aria-label={label}>
      <Icon size={16} />
    </button>
  );
}

function Notice({ message, kind = "info" }) {
  if (!message) return null;
  return <div className={`notice ${kind}`}>{message}</div>;
}

function ChannelPicker({ config, setConfig, channel, onChannelChange }) {
  const value = channel || (config.bot_channel === "wechat" ? "wechat" : "feishu");
  const update = (nextChannel) => {
    onChannelChange?.(nextChannel);
    setConfig((current) => ({ ...current, bot_channel: nextChannel }));
  };
  return (
    <div className="channel-switch-card field-wide">
      <div>
        <span className="eyebrow">当前配置通道</span>
        <strong>{value === "wechat" ? "微信 Bot" : "飞书 Bot"}</strong>
        <p>这里只切换正在编辑的机器人配置；监听规则里再选择具体推送到哪个群或微信。</p>
      </div>
      <div className="segmented" role="group" aria-label="当前配置通道">
        <button className={value === "feishu" ? "active" : ""} type="button" onClick={() => update("feishu")}>
          飞书
        </button>
        <button className={value === "wechat" ? "active" : ""} type="button" onClick={() => update("wechat")}>
          微信
        </button>
      </div>
    </div>
  );
}

function SetupOverview({ channel, authorCount, threadCount, ruleCount, profileCount }) {
  const steps = [
    { icon: MessageSquare, title: "通道", value: `${channel === "wechat" ? "微信" : "飞书"} ${profileCount || 0} 组` },
    { icon: Database, title: "Cookie", value: "用于读取 NGA" },
    { icon: Users, title: "目标", value: `${authorCount || 0} 用户 / ${threadCount || 0} 帖子` },
    { icon: ListChecks, title: "规则", value: `${ruleCount || 0} 条监听` },
  ];
  return (
    <div className="setup-strip">
      {steps.map(({ icon: Icon, title, value }) => (
        <div className="setup-step" key={title}>
          <Icon size={18} />
          <div>
            <strong>{title}</strong>
            <span>{value}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

function confirmRemove(label = "这个条目") {
  return window.confirm(`确定删除${label}吗？`);
}

function TargetListEditor({ config, setConfig, configKey, fallbackKey, title, idLabel, hint = null }) {
  const [draft, setDraft] = useState(null);
  const rows = parseTargetList(config[configKey], config[fallbackKey]);
  const updateRows = (nextRows) => setConfig((current) => {
    const formatted = formatTargetList(nextRows);
    const firstId = String(nextRows.find((row) => String(row.id || "").trim())?.id || "").trim();
    return { ...current, [configKey]: formatted, ...(fallbackKey ? { [fallbackKey]: firstId } : {}) };
  });
  const updateRow = (index, patch) => updateRows(rows.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)));
  const openAdd = () => setDraft({ index: -1, id: "", label: "", error: "" });
  const openEdit = (index) => setDraft({ index, id: rows[index]?.id || "", label: rows[index]?.label || "", error: "" });
  const confirmDraft = () => {
    if (!draft) return;
    const id = String(draft.id || "").trim();
    if (!id) {
      setDraft((current) => ({ ...current, error: "请填写 ID。" }));
      return;
    }
    if (rows.some((row, index) => row.id === id && index !== draft.index)) {
      setDraft((current) => ({ ...current, error: "这个 ID 已经在列表里。" }));
      return;
    }
    if (draft.index >= 0) updateRow(draft.index, { id, label: String(draft.label || "").trim() });
    else updateRows([...rows, { id, label: String(draft.label || "").trim() }]);
    setDraft(null);
  };
  const deleteRow = (index) => {
    if (!confirmRemove(rows[index]?.label || rows[index]?.id || "这个条目")) return;
    updateRows(rows.filter((_, rowIndex) => rowIndex !== index));
  };
  return (
    <div className={`editor-card field-wide ${hint ? "validation-target-active" : ""}`} data-validation-target={configKey}>
      {hint ? <div className="field-alert">{hint}</div> : null}
      <div className="editor-header">
        <div>
          <h3>{title}</h3>
          <p>ID 和备注（非必填）分开填写，点击 + 后在弹窗里添加。</p>
        </div>
        <IconButton icon={Plus} label={`添加${title}`} kind="primary" onClick={openAdd} />
      </div>
      <div className="row-list">
        {rows.length ? (
          rows.map((row, index) => (
            <div className="list-row" key={`${configKey}-${index}`}>
              <div>
                <strong>{row.label || row.id}</strong>
                <span>{row.label ? row.id : idLabel}</span>
              </div>
              <IconButton icon={Edit3} label="编辑" kind="ghost" onClick={() => openEdit(index)} />
              <IconButton icon={Trash2} label="删除" kind="danger" onClick={() => deleteRow(index)} />
            </div>
          ))
        ) : (
          <div className="empty-row">暂无条目，点击 + 添加。</div>
        )}
      </div>
      {draft ? (
        <div className="modal-backdrop">
          <div className="modal-card">
            <div className="editor-header">
              <div>
                <h3>{draft.index >= 0 ? "编辑条目" : `添加${title}`}</h3>
                <p>保存后会自动写回兼容旧版的配置格式。</p>
              </div>
              <IconButton icon={X} label="关闭" onClick={() => setDraft(null)} />
            </div>
            <div className="grid compact-form">
              <label className="field">
                <span>{idLabel}</span>
                <input value={draft.id || ""} onChange={(event) => setDraft((current) => ({ ...current, id: event.target.value }))} />
              </label>
              <label className="field">
                <span>备注（非必填）</span>
                <input value={draft.label || ""} onChange={(event) => setDraft((current) => ({ ...current, label: event.target.value }))} />
              </label>
            </div>
            {draft.error ? <div className="notice error compact">{draft.error}</div> : null}
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

function ProfileGroupEditor({ title, kind, rows, setRows, busy, onQueryChats, onQueryDraftChats, hint = null }) {
  const [draft, setDraft] = useState(null);
  const [draftChatStatus, setDraftChatStatus] = useState(null);
  const emptyRow = () => kind === "feishu"
    ? { id: ensureId("feishu", {}), label: "", app_id: "", app_secret: "", id_type: "chat_id", chats: [] }
    : { id: ensureId("wechat", {}), label: "", token: "", base_url: "https://ilinkai.weixin.qq.com", cdn_base_url: "https://novac2c.cdn.weixin.qq.com/c2c", target_user_id: "", allowed_user_ids: "", poll_timeout_ms: "35000", account_id: "default", route_tag: "" };
  const openAdd = () => {
    setDraft({ index: -1, row: emptyRow() });
    setDraftChatStatus(null);
  };
  const openEdit = (index) => {
    setDraft({ index, row: { ...rows[index] } });
    setDraftChatStatus(null);
  };
  const updateRow = (index, patch) => setRows(rows.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)));
  const updateDraft = (patch) => setDraft((current) => ({ ...current, row: { ...current.row, ...patch } }));
  const queryDraftChats = async () => {
    if (!draft || kind !== "feishu" || !onQueryDraftChats) return;
    setDraftChatStatus({ kind: "info", text: "正在查询可用群..." });
    try {
      const result = await onQueryDraftChats(draft.row);
      if (!result?.ok) {
        setDraftChatStatus({ kind: "error", text: (result?.errors || [result?.error || "查询群组失败"]).join("\n") });
        return;
      }
      const chats = Array.isArray(result.chats) ? result.chats : [];
      updateDraft({ chats });
      setDraftChatStatus({ kind: chats.length ? "success" : "info", text: chats.length ? `已查询到 ${chats.length} 个群，确认后可在监听规则里选择。` : "没有查到可用群。请确认 App 已加入目标群后再查询。" });
    } catch (error) {
      setDraftChatStatus({ kind: "error", text: String(error?.message || error) });
    }
  };
  const deleteRow = (index) => {
    if (!confirmRemove(profileLabel(rows[index] || {}, kind))) return;
    setRows(rows.filter((_, rowIndex) => rowIndex !== index));
  };
  const confirmDraft = () => {
    if (!draft) return;
    if (kind === "feishu" && (!Array.isArray(draft.row.chats) || !draft.row.chats.length) && draftChatStatus?.text !== "当前还没有保存可用群。可以先点“查询可用群”，也可以稍后在配置列表里查询。") {
      setDraftChatStatus({ kind: "info", text: "当前还没有保存可用群。可以先点“查询可用群”，也可以稍后在配置列表里查询。" });
      return;
    }
    const row = { ...draft.row, id: ensureId(kind, draft.row) };
    if (draft.index >= 0) updateRow(draft.index, row);
    else setRows([...rows, row]);
    setDraft(null);
  };
  return (
    <div className={`editor-card field-wide ${hint ? "validation-target-active" : ""}`} data-validation-target={`${kind}-profiles`}>
      {hint ? <div className="field-alert">{hint}</div> : null}
      <div className="editor-header">
        <div>
          <h3>{title}</h3>
          <p>{kind === "feishu" ? "每组 App ID / Secret 独立缓存可见群组；新增时可以先查询群，避免后续监听规则无群可选。" : "每组微信 Token 独立保存目标用户和账号标识；点击编辑维护配置。"}</p>
        </div>
        <IconButton icon={Plus} label={`添加${title}`} kind="primary" onClick={openAdd} />
      </div>
      <div className="row-list">
        {rows.length ? rows.map((row, index) => (
          <div className={`list-row profile-list-row ${kind === "feishu" ? "with-query" : "compact-actions"}`} key={`${kind}-${row.id || index}`}>
            <div>
              <strong>{profileLabel(row, kind)}</strong>
              <span>{kind === "feishu" ? `${row.app_id || "未填写 App ID"} · ${Array.isArray(row.chats) ? row.chats.length : 0} 个群` : `${row.target_user_id || "未绑定目标用户"} · ${row.account_id || "default"}`}</span>
            </div>
            {kind === "feishu" ? (
              <button className="btn slim" type="button" disabled={busy} onClick={() => onQueryChats(row.id)}>
                <Search size={15} />
                查询群组
              </button>
            ) : null}
            <IconButton icon={Edit3} label="编辑" kind="ghost" onClick={() => openEdit(index)} />
            <IconButton icon={Trash2} label="删除" kind="danger" onClick={() => deleteRow(index)} />
          </div>
        )) : <div className="empty-row">暂无配置组，点击 + 添加。</div>}
      </div>
      {draft ? (
        <div className="modal-backdrop">
          <div className="modal-card">
            <div className="editor-header">
              <div>
                <h3>{draft.index >= 0 ? "编辑配置组" : "新增配置组"}</h3>
                <p>{kind === "feishu" ? "飞书凭证用于查询群组、收命令和发送消息。确认前先查询可用群，后续监听规则才有群可选。" : "微信配置用于扫码/Token 登录和主动推送。"}</p>
              </div>
              <IconButton icon={X} label="关闭" onClick={() => setDraft(null)} />
            </div>
            <div className="grid compact-form">
              <label className="field"><span>备注（非必填）</span><input value={draft.row.label || ""} onChange={(event) => updateDraft({ label: event.target.value })} /></label>
              {kind === "feishu" ? (
                <>
                  <label className="field"><span>App ID</span><input value={draft.row.app_id || ""} onChange={(event) => updateDraft({ app_id: event.target.value })} /></label>
                  <label className="field"><span>App Secret</span><input type="password" value={draft.row.app_secret || ""} onChange={(event) => updateDraft({ app_secret: event.target.value })} /></label>
                  <label className="field"><span>ID 类型</span><select value={draft.row.id_type || "chat_id"} onChange={(event) => updateDraft({ id_type: event.target.value })}>{FEISHU_ID_TYPE_OPTIONS.map((option) => <option key={option} value={option}>{feishuIdTypeLabel(option)}</option>)}</select></label>
                  <div className="field field-wide draft-chat-query">
                    <div>
                      <span>可用群查询</span>
                      <p>当前草稿已缓存 {Array.isArray(draft.row.chats) ? draft.row.chats.length : 0} 个群；没有群时监听规则里不会出现可选目标。</p>
                    </div>
                    <div className="draft-chat-controls single">
                      <button className="btn slim" type="button" disabled={busy} onClick={queryDraftChats}>
                        <Search size={15} />
                        查询可用群
                      </button>
                    </div>
                    {draftChatStatus ? <div className={`notice ${draftChatStatus.kind} compact`}>{draftChatStatus.text}</div> : null}
                  </div>
                </>
              ) : (
                <>
                  <label className="field"><span>Token</span><input type="password" value={draft.row.token || ""} onChange={(event) => updateDraft({ token: event.target.value })} /></label>
                  <label className="field"><span>目标用户 ID</span><input value={draft.row.target_user_id || ""} onChange={(event) => updateDraft({ target_user_id: event.target.value })} /></label>
                  <label className="field"><span>账号标识</span><input value={draft.row.account_id || ""} onChange={(event) => updateDraft({ account_id: event.target.value })} /></label>
                  <label className="field"><span>Base URL</span><input value={draft.row.base_url || ""} onChange={(event) => updateDraft({ base_url: event.target.value })} /></label>
                  <label className="field"><span>CDN Base URL</span><input value={draft.row.cdn_base_url || ""} onChange={(event) => updateDraft({ cdn_base_url: event.target.value })} /></label>
                  <label className="field"><span>允许用户 ID</span><input value={draft.row.allowed_user_ids || ""} onChange={(event) => updateDraft({ allowed_user_ids: event.target.value })} /></label>
                </>
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

function ListenRuleEditor({ rows, setRows, authorRows, threadRows, pushTargets, feishuProfiles, wechatProfiles, onEnsureRouteTarget, hint = null }) {
  const [ruleDraft, setRuleDraft] = useState(null);
  const [targetDraft, setTargetDraft] = useState(null);
  const emptyRule = () => ({
    id: ensureId("rule", {}),
    label: "",
    mode: "thread_author",
    author_id: authorRows[0]?.id || "",
    tid: threadRows[0]?.id || "",
    target_ids: pushTargets[0]?.id ? [pushTargets[0].id] : [],
  });
  const openAdd = () => setRuleDraft({ index: -1, row: emptyRule(), error: "" });
  const openEdit = (index) => setRuleDraft({ index, row: { ...rows[index], target_ids: selectedTargets(rows[index]) }, error: "" });
  const updateRow = (index, patch) => setRows(rows.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)));
  const updateRuleDraft = (patch) => setRuleDraft((current) => ({ ...current, row: { ...current.row, ...patch }, error: "" }));
  const deleteRow = (index) => {
    if (!confirmRemove(rows[index]?.label || ruleSource(rows[index] || {}) || "这个监听规则")) return;
    setRows(rows.filter((_, rowIndex) => rowIndex !== index));
  };
  const selectedTargets = (row) => (Array.isArray(row.target_ids) ? row.target_ids : []).filter(Boolean);
  const targetName = (targetId) => {
    const target = pushTargets.find((item) => item.id === targetId);
    return target ? targetLabel(target) : targetId;
  };
  const ruleSource = (row) => row.mode === "author"
    ? `用户主页 ${row.author_id || "-"}`
    : `帖子 ${row.tid || "-"} / 用户 ${row.author_id || "-"}`;
  const openTargetDraft = () => {
    const channel = feishuProfiles.length || !wechatProfiles.length ? "feishu" : "wechat";
    const profile = channel === "wechat" ? wechatProfiles[0] : feishuProfiles[0];
    const chats = channel === "feishu" && profile && Array.isArray(profile.chats) ? profile.chats : [];
    setTargetDraft({ channel, profile_id: profile?.id || "", receive_id: chats[0]?.chat_id || "" });
  };
  const targetDraftProfile = targetDraft?.channel === "wechat"
    ? wechatProfiles.find((profile) => profile.id === targetDraft.profile_id) || wechatProfiles[0]
    : feishuProfiles.find((profile) => profile.id === targetDraft?.profile_id) || feishuProfiles[0];
  const targetDraftChats = targetDraft?.channel === "feishu" && targetDraftProfile && Array.isArray(targetDraftProfile.chats) ? targetDraftProfile.chats : [];
  const confirmTargetDraft = () => {
    if (!targetDraft || !ruleDraft) return;
    const targetId = onEnsureRouteTarget(targetDraft);
    if (!targetId) return;
    const nextIds = selectedTargets(ruleDraft.row);
    if (!nextIds.includes(targetId)) nextIds.push(targetId);
    updateRuleDraft({ target_ids: nextIds });
    setTargetDraft(null);
  };
  const removeDraftTarget = (targetIndex) => {
    if (!ruleDraft) return;
    if (!confirmRemove(targetName(selectedTargets(ruleDraft.row)[targetIndex]) || "这个发送目标")) return;
    updateRuleDraft({ target_ids: selectedTargets(ruleDraft.row).filter((_, index) => index !== targetIndex) });
  };
  const confirmRuleDraft = () => {
    if (!ruleDraft) return;
    const row = { ...ruleDraft.row };
    row.author_id = String(row.author_id || "").trim();
    row.tid = row.mode === "author" ? "" : String(row.tid || "").trim();
    row.target_ids = selectedTargets(row);
    if (!row.author_id || (row.mode !== "author" && !row.tid)) {
      setRuleDraft((current) => ({ ...current, error: "请填写用户和帖子。" }));
      return;
    }
    if (!row.target_ids.length) {
      setRuleDraft((current) => ({ ...current, error: "请至少添加一个发送目标。" }));
      return;
    }
    row.id = row.id || (row.mode === "author" ? `author:${row.author_id}` : `thread_author:${row.tid}:${row.author_id}`);
    if (ruleDraft.index >= 0) updateRow(ruleDraft.index, row);
    else setRows([...rows, row]);
    setRuleDraft(null);
  };
  return (
    <div className={`editor-card field-wide ${hint ? "validation-target-active" : ""}`} data-validation-target="listen-rules">
      {hint ? <div className="field-alert">{hint}</div> : null}
      <div className="editor-header">
        <div>
          <h3>监听规则</h3>
          <p>列表只展示摘要；点击 + 或编辑后在弹窗里选择监听方式和发送目标。</p>
        </div>
        <IconButton icon={Plus} label="新增监听规则" kind="primary" onClick={openAdd} />
      </div>
      <div className="row-list">
        {rows.length ? rows.map((row, index) => (
          <div className="list-row rule-list-row" key={row.id || index}>
            <div>
              <strong>{row.label || ruleSource(row)}</strong>
              <span>{row.mode === "author" ? "用户主页监听" : "固定帖子筛选用户"} · {ruleSource(row)} · {selectedTargets(row).length} 个发送目标</span>
            </div>
            <IconButton icon={Edit3} label="编辑" kind="ghost" onClick={() => openEdit(index)} />
            <IconButton icon={Trash2} label="删除" kind="danger" onClick={() => deleteRow(index)} />
          </div>
        )) : <div className="empty-row">暂无监听规则。点击 + 添加监听内容和发送目标。</div>}
      </div>
      {ruleDraft ? (
        <div className="modal-backdrop">
          <div className="modal-card">
            <div className="editor-header">
              <div>
                <h3>{ruleDraft.index >= 0 ? "编辑监听规则" : "新增监听规则"}</h3>
                <p>监听固定帖子筛选用户时，启动首轮会先用用户回复补抓，再进入帖子尾部扫描。</p>
              </div>
              <IconButton icon={X} label="关闭" onClick={() => setRuleDraft(null)} />
            </div>
            <div className="grid compact-form">
              <label className="field">
                <span>监听方式</span>
                <select value={ruleDraft.row.mode || "thread_author"} onChange={(event) => updateRuleDraft({ mode: event.target.value })}>
                  <option value="thread_author">固定帖子筛选用户</option>
                  <option value="author">用户主页监听</option>
                </select>
              </label>
              <label className="field"><span>备注（非必填）</span><input value={ruleDraft.row.label || ""} onChange={(event) => updateRuleDraft({ label: event.target.value })} /></label>
              <label className="field"><span>用户</span><select value={ruleDraft.row.author_id || ""} onChange={(event) => updateRuleDraft({ author_id: event.target.value })}>{authorRows.map((item) => <option key={item.id} value={item.id}>{item.label ? `${item.label} (${item.id})` : item.id}</option>)}</select></label>
              <label className="field"><span>帖子</span><select disabled={ruleDraft.row.mode === "author"} value={ruleDraft.row.tid || ""} onChange={(event) => updateRuleDraft({ tid: event.target.value })}>{threadRows.map((item) => <option key={item.id} value={item.id}>{item.label ? `${item.label} (${item.id})` : item.id}</option>)}</select></label>
            </div>
            <div className="modal-subsection">
              <div className="editor-header compact">
                <div>
                  <h3>发送目标</h3>
                  <p>可以添加多个飞书群或微信账号。</p>
                </div>
                <IconButton icon={Plus} label="添加发送目标" kind="primary" onClick={openTargetDraft} />
              </div>
              <div className="schedule-target-list">
                {selectedTargets(ruleDraft.row).length ? selectedTargets(ruleDraft.row).map((targetId, index) => (
                  <div className="schedule-target-row" key={`${targetId}-${index}`}>
                    <span>{targetName(targetId)}</span>
                    <IconButton icon={Trash2} label="删除发送目标" kind="danger" onClick={() => removeDraftTarget(index)} />
                  </div>
                )) : <span className="empty-inline">暂无发送目标，点击 + 添加。</span>}
              </div>
            </div>
            {ruleDraft.error ? <div className="notice error compact">{ruleDraft.error}</div> : null}
            <div className="inline-actions">
              <button className="btn" type="button" onClick={() => setRuleDraft(null)}>取消</button>
              <button className="btn primary" type="button" onClick={confirmRuleDraft}>确认</button>
            </div>
          </div>
        </div>
      ) : null}
      {targetDraft ? (
        <div className="modal-backdrop nested">
          <div className="modal-card small">
            <div className="editor-header">
              <div>
                <h3>新增发送目标</h3>
                <p>飞书选择配置组和群；微信只选择配置组。</p>
              </div>
              <IconButton icon={X} label="关闭" onClick={() => setTargetDraft(null)} />
            </div>
            <div className="grid compact-form">
              <label className="field">
                <span>通道</span>
                <select value={targetDraft.channel} onChange={(event) => {
                  const channel = event.target.value;
                  const profile = channel === "wechat" ? wechatProfiles[0] : feishuProfiles[0];
                  const chats = channel === "feishu" && profile && Array.isArray(profile.chats) ? profile.chats : [];
                  setTargetDraft((current) => ({ ...current, channel, profile_id: profile?.id || "", receive_id: chats[0]?.chat_id || "" }));
                }}>
                  <option value="feishu">飞书</option>
                  <option value="wechat">微信</option>
                </select>
              </label>
              {targetDraft.channel === "feishu" ? (
                <>
                  <label className="field">
                    <span>飞书配置</span>
                    <select value={targetDraft.profile_id} onChange={(event) => {
                      const profile = feishuProfiles.find((item) => item.id === event.target.value);
                      const chats = profile && Array.isArray(profile.chats) ? profile.chats : [];
                      setTargetDraft((current) => ({ ...current, profile_id: event.target.value, receive_id: chats[0]?.chat_id || "" }));
                    }}>
                      {feishuProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profileLabel(profile, "feishu")}</option>)}
                    </select>
                  </label>
                  <label className="field">
                    <span>飞书群 / chat_id</span>
                    <input list="rule-feishu-chats" value={targetDraft.receive_id || ""} onChange={(event) => setTargetDraft((current) => ({ ...current, receive_id: event.target.value }))} placeholder="选择或粘贴 chat_id" />
                    <datalist id="rule-feishu-chats">
                      {targetDraftChats.map((chat) => <option key={chat.chat_id} value={chat.chat_id}>{chatLabel(chat)}</option>)}
                    </datalist>
                  </label>
                </>
              ) : (
                <label className="field">
                  <span>微信配置</span>
                  <select value={targetDraft.profile_id} onChange={(event) => setTargetDraft((current) => ({ ...current, profile_id: event.target.value }))}>
                    {wechatProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profileLabel(profile, "wechat")}</option>)}
                  </select>
                </label>
              )}
            </div>
            <div className="inline-actions">
              <button className="btn" type="button" onClick={() => setTargetDraft(null)}>取消</button>
              <button className="btn primary" type="button" onClick={confirmTargetDraft}>确认</button>
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
  const deleteRow = (index) => {
    if (!confirmRemove(rows[index]?.label || `${rows[index]?.tid || ""}:${rows[index]?.authorId || ""}` || "这个条目")) return;
    updateRows(rows.filter((_, rowIndex) => rowIndex !== index));
  };
  return (
    <div className={`editor-card field-wide ${hint ? "validation-target-active" : ""}`} data-validation-target="listen-rules">
      {hint ? <div className="field-alert">{hint}</div> : null}
      <div className="editor-header">
        <div>
          <h3>帖内作者监听</h3>
          <p>拉取固定帖子新回复后按作者过滤；可为每个组合指定飞书群或独立机器人。</p>
        </div>
        <IconButton icon={Plus} label="添加帖内作者监听" kind="primary" onClick={addRow} />
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
                <span>备注（非必填）</span>
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
                  {FEISHU_ID_TYPE_OPTIONS.map((option) => (
                    <option key={option} value={option}>
                      {feishuIdTypeLabel(option)}
                    </option>
                  ))}
                </select>
              </label>
              <IconButton icon={Trash2} label="删除" kind="danger" onClick={() => deleteRow(index)} />
            </div>
          ))
        ) : (
          <div className="empty-row">暂无条目。使用 thread_author 或 both 模式时，点击 + 添加帖子和作者。</div>
        )}
      </div>
    </div>
  );
}

function AiModelControls({ config, setConfig, options, hint = null }) {
  const provider = config.ai_provider || "codex";
  const update = (key, value) => setConfig((current) => ({ ...current, [key]: value }));
  const modelOptions = options.aiModels?.[provider] || ["default", "auto"];
  const reasoningOptions = options.aiReasoning?.[provider] || ["default"];
  if (provider === "custom") {
    return (
      <div className={`field-wide ai-settings-grid ${hint ? "validation-target-active" : ""}`} data-validation-target="ai-settings">
        {hint ? <div className="field-alert field-wide">{hint}</div> : null}
        <Field config={config} setConfig={setConfig} spec={["ai_model", "模型", "text"]} />
        <Field config={config} setConfig={setConfig} spec={["ai_reasoning_effort", "思考强度", "text"]} />
      </div>
    );
  }
  const modelValue = modelOptions.includes(config.ai_model) ? config.ai_model : "default";
  const reasoningValue = reasoningOptions.includes(config.ai_reasoning_effort) ? config.ai_reasoning_effort : "default";
  return (
    <div className={`field-wide ai-settings-grid ${hint ? "validation-target-active" : ""}`} data-validation-target="ai-settings">
      {hint ? <div className="field-alert field-wide">{hint}</div> : null}
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
    </div>
  );
}

function AiScheduleTargets({ config, setConfig, pushTargets, feishuProfiles, wechatProfiles, onCreateScheduleTarget, hint = null }) {
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
    const target = pushTargets.find((item) => item.id === selectedIds[index]);
    if (!confirmRemove(target ? targetLabel(target) : selectedIds[index] || "这个发送目标")) return;
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
    <div className={`editor-card field-wide ${hint ? "validation-target-active" : ""}`} data-validation-target="ai-schedule-targets">
      {hint ? <div className="field-alert">{hint}</div> : null}
      <div className="editor-header">
        <div>
          <h3>定时分析发送目标</h3>
          <p>定时分析只跑一次，结果发送到下面这些目标。</p>
        </div>
        <div className="button-row compact">
          <IconButton icon={Plus} label="添加定时发送目标" kind="primary" onClick={openAdd} />
          <IconButton icon={Trash2} label="删除最后一个发送目标" kind="danger" onClick={() => selectedIds.length && removeAt(selectedIds.length - 1)} />
        </div>
      </div>
      <div className="schedule-target-list">
        {selectedIds.length ? selectedIds.map((targetId, index) => {
          const target = pushTargets.find((item) => item.id === targetId);
          return (
            <div className="schedule-target-row" key={`${targetId}-${index}`}>
              <span>{target ? targetLabel(target) : targetId}</span>
              <IconButton icon={Trash2} label="删除发送目标" kind="danger" onClick={() => removeAt(index)} />
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
              <IconButton icon={X} label="关闭" onClick={() => setDraft(null)} />
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
  const [selectedChannel, setSelectedChannel] = useState("feishu");
  const [savedSnapshot, setSavedSnapshot] = useState("");
  const [closeRequest, setCloseRequest] = useState(null);
  const [validationHint, setValidationHint] = useState(null);
  const [cookieCheck, setCookieCheck] = useState(null);
  const logOffsetRef = useRef(0);
  const bootstrappedRef = useRef(false);

  const channel = selectedChannel === "wechat" ? "wechat" : "feishu";
  const feishuProfiles = useMemo(() => parseProfiles(config, "feishu_bot_profiles"), [config]);
  const wechatProfiles = useMemo(() => parseProfiles(config, "wechat_bot_profiles"), [config]);
  const pushTargets = useMemo(() => parsePushTargets(config, feishuProfiles, wechatProfiles), [config, feishuProfiles, wechatProfiles]);
  const listenRules = useMemo(() => parseListenRules(config), [config]);
  const authorRows = useMemo(() => parseTargetList(config.watch_author_ids, config.default_author_id), [config.watch_author_ids, config.default_author_id]);
  const threadRows = useMemo(() => parseTargetList(config.preset_thread_ids, config.default_tid), [config.preset_thread_ids, config.default_tid]);
  const configSnapshot = useMemo(() => JSON.stringify(config), [config]);
  const isDirty = Boolean(savedSnapshot && configSnapshot !== savedSnapshot);
  const setStructured = (patch) => {
    setConfig((current) => {
      const currentFeishu = parseProfiles(current, "feishu_bot_profiles");
      const currentWechat = parseProfiles(current, "wechat_bot_profiles");
      const currentTargets = parsePushTargets(current, currentFeishu, currentWechat);
      const currentRules = parseListenRules(current);
      const nextFeishu = patch.feishuProfiles ?? currentFeishu;
      const nextWechat = patch.wechatProfiles ?? currentWechat;
      const validFeishuProfiles = new Set(nextFeishu.map((profile) => String(profile.id || "").trim()).filter(Boolean));
      const validWechatProfiles = new Set(nextWechat.map((profile) => String(profile.id || "").trim()).filter(Boolean));
      const nextTargets = (patch.pushTargets ?? currentTargets).filter((target) => {
        const channelValue = target.channel === "wechat" ? "wechat" : "feishu";
        const profileId = String(target.profile_id || "").trim();
        if (!profileId) return true;
        return channelValue === "wechat" ? validWechatProfiles.has(profileId) : validFeishuProfiles.has(profileId);
      });
      const validTargetIds = new Set(nextTargets.map((target) => String(target.id || "").trim()).filter(Boolean));
      const nextRules = (patch.listenRules ?? currentRules).map((rule) => ({
        ...rule,
        target_ids: (Array.isArray(rule.target_ids) ? rule.target_ids : String(rule.target_ids || "").split(/[,，;\s]+/))
          .map((targetId) => String(targetId || "").trim())
          .filter((targetId) => targetId && validTargetIds.has(targetId)),
      }));
      return applyStructuredConfig(current, {
        feishuProfiles: nextFeishu,
        wechatProfiles: nextWechat,
        pushTargets: nextTargets,
        listenRules: nextRules,
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
    if (!hasApiMethod("bootstrap") || isClosing()) return;
    try {
      const boot = await api().bootstrap();
      if (isClosing()) return;
      const merged = normalizeConfig(boot.config, boot.defaults);
      setConfig(merged);
      setSelectedChannel(merged.bot_channel === "wechat" ? "wechat" : "feishu");
      setDefaults(boot.defaults);
      setOptions(boot.options || {});
      setStatus(boot.status);
      setLogs(boot.logs?.text || "");
      const nextOffset = boot.logs?.offset || 0;
      logOffsetRef.current = nextOffset;
      setLogOffset(nextOffset);
      setAdvancedJson(JSON.stringify(merged, null, 2));
      setSavedSnapshot(JSON.stringify(merged));
      bootstrappedRef.current = true;
    } catch (error) {
      if (!isClosing()) {
        setMessage(String(error?.message || error));
        setMessageKind("error");
      }
    }
  };

  useEffect(() => {
    let stopped = false;
    let polling = false;
    let bootstrapPolling = false;
    const markClosing = () => {
      stopped = true;
      closingFlag = true;
    };
    const waitForBootstrap = async () => {
      if (stopped || isClosing() || bootstrapPolling || bootstrappedRef.current) return;
      if (!hasApiMethod("bootstrap")) return;
      bootstrapPolling = true;
      try {
        await refresh();
      } finally {
        bootstrapPolling = false;
      }
    };
    waitForBootstrap();
    window.addEventListener("pywebviewready", refresh);
    window.addEventListener("beforeunload", markClosing);
    window.addEventListener("pagehide", markClosing);
    const timer = window.setInterval(async () => {
      if (stopped || isClosing() || polling) return;
      if (!bootstrappedRef.current) {
        await waitForBootstrap();
        return;
      }
      if (!hasApiMethod("status") || !hasApiMethod("read_logs")) return;
      polling = true;
      try {
        const stat = await api().status();
        if (stopped || isClosing()) return;
        if (stat?.status) setStatus(stat.status);
        const next = await api().read_logs(logOffsetRef.current);
        if (stopped || isClosing()) return;
        if (next?.text) {
          setLogs((current) => `${current}${next.text}`.slice(-60000));
          const nextOffset = next.offset || 0;
          logOffsetRef.current = nextOffset;
          setLogOffset(nextOffset);
        } else if (next?.offset !== undefined) {
          logOffsetRef.current = next.offset;
          setLogOffset(next.offset);
        }
      } catch (error) {
        if (!stopped && !isClosing()) {
          setMessage(String(error?.message || error));
          setMessageKind("error");
        }
      } finally {
        polling = false;
      }
    }, 3000);
    return () => {
      stopped = true;
      window.removeEventListener("pywebviewready", refresh);
      window.removeEventListener("beforeunload", markClosing);
      window.removeEventListener("pagehide", markClosing);
      window.clearInterval(timer);
    };
  }, []);

  const openCloseDialog = async (options = {}) => {
    const forceExit = Boolean(options.forceExit);
    const behavior = forceExit ? "exit" : String(config.web_close_behavior || "ask");
    let running = Boolean(status.running);
    let latestPids = Array.isArray(status.pids) ? status.pids : [];
    setCloseRequest({
      dirty: isDirty,
      running,
      pids: latestPids,
      behavior,
      action: behavior === "minimize" ? "minimize" : "exit",
      step: behavior === "minimize" ? "final" : behavior === "exit" ? "dirty" : "background",
      remember: false,
      forceExit,
    });
  };

  const focusValidationErrors = (errors = []) => {
    const firstError = String(errors[0] || "请先补齐必要配置。");
    const section = validationSectionForError(firstError);
    const target = validationTargetForError(firstError);
    const channelForError = validationChannelForError(firstError);
    const hintText = firstError;
    if (channelForError) setSelectedChannel(channelForError);
    setValidationHint({ section, target, text: hintText, token: Date.now() });
    setMessage(firstError);
    setMessageKind("error");
    window.setTimeout(() => {
      const details = document.getElementById(`section-${section}`);
      if (details && "open" in details) details.open = true;
      const targetElement = document.querySelector(`[data-validation-target="${target}"]`);
      const parentDetails = targetElement?.closest("details");
      if (parentDetails && "open" in parentDetails) parentDetails.open = true;
      (targetElement || details || document.getElementById(section))?.scrollIntoView({ behavior: "smooth", block: "center" });
    }, 50);
  };

  const run = async (label, fn) => {
    if (isClosing()) return;
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
      if (isClosing()) return;
      if (!result?.ok) {
        const errors = result?.errors || [result?.error || `${label}失败`];
        setMessage(errors.join("\n"));
        setMessageKind("error");
        if (label === "保存配置" || label === "启动监听") focusValidationErrors(errors);
      } else {
        setMessage(result.warning ? `${label}完成\n${result.warning}` : `${label}完成`);
        setMessageKind(result.warning ? "info" : "success");
        if (result.config) {
          const normalized = normalizeConfig(result.config, defaults);
          setConfig(normalized);
          setSelectedChannel(normalized.bot_channel === "wechat" ? "wechat" : "feishu");
          setAdvancedJson(JSON.stringify(normalized, null, 2));
          if (label === "保存配置" || label === "启动监听") setSavedSnapshot(JSON.stringify(normalized));
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

  const startListening = async () => {
    if (!api()?.validate) {
      setMessage("pywebview API 未就绪");
      setMessageKind("error");
      return;
    }
    setBusy(true);
    try {
      const result = await api().validate(config);
      if (!result?.ok) {
        focusValidationErrors(result?.errors || [result?.error || "请先补齐必要配置。"]);
        return;
      }
      if (isDirty) {
        setMessage("有未保存配置，请先保存后再启动监听。");
        setMessageKind("error");
        return;
      }
      await run("启动监听", () => api().start(config));
    } catch (error) {
      setMessage(String(error?.message || error));
      setMessageKind("error");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (!validationHint) return undefined;
    const timer = window.setTimeout(() => setValidationHint(null), 6000);
    return () => window.clearTimeout(timer);
  }, [validationHint]);

  const sectionHint = (section) => (validationHint?.section === section && !validationHint?.target ? validationHint.text : null);
  const targetHint = (target) => (validationHint?.target === target ? validationHint.text : null);

  const applyJson = () => {
    try {
      const parsed = JSON.parse(advancedJson);
      const normalized = normalizeConfig(parsed, defaults);
      setConfig(normalized);
      setSelectedChannel(normalized.bot_channel === "wechat" ? "wechat" : "feishu");
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
  const queryChats = (profileId) => run("查询飞书群组", () => api().query_feishu_chats(config, profileId));
  const queryDraftChats = (profile) => api().query_feishu_chats_for_profile(profile);
  const checkNgaCookie = async () => {
    if (!api()?.check_nga_cookie) {
      setCookieCheck({ kind: "error", text: "pywebview API 未就绪" });
      return;
    }
    setBusy(true);
    setCookieCheck({ kind: "info", text: "正在检测 NGA Cookie..." });
    try {
      const result = await api().check_nga_cookie(config);
      if (!result?.ok) {
        const text = (result?.errors || [result?.error || "NGA Cookie 检测失败"]).join("\n");
        setCookieCheck({ kind: "error", text });
        focusValidationErrors([text]);
        return;
      }
      setCookieCheck({ kind: "success", text: result.message || "NGA Cookie 可用。" });
    } catch (error) {
      setCookieCheck({ kind: "error", text: String(error?.message || error) });
    } finally {
      setBusy(false);
    }
  };
  const resolveCloseStep = () => {
    if (!closeRequest) return null;
    if (closeRequest.step === "dirty") {
      if (closeRequest.dirty) return "dirty";
      return closeRequest.running ? "running" : "final";
    }
    if (closeRequest.step === "running") return closeRequest.running ? "running" : "final";
    return closeRequest.step || "background";
  };
  const continueClose = (patch = {}) => setCloseRequest((current) => {
    if (!current) return current;
    const next = { ...current, ...patch };
    if (next.step === "dirty" && !next.dirty) next.step = next.running ? "running" : "final";
    if (next.step === "running" && !next.running) next.step = "final";
    return next;
  });
  const saveAndContinueClose = async () => {
    if (!api()?.save_config) return;
    setBusy(true);
    setMessage("保存配置中...");
    setMessageKind("info");
    try {
      const result = await api().save_config(config);
      if (!result?.ok) {
        setMessage((result?.errors || [result?.error || "保存配置失败"]).join("\n"));
        setMessageKind("error");
        return;
      }
      const normalized = normalizeConfig(result.config || config, defaults);
      setConfig(normalized);
      setSelectedChannel(normalized.bot_channel === "wechat" ? "wechat" : "feishu");
      setAdvancedJson(JSON.stringify(normalized, null, 2));
      setSavedSnapshot(JSON.stringify(normalized));
      if (result.status) setStatus(result.status);
      setMessage("保存配置完成");
      setMessageKind("success");
      continueClose({
        dirty: false,
        step: "running",
        running: Boolean(closeRequest?.running),
        pids: Array.isArray(closeRequest?.pids) ? closeRequest.pids : [],
      });
    } catch (error) {
      setMessage(String(error?.message || error));
      setMessageKind("error");
    } finally {
      setBusy(false);
    }
  };
  const finishClose = async (action, remember = false) => {
    const request = closeRequest || {};
    const finalAction = action || request.action || "exit";
    const shouldRemember = Boolean(remember || request.remember);
    setCloseRequest(null);
    if (shouldRemember) {
      setConfig((current) => ({ ...current, web_close_behavior: finalAction }));
      setSavedSnapshot((current) => {
        try {
          const saved = JSON.parse(current || "{}");
          return JSON.stringify({ ...saved, web_close_behavior: finalAction });
        } catch {
          return current;
        }
      });
    }
    if (api()?.close_confirmed) {
      await api().close_confirmed({ action: finalAction, stop: finalAction === "exit", remember_behavior: shouldRemember });
    }
  };
  useEffect(() => {
    if (!closeRequest) return;
    const step = resolveCloseStep();
    if (step === "final") {
      finishClose(closeRequest.action || closeRequest.behavior || "exit", Boolean(closeRequest.remember));
    }
  }, [closeRequest]);
  return (
    <main>
      <aside>
        <div className="brand">
          <div className="logo">
            <img src="./app_icon.png?v=4" alt="" />
          </div>
          <div>
            <strong>NGA Wolf Watcher</strong>
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
          <a href="#quiet">免打扰</a>
          <a href="#runtime">运行参数</a>
          <a href="#advanced">高级配置</a>
          <a href="#logs">日志</a>
        </nav>
      </aside>

      <section className="content">
        <button id="nga-close-request-trigger" className="visually-hidden" type="button" onClick={openCloseDialog}>
          request close
        </button>
        <button id="nga-tray-exit-trigger" className="visually-hidden" type="button" onClick={() => openCloseDialog({ forceExit: true })}>
          request tray exit
        </button>
        <header>
          <div>
            <div className="title-row">
              <h1>监听配置</h1>
              {isDirty ? (
                <span className="dirty-pill">
                  <AlertTriangle size={15} />
                  有未保存修改
                </span>
              ) : null}
            </div>
            <p>配置消息通道、NGA Cookie、监听规则和 AI 分析。</p>
          </div>
          <div className="actions">
            <ActionButton icon={Save} kind="primary" disabled={busy} onClick={() => run("保存配置", () => api().save_config(config))}>
              保存
            </ActionButton>
            <ActionButton icon={Play} kind="primary" disabled={busy || status.running} onClick={startListening}>
              启动
            </ActionButton>
            <ActionButton icon={CircleStop} disabled={busy || !status.running} onClick={() => run("停止监听", () => api().stop())}>
              停止
            </ActionButton>
          </div>
        </header>

        {isDirty ? (
          <div className="unsaved-notice" role="status">
            <AlertTriangle size={17} />
            <span>当前配置已修改但尚未保存，保存后才会用于启动监听和下次打开。</span>
          </div>
        ) : null}
        <Notice message={message} kind={messageKind} />
        <SetupOverview
          channel={channel}
          authorCount={authorRows.length}
          threadCount={threadRows.length}
          ruleCount={listenRules.length}
          profileCount={channel === "wechat" ? wechatProfiles.length : feishuProfiles.length}
        />

        <Section icon={ShieldCheck} title="快速开始" description="首次使用按顺序完成：通道配置、NGA Cookie、用户/帖子、监听规则。" defaultOpen sectionId="quick" hint={sectionHint("quick")}>
          <div id="quick" className="grid" data-validation-target="quick-start">
            <ChannelPicker config={config} setConfig={setConfig} channel={channel} onChannelChange={setSelectedChannel} />
            {channel === "wechat" ? (
              <ProfileGroupEditor title="微信机器人配置组" kind="wechat" rows={wechatProfiles} setRows={(rows) => setStructured({ wechatProfiles: rows })} busy={busy} onQueryChats={queryChats} onQueryDraftChats={queryDraftChats} hint={targetHint("wechat-profiles")} />
            ) : (
              <ProfileGroupEditor title="飞书机器人配置组" kind="feishu" rows={feishuProfiles} setRows={(rows) => setStructured({ feishuProfiles: rows })} busy={busy} onQueryChats={queryChats} onQueryDraftChats={queryDraftChats} hint={targetHint("feishu-profiles")} />
            )}
            <NgaCookieField config={config} setConfig={setConfig} hint={targetHint("nga_cookie")} busy={busy} status={cookieCheck} onCheck={checkNgaCookie} />
            <TargetListEditor config={config} setConfig={setConfig} configKey="watch_author_ids" fallbackKey="default_author_id" title="用户 ID 列表" idLabel="用户 UID" hint={targetHint("watch_author_ids")} />
            <TargetListEditor config={config} setConfig={setConfig} configKey="preset_thread_ids" fallbackKey="default_tid" title="帖子预设" idLabel="帖子 ID" hint={targetHint("preset_thread_ids")} />
            <ListenRuleEditor rows={listenRules} setRows={(rows) => setStructured({ listenRules: rows })} authorRows={authorRows} threadRows={threadRows} pushTargets={pushTargets} feishuProfiles={feishuProfiles} wechatProfiles={wechatProfiles} onEnsureRouteTarget={ensureRouteTarget} hint={targetHint("listen-rules")} />
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
          sectionId="channel"
          hint={sectionHint("channel")}
        >
          <div id="channel" className="grid">
            <ChannelPicker config={config} setConfig={setConfig} channel={channel} onChannelChange={setSelectedChannel} />
            {channel === "wechat" ? (
              <ProfileGroupEditor title="微信机器人配置组" kind="wechat" rows={wechatProfiles} setRows={(rows) => setStructured({ wechatProfiles: rows })} busy={busy} onQueryChats={queryChats} onQueryDraftChats={queryDraftChats} hint={targetHint("wechat-profiles")} />
            ) : (
              <ProfileGroupEditor title="飞书机器人配置组" kind="feishu" rows={feishuProfiles} setRows={(rows) => setStructured({ feishuProfiles: rows })} busy={busy} onQueryChats={queryChats} onQueryDraftChats={queryDraftChats} hint={targetHint("feishu-profiles")} />
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

        <Section icon={Bot} title="AI 分析" description="AI 是公共配置，结果跟随当前消息通道发送。" defaultOpen={false} sectionId="ai" hint={sectionHint("ai")}>
          <div id="ai" className="grid">
            {fieldGroups.ai.map((spec) => (
              <Field key={spec[0]} config={config} setConfig={setConfig} spec={spec} hint={targetHint(spec[0])} />
            ))}
            <AiModelControls config={config} setConfig={setConfig} options={options} hint={targetHint("ai-settings")} />
            <AiScheduleTargets config={config} setConfig={setConfig} pushTargets={pushTargets} feishuProfiles={feishuProfiles} wechatProfiles={wechatProfiles} onCreateScheduleTarget={createScheduleTarget} hint={targetHint("ai-schedule-targets")} />
          </div>
        </Section>

        <Section icon={ShieldCheck} title="免打扰" description="设置一段连续免打扰时间，以及期间新回复的处理方式。" defaultOpen={false} sectionId="quiet" hint={sectionHint("quiet")}>
          <QuietHoursControls config={config} setConfig={setConfig} hint={targetHint("quiet-hours")} />
        </Section>

        <Section icon={Settings} title="运行参数" description="轮询、重试、帖内扫描等低频配置收在这里。" defaultOpen={false} sectionId="runtime" hint={sectionHint("runtime")}>
          <div id="runtime" className="grid">
            {fieldGroups.runtime.map((spec) => (
              <Field key={spec[0]} config={config} setConfig={setConfig} spec={spec} hint={targetHint(spec[0])} />
            ))}
          </div>
        </Section>

        <Section icon={Settings} title="关闭行为" description="控制点击窗口关闭按钮时每次询问、默认隐藏到托盘，还是默认退出程序。关闭弹窗里勾选记住选择后也会写入这里。" defaultOpen={false}>
          <div className="grid">
            {fieldGroups.close.map((spec) => (
              <Field key={spec[0]} config={config} setConfig={setConfig} spec={spec} />
            ))}
          </div>
        </Section>

        <Section icon={TerminalSquare} title="高级配置" description="保留全部旧配置字段，适合排查或迁移。" defaultOpen={false} sectionId="advanced" hint={sectionHint("advanced")}>
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
        <CloseConfirmModal
          step={resolveCloseStep()}
          request={closeRequest}
          setRequest={setCloseRequest}
          onCancel={() => setCloseRequest(null)}
          onContinue={continueClose}
          onSaveAndContinue={saveAndContinueClose}
          onFinish={finishClose}
        />
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
