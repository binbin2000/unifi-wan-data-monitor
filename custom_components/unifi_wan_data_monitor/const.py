"""Constants; no controller credentials belong here."""

DOMAIN = "unifi_wan_data_monitor"
NAME = "UniFi WAN Data Monitor"
DEFAULTS = {"quota_gb": 100.0, "billing_day": 1, "poll_interval": 60, "initial_used_gb": 0.0}
PLATFORMS = ["sensor", "binary_sensor"]
