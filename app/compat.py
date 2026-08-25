"""Compatibility rules between parts in a build.

A build is a dict with keys: gpu, cpu, motherboard, ram, storage, psu, case, cooler
(each value is a part dict from the parts database).
"""

PSU_HEADROOM = 1.2  # 20% headroom over system draw
BASE_SYSTEM_DRAW_W = 75  # mobo, RAM, storage, fans


def check_compatibility(build: dict) -> list:
    """Return a list of compatibility error strings. Empty list = fully compatible."""
    errors = []
    cpu = build.get("cpu")
    gpu = build.get("gpu")
    mobo = build.get("motherboard")
    ram = build.get("ram")
    psu = build.get("psu")
    case = build.get("case")
    cooler = build.get("cooler")

    if cpu and mobo:
        if cpu["socket"] != mobo["socket"]:
            errors.append(
                f"CPU socket {cpu['socket']} does not match motherboard socket {mobo['socket']}"
            )
        if ram and ram["ddr"] not in cpu["ddr"]:
            errors.append(f"RAM {ram['ddr']} is not supported by CPU {cpu['name']}")
    if mobo and ram:
        if ram["ddr"] != mobo["ddr"]:
            errors.append(
                f"RAM {ram['ddr']} does not match motherboard {mobo['ddr']} slots"
            )
    if mobo and case:
        if mobo["form_factor"] not in case["supports_form_factors"]:
            errors.append(
                f"Motherboard {mobo['form_factor']} does not fit case (supports {case['supports_form_factors']})"
            )
    if gpu and case:
        if gpu["length_mm"] > case["max_gpu_len_mm"]:
            errors.append(
                f"GPU length {gpu['length_mm']}mm exceeds case max {case['max_gpu_len_mm']}mm"
            )
    if cooler and case:
        if cooler["height_mm"] > case["max_cooler_height_mm"]:
            errors.append(
                f"Cooler height {cooler['height_mm']}mm exceeds case max {case['max_cooler_height_mm']}mm"
            )
    if cooler and cpu:
        if cpu["socket"] not in cooler["sockets"]:
            errors.append(
                f"Cooler does not support CPU socket {cpu['socket']}"
            )
    if cooler and cpu:
        if cooler["tdp_capacity_w"] < cpu["tdp_w"]:
            errors.append(
                f"Cooler capacity {cooler['tdp_capacity_w']}W insufficient for CPU TDP {cpu['tdp_w']}W"
            )
    if psu and cpu and gpu:
        draw = BASE_SYSTEM_DRAW_W + cpu["tdp_w"] + gpu["tdp_w"]
        if psu["wattage"] < draw * PSU_HEADROOM:
            errors.append(
                f"PSU {psu['wattage']}W too small: system draw ~{draw}W needs >= {int(draw * PSU_HEADROOM)}W"
            )
    return errors


def is_compatible(build: dict) -> bool:
    return not check_compatibility(build)


def recommended_psu_wattage(build: dict) -> int:
    """Minimum PSU wattage (with headroom) for a partial build (cpu+gpu)."""
    draw = BASE_SYSTEM_DRAW_W + build["cpu"]["tdp_w"] + build["gpu"]["tdp_w"]
    return int(draw * PSU_HEADROOM)
