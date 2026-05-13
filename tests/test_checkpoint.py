"""Checkpoint state machine + crash recovery."""

from __future__ import annotations

from pathlib import Path

from geedl.io.checkpoint import Checkpoint


def test_register_and_claim(tmp_path: Path):
    ckpt = Checkpoint(tmp_path / "ck.db")
    ckpt.register_tiles(["A00_2023", "B01_2023"])
    assert set(ckpt.pending_ids()) == {"A00_2023", "B01_2023"}
    assert ckpt.claim("A00_2023") is True
    assert ckpt.status("A00_2023") == "in_flight"
    # Second claim must fail.
    assert ckpt.claim("A00_2023") is False


def test_mark_done(tmp_path: Path):
    ckpt = Checkpoint(tmp_path / "ck.db")
    ckpt.register_tiles(["X"])
    ckpt.claim("X")
    ckpt.mark_done("X", str(tmp_path / "X.tif"))
    assert ckpt.status("X") == "done"
    assert ckpt.counts() == {"done": 1}


def test_mark_failed_then_retry(tmp_path: Path):
    ckpt = Checkpoint(tmp_path / "ck.db")
    ckpt.register_tiles(["X"])
    ckpt.claim("X")
    ckpt.mark_failed("X", "boom")
    assert ckpt.status("X") == "failed"
    # claim() should re-pick up failed tiles too.
    assert ckpt.claim("X") is True
    assert ckpt.status("X") == "in_flight"


def test_crash_recovery_resets_in_flight(tmp_path: Path):
    ckpt = Checkpoint(tmp_path / "ck.db")
    ckpt.register_tiles(["X"])
    ckpt.claim("X")
    # Simulate a half-written file
    out = tmp_path / "X.tif"
    out.write_text("garbage")
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text("garbage")
    # Update output_path so recover can find/delete the files
    ckpt._conn.execute(  # noqa: SLF001 — test reaches into internals
        "UPDATE tiles SET output_path=? WHERE id=?", (str(out), "X"),
    )
    ckpt.recover_from_crash(tmp_path)
    assert ckpt.status("X") == "pending"
    assert not out.exists()
    assert not tmp.exists()


def test_init_job_idempotent(tmp_path: Path):
    ckpt = Checkpoint(tmp_path / "ck.db")
    ckpt.init_job("hash1", "users/me/asset")
    ckpt.init_job("hash1", "users/me/asset")  # idempotent
    job = ckpt.get_job()
    assert job == ("hash1", "users/me/asset")
