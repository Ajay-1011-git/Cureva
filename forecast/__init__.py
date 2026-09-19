"""Act 4 — the Monte Carlo forecast.

Pure stdlib. No network, no numpy, no dependency on anything that could fail
during a graded run. The forecast is context attached to a real escalation
(PRD FR-18), never a freestanding report.
"""
from forecast.montecarlo import ForecastResult, forecast_site, forecast_study

__all__ = ["ForecastResult", "forecast_site", "forecast_study"]
