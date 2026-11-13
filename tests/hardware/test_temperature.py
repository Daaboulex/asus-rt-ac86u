def cpu_sensor(router):
    for zone in router.run("ls /sys/class/thermal").split():
        if not zone.startswith("thermal_zone"):
            continue
        if router.run(f"cat /sys/class/thermal/{zone}/type").strip() == "cpu-thermal":
            return f"/sys/class/thermal/{zone}/temp"
    raise AssertionError("no thermal zone named cpu-thermal")


def test_cpu_temperature_reads_like_a_running_cpu(router):
    millidegrees = int(router.run(f"cat {cpu_sensor(router)}"))
    assert 15_000 <= millidegrees <= 100_000, f"{millidegrees / 1000:.1f} C"


def test_cpu_temperature_rises_under_load(router):
    sensor = cpu_sensor(router)
    idle = int(router.run(f"cat {sensor}"))
    loaded = int(
        router.run(
            "pids=''; for i in 1 2 3 4; do sh -c 'while :; do :; done' & pids=\"$pids $!\"; done; "
            f"sleep 30; cat {sensor}; kill $pids",
            timeout=90,
        )
    )
    assert loaded - idle >= 1_000, (
        f"idle {idle / 1000:.1f} C, after 30 s on all cores {loaded / 1000:.1f} C"
    )
