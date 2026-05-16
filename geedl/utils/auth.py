"""EE initialisation helper — the single place that calls ee.Initialize."""

from __future__ import annotations

from typing import TYPE_CHECKING

import ee

if TYPE_CHECKING:
    from ..config import JobConfig


def initialize_ee(cfg: "JobConfig") -> None:
    """Initialise the EE client according to cfg.auth."""
    if cfg.auth.method == "service_account":
        credentials = ee.ServiceAccountCredentials(
            cfg.auth.service_account_email,
            cfg.auth.key_file,
        )
        ee.Initialize(credentials=credentials, project=cfg.asset.project)
    else:
        ee.Initialize(project=cfg.asset.project)
