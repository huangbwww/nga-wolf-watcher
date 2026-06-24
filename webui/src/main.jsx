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
import StockDashboard from "./StockDashboard.jsx";
import "./styles.css";

const api = () => window.pywebview?.api;
let closingFlag = false;
const isClosing = () => closingFlag;
const hasApiMethod = (method) => typeof api()?.[method] === "function";
const CONFIG_HASHES = new Set(["#channel", "#ai", "#quiet", "#runtime", "#advanced", "#logs"]);
const pageForHash = (hash = "") => {
  if (hash === "#stock-dashboard" || hash === "") return "stock";
  if (hash === "#quick") return "quick";
  if (CONFIG_HASHES.has(hash)) return "config";
  return "config";
};
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
  dingtalk: [
    ["dingtalk_client_id", "Client ID / App Key", "text"],
    ["dingtalk_client_secret", "Client Secret / App Secret", "password"],
    ["dingtalk_robot_code", "Robot Code", "text"],
    ["dingtalk_target_user_ids", "目标用户 ID", "text"],
    ["dingtalk_allowed_user_ids", "允许用户 ID", "text"],
    ["dingtalk_account_id", "账号标识", "text"],
  ],
  ai: [
    ["ai_enabled", "启用 AI", "checkbox"],
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

const EMAIL_PROVIDER_PRESETS = [
  { id: "163", label: "网易 163 邮箱", smtp_host: "smtp.163.com", smtp_port: "465", smtp_security: "ssl", password_hint: "填写 163 邮箱里生成的授权码" },
  { id: "126", label: "网易 126 邮箱", smtp_host: "smtp.126.com", smtp_port: "465", smtp_security: "ssl", password_hint: "填写 126 邮箱里生成的授权码" },
  { id: "qq", label: "QQ 邮箱", smtp_host: "smtp.qq.com", smtp_port: "465", smtp_security: "ssl", password_hint: "填写 QQ 邮箱里生成的授权码" },
  { id: "gmail", label: "Gmail", smtp_host: "smtp.gmail.com", smtp_port: "587", smtp_security: "starttls", password_hint: "填写 Google 应用专用密码" },
  { id: "outlook", label: "Outlook / Microsoft 365", smtp_host: "smtp.office365.com", smtp_port: "587", smtp_security: "starttls", password_hint: "填写邮箱密码或应用密码" },
  { id: "custom", label: "自定义邮箱" },
];

function emailProviderPreset(id) {
  return EMAIL_PROVIDER_PRESETS.find((preset) => preset.id === id) || EMAIL_PROVIDER_PRESETS[0];
}

function emailProviderId(row) {
  const explicit = String(row.smtp_provider || "").trim();
  if (EMAIL_PROVIDER_PRESETS.some((preset) => preset.id === explicit)) return explicit;
  const host = String(row.smtp_host || "").trim().toLowerCase();
  const port = String(row.smtp_port || "").trim();
  const security = String(row.smtp_security || "").trim().toLowerCase();
  const matched = EMAIL_PROVIDER_PRESETS.find((preset) =>
    preset.id !== "custom"
    && preset.smtp_host === host
    && String(preset.smtp_port) === port
    && preset.smtp_security === security
  );
  return matched?.id || "custom";
}

function applyEmailProvider(row, providerId) {
  const preset = emailProviderPreset(providerId);
  if (preset.id === "custom") return { ...row, smtp_provider: "custom" };
  return {
    ...row,
    smtp_provider: preset.id,
    label: row.label || preset.label,
    smtp_host: preset.smtp_host,
    smtp_port: preset.smtp_port,
    smtp_security: preset.smtp_security,
  };
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
  const channel = target.channel === "wechat" ? "微信" : target.channel === "dingtalk" ? "钉钉" : target.channel === "wxpusher" ? "WxPusher" : "飞书";
  const name = String(target.label || target.id || target.receive_id || "").trim();
  const receive = String(target.receive_id || "").trim();
  const displayChannel = target.channel === "email" ? "邮箱" : channel;
  return `${displayChannel} / ${name}${receive ? ` -> ${receive}` : ""}`;
}

function channelTitle(channel) {
  if (channel === "email") return "邮箱";
  if (channel === "dingtalk") return "钉钉";
  if (channel === "wxpusher") return "WxPusher";
  return channel === "wechat" ? "微信" : "飞书";
}

function targetReceiveId(row) {
  return String(
    row.receive_id
    || row.chat_id
    || row.target_user_id
    || row.target_user_ids
    || row.feishu_receive_id
    || row.dingtalk_target_user_ids
    || row.email_to
    || row.wxpusher_spts
    || row.spt
    || row.spts
    || row.wxpusher_uids
    || row.uid
    || row.uids
    || row.wxpusher_topic_ids
    || row.topic_id
    || row.topic_ids
    || row.route_receive_id
    || ""
  ).trim();
}

function targetIdType(row, channel) {
  const explicit = String(row.id_type || row.receive_id_type || row.feishu_id_type || "").trim();
  if (explicit) return explicit;
  if (channel === "email") return "email";
  if (channel === "dingtalk" || channel === "wechat") return "user_id";
  if (channel === "wxpusher") {
    if (row.wxpusher_spts || row.spt || row.spts) return "spt";
    return row.wxpusher_topic_ids || row.topic_id || row.topic_ids ? "topic_id" : "uid";
  }
  return "chat_id";
}

function parseProfiles(config, key, legacy = {}) {
  const profileKind = key.includes("email") ? "email" : key.includes("dingtalk") ? "dingtalk" : key.includes("wxpusher") ? "wxpusher" : key.includes("feishu") ? "feishu" : "wechat";
  const rows = parseJsonList(config[key]).map((row) => ({ ...row, id: ensureId(profileKind, row) }));
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
  if (key === "dingtalk_bot_profiles" && (config.dingtalk_client_id || config.dingtalk_client_secret || config.dingtalk_robot_code)) {
    return [{
      id: "default",
      label: "默认钉钉",
      client_id: config.dingtalk_client_id || "",
      client_secret: config.dingtalk_client_secret || "",
      robot_code: config.dingtalk_robot_code || "",
      target_user_ids: config.dingtalk_target_user_ids || "",
      allowed_user_ids: config.dingtalk_allowed_user_ids || "",
      account_id: config.dingtalk_account_id || "default",
    }];
  }
  if (key === "email_smtp_profiles" && (config.email_username || config.email_password || config.email_from)) {
    return [{
      id: "default",
      label: "默认邮箱",
      smtp_host: config.email_smtp_host || "smtp.gmail.com",
      smtp_port: config.email_smtp_port || "587",
      smtp_security: config.email_smtp_security || "starttls",
      username: config.email_username || "",
      password: config.email_password || "",
      from_email: config.email_from || config.email_username || "",
      from_name: config.email_from_name || "NGA Wolf Watcher",
      reply_to: config.email_reply_to || "",
    }];
  }
  if (key === "wxpusher_profiles" && (config.wxpusher_spts || config.wxpusher_app_token)) {
    return [{
      id: "default",
      label: "默认 WxPusher",
      spts: config.wxpusher_spts || "",
      app_token: config.wxpusher_app_token || "",
      uids: config.wxpusher_uids || "",
      topic_ids: config.wxpusher_topic_ids || "",
      content_type: config.wxpusher_content_type || "markdown",
    }];
  }
  return legacy.rows || [];
}

function parsePushTargets(config, feishuProfiles, wechatProfiles, dingtalkProfiles = [], emailProfiles = [], wxpusherProfiles = []) {
  const rows = parseJsonList(config.push_targets).map((row) => {
    const channel = row.channel === "wechat" ? "wechat" : row.channel === "dingtalk" ? "dingtalk" : row.channel === "email" ? "email" : row.channel === "wxpusher" ? "wxpusher" : "feishu";
    return {
      ...row,
      id: ensureId("target", row),
      channel,
      receive_id: targetReceiveId(row),
      id_type: targetIdType(row, channel),
    };
  });
  if (rows.length) return rows;
  const fallback = [];
  if (feishuProfiles.length && config.feishu_receive_id) {
    fallback.push({ id: "default_feishu", label: "默认飞书群", channel: "feishu", profile_id: feishuProfiles[0].id, receive_id: config.feishu_receive_id, id_type: config.feishu_id_type || "chat_id", default_author_id: config.default_author_id || "", default_tid: config.default_tid || "" });
  }
  if (wechatProfiles.length && config.wechat_bot_target_user_id) {
    fallback.push({ id: "default_wechat", label: "默认微信", channel: "wechat", profile_id: wechatProfiles[0].id, receive_id: config.wechat_bot_target_user_id, id_type: "user_id", default_author_id: config.default_author_id || "", default_tid: config.default_tid || "" });
  }
  if (dingtalkProfiles.length && config.dingtalk_target_user_ids) {
    fallback.push({ id: "default_dingtalk", label: "默认钉钉", channel: "dingtalk", profile_id: dingtalkProfiles[0].id, receive_id: config.dingtalk_target_user_ids, id_type: "user_id", default_author_id: config.default_author_id || "", default_tid: config.default_tid || "" });
  }
  if (emailProfiles.length && config.email_to) {
    fallback.push({ id: "default_email", label: "默认邮箱", channel: "email", profile_id: emailProfiles[0].id, receive_id: config.email_to, id_type: "email", default_author_id: config.default_author_id || "", default_tid: config.default_tid || "" });
  }
  if (wxpusherProfiles.length && (config.wxpusher_spts || wxpusherProfiles.some((profile) => profile.spts))) {
    fallback.push({ id: "default_wxpusher", label: "默认 WxPusher", channel: "wxpusher", profile_id: wxpusherProfiles[0].id, receive_id: "", id_type: "spt", default_author_id: config.default_author_id || "", default_tid: config.default_tid || "" });
  } else if (wxpusherProfiles.length && (config.wxpusher_uids || config.wxpusher_topic_ids)) {
    fallback.push({ id: "default_wxpusher", label: "默认 WxPusher", channel: "wxpusher", profile_id: wxpusherProfiles[0].id, receive_id: config.wxpusher_uids || config.wxpusher_topic_ids, id_type: config.wxpusher_uids ? "uid" : "topic_id", default_author_id: config.default_author_id || "", default_tid: config.default_tid || "" });
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

function applyStructuredConfig(config, { feishuProfiles, wechatProfiles, dingtalkProfiles = [], emailProfiles = [], wxpusherProfiles = [], pushTargets, listenRules }) {
  const next = {
    ...config,
    feishu_bot_profiles: formatJsonList(feishuProfiles),
    wechat_bot_profiles: formatJsonList(wechatProfiles),
    dingtalk_bot_profiles: formatJsonList(dingtalkProfiles),
    email_smtp_profiles: formatJsonList(emailProfiles),
    wxpusher_profiles: formatJsonList(wxpusherProfiles),
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
  if (dingtalkProfiles[0]) {
    next.dingtalk_client_id = dingtalkProfiles[0].client_id || "";
    next.dingtalk_client_secret = dingtalkProfiles[0].client_secret || "";
    next.dingtalk_robot_code = dingtalkProfiles[0].robot_code || "";
    next.dingtalk_target_user_ids = dingtalkProfiles[0].target_user_ids || "";
    next.dingtalk_allowed_user_ids = dingtalkProfiles[0].allowed_user_ids || "";
    next.dingtalk_account_id = dingtalkProfiles[0].account_id || "default";
  } else {
    next.dingtalk_client_id = "";
    next.dingtalk_client_secret = "";
    next.dingtalk_robot_code = "";
    next.dingtalk_target_user_ids = "";
    next.dingtalk_allowed_user_ids = "";
    next.dingtalk_account_id = "default";
  }
  if (emailProfiles[0]) {
    next.email_smtp_host = emailProfiles[0].smtp_host || "smtp.gmail.com";
    next.email_smtp_port = emailProfiles[0].smtp_port || "587";
    next.email_smtp_security = emailProfiles[0].smtp_security || "starttls";
    next.email_username = emailProfiles[0].username || "";
    next.email_password = emailProfiles[0].password || "";
    next.email_from = emailProfiles[0].from_email || "";
    next.email_from_name = emailProfiles[0].from_name || "NGA Wolf Watcher";
    next.email_reply_to = emailProfiles[0].reply_to || "";
  } else {
    next.email_smtp_host = "smtp.gmail.com";
    next.email_smtp_port = "587";
    next.email_smtp_security = "starttls";
    next.email_username = "";
    next.email_password = "";
    next.email_from = "";
    next.email_from_name = "NGA Wolf Watcher";
    next.email_reply_to = "";
  }
  if (wxpusherProfiles[0]) {
    next.wxpusher_spts = wxpusherProfiles[0].spts || "";
    next.wxpusher_app_token = wxpusherProfiles[0].app_token || "";
    next.wxpusher_uids = wxpusherProfiles[0].uids || "";
    next.wxpusher_topic_ids = wxpusherProfiles[0].topic_ids || "";
    next.wxpusher_content_type = wxpusherProfiles[0].content_type || "markdown";
  } else {
    next.wxpusher_spts = "";
    next.wxpusher_app_token = "";
    next.wxpusher_uids = "";
    next.wxpusher_topic_ids = "";
    next.wxpusher_content_type = "markdown";
  }
  const firstFeishuTarget = pushTargets.find((target) => (target.channel || "feishu") === "feishu");
  next.feishu_receive_id = firstFeishuTarget?.receive_id || "";
  if (firstFeishuTarget?.id_type) next.feishu_id_type = firstFeishuTarget.id_type;
  const firstEmailTarget = pushTargets.find((target) => target.channel === "email");
  next.email_to = firstEmailTarget?.receive_id || "";
  const firstWxPusherTarget = pushTargets.find((target) => target.channel === "wxpusher");
  if (firstWxPusherTarget) {
    if (["spt", "spts"].includes(firstWxPusherTarget.id_type || "")) {
      next.wxpusher_uids = "";
      next.wxpusher_topic_ids = "";
    } else if (["topic", "topic_id", "topic_ids"].includes(firstWxPusherTarget.id_type || "")) {
      next.wxpusher_topic_ids = firstWxPusherTarget.receive_id || "";
      next.wxpusher_uids = "";
    } else {
      next.wxpusher_uids = firstWxPusherTarget.receive_id || "";
      next.wxpusher_topic_ids = "";
    }
  }
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
  if (/飞书|Feishu|Receive ID|chat_id|微信|WeChat|Bot Token|钉钉|DingTalk|WxPusher|WXPUSHER|SPT|appToken|App Token|机器人|发送目标|通道/.test(text)) return "quick";
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
  if (/钉钉|DingTalk|dingtalk|Client ID|Client Secret|Robot Code/.test(text)) return "dingtalk-profiles";
  if (/Email|SMTP|email|邮箱|邮件/.test(text)) return "email-profiles";
  if (/WxPusher|WXPUSHER|SPT|appToken|App Token|Topic/.test(text)) return "wxpusher-profiles";
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
  if (/钉钉|DingTalk|dingtalk/.test(text)) return "dingtalk";
  if (/Email|SMTP|email|邮箱|邮件/.test(text)) return "email";
  if (/WxPusher|WXPUSHER|SPT|appToken|App Token|Topic/.test(text)) return "wxpusher";
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
  const value = channel || (config.bot_channel === "wechat" ? "wechat" : config.bot_channel === "dingtalk" ? "dingtalk" : config.bot_channel === "email" ? "email" : config.bot_channel === "wxpusher" ? "wxpusher" : "feishu");
  const update = (nextChannel) => {
    onChannelChange?.(nextChannel);
    setConfig((current) => ({ ...current, bot_channel: nextChannel }));
  };
  return (
    <div className="channel-switch-card field-wide">
      <div>
        <span className="eyebrow">当前配置通道</span>
        <strong>{value === "wechat" ? "微信 Bot" : value === "dingtalk" ? "钉钉 Bot" : value === "email" ? "邮箱 SMTP" : value === "wxpusher" ? "WxPusher" : "飞书 Bot"}</strong>
        <p>这里只切换正在编辑的通道配置；监听规则里再选择具体推送目标。</p>
      </div>
      <div className="segmented" role="group" aria-label="当前配置通道">
        <button className={value === "feishu" ? "active" : ""} type="button" onClick={() => update("feishu")}>
          飞书
        </button>
        <button className={value === "wechat" ? "active" : ""} type="button" onClick={() => update("wechat")}>
          微信
        </button>
        <button className={value === "dingtalk" ? "active" : ""} type="button" onClick={() => update("dingtalk")}>
          钉钉
        </button>
        <button className={value === "email" ? "active" : ""} type="button" onClick={() => update("email")}>
          邮箱
        </button>
        <button className={value === "wxpusher" ? "active" : ""} type="button" onClick={() => update("wxpusher")}>
          WxPusher
        </button>
      </div>
    </div>
  );
}

function SetupOverview({ channel, authorCount, threadCount, ruleCount, profileCount }) {
  const steps = [
    { icon: MessageSquare, title: "通道", value: `${channel === "email" ? "邮箱" : channel === "dingtalk" ? "钉钉" : channel === "wechat" ? "微信" : channel === "wxpusher" ? "WxPusher" : "飞书"} ${profileCount || 0} 组` },
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

function ProfileGroupEditor({ title, kind, rows, setRows, busy, onQueryChats, onQueryDraftChats, onRecentDingtalkUser, hint = null }) {
  const [draft, setDraft] = useState(null);
  const [draftChatStatus, setDraftChatStatus] = useState(null);
  const emptyRow = () => kind === "feishu"
    ? { id: ensureId("feishu", {}), label: "", app_id: "", app_secret: "", id_type: "chat_id", chats: [] }
    : kind === "email"
      ? applyEmailProvider({ id: ensureId("email", {}), label: "", username: "", password: "", from_email: "", from_name: "NGA Wolf Watcher", reply_to: "" }, "163")
    : kind === "wxpusher"
      ? { id: ensureId("wxpusher", {}), label: "", spts: "", app_token: "", uids: "", topic_ids: "", content_type: "markdown" }
    : kind === "dingtalk"
      ? { id: ensureId("dingtalk", {}), label: "", client_id: "", client_secret: "", robot_code: "", target_user_ids: "", allowed_user_ids: "", account_id: "default" }
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
  const replaceDraftRow = (row) => setDraft((current) => ({ ...current, row }));
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
  const fillRecentDingtalkUser = async () => {
    if (!draft || kind !== "dingtalk" || !onRecentDingtalkUser) return;
    setDraftChatStatus({ kind: "info", text: "正在读取最近收到的钉钉用户 ID..." });
    try {
      const result = await onRecentDingtalkUser(draft.row);
      if (!result?.ok) {
        setDraftChatStatus({ kind: "error", text: (result?.errors || [result?.error || "没有可用的钉钉用户 ID"]).join("\n") });
        return;
      }
      const userId = String(result.user_id || result.user?.user_id || "").trim();
      updateDraft({ target_user_ids: userId });
      const senderName = String(result.user?.sender_name || "").trim();
      setDraftChatStatus({ kind: "success", text: senderName ? `已填入 ${senderName} 的钉钉用户 ID` : "已填入最近钉钉用户 ID" });
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
  const profileDescription = kind === "feishu"
    ? "每组 App ID / Secret 独立缓存可见群组；新增时可以先查询群，避免后续监听规则无群可选。"
    : kind === "email"
      ? "邮箱配置只用于发送通知，不接收邮件回复或聊天命令；收件邮箱在监听规则里填写。"
    : kind === "dingtalk"
      ? "每组钉钉 Stream 应用独立保存 Client ID、Secret 和主动推送目标用户。"
    : kind === "wxpusher"
      ? "每组 WxPusher 配置只需要填写 SPT，适合个人极简推送。"
    : "每组微信 Token 独立保存目标用户和账号标识；点击编辑维护配置。";
  const profileMeta = (row) => kind === "feishu"
    ? `${row.app_id || "未填写 App ID"} · ${Array.isArray(row.chats) ? row.chats.length : 0} 个群`
    : kind === "email"
      ? `${row.from_email || row.username || "未填写发件邮箱"} · ${row.smtp_host || "未填写 SMTP 服务器"}`
    : kind === "dingtalk"
      ? `${row.target_user_ids || "未填写目标用户"} · ${row.account_id || "default"}`
    : kind === "wxpusher"
      ? `${row.spts || "未填写 SPT"} · 极简推送`
    : `${row.target_user_id || "未绑定目标用户"} · ${row.account_id || "default"}`;
  const modalDescription = kind === "feishu"
    ? "飞书凭证用于查询群组、收命令和发送消息。确认前先查询可用群，后续监听规则才有群可选。"
    : kind === "dingtalk"
      ? "钉钉配置使用 Stream 模式收消息，使用机器人工作通知接口主动推送。"
    : kind === "wxpusher"
      ? "在 WxPusher 客户端里复制 SPT，填到这里即可推送。"
    : kind === "email"
      ? "邮箱配置只负责发送通知；收件人地址在发送目标里填写。"
    : "微信配置用于扫码/Token 登录和主动推送。";
  return (
    <div className={`editor-card field-wide ${hint ? "validation-target-active" : ""}`} data-validation-target={`${kind}-profiles`}>
      {hint ? <div className="field-alert">{hint}</div> : null}
      <div className="editor-header">
        <div>
          <h3>{title}</h3>
          <p>{profileDescription}</p>
        </div>
        <IconButton icon={Plus} label={`添加${title}`} kind="primary" onClick={openAdd} />
      </div>
      <div className="row-list">
        {rows.length ? rows.map((row, index) => (
          <div className={`list-row profile-list-row ${kind === "feishu" ? "with-query" : "compact-actions"}`} key={`${kind}-${row.id || index}`}>
            <div>
              <strong>{profileLabel(row, kind)}</strong>
              <span>{profileMeta(row)}</span>
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
                <p>{modalDescription}</p>
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
              ) : kind === "email" ? (
                <>
                  <label className="field">
                    <span>邮箱类型</span>
                    <select value={emailProviderId(draft.row)} onChange={(event) => replaceDraftRow(applyEmailProvider(draft.row, event.target.value))}>
                      {EMAIL_PROVIDER_PRESETS.map((preset) => <option key={preset.id} value={preset.id}>{preset.label}</option>)}
                    </select>
                  </label>
                  {emailProviderId(draft.row) === "custom" ? (
                    <>
                      <label className="field"><span>SMTP 服务器</span><input value={draft.row.smtp_host || ""} onChange={(event) => updateDraft({ smtp_host: event.target.value })} placeholder="例如 smtp.gmail.com" /></label>
                      <label className="field"><span>端口</span><input value={draft.row.smtp_port || ""} onChange={(event) => updateDraft({ smtp_port: event.target.value })} placeholder="587" /></label>
                      <label className="field"><span>加密方式</span><select value={draft.row.smtp_security || "starttls"} onChange={(event) => updateDraft({ smtp_security: event.target.value })}><option value="starttls">STARTTLS（常用）</option><option value="ssl">SSL/TLS</option><option value="none">不加密</option></select></label>
                    </>
                  ) : (
                    <div className="field field-wide preset-summary">
                      <span>服务器设置</span>
                      <p>{draft.row.smtp_host} · {draft.row.smtp_port} · {draft.row.smtp_security === "ssl" ? "SSL/TLS" : "STARTTLS"}</p>
                    </div>
                  )}
                  <label className="field"><span>发件邮箱</span><input value={draft.row.from_email || draft.row.username || ""} onChange={(event) => updateDraft({ username: event.target.value, from_email: event.target.value })} placeholder="用于登录并显示为发件地址" /></label>
                  <label className="field"><span>密码或授权码</span><input type="password" value={draft.row.password || ""} onChange={(event) => updateDraft({ password: event.target.value })} placeholder={emailProviderPreset(emailProviderId(draft.row)).password_hint || "填写邮箱服务商提供的密码或授权码"} /></label>
                  <label className="field"><span>发件人名称</span><input value={draft.row.from_name || ""} onChange={(event) => updateDraft({ from_name: event.target.value })} placeholder="例如 NGA Wolf Watcher" /></label>
                  <label className="field"><span>回复地址（可选）</span><input value={draft.row.reply_to || ""} onChange={(event) => updateDraft({ reply_to: event.target.value })} placeholder="不填则不设置" /></label>
                </>
              ) : kind === "wxpusher" ? (
                <>
                  <label className="field field-wide"><span>SPT</span><input type="password" value={draft.row.spts || ""} onChange={(event) => updateDraft({ spts: event.target.value, app_token: "", uids: "", topic_ids: "", content_type: "markdown" })} placeholder="在 WxPusher 客户端复制 SPT，多个用逗号分隔" /></label>
                  <div className="field field-wide preset-summary">
                    <span>极简推送</span>
                    <p>填写 SPT 后即可用于 NGA 新回复、免打扰汇总和 AI 分析结果推送。</p>
                  </div>
                </>
              ) : kind === "dingtalk" ? (
                <>
                  <label className="field"><span>Client ID / App Key</span><input value={draft.row.client_id || ""} onChange={(event) => updateDraft({ client_id: event.target.value })} /></label>
                  <label className="field"><span>Client Secret / App Secret</span><input type="password" value={draft.row.client_secret || ""} onChange={(event) => updateDraft({ client_secret: event.target.value })} /></label>
                  <label className="field"><span>Robot Code</span><input value={draft.row.robot_code || ""} onChange={(event) => updateDraft({ robot_code: event.target.value })} placeholder="主动推送需要，空则使用 Client ID" /></label>
                  <label className="field"><span>目标用户 ID</span><input value={draft.row.target_user_ids || ""} onChange={(event) => updateDraft({ target_user_ids: event.target.value })} placeholder="多个用逗号分隔" /></label>
                  <div className="field field-wide draft-chat-query">
                    <div>
                      <span>自动填入目标用户</span>
                      <p>先在钉钉给机器人发送 /start 或任意消息，再点击读取最近用户 ID。</p>
                    </div>
                    <div className="draft-chat-controls single">
                      <button className="btn slim" type="button" disabled={busy} onClick={fillRecentDingtalkUser}>
                        <Search size={15} />
                        获取最近用户 ID
                      </button>
                    </div>
                    {draftChatStatus ? <div className={`notice ${draftChatStatus.kind} compact`}>{draftChatStatus.text}</div> : null}
                  </div>
                  <label className="field"><span>允许用户 ID</span><input value={draft.row.allowed_user_ids || ""} onChange={(event) => updateDraft({ allowed_user_ids: event.target.value })} placeholder="为空则不限制" /></label>
                  <label className="field"><span>账号标识</span><input value={draft.row.account_id || ""} onChange={(event) => updateDraft({ account_id: event.target.value })} /></label>
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

function ListenRuleEditor({ rows, setRows, authorRows, threadRows, pushTargets, feishuProfiles, wechatProfiles, dingtalkProfiles = [], emailProfiles = [], wxpusherProfiles = [], onEnsureRouteTarget, onSendTestTarget, busy = false, hint = null }) {
  const [ruleDraft, setRuleDraft] = useState(null);
  const [targetDraft, setTargetDraft] = useState(null);
  const emptyRule = () => ({
    id: ensureId("rule", {}),
    group_id: ensureId("rule_group", {}),
    label: "",
    mode: "thread_author",
    author_id: authorRows[0]?.id || "",
    author_ids: authorRows[0]?.id ? [authorRows[0].id] : [],
    tid: threadRows[0]?.id || "",
    tids: threadRows[0]?.id ? [threadRows[0].id] : [],
    target_ids: pushTargets[0]?.id ? [pushTargets[0].id] : [],
  });
  const openAdd = () => setRuleDraft({ indices: [], row: emptyRule(), error: "" });
  const updateRuleDraft = (patch) => setRuleDraft((current) => ({ ...current, row: { ...current.row, ...patch }, error: "" }));
  const selectedTargets = (row) => (Array.isArray(row.target_ids) ? row.target_ids : []).filter(Boolean);
  const selectedAuthors = (row) => {
    if (Array.isArray(row.author_ids)) return row.author_ids.map((authorId) => String(authorId || "").trim()).filter(Boolean);
    const authorId = String(row.author_id || "").trim();
    return authorId ? [authorId] : [];
  };
  const selectedThreads = (row) => {
    if (row.mode === "author") return [];
    if (Array.isArray(row.tids)) return row.tids.map((tid) => String(tid || "").trim()).filter(Boolean);
    const tid = String(row.tid || "").trim();
    return tid ? [tid] : [];
  };
  const ruleIdentity = (row) => row.mode === "author" ? `author:${row.author_id || ""}` : `thread_author:${row.tid || ""}:${row.author_id || ""}`;
  const authorName = (authorId) => {
    const author = authorRows.find((item) => item.id === authorId);
    return author ? (author.label ? `${author.label} (${author.id})` : author.id) : authorId;
  };
  const threadName = (threadId) => {
    const thread = threadRows.find((item) => item.id === threadId);
    return thread ? (thread.label ? `${thread.label} (${thread.id})` : thread.id) : threadId;
  };
  const toggleDraftAuthor = (authorId) => {
    if (!ruleDraft) return;
    const currentIds = selectedAuthors(ruleDraft.row);
    const nextIds = currentIds.includes(authorId) ? currentIds.filter((item) => item !== authorId) : [...currentIds, authorId];
    updateRuleDraft({ author_ids: nextIds, author_id: nextIds[0] || "" });
  };
  const toggleDraftThread = (threadId) => {
    if (!ruleDraft) return;
    const currentIds = selectedThreads(ruleDraft.row);
    const nextIds = currentIds.includes(threadId) ? currentIds.filter((item) => item !== threadId) : [...currentIds, threadId];
    updateRuleDraft({ tids: nextIds, tid: nextIds[0] || "" });
  };
  const targetName = (targetId) => {
    const target = pushTargets.find((item) => item.id === targetId);
    return target ? targetLabel(target) : targetId;
  };
  const ruleGroups = (() => {
    const groups = [];
    const byKey = new Map();
    rows.forEach((row, index) => {
      const groupId = String(row.group_id || "").trim();
      const key = groupId ? `group:${groupId}` : `row:${index}`;
      let group = byKey.get(key);
      if (!group) {
        group = {
          key,
          group_id: groupId,
          mode: row.mode || "thread_author",
          label: row.label || "",
          indices: [],
          rows: [],
          author_ids: [],
          tids: [],
          target_ids: [],
        };
        byKey.set(key, group);
        groups.push(group);
      }
      group.indices.push(index);
      group.rows.push(row);
      if (row.label && !group.label) group.label = row.label;
      for (const authorId of selectedAuthors(row)) {
        if (!group.author_ids.includes(authorId)) group.author_ids.push(authorId);
      }
      for (const tid of selectedThreads(row)) {
        if (!group.tids.includes(tid)) group.tids.push(tid);
      }
      for (const targetId of selectedTargets(row)) {
        if (!group.target_ids.includes(targetId)) group.target_ids.push(targetId);
      }
    });
    return groups;
  })();
  const groupSource = (group) => group.mode === "author"
    ? `${group.author_ids.length || 0} 个用户`
    : `${group.author_ids.length || 0} 个用户 × ${group.tids.length || 0} 个帖子`;
  const groupTitle = (group) => {
    if (group.label) return group.label;
    if (group.mode === "author") {
      return group.author_ids.length === 1 ? `用户主页 ${authorName(group.author_ids[0])}` : `${group.author_ids.length || 0} 个用户主页`;
    }
    if (group.author_ids.length === 1 && group.tids.length === 1) {
      return `帖子 ${threadName(group.tids[0])} / 用户 ${authorName(group.author_ids[0])}`;
    }
    return groupSource(group);
  };
  const openEditGroup = (group) => {
    const first = group.rows[0] || {};
    setRuleDraft({
      indices: group.indices,
      row: {
        ...first,
        group_id: group.group_id || ensureId("rule_group", {}),
        label: group.label || "",
        mode: group.mode || "thread_author",
        author_id: group.author_ids[0] || "",
        author_ids: group.author_ids,
        tid: group.tids[0] || "",
        tids: group.tids,
        target_ids: group.target_ids,
      },
      error: "",
    });
  };
  const deleteGroup = (group) => {
    if (!confirmRemove(groupTitle(group) || "这个监听规则")) return;
    const indexes = new Set(group.indices);
    setRows(rows.filter((_, rowIndex) => !indexes.has(rowIndex)));
  };
  const openTargetDraft = () => {
    const channel = feishuProfiles.length ? "feishu" : wechatProfiles.length ? "wechat" : dingtalkProfiles.length ? "dingtalk" : emailProfiles.length ? "email" : "wxpusher";
    const profile = channel === "wechat" ? wechatProfiles[0] : channel === "dingtalk" ? dingtalkProfiles[0] : channel === "email" ? emailProfiles[0] : channel === "wxpusher" ? wxpusherProfiles[0] : feishuProfiles[0];
    const chats = channel === "feishu" && profile && Array.isArray(profile.chats) ? profile.chats : [];
    const receive_id = channel === "dingtalk" ? (profile?.target_user_ids || "") : channel === "wxpusher" ? "" : chats[0]?.chat_id || "";
    const id_type = channel === "wxpusher" ? "spt" : undefined;
    setTargetDraft({ channel, profile_id: profile?.id || "", receive_id, id_type });
  };
  const targetDraftProfile = targetDraft?.channel === "wechat"
    ? wechatProfiles.find((profile) => profile.id === targetDraft.profile_id) || wechatProfiles[0]
    : targetDraft?.channel === "dingtalk"
      ? dingtalkProfiles.find((profile) => profile.id === targetDraft.profile_id) || dingtalkProfiles[0]
    : targetDraft?.channel === "email"
      ? emailProfiles.find((profile) => profile.id === targetDraft.profile_id) || emailProfiles[0]
    : targetDraft?.channel === "wxpusher"
      ? wxpusherProfiles.find((profile) => profile.id === targetDraft.profile_id) || wxpusherProfiles[0]
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
    const authorIds = selectedAuthors(row);
    const threadIds = row.mode === "author" ? [] : selectedThreads(row);
    row.author_id = String(authorIds[0] || row.author_id || "").trim();
    row.tid = row.mode === "author" ? "" : String(threadIds[0] || row.tid || "").trim();
    row.target_ids = selectedTargets(row);
    if (!authorIds.length || (row.mode !== "author" && !threadIds.length)) {
      setRuleDraft((current) => ({ ...current, error: "请填写用户和帖子。" }));
      return;
    }
    if (!row.target_ids.length) {
      setRuleDraft((current) => ({ ...current, error: "请至少添加一个发送目标。" }));
      return;
    }
    const groupId = String(row.group_id || "").trim() || ensureId("rule_group", {});
    const sourcePairs = row.mode === "author"
      ? authorIds.map((authorId) => ({ authorId, tid: "" }))
      : threadIds.flatMap((tid) => authorIds.map((authorId) => ({ authorId, tid })));
    const generatedRules = sourcePairs.map(({ authorId, tid }) => {
      const nextRow = {
        ...row,
        id: row.mode === "author" ? `author:${authorId}` : `thread_author:${tid}:${authorId}`,
        group_id: groupId,
        author_id: authorId,
        tid,
      };
      delete nextRow.author_ids;
      delete nextRow.tids;
      return nextRow;
    });
    const uniqueRules = [];
    const generatedKeys = new Set();
    for (const generated of generatedRules) {
      const key = ruleIdentity(generated);
      if (generatedKeys.has(key)) continue;
      generatedKeys.add(key);
      uniqueRules.push(generated);
    }
    const oldIndices = new Set(ruleDraft.indices || []);
    if (!oldIndices.size) {
      const existingKeys = new Set(rows.map(ruleIdentity));
      const newRules = uniqueRules.filter((item) => !existingKeys.has(ruleIdentity(item)));
      if (!newRules.length) {
        setRuleDraft((current) => ({ ...current, error: "所选用户和帖子已经有相同监听规则。" }));
        return;
      }
      setRows([...rows, ...newRules]);
    } else {
      const nextRows = [];
      let inserted = false;
      rows.forEach((existing, index) => {
        if (oldIndices.has(index)) {
          if (!inserted) {
            nextRows.push(...uniqueRules);
            inserted = true;
          }
          return;
        }
        if (generatedKeys.has(ruleIdentity(existing))) return;
        nextRows.push(existing);
      });
      if (!inserted) nextRows.push(...uniqueRules);
      setRows(nextRows);
    }
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
        {ruleGroups.length ? ruleGroups.map((group) => (
          <div className="list-row rule-list-row" key={group.key}>
            <div>
              <strong>{groupTitle(group)}</strong>
              <span>{group.mode === "author" ? "用户主页监听" : "固定帖子筛选用户"} · {groupSource(group)} · {group.target_ids.length} 个发送目标 · {group.rows.length} 条底层规则</span>
            </div>
            <IconButton icon={Edit3} label="编辑" kind="ghost" onClick={() => openEditGroup(group)} />
            <IconButton icon={Trash2} label="删除" kind="danger" onClick={() => deleteGroup(group)} />
          </div>
        )) : <div className="empty-row">暂无监听规则。点击 + 添加监听内容和发送目标。</div>}
      </div>
      {ruleDraft ? (
        <div className="modal-backdrop">
          <div className="modal-card">
            <div className="editor-header">
              <div>
                <h3>{(ruleDraft.indices || []).length ? "编辑监听规则" : "新增监听规则"}</h3>
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
              <div className="field field-wide">
                <span>用户</span>
                <div className="rule-thread-picker">
                  {authorRows.length ? authorRows.map((item) => (
                    <label key={item.id} className="check-row">
                      <input type="checkbox" checked={selectedAuthors(ruleDraft.row).includes(item.id)} onChange={() => toggleDraftAuthor(item.id)} />
                      <span>{authorName(item.id)}</span>
                    </label>
                  )) : <div className="empty-inline">暂无用户预设，请先在目标里添加用户。</div>}
                </div>
              </div>
              <div className="field field-wide">
                <span>帖子</span>
                {ruleDraft.row.mode === "author" ? (
                  <div className="empty-inline">用户主页监听不需要选择帖子。</div>
                ) : (
                  <div className="rule-thread-picker">
                    {threadRows.length ? threadRows.map((item) => (
                      <label key={item.id} className="check-row">
                        <input type="checkbox" checked={selectedThreads(ruleDraft.row).includes(item.id)} onChange={() => toggleDraftThread(item.id)} />
                        <span>{threadName(item.id)}</span>
                      </label>
                    )) : <div className="empty-inline">暂无帖子预设，请先在目标里添加帖子。</div>}
                  </div>
                )}
              </div>
              {ruleDraft.row.mode !== "author" ? <p className="rule-picker-note">用户和帖子都支持多选。保存时会按“每个帖子监听每个用户”的方式展开。</p> : null}
            </div>
            <div className="modal-subsection">
              <div className="editor-header compact">
                <div>
                  <h3>发送目标</h3>
                  <p>可以添加多个飞书群、微信账号、钉钉用户或收件邮箱。</p>
                </div>
                <IconButton icon={Plus} label="添加发送目标" kind="primary" onClick={openTargetDraft} />
              </div>
              <div className="schedule-target-list">
                {selectedTargets(ruleDraft.row).length ? selectedTargets(ruleDraft.row).map((targetId, index) => (
                  <div className="schedule-target-row" key={`${targetId}-${index}`}>
                    <span>{targetName(targetId)}</span>
                    {onSendTestTarget ? (
                      <button className="btn slim" type="button" disabled={busy} onClick={() => onSendTestTarget(targetId)}>
                        <MessageSquare size={15} />
                        发送测试
                      </button>
                    ) : null}
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
                <p>飞书选择配置组和群；微信/钉钉选择配置组，邮箱填写收件地址。</p>
              </div>
              <IconButton icon={X} label="关闭" onClick={() => setTargetDraft(null)} />
            </div>
            <div className="grid compact-form">
              <label className="field">
                <span>通道</span>
                <select value={targetDraft.channel} onChange={(event) => {
                  const channel = event.target.value;
                  const profile = channel === "wechat" ? wechatProfiles[0] : channel === "dingtalk" ? dingtalkProfiles[0] : channel === "email" ? emailProfiles[0] : channel === "wxpusher" ? wxpusherProfiles[0] : feishuProfiles[0];
                  const chats = channel === "feishu" && profile && Array.isArray(profile.chats) ? profile.chats : [];
                  const receive_id = channel === "dingtalk" ? (profile?.target_user_ids || "") : channel === "wxpusher" ? "" : chats[0]?.chat_id || "";
                  const id_type = channel === "wxpusher" ? "spt" : undefined;
                  setTargetDraft((current) => ({ ...current, channel, profile_id: profile?.id || "", receive_id, id_type }));
                }}>
                  <option value="feishu">飞书</option>
                  <option value="wechat">微信</option>
                  <option value="dingtalk">钉钉</option>
                  <option value="email">邮箱</option>
                  <option value="wxpusher">WxPusher</option>
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
              ) : targetDraft.channel === "dingtalk" ? (
                <>
                  <label className="field">
                    <span>钉钉配置</span>
                    <select value={targetDraft.profile_id} onChange={(event) => {
                      const profile = dingtalkProfiles.find((item) => item.id === event.target.value);
                      setTargetDraft((current) => ({ ...current, profile_id: event.target.value, receive_id: profile?.target_user_ids || "" }));
                    }}>
                      {dingtalkProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profileLabel(profile, "dingtalk")}</option>)}
                    </select>
                  </label>
                  <label className="field">
                    <span>目标用户 ID</span>
                    <input value={targetDraft.receive_id || ""} onChange={(event) => setTargetDraft((current) => ({ ...current, receive_id: event.target.value }))} placeholder="多个用逗号分隔" />
                  </label>
                </>
              ) : targetDraft.channel === "email" ? (
                <>
                  <label className="field">
                    <span>邮箱发信配置</span>
                    <select value={targetDraft.profile_id} onChange={(event) => setTargetDraft((current) => ({ ...current, profile_id: event.target.value }))}>
                      {emailProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profileLabel(profile, "email")}</option>)}
                    </select>
                  </label>
                  <label className="field">
                    <span>收件邮箱</span>
                    <input value={targetDraft.receive_id || ""} onChange={(event) => setTargetDraft((current) => ({ ...current, receive_id: event.target.value }))} placeholder="name@gmail.com" />
                  </label>
                </>
              ) : targetDraft.channel === "wxpusher" ? (
                <>
                  <label className="field">
                    <span>WxPusher 配置</span>
                    <select value={targetDraft.profile_id} onChange={(event) => {
                      const profile = wxpusherProfiles.find((item) => item.id === event.target.value);
                      setTargetDraft((current) => ({ ...current, profile_id: event.target.value, receive_id: "", id_type: "spt" }));
                    }}>
                      {wxpusherProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profileLabel(profile, "wxpusher")}</option>)}
                    </select>
                  </label>
                  <div className="field field-wide preset-summary">
                    <span>发送目标</span>
                    <p>使用所选配置组里的 SPT 发送。</p>
                  </div>
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

function AiAgentControls({ config, setConfig, options, hint = null }) {
  const provider = config.ai_provider || "codex";
  const update = (key, value) => setConfig((current) => ({ ...current, [key]: value }));
  const modelOptions = options.aiModels?.[provider] || [];
  const reasoningOptions = options.aiReasoning?.[provider] || [];
  const providerSpec = ["ai_provider", "AI Agent", "select", options.aiProviders || ["codex", "claude", "codewhale", "custom"]];
  if (provider === "custom") {
    return (
      <div className={`field-wide ai-settings-grid ai-agent-grid ${hint ? "validation-target-active" : ""}`} data-validation-target="ai-settings">
        {hint ? <div className="field-alert field-wide">{hint}</div> : null}
        <Field config={config} setConfig={setConfig} spec={providerSpec} />
        <Field config={config} setConfig={setConfig} spec={["ai_model", "模型", "text"]} />
        <Field config={config} setConfig={setConfig} spec={["ai_reasoning_effort", "思考强度", "text"]} />
      </div>
    );
  }
  const modelValue = modelOptions.includes(config.ai_model) ? config.ai_model : modelOptions[0] || "";
  const reasoningValue = reasoningOptions.includes(config.ai_reasoning_effort) ? config.ai_reasoning_effort : reasoningOptions[0] || "";
  return (
    <div className={`field-wide ai-settings-grid ai-agent-grid ${hint ? "validation-target-active" : ""}`} data-validation-target="ai-settings">
      {hint ? <div className="field-alert field-wide">{hint}</div> : null}
      <Field config={config} setConfig={setConfig} spec={providerSpec} />
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

function AiScheduleTargets({ config, setConfig, pushTargets, feishuProfiles, wechatProfiles, dingtalkProfiles = [], emailProfiles = [], wxpusherProfiles = [], onCreateScheduleTarget, onSendTestTarget, busy = false, hint = null }) {
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
    const channel = feishuProfiles.length ? "feishu" : wechatProfiles.length ? "wechat" : dingtalkProfiles.length ? "dingtalk" : emailProfiles.length ? "email" : "wxpusher";
    const profile = channel === "wechat" ? wechatProfiles[0] : channel === "dingtalk" ? dingtalkProfiles[0] : channel === "email" ? emailProfiles[0] : channel === "wxpusher" ? wxpusherProfiles[0] : feishuProfiles[0];
    const chats = channel === "feishu" && profile && Array.isArray(profile.chats) ? profile.chats : [];
    const receive_id = channel === "dingtalk" ? (profile?.target_user_ids || "") : channel === "wxpusher" ? "" : chats[0]?.chat_id || "";
    const id_type = channel === "wxpusher" ? "spt" : undefined;
    setDraft({ channel, profile_id: profile?.id || "", receive_id, id_type });
  };
  const draftProfile = draft?.channel === "wechat"
    ? wechatProfiles.find((profile) => profile.id === draft.profile_id) || wechatProfiles[0]
    : draft?.channel === "dingtalk"
      ? dingtalkProfiles.find((profile) => profile.id === draft.profile_id) || dingtalkProfiles[0]
    : draft?.channel === "email"
      ? emailProfiles.find((profile) => profile.id === draft.profile_id) || emailProfiles[0]
    : draft?.channel === "wxpusher"
      ? wxpusherProfiles.find((profile) => profile.id === draft.profile_id) || wxpusherProfiles[0]
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
              {onSendTestTarget ? (
                <button className="btn slim" type="button" disabled={busy} onClick={() => onSendTestTarget(targetId)}>
                  <MessageSquare size={15} />
                  发送测试
                </button>
              ) : null}
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
                <p>飞书选择配置组和群；微信/钉钉选择配置组；邮箱选择发信配置并填写收件邮箱。</p>
              </div>
              <IconButton icon={X} label="关闭" onClick={() => setDraft(null)} />
            </div>
            <div className="grid compact-form">
              <label className="field">
                <span>通道</span>
                <select value={draft.channel} onChange={(event) => {
                  const channel = event.target.value;
                  const profile = channel === "wechat" ? wechatProfiles[0] : channel === "dingtalk" ? dingtalkProfiles[0] : channel === "email" ? emailProfiles[0] : channel === "wxpusher" ? wxpusherProfiles[0] : feishuProfiles[0];
                  const chats = channel === "feishu" && profile && Array.isArray(profile.chats) ? profile.chats : [];
                  const receive_id = channel === "dingtalk" ? (profile?.target_user_ids || "") : channel === "wxpusher" ? "" : chats[0]?.chat_id || "";
                  const id_type = channel === "wxpusher" ? "spt" : undefined;
                  setDraft({ channel, profile_id: profile?.id || "", receive_id, id_type });
                }}>
                  <option value="feishu">飞书</option>
                  <option value="wechat">微信</option>
                  <option value="dingtalk">钉钉</option>
                  <option value="email">邮箱</option>
                  <option value="wxpusher">WxPusher</option>
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
              ) : draft.channel === "dingtalk" ? (
                <>
                  <label className="field">
                    <span>钉钉配置</span>
                    <select value={draft.profile_id} onChange={(event) => {
                      const profile = dingtalkProfiles.find((item) => item.id === event.target.value);
                      setDraft((current) => ({ ...current, profile_id: event.target.value, receive_id: profile?.target_user_ids || "" }));
                    }}>
                      {dingtalkProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profileLabel(profile, "dingtalk")}</option>)}
                    </select>
                  </label>
                  <label className="field">
                    <span>目标用户 ID</span>
                    <input value={draft.receive_id || ""} onChange={(event) => setDraft((current) => ({ ...current, receive_id: event.target.value }))} placeholder="多个用逗号分隔" />
                  </label>
                </>
              ) : draft.channel === "email" ? (
                <>
                  <label className="field">
                    <span>邮箱发信配置</span>
                    <select value={draft.profile_id} onChange={(event) => setDraft((current) => ({ ...current, profile_id: event.target.value }))}>
                      {emailProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profileLabel(profile, "email")}</option>)}
                    </select>
                  </label>
                  <label className="field">
                    <span>收件邮箱</span>
                    <input value={draft.receive_id || ""} onChange={(event) => setDraft((current) => ({ ...current, receive_id: event.target.value }))} placeholder="name@gmail.com" />
                  </label>
                </>
              ) : draft.channel === "wxpusher" ? (
                <>
                  <label className="field">
                    <span>WxPusher 配置</span>
                    <select value={draft.profile_id} onChange={(event) => {
                      const profile = wxpusherProfiles.find((item) => item.id === event.target.value);
                      setDraft((current) => ({ ...current, profile_id: event.target.value, receive_id: "", id_type: "spt" }));
                    }}>
                      {wxpusherProfiles.map((profile) => <option key={profile.id} value={profile.id}>{profileLabel(profile, "wxpusher")}</option>)}
                    </select>
                  </label>
                  <div className="field field-wide preset-summary">
                    <span>发送目标</span>
                    <p>使用所选配置组里的 SPT 发送。</p>
                  </div>
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
  const [activePage, setActivePage] = useState(() => pageForHash(window.location.hash));
  const [activeHash, setActiveHash] = useState(() => window.location.hash || "#stock-dashboard");
  const logOffsetRef = useRef(0);
  const bootstrappedRef = useRef(false);

  const channel = selectedChannel === "wechat" ? "wechat" : selectedChannel === "dingtalk" ? "dingtalk" : selectedChannel === "email" ? "email" : selectedChannel === "wxpusher" ? "wxpusher" : "feishu";
  const feishuProfiles = useMemo(() => parseProfiles(config, "feishu_bot_profiles"), [config]);
  const wechatProfiles = useMemo(() => parseProfiles(config, "wechat_bot_profiles"), [config]);
  const dingtalkProfiles = useMemo(() => parseProfiles(config, "dingtalk_bot_profiles"), [config]);
  const emailProfiles = useMemo(() => parseProfiles(config, "email_smtp_profiles"), [config]);
  const wxpusherProfiles = useMemo(() => parseProfiles(config, "wxpusher_profiles"), [config]);
  const pushTargets = useMemo(() => parsePushTargets(config, feishuProfiles, wechatProfiles, dingtalkProfiles, emailProfiles, wxpusherProfiles), [config, feishuProfiles, wechatProfiles, dingtalkProfiles, emailProfiles, wxpusherProfiles]);
  const listenRules = useMemo(() => parseListenRules(config), [config]);
  const authorRows = useMemo(() => parseTargetList(config.watch_author_ids, config.default_author_id), [config.watch_author_ids, config.default_author_id]);
  const threadRows = useMemo(() => parseTargetList(config.preset_thread_ids, config.default_tid), [config.preset_thread_ids, config.default_tid]);
  const configSnapshot = useMemo(() => JSON.stringify(config), [config]);
  const isDirty = Boolean(savedSnapshot && configSnapshot !== savedSnapshot);
  const setStructured = (patch) => {
    setConfig((current) => {
      const currentFeishu = parseProfiles(current, "feishu_bot_profiles");
      const currentWechat = parseProfiles(current, "wechat_bot_profiles");
      const currentDingtalk = parseProfiles(current, "dingtalk_bot_profiles");
      const currentEmail = parseProfiles(current, "email_smtp_profiles");
      const currentWxPusher = parseProfiles(current, "wxpusher_profiles");
      const currentTargets = parsePushTargets(current, currentFeishu, currentWechat, currentDingtalk, currentEmail, currentWxPusher);
      const currentRules = parseListenRules(current);
      const nextFeishu = patch.feishuProfiles ?? currentFeishu;
      const nextWechat = patch.wechatProfiles ?? currentWechat;
      const nextDingtalk = patch.dingtalkProfiles ?? currentDingtalk;
      const nextEmail = patch.emailProfiles ?? currentEmail;
      const nextWxPusher = patch.wxpusherProfiles ?? currentWxPusher;
      const validFeishuProfiles = new Set(nextFeishu.map((profile) => String(profile.id || "").trim()).filter(Boolean));
      const validWechatProfiles = new Set(nextWechat.map((profile) => String(profile.id || "").trim()).filter(Boolean));
      const validDingtalkProfiles = new Set(nextDingtalk.map((profile) => String(profile.id || "").trim()).filter(Boolean));
      const validEmailProfiles = new Set(nextEmail.map((profile) => String(profile.id || "").trim()).filter(Boolean));
      const validWxPusherProfiles = new Set(nextWxPusher.map((profile) => String(profile.id || "").trim()).filter(Boolean));
      const nextTargets = (patch.pushTargets ?? currentTargets).filter((target) => {
        const channelValue = target.channel === "wechat" ? "wechat" : target.channel === "dingtalk" ? "dingtalk" : target.channel === "email" ? "email" : target.channel === "wxpusher" ? "wxpusher" : "feishu";
        const profileId = String(target.profile_id || "").trim();
        if (!profileId) return true;
        if (channelValue === "wechat") return validWechatProfiles.has(profileId);
        if (channelValue === "dingtalk") return validDingtalkProfiles.has(profileId);
        if (channelValue === "email") return validEmailProfiles.has(profileId);
        if (channelValue === "wxpusher") return validWxPusherProfiles.has(profileId);
        return validFeishuProfiles.has(profileId);
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
        dingtalkProfiles: nextDingtalk,
        emailProfiles: nextEmail,
        wxpusherProfiles: nextWxPusher,
        pushTargets: nextTargets,
        listenRules: nextRules,
      });
    });
  };
  const ensureRouteTarget = (draft) => {
    const channelValue = draft.channel === "wechat" ? "wechat" : draft.channel === "dingtalk" ? "dingtalk" : draft.channel === "email" ? "email" : draft.channel === "wxpusher" ? "wxpusher" : "feishu";
    const profile = channelValue === "wechat"
      ? wechatProfiles.find((item) => item.id === draft.profile_id) || wechatProfiles[0]
      : channelValue === "dingtalk"
        ? dingtalkProfiles.find((item) => item.id === draft.profile_id) || dingtalkProfiles[0]
      : channelValue === "email"
        ? emailProfiles.find((item) => item.id === draft.profile_id) || emailProfiles[0]
      : channelValue === "wxpusher"
        ? wxpusherProfiles.find((item) => item.id === draft.profile_id) || wxpusherProfiles[0]
        : feishuProfiles.find((item) => item.id === draft.profile_id) || feishuProfiles[0];
    const profileId = profile?.id || "";
    const hasWxPusherSpt = channelValue !== "wxpusher" || String(profile?.spts || "").trim();
    const targetIdType = channelValue === "wxpusher" ? "spt" : "";
    const receiveId = channelValue === "wechat" ? String(profile?.target_user_id || "").trim() : channelValue === "dingtalk" ? String(draft.receive_id || profile?.target_user_ids || "").trim() : channelValue === "wxpusher" ? "" : String(draft.receive_id || "").trim();
    if (!profileId || !hasWxPusherSpt || (channelValue !== "wxpusher" && !receiveId)) {
      setMessage(channelValue === "wechat" ? "微信配置缺少目标用户 ID" : channelValue === "dingtalk" ? "钉钉配置缺少目标用户 ID" : channelValue === "email" ? "请选择邮箱发信配置并填写收件邮箱" : channelValue === "wxpusher" ? "请选择 WxPusher 配置并填写 SPT" : "请选择飞书配置和飞书群");
      setMessageKind("error");
      return "";
    }
    let target = pushTargets.find((item) => (item.channel || "feishu") === channelValue && item.profile_id === profileId && item.receive_id === receiveId && (channelValue !== "wxpusher" || (item.id_type || "uid") === targetIdType));
    const nextTargets = [...pushTargets];
    if (!target) {
      const chat = channelValue === "feishu" && Array.isArray(profile?.chats)
        ? profile.chats.find((item) => String(item.chat_id || item.id || "") === receiveId)
        : null;
      target = {
        id: ensureId("target", {}),
        label: channelValue === "feishu" ? String(chat?.name || chat?.title || receiveId) : channelValue === "email" ? receiveId : channelValue === "wxpusher" ? profileLabel(profile, "WxPusher") : profileLabel(profile, channelValue),
        channel: channelValue,
        profile_id: profileId,
        receive_id: receiveId,
        id_type: channelValue === "wechat" || channelValue === "dingtalk" ? "user_id" : channelValue === "email" ? "email" : channelValue === "wxpusher" ? targetIdType : profile?.id_type || "chat_id",
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
      const currentDingtalk = parseProfiles(current, "dingtalk_bot_profiles");
      const currentEmail = parseProfiles(current, "email_smtp_profiles");
      const currentWxPusher = parseProfiles(current, "wxpusher_profiles");
      const currentTargets = parsePushTargets(current, currentFeishu, currentWechat, currentDingtalk, currentEmail, currentWxPusher);
      const currentRules = parseListenRules(current);
      const channelValue = draft.channel === "wechat" ? "wechat" : draft.channel === "dingtalk" ? "dingtalk" : draft.channel === "email" ? "email" : draft.channel === "wxpusher" ? "wxpusher" : "feishu";
      const profile = channelValue === "wechat"
        ? currentWechat.find((item) => item.id === draft.profile_id) || currentWechat[0]
        : channelValue === "dingtalk"
          ? currentDingtalk.find((item) => item.id === draft.profile_id) || currentDingtalk[0]
        : channelValue === "email"
          ? currentEmail.find((item) => item.id === draft.profile_id) || currentEmail[0]
        : channelValue === "wxpusher"
          ? currentWxPusher.find((item) => item.id === draft.profile_id) || currentWxPusher[0]
          : currentFeishu.find((item) => item.id === draft.profile_id) || currentFeishu[0];
      const profileId = profile?.id || "";
      const hasWxPusherSpt = channelValue !== "wxpusher" || String(profile?.spts || "").trim();
      const targetIdType = channelValue === "wxpusher" ? "spt" : "";
      const receiveId = channelValue === "wechat" ? String(profile?.target_user_id || "").trim() : channelValue === "dingtalk" ? String(draft.receive_id || profile?.target_user_ids || "").trim() : channelValue === "wxpusher" ? "" : String(draft.receive_id || "").trim();
      if (!profileId || !hasWxPusherSpt || (channelValue !== "wxpusher" && !receiveId)) {
        setMessage(channelValue === "wechat" ? "微信配置缺少目标用户 ID" : channelValue === "dingtalk" ? "钉钉配置缺少目标用户 ID" : channelValue === "email" ? "请选择邮箱发信配置并填写收件邮箱" : channelValue === "wxpusher" ? "请选择 WxPusher 配置并填写 SPT" : "请选择飞书配置和飞书群");
        setMessageKind("error");
        return current;
      }
      let target = currentTargets.find((item) => (item.channel || "feishu") === channelValue && item.profile_id === profileId && item.receive_id === receiveId && (channelValue !== "wxpusher" || (item.id_type || "uid") === targetIdType));
      const nextTargets = [...currentTargets];
      if (!target) {
        const chat = channelValue === "feishu" && Array.isArray(profile?.chats)
          ? profile.chats.find((item) => String(item.chat_id || item.id || "") === receiveId)
          : null;
        target = {
          id: ensureId("target", {}),
          label: channelValue === "feishu" ? String(chat?.name || chat?.title || receiveId) : channelValue === "email" ? receiveId : channelValue === "wxpusher" ? profileLabel(profile, "WxPusher") : profileLabel(profile, channelValue),
          channel: channelValue,
          profile_id: profileId,
          receive_id: receiveId,
          id_type: channelValue === "wechat" || channelValue === "dingtalk" ? "user_id" : channelValue === "email" ? "email" : channelValue === "wxpusher" ? targetIdType : profile?.id_type || "chat_id",
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
        dingtalkProfiles: currentDingtalk,
        emailProfiles: currentEmail,
        wxpusherProfiles: currentWxPusher,
        pushTargets: nextTargets,
        listenRules: currentRules,
      });
      setMessage("已添加定时发送目标");
      setMessageKind("success");
      return { ...next, ai_schedule_target_ids: selected.join(",") };
    });
  };
  const runningText = status.running ? `运行中 PID ${status.pids?.join(", ")}` : "未启动";
  const openConfigSection = (hash, block = "start") => {
    const section = String(hash || "").replace(/^#/, "");
    if (!section) return;
    const target = document.querySelector(`#${section}`);
    const details = document.getElementById(`section-${section}`) || target?.closest("details");
    if (details && "open" in details) details.open = true;
    (target || details)?.scrollIntoView({ behavior: "smooth", block });
  };
  const navigateTo = (hash, event) => {
    event?.preventDefault();
    const nextHash = hash || "#stock-dashboard";
    if (window.location.hash !== nextHash) window.history.pushState(null, "", nextHash);
    const nextPage = pageForHash(nextHash);
    setActivePage(nextPage);
    setActiveHash(nextHash);
    window.setTimeout(() => {
      if (nextPage === "stock" || nextPage === "quick") {
        document.querySelector(".content")?.scrollTo({ top: 0, behavior: "smooth" });
        window.scrollTo({ top: 0, behavior: "smooth" });
        return;
      }
      openConfigSection(nextHash);
    }, 0);
  };

  const refresh = async () => {
    if (!hasApiMethod("bootstrap") || isClosing()) return;
    try {
      const boot = await api().bootstrap();
      if (isClosing()) return;
      const merged = normalizeConfig(boot.config, boot.defaults);
      setConfig(merged);
      setSelectedChannel(merged.bot_channel === "wechat" ? "wechat" : merged.bot_channel === "dingtalk" ? "dingtalk" : merged.bot_channel === "email" ? "email" : merged.bot_channel === "wxpusher" ? "wxpusher" : "feishu");
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

  useEffect(() => {
    const syncPageFromLocation = () => {
      const hash = window.location.hash || "#stock-dashboard";
      setActiveHash(hash);
      setActivePage(pageForHash(hash));
    };
    window.addEventListener("hashchange", syncPageFromLocation);
    window.addEventListener("popstate", syncPageFromLocation);
    return () => {
      window.removeEventListener("hashchange", syncPageFromLocation);
      window.removeEventListener("popstate", syncPageFromLocation);
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
    setActivePage(section === "quick" ? "quick" : "config");
    setActiveHash(section === "quick" ? "#quick" : `#${section}`);
    setValidationHint({ section, target, text: hintText, token: Date.now() });
    setMessage(firstError);
    setMessageKind("error");
    window.setTimeout(() => {
      const targetElement = document.querySelector(`[data-validation-target="${target}"]`);
      const parentDetails = targetElement?.closest("details");
      if (parentDetails && "open" in parentDetails) parentDetails.open = true;
      if (targetElement) {
        targetElement.scrollIntoView({ behavior: "smooth", block: "center" });
      } else {
        openConfigSection(`#${section}`, "center");
      }
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
          setSelectedChannel(normalized.bot_channel === "wechat" ? "wechat" : normalized.bot_channel === "dingtalk" ? "dingtalk" : normalized.bot_channel === "email" ? "email" : normalized.bot_channel === "wxpusher" ? "wxpusher" : "feishu");
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
      setSelectedChannel(normalized.bot_channel === "wechat" ? "wechat" : normalized.bot_channel === "dingtalk" ? "dingtalk" : normalized.bot_channel === "email" ? "email" : normalized.bot_channel === "wxpusher" ? "wxpusher" : "feishu");
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
      "监听规则里直接选择飞书群、微信账号或收件邮箱；手动查询可以使用所有已保存的用户和帖子。",
      "邮箱通道只用于发送通知，不接收邮件回复或聊天命令；飞书和微信仍可作为交互入口。",
    ],
    []
  );
  const queryChats = (profileId) => run("查询飞书群组", () => api().query_feishu_chats(config, profileId));
  const queryDraftChats = (profile) => api().query_feishu_chats_for_profile(profile);
  const recentDingtalkUser = (profile) => api().recent_dingtalk_user_for_profile(profile);
  const sendTestTarget = (targetId) => run("发送测试消息", () => api().send_test_target(config, targetId));
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
      setSelectedChannel(normalized.bot_channel === "wechat" ? "wechat" : normalized.bot_channel === "dingtalk" ? "dingtalk" : normalized.bot_channel === "email" ? "email" : normalized.bot_channel === "wxpusher" ? "wxpusher" : "feishu");
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
          <a href="#stock-dashboard" className={activeHash === "#stock-dashboard" ? "active" : ""} onClick={(event) => navigateTo("#stock-dashboard", event)}>股票看板</a>
          <a href="#quick" className={activeHash === "#quick" ? "active" : ""} onClick={(event) => navigateTo("#quick", event)}>快速开始</a>
          <a href="#channel" className={activeHash === "#channel" ? "active" : ""} onClick={(event) => navigateTo("#channel", event)}>消息通道</a>
          <a href="#ai" className={activeHash === "#ai" ? "active" : ""} onClick={(event) => navigateTo("#ai", event)}>AI 分析</a>
          <a href="#quiet" className={activeHash === "#quiet" ? "active" : ""} onClick={(event) => navigateTo("#quiet", event)}>免打扰</a>
          <a href="#runtime" className={activeHash === "#runtime" ? "active" : ""} onClick={(event) => navigateTo("#runtime", event)}>运行参数</a>
          <a href="#advanced" className={activeHash === "#advanced" ? "active" : ""} onClick={(event) => navigateTo("#advanced", event)}>高级配置</a>
          <a href="#logs" className={activeHash === "#logs" ? "active" : ""} onClick={(event) => navigateTo("#logs", event)}>日志</a>
        </nav>
      </aside>

      <section className={`content page-${activePage}`}>
        <button id="nga-close-request-trigger" className="visually-hidden" type="button" onClick={openCloseDialog}>
          request close
        </button>
        <button id="nga-tray-exit-trigger" className="visually-hidden" type="button" onClick={() => openCloseDialog({ forceExit: true })}>
          request tray exit
        </button>
        {activePage === "stock" ? <StockDashboard api={api} /> : null}
        {activePage !== "stock" ? (
          <>
        <header>
          <div>
            <div className="title-row">
              <h1>{activePage === "quick" ? "快速开始" : "监听配置"}</h1>
              {isDirty ? (
                <span className="dirty-pill">
                  <AlertTriangle size={15} />
                  有未保存修改
                </span>
              ) : null}
            </div>
            <p>{activePage === "quick" ? "首次使用按顺序完成通道、NGA Cookie、用户/帖子和监听规则。" : "配置消息通道、NGA Cookie、监听规则和 AI 分析。"}</p>
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
        {activePage === "quick" ? (
          <>
        <SetupOverview
          channel={channel}
          authorCount={authorRows.length}
          threadCount={threadRows.length}
          ruleCount={listenRules.length}
          profileCount={channel === "wechat" ? wechatProfiles.length : channel === "dingtalk" ? dingtalkProfiles.length : channel === "email" ? emailProfiles.length : channel === "wxpusher" ? wxpusherProfiles.length : feishuProfiles.length}
        />

        <Section icon={ShieldCheck} title="配置步骤" description="按顺序完成：通道配置、NGA Cookie、用户/帖子、监听规则。" defaultOpen sectionId="quick" hint={sectionHint("quick")}>
          <div id="quick" className="grid" data-validation-target="quick-start">
            <ChannelPicker config={config} setConfig={setConfig} channel={channel} onChannelChange={setSelectedChannel} />
            {channel === "wechat" ? (
              <ProfileGroupEditor title="微信机器人配置组" kind="wechat" rows={wechatProfiles} setRows={(rows) => setStructured({ wechatProfiles: rows })} busy={busy} onQueryChats={queryChats} onQueryDraftChats={queryDraftChats} hint={targetHint("wechat-profiles")} />
            ) : channel === "dingtalk" ? (
              <ProfileGroupEditor title="钉钉机器人配置组" kind="dingtalk" rows={dingtalkProfiles} setRows={(rows) => setStructured({ dingtalkProfiles: rows })} busy={busy} onQueryChats={queryChats} onQueryDraftChats={queryDraftChats} onRecentDingtalkUser={recentDingtalkUser} hint={targetHint("dingtalk-profiles")} />
            ) : channel === "email" ? (
              <ProfileGroupEditor title="邮箱发信配置组" kind="email" rows={emailProfiles} setRows={(rows) => setStructured({ emailProfiles: rows })} busy={busy} onQueryChats={queryChats} onQueryDraftChats={queryDraftChats} hint={targetHint("email-profiles")} />
            ) : channel === "wxpusher" ? (
              <ProfileGroupEditor title="WxPusher 配置组" kind="wxpusher" rows={wxpusherProfiles} setRows={(rows) => setStructured({ wxpusherProfiles: rows })} busy={busy} onQueryChats={queryChats} onQueryDraftChats={queryDraftChats} hint={targetHint("wxpusher-profiles")} />
            ) : (
              <ProfileGroupEditor title="飞书机器人配置组" kind="feishu" rows={feishuProfiles} setRows={(rows) => setStructured({ feishuProfiles: rows })} busy={busy} onQueryChats={queryChats} onQueryDraftChats={queryDraftChats} hint={targetHint("feishu-profiles")} />
            )}
            <NgaCookieField config={config} setConfig={setConfig} hint={targetHint("nga_cookie")} busy={busy} status={cookieCheck} onCheck={checkNgaCookie} />
            <TargetListEditor config={config} setConfig={setConfig} configKey="watch_author_ids" fallbackKey="default_author_id" title="用户 ID 列表" idLabel="用户 UID" hint={targetHint("watch_author_ids")} />
            <TargetListEditor config={config} setConfig={setConfig} configKey="preset_thread_ids" fallbackKey="default_tid" title="帖子预设" idLabel="帖子 ID" hint={targetHint("preset_thread_ids")} />
            <ListenRuleEditor rows={listenRules} setRows={(rows) => setStructured({ listenRules: rows })} authorRows={authorRows} threadRows={threadRows} pushTargets={pushTargets} feishuProfiles={feishuProfiles} wechatProfiles={wechatProfiles} dingtalkProfiles={dingtalkProfiles} emailProfiles={emailProfiles} wxpusherProfiles={wxpusherProfiles} onEnsureRouteTarget={ensureRouteTarget} onSendTestTarget={sendTestTarget} busy={busy} hint={targetHint("listen-rules")} />
          </div>
          <div className="hint-list">
            {threadHelp.map((line) => (
              <span key={line}>{line}</span>
            ))}
          </div>
        </Section>
          </>
        ) : null}

        {activePage === "config" ? (
          <>
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
            ) : channel === "dingtalk" ? (
              <ProfileGroupEditor title="钉钉机器人配置组" kind="dingtalk" rows={dingtalkProfiles} setRows={(rows) => setStructured({ dingtalkProfiles: rows })} busy={busy} onQueryChats={queryChats} onQueryDraftChats={queryDraftChats} onRecentDingtalkUser={recentDingtalkUser} hint={targetHint("dingtalk-profiles")} />
            ) : channel === "email" ? (
              <ProfileGroupEditor title="邮箱发信配置组" kind="email" rows={emailProfiles} setRows={(rows) => setStructured({ emailProfiles: rows })} busy={busy} onQueryChats={queryChats} onQueryDraftChats={queryDraftChats} hint={targetHint("email-profiles")} />
            ) : channel === "wxpusher" ? (
              <ProfileGroupEditor title="WxPusher 配置组" kind="wxpusher" rows={wxpusherProfiles} setRows={(rows) => setStructured({ wxpusherProfiles: rows })} busy={busy} onQueryChats={queryChats} onQueryDraftChats={queryDraftChats} hint={targetHint("wxpusher-profiles")} />
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
            {fieldGroups.ai.filter((spec) => spec[0] === "ai_enabled").map((spec) => (
              <Field key={spec[0]} config={config} setConfig={setConfig} spec={spec} hint={targetHint(spec[0])} />
            ))}
            <AiAgentControls config={config} setConfig={setConfig} options={options} hint={targetHint("ai-settings")} />
            {fieldGroups.ai.filter((spec) => spec[0] !== "ai_enabled").map((spec) => (
              <Field key={spec[0]} config={config} setConfig={setConfig} spec={spec} hint={targetHint(spec[0])} />
            ))}
            <AiScheduleTargets config={config} setConfig={setConfig} pushTargets={pushTargets} feishuProfiles={feishuProfiles} wechatProfiles={wechatProfiles} dingtalkProfiles={dingtalkProfiles} emailProfiles={emailProfiles} wxpusherProfiles={wxpusherProfiles} onCreateScheduleTarget={createScheduleTarget} onSendTestTarget={sendTestTarget} busy={busy} hint={targetHint("ai-schedule-targets")} />
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
          </>
        ) : null}
          </>
        ) : null}
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
