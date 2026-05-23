import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Activity,
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
    ["jitter", "随机抖动秒", "number"],
    ["retries", "重试次数", "number"],
    ["retry_initial_delay", "重试初始等待秒", "number"],
    ["retry_delay", "重试递增秒", "number"],
    ["nga_request_min_interval", "NGA 请求最小间隔秒", "number"],
  ],
  close: [
    ["web_close_behavior", "关闭按钮行为", "select", ["ask", "minimize", "exit"]],
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

function Field({ config, setConfig, spec }) {
  const [key, label, type, options] = spec;
  let value = config[key] ?? "";
  if ((key === "ai_auto_analysis_prompt" || key === "ai_schedule_prompt") && !String(value || "").trim()) {
    value = DEFAULT_AI_ANALYSIS_PROMPT;
  }
  const update = (next) => setConfig((current) => ({ ...current, [key]: next }));
  if (key === "ai_schedule_windows") {
    return <ScheduleWindowField config={config} setConfig={setConfig} label={label} />;
  }
  if (type === "textarea") {
    return (
      <label className="field field-wide">
        <span>{label}</span>
        <textarea value={value || ""} onChange={(event) => update(event.target.value)} rows={key === "nga_cookie" ? 4 : 3} />
      </label>
    );
  }
  if (type === "select") {
    const optionLabel = (option) => {
      if (key === "web_close_behavior") return { ask: "每次询问", minimize: "最小化到后台图标", exit: "直接退出程序" }[option] || option;
      return option;
    };
    return (
      <label className="field">
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
      <label className="switch-row">
        <span>{label}</span>
        <input type="checkbox" checked={Boolean(value)} onChange={(event) => update(event.target.checked)} aria-label={label} />
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

function ScheduleWindowField({ config, setConfig, label }) {
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
    <div className="field field-wide schedule-window-picker">
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

function QuietHoursControls({ config, setConfig }) {
  const update = (patch) => setConfig((current) => ({ ...current, ...patch }));
  const startDay = String(config.quiet_start_day ?? "5");
  const endDay = String(config.quiet_end_day ?? "0");
  const policy = String(config.quiet_policy || "ignore");
  return (
    <div id="quiet" className="grid">
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

function CloseConfirmModal({ step, request, setRequest, onCancel, onContinue, onFinish }) {
  if (!step || !request) return null;
  if (step === "dirty") {
    return (
      <div className="modal-backdrop">
        <div className="modal-card small">
          <div className="editor-header">
            <div>
              <h3>有未保存配置</h3>
              <p>当前修改还没有保存，继续关闭会放弃这些修改。</p>
            </div>
            <IconButton icon={X} label="取消关闭" onClick={onCancel} />
          </div>
          <div className="inline-actions">
            <button className="btn" type="button" onClick={onCancel}>返回</button>
            <button className="btn primary" type="button" onClick={() => onContinue({ dirty: false })}>放弃修改并继续</button>
          </div>
        </div>
      </div>
    );
  }
  if (step === "running") {
    return (
      <div className="modal-backdrop">
        <div className="modal-card small">
          <div className="editor-header">
            <div>
              <h3>监听仍在运行</h3>
              <p>退出前需要先停止监听进程，避免后台继续推送。</p>
            </div>
            <IconButton icon={X} label="取消关闭" onClick={onCancel} />
          </div>
          <div className="inline-actions">
            <button className="btn" type="button" onClick={onCancel}>返回</button>
            <button className="btn primary" type="button" onClick={() => onContinue({ running: false, stopOnExit: true })}>停止监听并继续</button>
          </div>
        </div>
      </div>
    );
  }
  if (step === "background") {
    return (
      <div className="modal-backdrop">
        <div className="modal-card small">
          <div className="editor-header">
            <div>
              <h3>关闭窗口</h3>
              <p>可以直接退出程序，也可以最小化到后台图标，之后从托盘图标恢复窗口。</p>
            </div>
            <IconButton icon={X} label="取消关闭" onClick={onCancel} />
          </div>
          <label className="remember-row">
            <input type="checkbox" checked={Boolean(request.remember)} onChange={(event) => setRequest((current) => ({ ...current, remember: event.target.checked }))} />
            <span>记住这次选择</span>
          </label>
          <div className="inline-actions">
            <button className="btn" type="button" onClick={onCancel}>取消</button>
            <button className="btn" type="button" onClick={() => onFinish("exit", Boolean(request.remember))}>退出程序</button>
            <button className="btn primary" type="button" onClick={() => onFinish("minimize", Boolean(request.remember))}>最小化到后台图标</button>
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

function TargetListEditor({ config, setConfig, configKey, fallbackKey, title, idLabel }) {
  const [draft, setDraft] = useState(null);
  const rows = parseTargetList(config[configKey], config[fallbackKey]);
  const updateRows = (nextRows) => setConfig((current) => {
    const formatted = formatTargetList(nextRows);
    const firstId = String(nextRows.find((row) => String(row.id || "").trim())?.id || "").trim();
    return { ...current, [configKey]: formatted, ...(fallbackKey && firstId ? { [fallbackKey]: firstId } : {}) };
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
    <div className="editor-card field-wide">
      <div className="editor-header">
        <div>
          <h3>{title}</h3>
          <p>ID 和备注分开填写，点击 + 后在弹窗里添加。</p>
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
                <span>备注</span>
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

function ProfileGroupEditor({ title, kind, rows, setRows, busy, onQueryChats }) {
  const [chatQueries, setChatQueries] = useState({});
  const [draft, setDraft] = useState(null);
  const emptyRow = () => kind === "feishu"
    ? { id: ensureId("feishu", {}), label: "", app_id: "", app_secret: "", id_type: "chat_id", chats: [] }
    : { id: ensureId("wechat", {}), label: "", token: "", base_url: "https://ilinkai.weixin.qq.com", cdn_base_url: "https://novac2c.cdn.weixin.qq.com/c2c", target_user_id: "", allowed_user_ids: "", poll_timeout_ms: "35000", account_id: "default", route_tag: "" };
  const openAdd = () => setDraft({ index: -1, row: emptyRow() });
  const openEdit = (index) => setDraft({ index, row: { ...rows[index] } });
  const updateRow = (index, patch) => setRows(rows.map((row, rowIndex) => (rowIndex === index ? { ...row, ...patch } : row)));
  const updateDraft = (patch) => setDraft((current) => ({ ...current, row: { ...current.row, ...patch } }));
  const deleteRow = (index) => {
    if (!confirmRemove(profileLabel(rows[index] || {}, kind))) return;
    setRows(rows.filter((_, rowIndex) => rowIndex !== index));
  };
  const confirmDraft = () => {
    if (!draft) return;
    const row = { ...draft.row, id: ensureId(kind, draft.row) };
    if (draft.index >= 0) updateRow(draft.index, row);
    else setRows([...rows, row]);
    setDraft(null);
  };
  return (
    <div className="editor-card field-wide">
      <div className="editor-header">
        <div>
          <h3>{title}</h3>
          <p>{kind === "feishu" ? "每组 App ID / Secret 独立缓存可见群组；点击编辑维护凭证。" : "每组微信 Token 独立保存目标用户和账号标识；点击编辑维护配置。"}</p>
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
              <>
                <label><span>搜索群名</span><input placeholder="新群没出现时输入群名" value={chatQueries[row.id] || ""} onChange={(event) => setChatQueries((current) => ({ ...current, [row.id]: event.target.value }))} /></label>
                <button className="btn slim" type="button" disabled={busy} onClick={() => onQueryChats(row.id, chatQueries[row.id] || "")}>
                  <Search size={15} />
                  查询
                </button>
              </>
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
                <p>{kind === "feishu" ? "飞书凭证用于查询群组、收命令和发送消息。" : "微信配置用于扫码/Token 登录和主动推送。"}</p>
              </div>
              <IconButton icon={X} label="关闭" onClick={() => setDraft(null)} />
            </div>
            <div className="grid compact-form">
              <label className="field"><span>备注</span><input value={draft.row.label || ""} onChange={(event) => updateDraft({ label: event.target.value })} /></label>
              {kind === "feishu" ? (
                <>
                  <label className="field"><span>App ID</span><input value={draft.row.app_id || ""} onChange={(event) => updateDraft({ app_id: event.target.value })} /></label>
                  <label className="field"><span>App Secret</span><input type="password" value={draft.row.app_secret || ""} onChange={(event) => updateDraft({ app_secret: event.target.value })} /></label>
                  <label className="field"><span>ID 类型</span><select value={draft.row.id_type || "chat_id"} onChange={(event) => updateDraft({ id_type: event.target.value })}><option value="chat_id">chat_id</option><option value="open_id">open_id</option><option value="user_id">user_id</option><option value="union_id">union_id</option></select></label>
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

function ListenRuleEditor({ rows, setRows, authorRows, threadRows, pushTargets, feishuProfiles, wechatProfiles, onEnsureRouteTarget }) {
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
    <div className="editor-card field-wide">
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
              <label className="field"><span>备注</span><input value={ruleDraft.row.label || ""} onChange={(event) => updateRuleDraft({ label: event.target.value })} /></label>
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
    <div className="editor-card field-wide">
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
    <div className="editor-card field-wide">
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

  const openCloseDialog = () => {
    setCloseRequest({
      dirty: isDirty,
      running: Boolean(status.running),
      behavior: String(config.web_close_behavior || "ask"),
      remember: false,
    });
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
        setMessage((result?.errors || [result?.error || `${label}失败`]).join("\n"));
        setMessageKind("error");
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
  const queryChats = (profileId, searchQuery = "") => run("查询飞书群组", () => api().query_feishu_chats(config, profileId, searchQuery));
  const resolveCloseStep = () => {
    if (!closeRequest) return null;
    if (closeRequest.dirty) return "dirty";
    if (closeRequest.running) return "running";
    if (closeRequest.behavior === "minimize" || closeRequest.behavior === "exit") return "final";
    return "background";
  };
  const continueClose = (patch = {}) => setCloseRequest((current) => (current ? { ...current, ...patch } : current));
  const finishClose = async (action, remember = false) => {
    const request = closeRequest || {};
    setCloseRequest(null);
    if (remember) {
      setConfig((current) => ({ ...current, web_close_behavior: action }));
    }
    if (api()?.close_confirmed) {
      await api().close_confirmed({ action, stop: Boolean(request.running || request.stopOnExit), remember_behavior: remember });
    }
  };
  useEffect(() => {
    if (!closeRequest) return;
    if (closeRequest.dirty || closeRequest.running) return;
    if (closeRequest.behavior === "minimize" || closeRequest.behavior === "exit") {
      finishClose(closeRequest.behavior, false);
    }
  }, [closeRequest]);
  return (
    <main>
      <aside>
        <div className="brand">
          <div className="logo">
            <img src="./app_icon.png" alt="" />
          </div>
          <div>
            <strong>NGA Wolf Watcher</strong>
            <span>Web UI</span>
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
        <header>
          <div>
            <h1>监听配置</h1>
            <p>配置消息通道、NGA Cookie、监听规则和 AI 分析。</p>
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
        <SetupOverview
          channel={channel}
          authorCount={authorRows.length}
          threadCount={threadRows.length}
          ruleCount={listenRules.length}
          profileCount={channel === "wechat" ? wechatProfiles.length : feishuProfiles.length}
        />

        <Section icon={ShieldCheck} title="快速开始" description="首次使用按顺序完成：通道配置、NGA Cookie、用户/帖子、监听规则。" defaultOpen>
          <div id="quick" className="grid">
            <ChannelPicker config={config} setConfig={setConfig} channel={channel} onChannelChange={setSelectedChannel} />
            {channel === "wechat" ? (
              <ProfileGroupEditor title="微信机器人配置组" kind="wechat" rows={wechatProfiles} setRows={(rows) => setStructured({ wechatProfiles: rows })} busy={busy} onQueryChats={queryChats} />
            ) : (
              <ProfileGroupEditor title="飞书机器人配置组" kind="feishu" rows={feishuProfiles} setRows={(rows) => setStructured({ feishuProfiles: rows })} busy={busy} onQueryChats={queryChats} />
            )}
            <Field config={config} setConfig={setConfig} spec={["nga_cookie", "NGA Cookie", "textarea"]} />
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
            <ChannelPicker config={config} setConfig={setConfig} channel={channel} onChannelChange={setSelectedChannel} />
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

        <Section icon={ShieldCheck} title="免打扰" description="设置一段连续免打扰时间，以及期间新回复的处理方式。" defaultOpen={false}>
          <QuietHoursControls config={config} setConfig={setConfig} />
        </Section>

        <Section icon={Settings} title="运行参数" description="轮询、重试、帖内扫描等低频配置收在这里。" defaultOpen={false}>
          <div id="runtime" className="grid">
            {fieldGroups.runtime.map((spec) => (
              <Field key={spec[0]} config={config} setConfig={setConfig} spec={spec} />
            ))}
          </div>
        </Section>

        <Section icon={Settings} title="关闭行为" description="控制点击窗口关闭按钮时退出程序还是最小化到后台图标。" defaultOpen={false}>
          <div className="grid">
            {fieldGroups.close.map((spec) => (
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
        <CloseConfirmModal
          step={resolveCloseStep()}
          request={closeRequest}
          setRequest={setCloseRequest}
          onCancel={() => setCloseRequest(null)}
          onContinue={continueClose}
          onFinish={finishClose}
        />
      </section>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
