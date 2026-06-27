import React, { useEffect, useMemo, useRef, useState } from "react";
import * as echarts from "echarts";
import {
  ArrowLeft,
  BarChart3,
  Briefcase,
  ChevronLeft,
  ChevronRight,
  Download,
  GripVertical,
  Layers3,
  LineChart,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Star,
  Trash2,
  Upload,
} from "lucide-react";

const FOCUS_GROUP = "重点关注";

const PERIODS = [
  ["minute", "分时"],
  ["m5", "5分"],
  ["m15", "15分"],
  ["m30", "30分"],
  ["m60", "60分"],
  ["day", "日K"],
  ["week", "周K"],
  ["month", "月K"],
];

const INDICATORS = [
  ["ma", "MA"],
  ["boll", "BOLL"],
  ["both", "MA+BOLL"],
];

const SOURCE_LABELS = {
  "up-leg-high": "上涨段高点",
  "down-leg-low": "下跌段低点",
  "running-tail-high": "尾段新高",
  "running-tail-low": "尾段新低",
  range: "区间兜底",
  none: "无",
};

function toNumber(value) {
  const n = Number.parseFloat(value);
  return Number.isFinite(n) ? n : 0;
}

function formatNumber(value, digits = 2) {
  const n = toNumber(value);
  if (!n) return "--";
  return n.toLocaleString("zh-CN", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function formatCompact(value) {
  const n = toNumber(value);
  if (!n) return "--";
  if (Math.abs(n) >= 100000000) return `${(n / 100000000).toFixed(2)}亿`;
  if (Math.abs(n) >= 10000) return `${(n / 10000).toFixed(2)}万`;
  return n.toFixed(0);
}

function formatPct(value) {
  const n = toNumber(value);
  if (n > 0) return `+${n.toFixed(2)}%`;
  if (n < 0) return `${n.toFixed(2)}%`;
  return "0.00%";
}

function formatTradeDate(value) {
  const raw = String(value || "").replace(/\D/g, "");
  if (raw.length === 8) return `${raw.slice(0, 4)}-${raw.slice(4, 6)}-${raw.slice(6, 8)}`;
  return String(value || "");
}

function hasChartData(payload) {
  if (!payload) return false;
  if (payload.kind === "minute" || payload.kind === "market-minute") return Boolean(payload.main?.points?.length);
  if (payload.kind === "kline") return Boolean(payload.klines?.length);
  return true;
}

function minuteTradeLabel(payload) {
  if (!payload || (payload.kind !== "minute" && payload.kind !== "market-minute")) return "";
  const label = formatTradeDate(payload.main?.date);
  if (!label) return "";
  if (payload.selectedDate) return `${label} 历史分时`;
  return payload.main?.isFallback || payload.main?.source === "recent-trading-day" ? `${label} 最近交易日分时` : `${label} 分时`;
}

function minuteDateOptions(payload) {
  const options = Array.isArray(payload?.recentMinutes) ? payload.recentMinutes : [];
  const seen = new Set();
  const result = [];
  options.forEach((option) => {
    const date = String(option?.date || "");
    if (!date || seen.has(date)) return;
    seen.add(date);
    result.push(option);
  });
  if (payload?.main?.date && !seen.has(String(payload.main.date))) {
    result.unshift({ date: payload.main.date, pointCount: payload.main.points?.length || 0 });
  }
  return result;
}

function priceTone(value) {
  const n = toNumber(value);
  if (n > 0) return "up";
  if (n < 0) return "down";
  return "flat";
}

function isPositionItem(item) {
  return toNumber(item?.cost) > 0 || toNumber(item?.shares) > 0 || Boolean(String(item?.buyDate || "").trim());
}

function positionValue(item) {
  const shares = toNumber(item?.shares);
  const now = toNumber(item?.now);
  return shares > 0 && now > 0 ? shares * now : 0;
}

function positionCostValue(item) {
  const shares = toNumber(item?.shares);
  const cost = toNumber(item?.cost);
  return shares > 0 && cost > 0 ? shares * cost : 0;
}

function positionProfit(item) {
  const shares = toNumber(item?.shares);
  const now = toNumber(item?.now);
  const cost = toNumber(item?.cost);
  return shares > 0 && now > 0 && cost > 0 ? (now - cost) * shares : 0;
}

function positionProfitPct(item) {
  const now = toNumber(item?.now);
  const cost = toNumber(item?.cost);
  return now > 0 && cost > 0 ? ((now - cost) / cost) * 100 : 0;
}

function calcMA(values, period) {
  return values.map((_, index) => {
    if (index < period - 1) return null;
    let sum = 0;
    for (let cursor = index - period + 1; cursor <= index; cursor += 1) sum += values[cursor];
    return +(sum / period).toFixed(3);
  });
}

function calcBoll(values, period = 20, k = 2) {
  return values.map((_, index) => {
    if (index < period - 1) return { mid: null, up: null, low: null };
    const slice = values.slice(index - period + 1, index + 1);
    const mid = slice.reduce((sum, item) => sum + item, 0) / slice.length;
    const variance = slice.reduce((sum, item) => sum + (item - mid) ** 2, 0) / period;
    const std = Math.sqrt(variance);
    return {
      mid: +mid.toFixed(3),
      up: +(mid + k * std).toFixed(3),
      low: +(mid - k * std).toFixed(3),
    };
  });
}

function adviceLabel(className) {
  if (className === "advice-danger") return "danger";
  if (className === "advice-warning") return "warning";
  if (className === "advice-gold") return "gold";
  if (className === "advice-blue") return "blue";
  if (className === "advice-cyan") return "cyan";
  return "normal";
}

function sourceLabel(value) {
  return SOURCE_LABELS[value] || value || "未计算";
}

function stockRowClass(item, activeCode = "") {
  return [
    activeCode === item?.fullCode ? "selected" : "",
    item?.group === FOCUS_GROUP ? "focus-row" : "",
    isPositionItem(item) ? "position-row" : "",
    item?.isBreakLow ? "break-row" : "",
  ].filter(Boolean).join(" ");
}

function KeyValueLine({ label, value, tone = "" }) {
  return (
    <span className="kv-line">
      <b>{label}</b>
      <em className={tone}>{value}</em>
    </span>
  );
}

function StockIdentity({ item, showGroup = true, dragProps = null }) {
  return (
    <div className="stock-name-cell">
      <div className="stock-name-main">
        {dragProps ? (
          <button type="button" className="drag-handle" title="按住拖拽排序" {...dragProps}>
            <GripVertical size={16} />
          </button>
        ) : null}
        <div>
          <strong>{item.name || item.fullCode}</strong>
          <span>{item.fullCode}</span>
          <div className="stock-row-tags">
            {item.group === FOCUS_GROUP ? <em className="stock-tag focus">重点</em> : null}
            {isPositionItem(item) ? <em className="stock-tag position">持仓</em> : null}
            {item.isBreakLow ? <em className="stock-tag warn">破位</em> : null}
            {item.exRights ? <em className="stock-tag ex">除权?</em> : null}
            {showGroup && item.group && item.group !== FOCUS_GROUP ? <em className="stock-tag group">{item.group}</em> : null}
          </div>
        </div>
      </div>
    </div>
  );
}

function QuoteCell({ item }) {
  return (
    <div className={`stock-price ${priceTone(item.changePct)}`}>
      <strong>{formatNumber(item.now, 2)}</strong>
      <span>{formatPct(item.changePct)}</span>
    </div>
  );
}

function LiquidityCell({ item }) {
  const amountUnit = item.fullCode?.startsWith("hk") ? 1 : 10000;
  return (
    <div className="stock-mini-metric">
      <KeyValueLine label="量" value={formatCompact(item.volume)} />
      <KeyValueLine label="额" value={formatCompact(item.amount * amountUnit)} />
      <KeyValueLine label="均" value={formatNumber(item.avg, 3)} />
      <KeyValueLine label="换" value={`${formatNumber(item.turnoverRate, 2)}%`} />
    </div>
  );
}

function FibCell({ item }) {
  return (
    <div className="fib-stack">
      <KeyValueLine label="0.382" value={item.f382 || "--"} />
      <KeyValueLine label="0.618" value={item.f618 || "--"} />
      <KeyValueLine label="0.786" value={item.f786 || "--"} />
    </div>
  );
}

function PressureCell({ item }) {
  return (
    <div className="fib-stack">
      <KeyValueLine label="压" value={item.topLine || "--"} tone="up" />
      <KeyValueLine label="撑" value={item.bottomLine || "--"} tone="down" />
    </div>
  );
}

function StrategyBadge({ className = "", children }) {
  return <span className={`strategy-badge ${className}`}>{children}</span>;
}

function downloadText(filename, text, type = "text/csv;charset=utf-8") {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export default function StockDashboard({ api }) {
  const [watchlist, setWatchlist] = useState({ groups: [], activeGroup: "__all__", items: [] });
  const [indexes, setIndexes] = useState([]);
  const [activeGroup, setActiveGroup] = useState("__all__");
  const [query, setQuery] = useState("");
  const [suggestions, setSuggestions] = useState([]);
  const [newGroup, setNewGroup] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [messageKind, setMessageKind] = useState("info");
  const [chartTarget, setChartTarget] = useState(null);
  const [chartPeriod, setChartPeriod] = useState("day");
  const [chartMinuteDate, setChartMinuteDate] = useState("");
  const [chartIndicator, setChartIndicator] = useState("ma");
  const [chartPayload, setChartPayload] = useState(null);
  const [chartLoading, setChartLoading] = useState(false);
  const [chartError, setChartError] = useState("");
  const [detailOpen, setDetailOpen] = useState(false);
  const [detailQuery, setDetailQuery] = useState("");
  const [boardMode, setBoardMode] = useState("watchlist");
  const [disclaimerOpen, setDisclaimerOpen] = useState(false);
  const [stockDataMeta, setStockDataMeta] = useState({ dataPath: "", dataMtime: 0, dataSize: 0 });
  const chartRef = useRef(null);
  const chartInstanceRef = useRef(null);
  const fileInputRef = useRef(null);
  const refreshInFlightRef = useRef(false);
  const dragSourceCodeRef = useRef("");

  const apiClient = api?.();
  const items = Array.isArray(watchlist.items) ? watchlist.items : [];
  const groups = Array.isArray(watchlist.groups) ? watchlist.groups : [];
  const filteredItems = useMemo(() => {
    if (activeGroup === "__none__") return items.filter((item) => !item.group);
    if (activeGroup !== "__all__") return items.filter((item) => item.group === activeGroup);
    return items;
  }, [activeGroup, items]);
  const positionItems = useMemo(() => items.filter(isPositionItem), [items]);
  const focusItems = useMemo(() => items.filter((item) => item.group === FOCUS_GROUP), [items]);
  const positionSummary = useMemo(() => {
    const marketValue = positionItems.reduce((sum, item) => sum + positionValue(item), 0);
    const costValue = positionItems.reduce((sum, item) => sum + positionCostValue(item), 0);
    const profit = positionItems.reduce((sum, item) => sum + positionProfit(item), 0);
    return {
      marketValue,
      costValue,
      profit,
      profitPct: costValue > 0 ? (profit / costValue) * 100 : 0,
    };
  }, [positionItems]);
  const activeStockItem = useMemo(
    () => (chartTarget?.type === "stock" ? items.find((item) => item.fullCode === chartTarget?.code) || null : null),
    [chartTarget, filteredItems, items]
  );
  const selectedItem = activeStockItem || filteredItems[0] || items[0] || null;
  const detailItems = useMemo(() => {
    const base = boardMode === "positions" ? positionItems : filteredItems.length ? filteredItems : items;
    const keyword = detailQuery.trim().toLowerCase();
    if (!keyword) return base;
    return base.filter((item) => {
      const haystack = [item.name, item.fullCode, item.code, item.group, item.market]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(keyword);
    });
  }, [boardMode, detailQuery, filteredItems, items, positionItems]);

  const applyWatchlist = (next) => {
    if (!next) return;
    setWatchlist(next);
    setDisclaimerOpen(next.disclaimerAccepted === false);
    const nextGroups = Array.isArray(next.groups) ? next.groups : [];
    setActiveGroup((current) => {
      const wanted = current || next.activeGroup || "__all__";
      return wanted === "__all__" || wanted === "__none__" || nextGroups.includes(wanted) ? wanted : "__all__";
    });
    const nextItems = Array.isArray(next.items) ? next.items : [];
    if (nextItems[0]) {
      setChartTarget((current) => current || { type: "stock", code: nextItems[0].fullCode, name: nextItems[0].name });
    }
  };

  const showMessage = (text, kind = "info") => {
    setMessage(text || "");
    setMessageKind(kind);
  };

  const runAction = async (label, action, { silent = false } = {}) => {
    if (!apiClient) {
      return null;
    }
    if (!silent) setBusy(true);
    try {
      const result = await action(apiClient);
      if (!result?.ok) {
        showMessage(result?.error || `${label}失败`, "error");
        return result;
      }
      if (result.watchlist) applyWatchlist(result.watchlist);
      if (result.indexes) setIndexes(result.indexes);
      if (result.dataPath || result.dataMtime) {
        setStockDataMeta({
          dataPath: result.dataPath || stockDataMeta.dataPath || "",
          dataMtime: result.dataMtime || 0,
          dataSize: result.dataSize || 0,
        });
      }
      if (!silent) showMessage(`${label}完成`, "success");
      return result;
    } catch (error) {
      showMessage(String(error?.message || error), "error");
      return null;
    } finally {
      if (!silent) setBusy(false);
    }
  };

  const bootstrap = async () => {
    if (refreshInFlightRef.current) return;
    refreshInFlightRef.current = true;
    try {
      await runAction("加载股票看板", async (client) => {
        const result = await client.stock_bootstrap();
        if (result?.watchlist) applyWatchlist(result.watchlist);
        if (result?.indexes) setIndexes(result.indexes);
        return result;
      }, { silent: true });
    } finally {
      refreshInFlightRef.current = false;
    }
  };

  const runQuoteRefresh = (includeKline = true, { silent = false } = {}) => {
    if (refreshInFlightRef.current) return Promise.resolve(null);
    refreshInFlightRef.current = true;
    return runAction("刷新行情", async (client) => {
      const result = await client.stock_refresh(includeKline);
      if (result?.ok) return result;
      if (typeof client.stock_reload === "function") {
        const fallback = await client.stock_reload(Boolean(includeKline));
        if (fallback?.ok) return fallback;
      }
      return result;
    }, { silent }).finally(() => {
      refreshInFlightRef.current = false;
    });
  };

  useEffect(() => {
    bootstrap();
  }, []);

  useEffect(() => {
    if (!apiClient || !query.trim()) {
      setSuggestions([]);
      return undefined;
    }
    let cancelled = false;
    const timer = window.setTimeout(async () => {
      try {
        const result = await apiClient.stock_search(query.trim(), 10);
        if (!cancelled) setSuggestions(result?.ok ? result.results || [] : []);
      } catch {
        if (!cancelled) setSuggestions([]);
      }
    }, 220);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [query]);

  useEffect(() => {
    if (!apiClient) return undefined;
    const timer = window.setInterval(() => {
      runQuoteRefresh(false, { silent: true });
    }, 3000);
    return () => window.clearInterval(timer);
  }, [apiClient]);

  useEffect(() => {
    if (!chartTarget && selectedItem) {
      setChartTarget({ type: "stock", code: selectedItem.fullCode, name: selectedItem.name });
    }
  }, [chartTarget, selectedItem]);

  const loadChart = async (target = chartTarget, period = chartPeriod, minuteDate = chartMinuteDate, options = {}) => {
    if (!target?.code) return;
    if (!apiClient) {
      setChartPayload(null);
      setChartError("");
      return;
    }
    const showLoading = options.showLoading !== false;
    setChartError("");
    if (showLoading) setChartLoading(true);
    const selectedMinuteDate = period === "minute" ? minuteDate : "";
    try {
      const result = target.type === "market"
        ? await apiClient.stock_market_chart(target.code, period, selectedMinuteDate)
        : await apiClient.stock_chart(target.code, period, selectedMinuteDate);
      if (!result?.ok) {
        setChartError(result?.error || "图表加载失败");
        return;
      }
      setChartPayload({ ...result, target });
    } catch (error) {
      setChartError(String(error?.message || error));
    } finally {
      if (showLoading) setChartLoading(false);
    }
  };

  useEffect(() => {
    if (!chartTarget?.code) return undefined;
    const timer = window.setTimeout(() => loadChart(chartTarget, chartPeriod), detailOpen ? 80 : 0);
    return () => window.clearTimeout(timer);
  }, [chartTarget?.code, chartTarget?.type, chartPeriod, chartMinuteDate, detailOpen]);

  useEffect(() => {
    if (!detailOpen || chartPeriod !== "minute" || chartMinuteDate || !chartTarget?.code || !apiClient) return undefined;
    const timer = window.setInterval(() => {
      loadChart(chartTarget, "minute", "", { showLoading: false });
    }, 3000);
    return () => window.clearInterval(timer);
  }, [detailOpen, chartTarget?.code, chartTarget?.type, chartPeriod, chartMinuteDate, apiClient]);

  useEffect(() => {
    if (!detailOpen || !chartRef.current) return undefined;
    const chart = echarts.init(chartRef.current);
    chartInstanceRef.current = chart;
    const resize = () => chart.resize();
    window.addEventListener("resize", resize);
    window.setTimeout(() => {
      chart.resize();
      renderChart();
    }, 0);
    return () => {
      window.removeEventListener("resize", resize);
      chart.dispose();
      if (chartInstanceRef.current === chart) chartInstanceRef.current = null;
    };
  }, [detailOpen]);

  useEffect(() => {
    if (!detailOpen) return undefined;
    const previousOverflow = document.body.style.overflow;
    const handleKeyDown = (event) => {
      if (event.key === "Escape") setDetailOpen(false);
    };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [detailOpen]);

  useEffect(() => {
    renderChart();
  }, [chartPayload, chartIndicator, items, detailOpen]);

  const renderChart = () => {
    const chart = chartInstanceRef.current;
    if (!chart) return;
    try {
      if (!chartPayload) {
        chart.clear();
        return;
      }
      if (chartPayload.kind === "minute") {
        renderStockMinute(chart, chartPayload.main, chartPayload.target?.name || chartPayload.code);
        return;
      }
      if (chartPayload.kind === "market-minute") {
        renderMarketMinute(chart, chartPayload.main, chartPayload.small, chartPayload.target?.name || chartPayload.code);
        return;
      }
      const strategyItem = chartPayload.target?.type === "market"
        ? { chartIndicator }
        : { ...(chartPayload.item || selectedItem || {}), chartIndicator };
      renderKline(chart, chartPayload.klines || [], strategyItem, chartPayload.target?.name || chartPayload.code);
    } catch (error) {
      chart.clear();
      setChartError(String(error?.message || error));
    }
  };

  const addCurrentQuery = async () => {
    const first = suggestions[0];
    const rawCodes = first ? [first.fullCode] : query.split(/[,\s，、]+/).filter(Boolean);
    if (!rawCodes.length) {
      showMessage("请输入股票代码或名称", "error");
      return;
    }
    const group = activeGroup !== "__all__" && activeGroup !== "__none__" ? activeGroup : "";
    const result = await runAction("添加自选", (client) => client.stock_add_codes(rawCodes, group));
    if (result?.ok) {
      setQuery("");
      setSuggestions([]);
      const code = first?.fullCode || rawCodes[0];
      setChartTarget({ type: "stock", code, name: first?.name || code });
    }
  };

  const addSuggestion = async (item) => {
    const group = activeGroup !== "__all__" && activeGroup !== "__none__" ? activeGroup : "";
    const result = await runAction("添加自选", (client) => client.stock_add_codes([item.fullCode], group));
    if (result?.ok) {
      setQuery("");
      setSuggestions([]);
      setChartTarget({ type: "stock", code: item.fullCode, name: item.name });
    }
  };

  const refresh = (includeKline = true) => runQuoteRefresh(includeKline);

  const updateItem = (code, patch) => runAction("保存股票", (client) => client.stock_update_item(code, patch), { silent: true });

  const markFocus = (item) => updateItem(item.fullCode, { group: FOCUS_GROUP });

  const acceptDisclaimer = () => runAction("确认风险提示", (client) => client.stock_accept_disclaimer(), { silent: true });

  const clearWatchlist = () => {
    if (!items.length) return;
    if (!window.confirm("确定清空所有股票看板数据吗？")) return;
    runAction("清空列表", (client) => client.stock_clear_watchlist());
  };

  const reorderItems = (sourceCode, targetCode) => {
    if (!sourceCode || !targetCode || sourceCode === targetCode) return;
    const nextItems = [...items];
    const from = nextItems.findIndex((item) => item.fullCode === sourceCode);
    const to = nextItems.findIndex((item) => item.fullCode === targetCode);
    if (from < 0 || to < 0 || from === to) return;
    const [moved] = nextItems.splice(from, 1);
    nextItems.splice(to, 0, moved);
    runAction("调整排序", (client) => client.stock_reorder_items(nextItems.map((item) => item.fullCode)), { silent: true });
  };

  const dragPropsFor = (item) => ({
    draggable: true,
    onClick: (event) => event.stopPropagation(),
    onDragStart: (event) => {
      event.stopPropagation();
      dragSourceCodeRef.current = item.fullCode;
      event.dataTransfer.effectAllowed = "move";
      event.dataTransfer.setData("text/plain", item.fullCode);
    },
    onDragOver: (event) => {
      event.preventDefault();
      event.stopPropagation();
      event.dataTransfer.dropEffect = "move";
    },
    onDrop: (event) => {
      event.preventDefault();
      event.stopPropagation();
      const sourceCode = event.dataTransfer.getData("text/plain") || dragSourceCodeRef.current;
      dragSourceCodeRef.current = "";
      reorderItems(sourceCode, item.fullCode);
    },
    onDragEnd: () => {
      dragSourceCodeRef.current = "";
    },
  });

  const deleteItem = (item) => {
    if (!window.confirm(`删除 ${item.name || item.fullCode}？`)) return;
    runAction("删除自选", (client) => client.stock_delete_item(item.fullCode));
  };

  const recalcItem = (item) => runAction("重算策略", (client) => client.stock_recalculate(item.fullCode));

  const addGroup = () => {
    const name = newGroup.trim();
    if (!name || groups.includes(name)) return;
    runAction("新增分组", (client) => client.stock_update_groups([...groups, name], name));
    setNewGroup("");
  };

  const renameGroup = (oldName) => {
    if (oldName === FOCUS_GROUP) {
      showMessage("重点关注是默认分组，不能重命名。", "error");
      return;
    }
    const name = window.prompt("分组名称", oldName);
    const next = String(name || "").trim();
    if (!next || next === oldName || groups.includes(next)) return;
    const nextGroups = groups.map((group) => (group === oldName ? next : group));
    const groupItems = items.filter((item) => item.group === oldName);
    runAction("重命名分组", async (client) => {
      await client.stock_update_groups(nextGroups, activeGroup === oldName ? next : activeGroup);
      for (const item of groupItems) await client.stock_update_item(item.fullCode, { group: next });
      return client.stock_refresh(false);
    });
  };

  const deleteGroup = (name) => {
    if (name === FOCUS_GROUP) {
      showMessage("重点关注是默认分组，不能删除。", "error");
      return;
    }
    if (!window.confirm(`删除分组 ${name}？组内股票会回到未分组。`)) return;
    const nextGroups = groups.filter((group) => group !== name);
    const groupItems = items.filter((item) => item.group === name);
    runAction("删除分组", async (client) => {
      await client.stock_update_groups(nextGroups, activeGroup === name ? "__all__" : activeGroup);
      for (const item of groupItems) await client.stock_update_item(item.fullCode, { group: "" });
      return client.stock_refresh(false);
    });
  };

  const exportCsv = () => runAction("导出 CSV", async (client) => {
    const result = await client.stock_export_csv();
    if (result?.ok) downloadText(result.filename || "策略备份.csv", result.csv || "");
    return result;
  });

  const importCsv = (event) => {
    const file = event.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      runAction("导入 CSV", (client) => client.stock_import_csv(String(reader.result || "")));
      event.target.value = "";
    };
    reader.readAsText(file, "utf-8");
  };

  const setStockTarget = (item) => {
    if (!item) return;
    const target = { type: "stock", code: item.fullCode, name: item.name };
    setChartTarget(target);
    if (chartTarget?.type === "stock" && chartTarget?.code === item.fullCode) {
      loadChart(target, chartPeriod);
    }
  };

  const openStockWorkbench = (item) => {
    setDetailOpen(true);
    setChartError("");
    setStockTarget(item);
  };

  const switchDetailStock = (item) => {
    setStockTarget(item);
  };

  const stepDetailStock = (offset) => {
    const cycleItems = detailItems.length ? detailItems : items;
    if (!cycleItems.length) return;
    const currentIndex = cycleItems.findIndex((item) => item.fullCode === activeStockItem?.fullCode);
    const nextIndex = currentIndex >= 0
      ? (currentIndex + offset + cycleItems.length) % cycleItems.length
      : 0;
    setStockTarget(cycleItems[nextIndex]);
  };

  const chooseMarket = (idx) => {
    setChartTarget({ type: "market", code: idx.fullCode || idx.code, name: idx.name });
    setChartPeriod("minute");
    setDetailOpen(true);
  };

  return (
    <section id="stock-dashboard" className="stock-dashboard">
      <div className="stock-topline">
        <div>
          <h1>股票看板</h1>
          <p>自选、分组、实时行情、量能、K线与牛股策略</p>
        </div>
        <div className="stock-clock" title={stockDataMeta.dataPath ? `本地列表：${stockDataMeta.dataPath}` : ""}>
          <span>刷新</span>
          <strong>{watchlist.lastRefreshTime || "--"}</strong>
        </div>
      </div>

      <div className="market-strip">
        {indexes.map((idx) => (
          <button key={idx.code || idx.fullCode} type="button" className={`market-tile ${priceTone(idx.changePct)}`} onClick={() => chooseMarket(idx)}>
            <span>{idx.name}</span>
            <strong>{formatNumber(idx.now, 2)}</strong>
            <em>{formatPct(idx.changePct)}</em>
          </button>
        ))}
      </div>

      <div className="stock-command-panel">
        <div className="stock-search-box">
          <Search size={18} />
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") addCurrentQuery();
            }}
            placeholder="搜索名称、代码或拼音"
          />
          <button type="button" className="stock-command primary" onClick={addCurrentQuery} disabled={busy}>
            <Plus size={16} />
            添加
          </button>
          {suggestions.length ? (
            <div className="stock-suggestions">
              {suggestions.map((item) => (
                <button key={item.fullCode} type="button" onClick={() => addSuggestion(item)}>
                  <span>
                    <strong>{item.name}</strong>
                    <small>{item.fullCode} · {item.market}{item.type ? ` · ${item.type}` : ""}</small>
                  </span>
                  <em className={priceTone(item.changePct)}>{formatNumber(item.now, 2)} {formatPct(item.changePct)}</em>
                </button>
              ))}
            </div>
          ) : null}
        </div>
        <div className="stock-actions">
          <button type="button" className="stock-command" onClick={() => refresh(true)} disabled={busy} title="刷新行情和策略">
            <RefreshCw size={16} />
            刷新
          </button>
          <button type="button" className="stock-command danger" onClick={clearWatchlist} disabled={busy || !items.length} title="清空列表">
            <Trash2 size={16} />
            清空
          </button>
          <button type="button" className="stock-command" onClick={exportCsv} disabled={busy} title="导出 CSV">
            <Download size={16} />
            导出
          </button>
          <button type="button" className="stock-command" onClick={() => fileInputRef.current?.click()} disabled={busy} title="导入 CSV">
            <Upload size={16} />
            导入
          </button>
          <input ref={fileInputRef} className="visually-hidden" type="file" accept=".csv,text/csv" onChange={importCsv} />
        </div>
      </div>

      {message ? <div className={`stock-message ${messageKind}`}>{message}</div> : null}

      {disclaimerOpen ? (
        <div className="stock-modal-backdrop" role="dialog" aria-modal="true" aria-label="免责声明">
          <div className="stock-disclaimer">
            <h2>免责声明</h2>
            <p>本看板仅用于辅助记录自选、持仓和策略计算结果，不构成任何投资建议。</p>
            <p>行情数据来自公开接口，可能存在延迟、缺失或计算误差；策略信号只用于观察，不代表买卖指令。</p>
            <p>请自行判断风险，盈亏自负。</p>
            <button type="button" className="stock-command primary" onClick={acceptDisclaimer}>
              我已阅读并知晓
            </button>
          </div>
        </div>
      ) : null}

      <div className="stock-board-tabs">
        <button type="button" className={boardMode === "watchlist" && activeGroup === "__all__" ? "active" : ""} onClick={() => { setBoardMode("watchlist"); setActiveGroup("__all__"); }}>
          自选看板 <span>{items.length}</span>
        </button>
        <button type="button" className={boardMode === "positions" ? "active" : ""} onClick={() => setBoardMode("positions")}>
          持仓看板 <span>{positionItems.length}</span>
        </button>
        <button type="button" className={boardMode === "watchlist" && activeGroup === FOCUS_GROUP ? "active" : ""} onClick={() => { setBoardMode("watchlist"); setActiveGroup(FOCUS_GROUP); }}>
          重点关注 <span>{focusItems.length}</span>
        </button>
      </div>

      {boardMode === "watchlist" ? (
        <div className="stock-group-bar">
          <button type="button" className={activeGroup === "__all__" ? "active" : ""} onClick={() => setActiveGroup("__all__")}>
            全部 <span>{items.length}</span>
          </button>
          {groups.map((group) => (
            <button key={group} type="button" className={activeGroup === group ? "active" : ""} onClick={() => setActiveGroup(group)}>
              {group} <span>{items.filter((item) => item.group === group).length}</span>
            </button>
          ))}
          <button type="button" className={activeGroup === "__none__" ? "active" : ""} onClick={() => setActiveGroup("__none__")}>
            未分组 <span>{items.filter((item) => !item.group).length}</span>
          </button>
          <div className="stock-group-editor">
            <Layers3 size={15} />
            <input value={newGroup} onChange={(event) => setNewGroup(event.target.value)} onKeyDown={(event) => event.key === "Enter" && addGroup()} placeholder="新分组" />
            <button type="button" onClick={addGroup}><Plus size={14} /></button>
          </div>
        </div>
      ) : null}

      <div className="stock-workspace">
        {boardMode === "positions" ? (
        <PositionBoard
            items={positionItems}
            summary={positionSummary}
            onOpen={openStockWorkbench}
            onUpdateItem={updateItem}
            onMarkFocus={markFocus}
            dragPropsFor={dragPropsFor}
          />
        ) : (
        <>
        <div className="stock-table-shell">
          <div className="stock-table-header">
            <strong>{activeGroup === "__all__" ? "全部自选" : activeGroup === "__none__" ? "未分组" : activeGroup}</strong>
            <span>{filteredItems.length} 只</span>
          </div>
          <div className="stock-table-scroll">
            <table className="stock-table">
              <thead>
                <tr>
                  <th>股票</th>
                  <th>最新价</th>
                  <th>量能/均价</th>
                  <th>阶段顶底</th>
                  <th>常规/强防/深坑</th>
                  <th>日内压力/支撑</th>
                  <th>操作建议</th>
                  <th>操作建议2</th>
                  <th>分组</th>
                  <th>操作</th>
                </tr>
              </thead>
              <tbody>
                {filteredItems.map((item) => (
                  <tr key={item.fullCode} className={stockRowClass(item, activeStockItem?.fullCode)} onClick={() => openStockWorkbench(item)}>
                    <td>
                      <StockIdentity item={item} dragProps={dragPropsFor(item)} />
                    </td>
                    <td>
                      <QuoteCell item={item} />
                    </td>
                    <td>
                      <LiquidityCell item={item} />
                    </td>
                    <td>
                      <EditablePair
                        high={item.high}
                        low={item.low}
                        onCommit={(patch) => updateItem(item.fullCode, patch)}
                      />
                    </td>
                    <td>
                      <FibCell item={item} />
                    </td>
                    <td>
                      <PressureCell item={item} />
                    </td>
                    <td>
                      <StrategyBadge className={adviceLabel(item.adviceClass)}>{item.signal || "观望"}</StrategyBadge>
                    </td>
                    <td>
                      <StrategyBadge className={`soft ${adviceLabel(item.advice2Class)}`}>{item.advice2 || "待计算"}</StrategyBadge>
                    </td>
                    <td>
                      <select value={item.group || ""} onClick={(event) => event.stopPropagation()} onChange={(event) => updateItem(item.fullCode, { group: event.target.value })}>
                        <option value="">未分组</option>
                        {groups.map((group) => <option key={group} value={group}>{group}</option>)}
                      </select>
                    </td>
                    <td>
                      <div className="row-actions" onClick={(event) => event.stopPropagation()}>
                        <button type="button" onClick={() => openStockWorkbench(item)} title="打开单股工作台"><BarChart3 size={15} /></button>
                        <button type="button" className={item.group === FOCUS_GROUP ? "active" : ""} onClick={() => markFocus(item)} title="设为重点关注"><Star size={15} /></button>
                        <button type="button" onClick={() => recalcItem(item)} title="重算顶底"><RefreshCw size={15} /></button>
                        <button type="button" onClick={() => deleteItem(item)} title="删除"><Trash2 size={15} /></button>
                      </div>
                    </td>
                  </tr>
                ))}
                {!filteredItems.length ? (
                  <tr>
                    <td colSpan="10">
                      <div className="stock-empty">暂无自选</div>
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
        </div>

        {groups.length ? (
          <div className="group-admin stock-main-group-admin">
            {groups.map((group) => (
              <span key={group}>
                {group}
                {group === FOCUS_GROUP ? (
                  <em>默认</em>
                ) : (
                  <>
                    <button type="button" onClick={() => renameGroup(group)} title="重命名"><Pencil size={12} /></button>
                    <button type="button" onClick={() => deleteGroup(group)} title="删除"><Trash2 size={12} /></button>
                  </>
                )}
              </span>
            ))}
          </div>
        ) : null}
        </>
        )}
      </div>

      {detailOpen ? (
        <StockDetailWorkbench
          target={chartTarget}
          item={activeStockItem}
          items={detailItems}
          allCount={items.length}
          activeGroup={activeGroup}
          detailQuery={detailQuery}
          onDetailQueryChange={setDetailQuery}
          onClose={() => setDetailOpen(false)}
          onChooseStock={switchDetailStock}
          onStepStock={stepDetailStock}
          onRefresh={() => refresh(true)}
          onUpdateItem={updateItem}
          onRecalcItem={recalcItem}
          busy={busy}
          chartPeriod={chartPeriod}
          setChartPeriod={setChartPeriod}
          chartMinuteDate={chartMinuteDate}
          setChartMinuteDate={setChartMinuteDate}
          chartIndicator={chartIndicator}
          setChartIndicator={setChartIndicator}
          chartLoading={chartLoading}
          chartError={chartError}
          chartPayload={chartPayload}
          hasChartPayload={hasChartData(chartPayload)}
          chartRef={chartRef}
        />
      ) : null}
    </section>
  );
}

function PositionBoard({ items, summary, onOpen, onUpdateItem, onMarkFocus, dragPropsFor }) {
  return (
    <div className="position-board">
      <div className="position-summary-grid">
        <Metric label="持仓数量" value={`${items.length} 只`} />
        <Metric label="总市值" value={formatNumber(summary.marketValue, 2)} />
        <Metric label="成本市值" value={formatNumber(summary.costValue, 2)} />
        <Metric label="浮盈亏" value={`${formatNumber(summary.profit, 2)} / ${formatPct(summary.profitPct)}`} />
      </div>

      <div className="stock-table-shell">
        <div className="stock-table-header">
          <strong>持仓看板</strong>
          <span>按成本、数量或买入日识别持仓</span>
        </div>
        <div className="stock-table-scroll">
          <table className="stock-table position-table">
            <thead>
              <tr>
                <th>股票</th>
                <th>现价</th>
                <th>持仓信息</th>
                <th>浮盈亏</th>
                <th>阶段顶底</th>
                <th>常规/强防/深坑</th>
                <th>日内压力/支撑</th>
                <th>量能/均价</th>
                <th>操作建议</th>
                <th>操作建议2</th>
                <th>重点</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => {
                const profit = positionProfit(item);
                const profitPct = positionProfitPct(item);
                return (
                  <tr key={item.fullCode} className={stockRowClass(item)} onClick={() => onOpen(item)}>
                    <td>
                      <StockIdentity item={item} dragProps={dragPropsFor(item)} />
                    </td>
                    <td>
                      <QuoteCell item={item} />
                    </td>
                    <td>
                      <HoldingEditor item={item} onCommit={(patch) => onUpdateItem(item.fullCode, patch)} />
                    </td>
                    <td>
                      <div className={`position-profit ${priceTone(profit)}`}>
                        <strong>{formatNumber(profit, 2)}</strong>
                        <span>{formatPct(profitPct)}</span>
                      </div>
                    </td>
                    <td>
                      <EditablePair
                        high={item.high}
                        low={item.low}
                        onCommit={(patch) => onUpdateItem(item.fullCode, patch)}
                      />
                    </td>
                    <td>
                      <FibCell item={item} />
                    </td>
                    <td>
                      <PressureCell item={item} />
                    </td>
                    <td>
                      <LiquidityCell item={item} />
                    </td>
                    <td>
                      <StrategyBadge className={adviceLabel(item.adviceClass)}>{item.signal || "观望"}</StrategyBadge>
                    </td>
                    <td>
                      <StrategyBadge className={`soft ${adviceLabel(item.advice2Class)}`}>{item.advice2 || "待计算"}</StrategyBadge>
                    </td>
                    <td>
                      <button
                        type="button"
                        className={`focus-inline-button ${item.group === FOCUS_GROUP ? "active" : ""}`}
                        onClick={(event) => {
                          event.stopPropagation();
                          onMarkFocus(item);
                        }}
                      >
                        <Star size={15} />
                        {item.group === FOCUS_GROUP ? "已关注" : "设为重点"}
                      </button>
                    </td>
                    <td>
                      <div className="row-actions" onClick={(event) => event.stopPropagation()}>
                        <button type="button" onClick={() => onOpen(item)} title="打开单股工作台"><BarChart3 size={15} /></button>
                      </div>
                    </td>
                  </tr>
                );
              })}
              {!items.length ? (
                <tr>
                  <td colSpan="12">
                    <div className="stock-empty">暂无持仓。给股票填写成本、数量或买入日后会出现在这里。</div>
                  </td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function StockDetailWorkbench({
  target,
  item,
  items,
  allCount,
  activeGroup,
  detailQuery,
  onDetailQueryChange,
  onClose,
  onChooseStock,
  onStepStock,
  onRefresh,
  onUpdateItem,
  onRecalcItem,
  busy,
  chartPeriod,
  setChartPeriod,
  chartMinuteDate,
  setChartMinuteDate,
  chartIndicator,
  setChartIndicator,
  chartLoading,
  chartError,
  chartPayload,
  hasChartPayload,
  chartRef,
}) {
  const isMarket = target?.type === "market";
  const tone = item ? priceTone(item.changePct) : "flat";
  const groupLabel = activeGroup === "__all__" ? "全部自选" : activeGroup === "__none__" ? "未分组" : activeGroup;
  const title = target?.name || item?.name || "单股工作台";
  const code = target?.code || item?.fullCode || "";
  const amountUnit = item?.fullCode?.startsWith("hk") ? 1 : 10000;
  const minuteLabel = chartPeriod === "minute" ? minuteTradeLabel(chartPayload) : "";
  const minuteOptions = chartPeriod === "minute" ? minuteDateOptions(chartPayload) : [];

  return (
    <div className="stock-detail-workbench" role="dialog" aria-modal="true" aria-label="单股详情工作台">
      <div className="workbench-topbar">
        <button type="button" className="workbench-back" onClick={onClose}>
          <ArrowLeft size={18} />
          返回自选看板
        </button>
        <div className="workbench-title">
          <span>{isMarket ? "指数分时" : "单股工作台"}</span>
          <strong>{title}</strong>
          <em>{code}</em>
        </div>
        <div className={`workbench-quote ${tone}`}>
          <strong>{item ? formatNumber(item.now, 2) : "--"}</strong>
          <span>{item ? formatPct(item.changePct) : "指数"}</span>
        </div>
        <div className="workbench-nav">
          <button type="button" onClick={() => onStepStock(-1)} disabled={isMarket || !items.length} title="上一只">
            <ChevronLeft size={18} />
          </button>
          <button type="button" onClick={() => onStepStock(1)} disabled={isMarket || !items.length} title="下一只">
            <ChevronRight size={18} />
          </button>
          <button type="button" className="stock-command" onClick={onRefresh} disabled={busy} title="刷新行情和策略">
            <RefreshCw size={16} />
            刷新
          </button>
        </div>
      </div>

      <div className="workbench-body">
        <aside className="stock-switch-rail">
          <div className="switch-rail-head">
            <span>快速切股</span>
            <strong>{groupLabel} · {items.length}/{allCount}</strong>
          </div>
          <label className="switch-search">
            <Search size={15} />
            <input
              value={detailQuery}
              onChange={(event) => onDetailQueryChange(event.target.value)}
              placeholder="搜索当前列表"
            />
          </label>
          <div className="switch-stock-list">
            {items.map((stock) => (
              <button
                key={stock.fullCode}
                type="button"
                className={stock.fullCode === item?.fullCode ? "active" : ""}
                onClick={() => onChooseStock(stock)}
              >
                <span>
                  <strong>{stock.name || stock.fullCode}</strong>
                  <small>{stock.fullCode}</small>
                </span>
                <em className={priceTone(stock.changePct)}>{formatPct(stock.changePct)}</em>
              </button>
            ))}
            {!items.length ? <div className="switch-empty">没有匹配的自选股</div> : null}
          </div>
        </aside>

        <section className="workbench-chart-panel">
          <div className="chart-toolbar workbench-chart-toolbar">
            <div>
              <strong>{isMarket ? "指数分时" : "走势分析"}</strong>
              <span>{title} {code}{minuteLabel ? ` · ${minuteLabel}` : ""}</span>
            </div>
            <div className="chart-switches">
              {PERIODS.map(([value, label]) => (
                <button key={value} type="button" className={chartPeriod === value ? "active" : ""} onClick={() => setChartPeriod(value)}>
                  {label}
                </button>
              ))}
            </div>
          </div>
          {chartPeriod !== "minute" ? (
            <div className="indicator-switch">
              {INDICATORS.map(([value, label]) => (
                <button key={value} type="button" className={chartIndicator === value ? "active" : ""} onClick={() => setChartIndicator(value)}>
                  {label}
                </button>
              ))}
            </div>
          ) : (
            <div className="minute-date-switch">
              <label>
                <span>分时日期</span>
                <select value={chartMinuteDate} onChange={(event) => setChartMinuteDate(event.target.value)} disabled={chartLoading}>
                  <option value="">最新 / 最近交易日</option>
                  {minuteOptions.map((option) => (
                    <option key={option.date} value={option.date}>
                      {formatTradeDate(option.date)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
          )}
          <div className="chart-frame workbench-chart-frame">
            {chartLoading ? <div className="chart-loading">加载中...</div> : null}
            {!chartLoading && (chartError || !hasChartPayload) ? (
              <div className="chart-empty-state">{chartError || "暂无图表数据"}</div>
            ) : null}
            <div ref={chartRef} className="stock-chart" />
          </div>
        </section>

        <aside className="stock-workbench-side">
          {item && !isMarket ? (
            <>
              <div className="workbench-side-section">
                <div className="side-section-title">
                  <h3>牛股策略</h3>
                  <button type="button" onClick={() => onRecalcItem(item)} title="重算策略">
                    <RefreshCw size={14} />
                  </button>
                </div>
                <div className="strategy-stack workbench-strategy-stack">
                  <span className={`strategy-badge ${adviceLabel(item.adviceClass)}`}>{item.signal || "观望"}</span>
                  <span className={`strategy-badge soft ${adviceLabel(item.advice2Class)}`}>{item.advice2 || "待计算"}</span>
                </div>
              </div>

              <div className="stock-detail-grid workbench-metric-grid">
                <Metric label="成交量" value={formatCompact(item.volume)} />
                <Metric label="成交额" value={formatCompact(item.amount * amountUnit)} />
                <Metric label="换手" value={`${formatNumber(item.turnoverRate, 2)}%`} />
                <Metric label="均价" value={formatNumber(item.avg, 3)} />
                <Metric label="趋势" value={item.trend || "--"} />
                <Metric label="K线状态" value={item.klineStatus || "--"} />
              </div>

              <div className="workbench-side-section">
                <h3>顶底与回撤</h3>
                <div className="side-edit-row">
                  <span>高点 / 低点</span>
                  <EditablePair
                    high={item.high}
                    low={item.low}
                    onCommit={(patch) => onUpdateItem(item.fullCode, patch)}
                  />
                </div>
                <div className="stock-detail-grid workbench-metric-grid compact">
                  <Metric label="0.382" value={item.f382 || "--"} />
                  <Metric label="0.618" value={item.f618 || "--"} />
                  <Metric label="0.786" value={item.f786 || "--"} />
                  <Metric label="顶部来源" value={sourceLabel(item.swingHighSource)} />
                  <Metric label="压力" value={item.topLine || "--"} />
                  <Metric label="支撑" value={item.bottomLine || "--"} />
                </div>
              </div>

              <div className="workbench-side-section">
                <h3>持仓信息</h3>
                <div className="side-edit-row">
                  <span>成本 / 数量 / 买入日</span>
                  <HoldingEditor item={item} onCommit={(patch) => onUpdateItem(item.fullCode, patch)} />
                </div>
                <div className="stock-detail-grid workbench-metric-grid compact">
                  <Metric label="持仓天数" value={item.holdDays || "--"} />
                  <Metric label="浮盈亏" value={`${formatNumber(positionProfit(item), 2)} / ${formatPct(positionProfitPct(item))}`} />
                  <Metric label="底部来源" value={sourceLabel(item.swingLowSource)} />
                </div>
              </div>
            </>
          ) : (
            <div className="market-note workbench-market-note">
              <LineChart size={17} />
              <span>指数分时中白线为所选指数，黄线为中证1000。左侧列表可直接切回个股工作台。</span>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}

function EditablePair({ high, low, onCommit }) {
  const [nextHigh, setNextHigh] = useState(high || "");
  const [nextLow, setNextLow] = useState(low || "");

  useEffect(() => setNextHigh(high || ""), [high]);
  useEffect(() => setNextLow(low || ""), [low]);

  const commit = () => {
    if (String(nextHigh) !== String(high) || String(nextLow) !== String(low)) {
      onCommit({ high: nextHigh, low: nextLow });
    }
  };

  return (
    <div className="editable-pair" onClick={(event) => event.stopPropagation()}>
      <input value={nextHigh} onChange={(event) => setNextHigh(event.target.value)} onBlur={commit} placeholder="高点" />
      <input value={nextLow} onChange={(event) => setNextLow(event.target.value)} onBlur={commit} placeholder="低点" />
    </div>
  );
}

function HoldingEditor({ item, onCommit }) {
  const [cost, setCost] = useState(item.cost || "");
  const [shares, setShares] = useState(item.shares || "");
  const [buyDate, setBuyDate] = useState(item.buyDate || "");

  useEffect(() => setCost(item.cost || ""), [item.cost]);
  useEffect(() => setShares(item.shares || ""), [item.shares]);
  useEffect(() => setBuyDate(item.buyDate || ""), [item.buyDate]);

  const commit = () => {
    const patch = {};
    if (String(cost) !== String(item.cost || "")) patch.cost = cost;
    if (String(shares) !== String(item.shares || "")) patch.shares = shares;
    if (String(buyDate) !== String(item.buyDate || "")) patch.buyDate = buyDate;
    if (Object.keys(patch).length) onCommit(patch);
  };

  return (
    <div className="holding-editor" onClick={(event) => event.stopPropagation()}>
      <input value={cost} onChange={(event) => setCost(event.target.value)} onBlur={commit} placeholder="成本" />
      <input value={shares} onChange={(event) => setShares(event.target.value)} onBlur={commit} placeholder="数量" />
      <input value={buyDate} onChange={(event) => setBuyDate(event.target.value)} onBlur={commit} placeholder="日期" />
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div className="metric">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function renderStockMinute(chart, main, name) {
  if (!main?.points?.length) {
    chart.clear();
    return;
  }
  const times = main.points.map((point) => `${point.time.slice(0, 2)}:${point.time.slice(2, 4)}`);
  const prices = main.points.map((point) => point.price);
  const volumes = main.points.map((point, index) => Math.max(point.volume - (index > 0 ? main.points[index - 1].volume : 0), 0));
  let cumVolume = 0;
  let cumAmount = 0;
  const avgs = main.points.map((point, index) => {
    cumVolume += volumes[index];
    cumAmount += point.price * volumes[index];
    return cumVolume > 0 ? +(cumAmount / cumVolume).toFixed(3) : +point.price.toFixed(3);
  });
  const volumeColors = main.points.map((point, index) => point.price >= (index > 0 ? main.points[index - 1].price : main.prevClose) ? "#d84a4a" : "#1f9d72");
  chart.setOption({
    animation: false,
    tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
    legend: { data: ["现价", "均价"], top: 0 },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    grid: [
      { left: 8, right: 12, top: 30, height: "58%", containLabel: true },
      { left: 8, right: 12, top: "76%", height: "18%", containLabel: true },
    ],
    xAxis: [
      { type: "category", data: times, boundaryGap: false, axisLabel: { interval: 29 } },
      { type: "category", data: times, gridIndex: 1, boundaryGap: false, axisLabel: { show: false }, axisTick: { show: false } },
    ],
    yAxis: [
      { type: "value", scale: true, splitLine: { lineStyle: { color: "#e6edf5" } } },
      { type: "value", gridIndex: 1, axisLabel: { show: false }, splitLine: { show: false } },
    ],
    series: [
      {
        name: "现价",
        type: "line",
        data: prices,
        showSymbol: false,
        lineStyle: { width: 1.7, color: "#132238" },
        markLine: {
          symbol: "none",
          data: [{ yAxis: main.prevClose, lineStyle: { color: "#94a3b8", type: "dashed" }, label: { formatter: "昨收" } }],
        },
      },
      { name: "均价", type: "line", data: avgs, showSymbol: false, lineStyle: { width: 1.6, color: "#d9991f" } },
      { name: "成交量", type: "bar", data: volumes, xAxisIndex: 1, yAxisIndex: 1, itemStyle: { color: ({ dataIndex }) => volumeColors[dataIndex] } },
    ],
  }, true);
  chart.resize();
}

function renderMarketMinute(chart, main, small, name) {
  if (!main?.points?.length) {
    chart.clear();
    return;
  }
  const times = main.points.map((point) => `${point.time.slice(0, 2)}:${point.time.slice(2, 4)}`);
  const smallMap = {};
  if (small?.points) small.points.forEach((point) => { smallMap[point.time] = point; });
  const toPct = (price, base) => (base > 0 ? +(((price - base) / base) * 100).toFixed(3) : null);
  const whitePct = main.points.map((point) => toPct(point.price, main.prevClose));
  const yellowPct = main.points.map((point) => {
    const peer = smallMap[point.time];
    return peer && small.prevClose > 0 ? toPct(peer.price, small.prevClose) : null;
  });
  const volumes = main.points.map((point, index) => Math.max(point.volume - (index > 0 ? main.points[index - 1].volume : 0), 0));
  const volumeColors = main.points.map((point, index) => point.price >= (index > 0 ? main.points[index - 1].price : main.prevClose) ? "#d84a4a" : "#1f9d72");
  const whiteName = `${name}(白线)`;
  chart.setOption({
    animation: false,
    tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
    legend: { data: [whiteName, "中证1000(黄线)"], top: 0 },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    grid: [
      { left: 8, right: 12, top: 30, height: "58%", containLabel: true },
      { left: 8, right: 12, top: "76%", height: "18%", containLabel: true },
    ],
    xAxis: [
      { type: "category", data: times, boundaryGap: false, axisLabel: { interval: 29 } },
      { type: "category", data: times, gridIndex: 1, boundaryGap: false, axisLabel: { show: false }, axisTick: { show: false } },
    ],
    yAxis: [
      { type: "value", scale: true, axisLabel: { formatter: (value) => `${value.toFixed(2)}%` }, splitLine: { lineStyle: { color: "#e6edf5" } } },
      { type: "value", gridIndex: 1, axisLabel: { show: false }, splitLine: { show: false } },
    ],
    series: [
      {
        name: whiteName,
        type: "line",
        data: whitePct,
        showSymbol: false,
        lineStyle: { width: 1.7, color: "#132238" },
        markLine: { symbol: "none", data: [{ yAxis: 0, lineStyle: { color: "#94a3b8", type: "dashed" }, label: { formatter: "昨收" } }] },
      },
      { name: "中证1000(黄线)", type: "line", data: yellowPct, showSymbol: false, lineStyle: { width: 1.6, color: "#d9991f" } },
      { name: "成交量", type: "bar", data: volumes, xAxisIndex: 1, yAxisIndex: 1, itemStyle: { color: ({ dataIndex }) => volumeColors[dataIndex] } },
    ],
  }, true);
  chart.resize();
}

function renderKline(chart, klines, item, name) {
  if (!klines.length) {
    chart.clear();
    return;
  }
  const previousZoom = Array.isArray(chart.getOption?.().dataZoom) ? chart.getOption().dataZoom : [];
  const zoomValue = (index, key, fallback) => {
    const value = Number(previousZoom[index]?.[key]);
    return Number.isFinite(value) ? value : fallback;
  };
  const insideStart = zoomValue(0, "start", 45);
  const insideEnd = zoomValue(0, "end", 100);
  const sliderStart = zoomValue(1, "start", insideStart);
  const sliderEnd = zoomValue(1, "end", insideEnd);
  const dates = klines.map((bar) => String(bar.date));
  const candle = klines.map((bar) => [bar.open, bar.close, bar.low, bar.high]);
  const closes = klines.map((bar) => toNumber(bar.close));
  const volumes = klines.map((bar) => toNumber(bar.volume));
  const volumeColors = klines.map((bar) => toNumber(bar.close) >= toNumber(bar.open) ? "#d84a4a" : "#1f9d72");
  const series = [
    {
      name,
      type: "candlestick",
      data: candle,
      itemStyle: { color: "#d84a4a", color0: "#1f9d72", borderColor: "#d84a4a", borderColor0: "#1f9d72" },
      markLine: {
        symbol: "none",
        silent: true,
        data: buildMarkLines(item),
      },
    },
  ];
  const legend = [name];
  if (item?.chartIndicator !== "boll") {
    legend.push("MA5", "MA15", "MA20");
    series.push(
      { name: "MA5", type: "line", data: calcMA(closes, 5), showSymbol: false, smooth: true, lineStyle: { width: 1.4, color: "#d9991f" } },
      { name: "MA15", type: "line", data: calcMA(closes, 15), showSymbol: false, smooth: true, lineStyle: { width: 1.4, color: "#7c6ee6" } },
      { name: "MA20", type: "line", data: calcMA(closes, 20), showSymbol: false, smooth: true, lineStyle: { width: 1.5, color: "#2367b6" } },
    );
  }
  if (item?.chartIndicator === "boll" || item?.chartIndicator === "both") {
    const boll = calcBoll(closes);
    legend.push("BOLL上轨", "BOLL中轨", "BOLL下轨");
    series.push(
      { name: "BOLL上轨", type: "line", data: boll.map((bar) => bar.up), showSymbol: false, lineStyle: { width: 1, type: "dashed", color: "#d84a4a" } },
      { name: "BOLL中轨", type: "line", data: boll.map((bar) => bar.mid), showSymbol: false, lineStyle: { width: 1.4, color: "#d9991f" } },
      { name: "BOLL下轨", type: "line", data: boll.map((bar) => bar.low), showSymbol: false, lineStyle: { width: 1, type: "dashed", color: "#1f9d72" } },
    );
  }
  series.push({ name: "成交量", type: "bar", data: volumes, xAxisIndex: 1, yAxisIndex: 1, itemStyle: { color: ({ dataIndex }) => volumeColors[dataIndex] } });
  chart.setOption({
    animation: false,
    tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
    legend: { data: legend, top: 0 },
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    grid: [
      { left: 8, right: 12, top: 32, height: "58%", containLabel: true },
      { left: 8, right: 12, top: "76%", height: "18%", containLabel: true },
    ],
    xAxis: [
      { type: "category", data: dates, boundaryGap: true },
      { type: "category", data: dates, gridIndex: 1, boundaryGap: true, axisLabel: { show: false }, axisTick: { show: false } },
    ],
    yAxis: [
      { type: "value", scale: true, splitLine: { lineStyle: { color: "#e6edf5" } } },
      { type: "value", gridIndex: 1, axisLabel: { show: false }, splitLine: { show: false } },
    ],
    dataZoom: [
      { type: "inside", xAxisIndex: [0, 1], start: insideStart, end: insideEnd },
      { type: "slider", xAxisIndex: [0, 1], start: sliderStart, end: sliderEnd, bottom: 4, height: 18 },
    ],
    series,
  }, true);
  chart.resize();
}

function buildMarkLines(item) {
  if (!item) return [];
  const lines = [
    ["0.382", item.f382, "#159c9c"],
    ["0.618", item.f618, "#d9991f"],
    ["0.786", item.f786, "#d84a4a"],
    ["压力", item.topLine, "#7c6ee6"],
    ["支撑", item.bottomLine, "#1f9d72"],
  ];
  return lines
    .filter(([, value]) => toNumber(value) > 0)
    .map(([label, value, color]) => ({
      yAxis: toNumber(value),
      label: { formatter: `${label} ${value}`, position: "insideEndTop", color, fontSize: 10 },
      lineStyle: { color, type: "dashed", width: 1 },
    }));
}
