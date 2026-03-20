import React, { useState, useEffect } from 'react';
import {
  LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Area, AreaChart,
} from 'recharts';
import { getTrend } from '../api';

/**
 * TrendChart — Repo Health Over Time
 * Line chart showing average entropy score over the last 12 months.
 */

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: 'var(--bg-secondary)',
      border: '1px solid var(--border-subtle)',
      borderRadius: 'var(--radius-sm)',
      padding: '8px 12px',
      fontSize: '0.8rem',
    }}>
      <div style={{ color: 'var(--text-muted)', marginBottom: 4 }}>{label}</div>
      <div style={{ color: 'var(--accent-light)', fontWeight: 600 }}>
        Avg Entropy: {payload[0]?.value?.toFixed(1)}
      </div>
      {payload[0]?.payload?.module_count && (
        <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>
          {payload[0].payload.module_count} modules
        </div>
      )}
    </div>
  );
};

export default function TrendChart({ repoId }) {
  const [data, setData] = useState([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!repoId) return;
    setLoading(true);
    getTrend(repoId, 365)
      .then(d => setData(d))
      .catch(() => setData([]))
      .finally(() => setLoading(false));
  }, [repoId]);

  if (loading) {
    return (
      <div className="loading-container" style={{ minHeight: 200 }}>
        <div className="spinner" />
        <div className="loading-text">Loading trend data…</div>
      </div>
    );
  }

  if (!data.length) {
    return (
      <div className="empty-state" style={{ minHeight: 200 }}>
        <div className="empty-state-text text-muted">
          Not enough historical data yet. Run multiple scans over time to see trends.
        </div>
      </div>
    );
  }

  return (
    <div className="chart-container">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 10, right: 20, left: 0, bottom: 10 }}>
          <defs>
            <linearGradient id="entropyGradient" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#6366f1" stopOpacity={0.3} />
              <stop offset="100%" stopColor="#6366f1" stopOpacity={0.02} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
          <XAxis
            dataKey="date"
            tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
            axisLine={{ stroke: 'var(--border-subtle)' }}
            tickLine={false}
          />
          <YAxis
            domain={[0, 100]}
            tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
            axisLine={{ stroke: 'var(--border-subtle)' }}
            tickLine={false}
            width={35}
          />
          <Tooltip content={<CustomTooltip />} />
          <Area
            type="monotone"
            dataKey="avg_entropy"
            stroke="#6366f1"
            strokeWidth={2}
            fill="url(#entropyGradient)"
            dot={false}
            activeDot={{ r: 4, fill: '#6366f1', stroke: '#fff', strokeWidth: 2 }}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
