from datetime import datetime

from tasklane.timing_analysis import ObservedRun, analyze_timing_expectations


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def test_analyze_timing_expectations_accepts_expected_overlap_pattern() -> None:
    runs = [
        ObservedRun(
            name="cpu-exclusive-1",
            resource_class="cpu-exclusive",
            started_at=_dt("2026-03-22T10:00:00+00:00"),
            finished_at=_dt("2026-03-22T10:00:03+00:00"),
        ),
        ObservedRun(
            name="cpu-exclusive-2",
            resource_class="cpu-exclusive",
            started_at=_dt("2026-03-22T10:00:03.200000+00:00"),
            finished_at=_dt("2026-03-22T10:00:06.200000+00:00"),
        ),
        ObservedRun(
            name="gpu-host-exclusive-1",
            resource_class="gpu-host-exclusive",
            started_at=_dt("2026-03-22T10:00:06.400000+00:00"),
            finished_at=_dt("2026-03-22T10:00:09.400000+00:00"),
        ),
        ObservedRun(
            name="gpu-exclusive-1",
            resource_class="gpu-exclusive",
            started_at=_dt("2026-03-22T10:00:00.300000+00:00"),
            finished_at=_dt("2026-03-22T10:00:03.300000+00:00"),
        ),
        ObservedRun(
            name="cpu-light-1",
            resource_class="cpu-light",
            started_at=_dt("2026-03-22T10:00:00.100000+00:00"),
            finished_at=_dt("2026-03-22T10:00:03.100000+00:00"),
        ),
        ObservedRun(
            name="cpu-light-2",
            resource_class="cpu-light",
            started_at=_dt("2026-03-22T10:00:00.120000+00:00"),
            finished_at=_dt("2026-03-22T10:00:03.120000+00:00"),
        ),
    ]

    analysis = analyze_timing_expectations(runs)

    assert analysis.host_exclusive_serial_ok is True
    assert analysis.gpu_serial_ok is True
    assert analysis.cpu_light_parallel_ok is True
    assert analysis.cpu_light_overlaps_host_exclusive is True
    assert analysis.gpu_exclusive_overlaps_cpu_exclusive is True
    assert analysis.errors == []


def test_analyze_timing_expectations_flags_host_exclusive_overlap() -> None:
    runs = [
        ObservedRun(
            name="cpu-exclusive-1",
            resource_class="cpu-exclusive",
            started_at=_dt("2026-03-22T10:00:00+00:00"),
            finished_at=_dt("2026-03-22T10:00:03+00:00"),
        ),
        ObservedRun(
            name="gpu-host-exclusive-1",
            resource_class="gpu-host-exclusive",
            started_at=_dt("2026-03-22T10:00:01+00:00"),
            finished_at=_dt("2026-03-22T10:00:04+00:00"),
        ),
        ObservedRun(
            name="cpu-light-1",
            resource_class="cpu-light",
            started_at=_dt("2026-03-22T10:00:00+00:00"),
            finished_at=_dt("2026-03-22T10:00:03+00:00"),
        ),
        ObservedRun(
            name="cpu-light-2",
            resource_class="cpu-light",
            started_at=_dt("2026-03-22T10:00:00.100000+00:00"),
            finished_at=_dt("2026-03-22T10:00:03.100000+00:00"),
        ),
    ]

    analysis = analyze_timing_expectations(runs)

    assert analysis.host_exclusive_serial_ok is False
    assert any("Host-exclusive runs overlapped" in error for error in analysis.errors)


def test_analyze_timing_expectations_flags_gpu_slot_overlap() -> None:
    runs = [
        ObservedRun(
            name="gpu-exclusive-1",
            resource_class="gpu-exclusive",
            started_at=_dt("2026-03-22T10:00:00+00:00"),
            finished_at=_dt("2026-03-22T10:00:03+00:00"),
        ),
        ObservedRun(
            name="gpu-host-exclusive-1",
            resource_class="gpu-host-exclusive",
            started_at=_dt("2026-03-22T10:00:01+00:00"),
            finished_at=_dt("2026-03-22T10:00:04+00:00"),
        ),
        ObservedRun(
            name="cpu-exclusive-1",
            resource_class="cpu-exclusive",
            started_at=_dt("2026-03-22T10:00:00+00:00"),
            finished_at=_dt("2026-03-22T10:00:03+00:00"),
        ),
    ]

    analysis = analyze_timing_expectations(runs)

    assert analysis.gpu_serial_ok is False
    assert any("GPU-slot runs overlapped" in error for error in analysis.errors)
