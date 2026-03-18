import type { ScraperSourceQualityRow } from "../types";

type Props = {
  rows: ScraperSourceQualityRow[];
  windowHours?: number;
};

const formatLatest = (minutesSinceLatest: number | null) => {
  if (minutesSinceLatest === null) return "No snapshots yet";
  if (minutesSinceLatest < 1) return "just now";
  if (minutesSinceLatest < 60) return `${minutesSinceLatest} min ago`;
  const hours = Math.floor(minutesSinceLatest / 60);
  const minutes = minutesSinceLatest % 60;
  if (hours < 24) return `${hours}h ${minutes}m ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
};

export const SourceQualityPanel = ({ rows, windowHours = 24 }: Props) => {
  const sortedRows = [...rows].sort((left, right) => {
    const leftCoverage = left.effective_coverage_pct_24h ?? left.coverage_pct_24h;
    const rightCoverage = right.effective_coverage_pct_24h ?? right.coverage_pct_24h;
    if (leftCoverage !== rightCoverage) {
      return rightCoverage - leftCoverage;
    }
    return right.matched_skus_24h - left.matched_skus_24h;
  });

  const classifyCoverage = (row: ScraperSourceQualityRow) => {
    if (row.degraded) return "degraded";
    if (row.stale) return "stale";
    const coverage = row.effective_coverage_pct_24h ?? row.coverage_pct_24h;
    if (coverage >= 80) return "strong";
    if (coverage >= 50) return "fair";
    return "weak";
  };

  return (
    <section className="panel panel-source-quality">
      <h2>Scraper Source Quality ({windowHours}h)</h2>
      <div className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Source</th>
              <th>Mode</th>
              <th className="align-right">Coverage</th>
              <th className="align-right">Matched SKUs</th>
              <th className="align-right">Snapshots</th>
              <th>Latest</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {sortedRows.length === 0 ? (
              <tr>
                <td colSpan={7}>No competitor sources configured.</td>
              </tr>
            ) : (
              sortedRows.map((row) => {
                const coverageClass = classifyCoverage(row);
                const coverageValue = row.effective_coverage_pct_24h ?? row.coverage_pct_24h;
                return (
                  <tr key={row.source_id}>
                    <td>{row.source_name}</td>
                    <td>{row.mode}</td>
                    <td className="align-right">{coverageValue.toFixed(1)}%</td>
                    <td className="align-right">{row.matched_skus_24h}</td>
                    <td className="align-right">{row.snapshots_24h}</td>
                    <td>{formatLatest(row.minutes_since_latest)}</td>
                    <td>
                      {coverageClass === "degraded" ? (
                        <span className="status-pill status-pill--danger">Degraded</span>
                      ) : coverageClass === "strong" ? (
                        <span className="status-pill status-pill--healthy">Strong</span>
                      ) : coverageClass === "fair" ? (
                        <span className="status-pill status-pill--caution">Fair</span>
                      ) : coverageClass === "stale" ? (
                        <span className="status-pill status-pill--danger">Stale</span>
                      ) : (
                        <span className="status-pill status-pill--warning">Weak</span>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </section>
  );
};
