import React, { useState, useEffect } from 'react';
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, CartesianGrid, Area, AreaChart,
} from 'recharts';
import { getModuleDetail } from '../api';

/**
 * ModuleDetail — full drilldown view for a single module.
 *
 * Shows:
 * - Signal breakdown bar chart
 * - Entropy trend line (history)
 * - Forecast at 30/60/90 days
 * - Metadata (bus factor, blast radius, authors)
 */

function getSeverityColor(score) {
  if (score >= 85) return 'var(--critical)';
  if (score >= 70) return 'var(--high)';
  if (score >= 50) return 'var(--medium)';
  return 'var(--healthy)';
}

function getSeverityLabel(score) {
  if (score >= 85) return 'CRITICAL';
  if (score >= 70) return 'HIGH';
  if (score >= 50) return 'MEDIUM';
  return 'HEALTHY';
}

function SignalBar({ label, score, color }) {
  return (
    <div className="signal-bar-row">
      <div className="signal-bar-label">{label}</div>
      <div className="signal-bar-track">
        <div
          className="signal-bar-fill"
          style={{
            width: `${Math.max(score, 1)}%`,
            background: `linear-gradient(90deg, ${color}88, ${color})`,
          }}
        />
      </div>
      <div className="signal-bar-value" style={{ color }}>{score?.toFixed(0) ?? '—'}</div>
    </div>
  );
}

const ChartTooltip = ({ active, payload, label }) => {
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
      {payload.map((p, i) => (
        <div key={i} style={{ color: p.stroke || p.fill, fontWeight: 500 }}>
          {p.name}: {p.value?.toFixed(1)}
        </div>
      ))}
    </div>
  );
};

export default function ModuleDetail({ module, repoId }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!repoId || !module) { setLoading(false); return; }
    setLoading(true);
    getModuleDetail(repoId, module.module_path)
      .then(d => setDetail(d))
      .catch(() => setDetail(null))
      .finally(() => setLoading(false));
  }, [repoId, module?.module_path]);

  // Use the immediate module data as fallback
  const m = detail || module;
  if (!m) return null;

  const score = m.entropy_score;
  const color = getSeverityColor(score);
  const label = getSeverityLabel(score);
  const forecast = detail?.forecast;
  const history = detail?.history || [];

  const signalData = [
    { name: 'Knowledge', score: m.knowledge_score, color: '#ef4444' },
    { name: 'Dependencies', score: m.dep_score, color: '#f59e0b' },
    { name: 'Churn', score: m.churn_score, color: '#8b5cf6' },
    { name: 'Age', score: m.age_score, color: '#06b6d4' },
  ];

  return (
    <div>
      {/* Header */}
      <div className="card" style={{ marginBottom: 'var(--space-lg)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 'var(--space-md)' }}>
          <div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: '1rem', marginBottom: 4 }}>
              {m.module_path}
            </div>
            <span className={`severity-badge ${label.toLowerCase()}`}>{label}</span>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '2.5rem', fontWeight: 700, fontFamily: 'var(--font-mono)', color, lineHeight: 1 }}>
              {score?.toFixed(0)}
            </div>
            <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>/ 100</div>
          </div>
        </div>
      </div>

      <div className="detail-panel">
        {/* Signal Breakdown */}
        <div className="card">
          <h3 className="section-title">Signal Breakdown</h3>
          <div className="signal-bars">
            {signalData.map(s => (
              <SignalBar key={s.name} label={s.name} score={s.score} color={s.color} />
            ))}
          </div>
        </div>

        {/* Metadata */}
        <div className="card">
          <h3 className="section-title">Module Metadata</h3>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 'var(--space-md)' }}>
            <div>
              <div className="card-title">Blast Radius</div>
              <div style={{ fontSize: '1.5rem', fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
                {m.blast_radius ?? '—'}
              </div>
              <div className="card-label">modules depend on this</div>
            </div>
            <div>
              <div className="card-title">Bus Factor</div>
              <div style={{
                fontSize: '1.5rem', fontWeight: 700, fontFamily: 'var(--font-mono)',
                color: (m.bus_factor ?? 0) <= 1 ? 'var(--critical)' : 'var(--text-primary)',
              }}>
                {m.bus_factor ?? '—'}
                {(m.bus_factor ?? 0) <= 1 && <span style={{ fontSize: '0.7rem', marginLeft: 6 }}>⚠ CRITICAL</span>}
              </div>
              <div className="card-label">engineers can safely modify</div>
            </div>
            <div>
              <div className="card-title">Active Authors</div>
              <div style={{ fontSize: '1.2rem', fontFamily: 'var(--font-mono)' }}>
                {m.authors_active ?? '—'} / {m.authors_total ?? '—'}
              </div>
              <div className="card-label">still active in last 6 months</div>
            </div>
            <div>
              <div className="card-title">Months Since Refactor</div>
              <div style={{ fontSize: '1.2rem', fontFamily: 'var(--font-mono)' }}>
                {m.months_since_refactor?.toFixed(1) ?? '—'}
              </div>
              <div className="card-label">months since last structural change</div>
            </div>
          </div>
        </div>

        {/* Entropy History */}
        <div className="card">
          <h3 className="section-title">Entropy History</h3>
          {history.length > 1 ? (
            <div className="chart-container" style={{ height: 220 }}>
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={history} margin={{ top: 5, right: 5, left: 0, bottom: 5 }}>
                  <defs>
                    <linearGradient id="scoreGrad" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={color} stopOpacity={0.3} />
                      <stop offset="100%" stopColor={color} stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                  <XAxis dataKey="date" hide />
                  <YAxis domain={[0, 100]} width={30} tick={{ fill: 'var(--text-muted)', fontSize: 10 }} />
                  <Tooltip content={<ChartTooltip />} />
                  <Area type="monotone" dataKey="entropy_score" stroke={color} fill="url(#scoreGrad)" strokeWidth={2} dot={false} name="Entropy" />
                </AreaChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="text-muted text-sm">Not enough data points yet.</div>
          )}
        </div>

        {/* Forecast */}
        <div className="card">
          <h3 className="section-title">Forecast</h3>
          {forecast ? (
            <>
              <div style={{ marginBottom: 'var(--space-md)', fontSize: '0.85rem', color: 'var(--text-secondary)' }}>
                Trend: <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 600, color: forecast.trend_per_month > 0 ? 'var(--critical)' : 'var(--healthy)' }}>
                  {forecast.trend_per_month > 0 ? '+' : ''}{forecast.trend_per_month?.toFixed(2)}/month
                </span>
              </div>
              <div className="forecast-grid">
                {[
                  { period: '30 days', value: forecast.score_30d },
                  { period: '60 days', value: forecast.score_60d },
                  { period: '90 days', value: forecast.score_90d },
                ].map(f => (
                  <div key={f.period} className="forecast-card">
                    <div className="forecast-period">{f.period}</div>
                    <div className="forecast-value" style={{ color: getSeverityColor(f.value) }}>
                      {f.value?.toFixed(0) ?? '—'}
                    </div>
                  </div>
                ))}
              </div>
              {forecast.days_to_unmaintainable && (
                <div style={{ marginTop: 'var(--space-md)', padding: '8px 12px', background: 'var(--critical-bg)', borderRadius: 'var(--radius-sm)', fontSize: '0.8rem', color: 'var(--critical)' }}>
                  ⚠ Estimated unmaintainable in {forecast.days_to_unmaintainable} days ({Math.round(forecast.days_to_unmaintainable / 30)} months)
                </div>
              )}
            </>
          ) : (
            <div className="text-muted text-sm">Forecast not available — needs historical data.</div>
          )}
        </div>
      </div>
    </div>
  );
}
