def cpu_sensor(router):
    for hwmon in router.run("ls /sys/class/hwmon").split():
        if router.run(f"cat /sys/class/hwmon/{hwmon}/name").strip() == "bcm4908_cpu":
            return f"/sys/class/hwmon/{hwmon}/temp1_input"
    raise AssertionError("no hwmon device named bcm4908_cpu")


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
