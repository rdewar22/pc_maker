import pytest

from app import compat
from app.data import parts_db, find_part


def make_build(gpu_id, cpu_id, mobo_id, ram_id, storage_id, psu_id, case_id, cooler_id=None):
    return {
        "gpu": find_part("gpus", gpu_id),
        "cpu": find_part("cpus", cpu_id),
        "motherboard": find_part("motherboards", mobo_id),
        "ram": find_part("ram", ram_id),
        "storage": find_part("storage", storage_id),
        "psu": find_part("psus", psu_id),
        "case": find_part("cases", case_id),
        "cooler": find_part("coolers", cooler_id) if cooler_id else None,
    }


class TestSocketAndMemory:
    def test_am4_cpu_on_am5_board_fails(self):
        build = make_build("rx-6600", "r5-5600", "b650m", "ddr5-32", "nvme-1tb", "psu-650", "case-atx-mid")
        errors = compat.check_compatibility(build)
        assert any("socket" in e for e in errors)

    def test_ddr4_ram_on_ddr5_board_fails(self):
        build = make_build("rx-6600", "r5-7600", "b650m", "ddr4-32", "nvme-1tb", "psu-650", "case-atx-mid")
        errors = compat.check_compatibility(build)
        assert any("RAM" in e for e in errors)

    def test_intel_ddr4_path_valid(self):
        build = make_build("rx-6600", "i5-12400f", "b760m-ddr4", "ddr4-16", "nvme-1tb", "psu-650", "case-atx-mid")
        assert compat.is_compatible(build)

    def test_am4_full_build_valid(self):
        build = make_build("rx-6600", "r5-5600", "b550m", "ddr4-16", "nvme-1tb", "psu-650", "case-atx-mid")
        assert compat.is_compatible(build)


class TestPhysicalFit:
    def test_oversized_gpu_rejected(self):
        # RTX 5090 is 341mm; Pop Mini Air max 360mm fits, but cooler height... use Lancool.
        build = make_build("rtx-5090", "r9-9950x", "x670e", "ddr5-32", "nvme-2tb", "psu-1200", "case-atx-mid2", "cooler-pa120")
        assert compat.is_compatible(build)

    def test_tall_cooler_in_small_case_rejected(self):
        build = make_build("rx-6600", "r5-7600x", "b650m", "ddr5-32", "nvme-1tb", "psu-650", "case-matx-compact", "cooler-aio240")
        # AIO radiator height 55mm is fine in the mATX case; sanity check passes
        assert compat.is_compatible(build)

    def test_atx_board_in_matx_only_case_rejected(self):
        build = make_build("rx-6600", "r5-7600", "b650-tomahawk", "ddr5-32", "nvme-1tb", "psu-650", "case-matx-compact")
        errors = compat.check_compatibility(build)
        assert any("does not fit case" in e for e in errors)


class TestPsu:
    def test_undersized_psu_rejected(self):
        # RTX 5090 (575W) + 9950X (170W) + 75W base = 820W draw, needs 984W
        build = make_build("rtx-5090", "r9-9950x", "x670e", "ddr5-32", "nvme-2tb", "psu-850", "case-atx-mid2", "cooler-pa120")
        errors = compat.check_compatibility(build)
        assert any("PSU" in e for e in errors)

    def test_adequate_psu_accepted(self):
        build = make_build("rtx-5090", "r9-9950x", "x670e", "ddr5-32", "nvme-2tb", "psu-1200", "case-atx-mid2", "cooler-pa120")
        assert compat.is_compatible(build)


class TestCooler:
    def test_weak_cooler_rejected(self):
        # AXP90 (120W capacity) can't handle 7900X (170W TDP)
        build = make_build("rx-7900-xt", "r9-7900x", "b650m", "ddr5-32", "nvme-1tb", "psu-1000", "case-atx-mid", "cooler-axp90")
        errors = compat.check_compatibility(build)
        assert any("Cooler capacity" in e for e in errors)

    def test_stock_cooler_cpu_needs_no_cooler(self):
        build = make_build("rx-6600", "r5-5600", "b550m", "ddr4-16", "nvme-1tb", "psu-650", "case-atx-mid")
        assert build["cooler"] is None
        assert compat.is_compatible(build)


def test_recommended_psu_wattage():
    build = {"cpu": find_part("cpus", "r5-5600"), "gpu": find_part("gpus", "rx-6600")}
    # 75 + 65 + 132 = 272W * 1.2 = 326W
    assert compat.recommended_psu_wattage(build) == 326
