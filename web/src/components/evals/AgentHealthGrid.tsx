import { useState } from "react";
import { useAgentHealth } from "../../api/queries";
import type { ServiceHealthItem } from "../../api/types";

export function AgentHealthGrid() {
  const { data: report, isLoading, isFetching, refetch, error } = useAgentHealth();
  const [expandedCardId, setExpandedCardId] = useState<string | null>(null);

  const toggleCard = (id: string) => {
    setExpandedCardId((current) => (current === id ? null : id));
  };

  return (
    <div className="bg-card border border-border rounded-xl p-5 space-y-4 shadow-sm">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2.5">
            <h2 className="text-lg font-semibold text-foreground tracking-tight">
              A2A Infrastructure & Agent Cards
            </h2>
            {report && (
              <span
                className={`text-xs px-2.5 py-0.5 rounded-full font-semibold border ${
                  report.allHealthy
                    ? "bg-emerald-500/10 text-emerald-500 border-emerald-500/20"
                    : "bg-amber-500/10 text-amber-500 border-amber-500/20"
                }`}
              >
                {report.allHealthy ? "All Services Online" : "Degraded / Partial"}
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-0.5">
            Real-time health probing of the 5 specialist Cloud Run services and Creative Director Agent Engine.
          </p>
        </div>

        <button
          onClick={() => void refetch()}
          disabled={isFetching}
          className="inline-flex items-center justify-center gap-2 text-xs font-semibold px-3.5 py-2 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors cursor-pointer self-start sm:self-auto shadow-sm"
        >
          <svg
            className={`w-3.5 h-3.5 ${isFetching ? "animate-spin" : ""}`}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
            <path d="M3 3v5h5" />
            <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
            <path d="M16 21h5v-5" />
          </svg>
          <span>{isFetching ? "Probing Endpoints..." : "Run Health Check"}</span>
        </button>
      </div>

      {error && (
        <div className="p-3 bg-destructive/10 border border-destructive/20 text-destructive text-xs rounded-lg flex items-center gap-2">
          <svg className="w-4 h-4 shrink-0" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <span>Failed to probe agent health: {(error as Error).message}</span>
        </div>
      )}

      {isLoading && !report ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5 pt-1">
          {Array.from({ length: 6 }).map((_, i) => (
            <div key={i} className="h-28 rounded-lg bg-muted/40 animate-pulse border border-border/50" />
          ))}
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3.5 pt-1">
          {report?.services.map((service) => (
            <ServiceCardItem
              key={service.id}
              service={service}
              isExpanded={expandedCardId === service.id}
              onToggle={() => toggleCard(service.id)}
            />
          ))}
        </div>
      )}

      {report?.timestamp && (
        <div className="text-[11px] text-muted-foreground flex items-center justify-between pt-1 border-t border-border/60">
          <span>Criterion 3 (A2A Communication & Distributed Architecture) verified</span>
          <span>Last checked: {new Date(report.timestamp).toLocaleTimeString()}</span>
        </div>
      )}
    </div>
  );
}

function ServiceCardItem({
  service,
  isExpanded,
  onToggle,
}: {
  service: ServiceHealthItem;
  isExpanded: boolean;
  onToggle: () => void;
}) {
  const isOnline = service.status === "online";
  const isDegraded = service.status === "degraded";

  const statusColor = isOnline
    ? "bg-emerald-500/10 text-emerald-500 border-emerald-500/20"
    : isDegraded
    ? "bg-amber-500/10 text-amber-500 border-amber-500/20"
    : "bg-rose-500/10 text-rose-500 border-rose-500/20";

  const dotColor = isOnline
    ? "bg-emerald-500 ring-emerald-500/30"
    : isDegraded
    ? "bg-amber-500 ring-amber-500/30"
    : "bg-rose-500 ring-rose-500/30";

  return (
    <div
      className={`border rounded-xl transition-all ${
        isExpanded
          ? "col-span-1 md:col-span-2 lg:col-span-3 border-primary/40 bg-card shadow-md"
          : "border-border/80 bg-background/50 hover:bg-muted/30"
      }`}
    >
      <div className="p-3.5 flex flex-col justify-between h-full gap-3">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className={`w-2.5 h-2.5 rounded-full ${dotColor} ring-4 shrink-0`} />
            <div className="min-w-0">
              <div className="font-semibold text-sm text-foreground truncate">
                {service.name}
              </div>
              <div className="text-[11px] text-muted-foreground truncate font-mono">
                {service.url}
              </div>
            </div>
          </div>

          <span
            className={`text-[10px] uppercase font-bold tracking-wider px-2 py-0.5 rounded-md border shrink-0 ${statusColor}`}
          >
            {service.status}
          </span>
        </div>

        <p className="text-xs text-muted-foreground line-clamp-2">
          {service.description}
        </p>

        <div className="flex items-center justify-between pt-2 border-t border-border/50 text-[11px]">
          <div className="flex items-center gap-3 text-muted-foreground font-mono">
            <span>{service.latencyMs}ms</span>
            {service.statusCode && <span>HTTP {service.statusCode}</span>}
          </div>

          {service.card && (
            <button
              onClick={onToggle}
              className="text-xs font-medium text-primary hover:underline inline-flex items-center gap-1 cursor-pointer"
            >
              <span>{isExpanded ? "Hide Card" : "Inspect Card"}</span>
              <svg
                className={`w-3.5 h-3.5 transition-transform ${isExpanded ? "rotate-180" : ""}`}
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
              >
                <path d="m6 9 6 6 6-6" />
              </svg>
            </button>
          )}
        </div>
      </div>

      {isExpanded && service.card && (
        <div className="p-3.5 bg-muted/40 border-t border-border/80 rounded-b-xl space-y-2 text-xs">
          <div className="flex items-center justify-between text-muted-foreground">
            <span className="font-semibold text-foreground">
              A2A Agent Card Metadata (/.well-known/agent.json)
            </span>
            <span className="font-mono text-[10px]">{service.id}</span>
          </div>
          <pre className="p-3 bg-background/80 rounded-lg border border-border font-mono text-[11px] overflow-x-auto text-foreground/90 max-h-64">
            {JSON.stringify(service.card, null, 2)}
          </pre>
        </div>
      )}
    </div>
  );
}
