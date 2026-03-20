import React, { useMemo } from 'react';

/**
 * Entropy Heatmap — Treemap visualization.
 * Box size = relative size (all equal), colour = entropy score.
 * Red (critical >85), Orange (high 70-85), Yellow/Cyan (medium 50-70), Green (healthy <50)
 */

function getColor(score) {
  if (score >= 85) return '#dc2626';
  if (score >= 75) return '#ea580c';
  if (score >= 70) return '#d97706';
  if (score >= 60) return '#ca8a04';
  if (score >= 50) return '#0891b2';
  if (score >= 35) return '#059669';
  return '#16a34a';
}

function getColorOpacity(score) {
  // Higher scores = more opaque
  return 0.6 + (score / 100) * 0.4;
}

export default function Heatmap({ modules = [], onSelect }) {
  const sortedModules = useMemo(
    () => [...modules].sort((a, b) => b.entropy_score - a.entropy_score),
    [modules]
  );

  if (!sortedModules.length) {
    return (
      <div className="empty-state">
        <div className="empty-state-icon">📊</div>
        <div className="empty-state-text">No module data available. Run a scan first.</div>
      </div>
    );
  }

  // Calculate grid dimensions for treemap-like layout
  const total = sortedModules.length;
  const cols = Math.ceil(Math.sqrt(total * 1.5));
  const cellSize = Math.max(80, Math.floor(1200 / cols));

  return (
    <div className="treemap-container" style={{
      display: 'grid',
      gridTemplateColumns: `repeat(auto-fill, minmax(${cellSize}px, 1fr))`,
      gap: '2px',
      padding: '2px',
      background: 'var(--bg-secondary)',
    }}>
      {sortedModules.map(m => {
        const bg = getColor(m.entropy_score);
        const opacity = getColorOpacity(m.entropy_score);
        const shortPath = m.module_path.split('/').pop() || m.module_path;

        return (
          <div
            key={m.module_path}
            className="treemap-cell"
            title={`${m.module_path}\nEntropy: ${m.entropy_score.toFixed(0)}`}
            style={{
              backgroundColor: bg,
              opacity,
              minHeight: cellSize * 0.7,
              flexDirection: 'column',
              justifyContent: 'space-between',
              padding: '8px',
            }}
            onClick={() => onSelect?.(m)}
          >
            <div className="treemap-label">{shortPath}</div>
            <div className="treemap-score" style={{ marginTop: 4 }}>
              {m.entropy_score.toFixed(0)}
            </div>
          </div>
        );
      })}
    </div>
  );
}
