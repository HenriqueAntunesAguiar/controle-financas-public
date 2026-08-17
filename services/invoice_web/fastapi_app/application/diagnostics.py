"""Caso de uso para inspecionar dependencias sem revelar configuracoes."""

from __future__ import annotations

from fastapi_app.application.ports import AuditLogPort, HealthProbePort


class DiagnosticsUseCase:
    def __init__(self, probes: list[HealthProbePort], audit: AuditLogPort):
        self.probes = probes
        self.audit = audit

    def connections(self) -> dict:
        components = []
        for probe in self.probes:
            status = probe.probe()
            components.append(status.as_dict())
            self.audit.emit(
                "connection.probe",
                level="info" if status.status == "ok" else "warning",
                component=status.component,
                outcome=status.status,
                duration_ms=status.latency_ms,
            )
        return {
            "status": "ok" if all(item["status"] == "ok" for item in components) else "degraded",
            "components": components,
        }

    def logs(self, limit: int = 50) -> list[dict]:
        return self.audit.recent(max(1, min(limit, 200)))
