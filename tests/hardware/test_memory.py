import re

from conftest import RADIO_2G_SLOT, RADIO_5G_SLOT


def test_each_radio_has_its_own_dma_pool(router):
    log = router.dmesg()
    pools = re.findall(r"created restricted DMA pool at (0x[0-9a-f]+)", log)
    assert len(set(pools)) == 2, f"pools: {pools}"
    for slot in (RADIO_2G_SLOT, RADIO_5G_SLOT):
        assert re.search(rf"brcmfmac {slot}: assigned reserved memory node", log), slot


def test_radio_windows_map_only_their_pool(router):
    windows = re.findall(r"IB MEM 0x([0-9a-f]+)\.\.0x([0-9a-f]+) -> 0x([0-9a-f]+)", router.dmesg())
    assert len(windows) == 2, windows
    for start, end, bus in windows:
        assert int(end, 16) - int(start, 16) + 1 <= 0x2000000, (start, end)
        assert int(bus, 16) == int(start, 16), "a pool seen at another bus address than its own"


def test_kernel_keeps_no_default_bounce_buffer(router):
    log = router.dmesg()
    assert "swiotlb=noforce" in router.run("cat /proc/cmdline")
    assert "software IO TLB: mapped" not in log


def test_memory_is_available(router):
    meminfo = router.run("cat /proc/meminfo")
    available = int(re.search(r"MemAvailable:\s+(\d+) kB", meminfo).group(1))
    assert available >= 300 * 1024, f"{available // 1024} MiB available"
