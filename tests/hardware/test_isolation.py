import pytest

BRIDGE = "br-lan"
CLIENT = ("hwtest-client", "hwtest-c", "02:00:00:00:15:01")
PEER = ("hwtest-peer", "hwtest-p", "02:00:00:00:15:02")
LEASE = "/tmp/hardware-test-lease"
PING = "ping -c 2 -W 2"


def reaches(router, namespace: str, command: str) -> bool:
    return router.ssh(f"ip netns exec {namespace} {command}", timeout=60).returncode == 0


def lease(router, namespace: str) -> str:
    script = f"{LEASE}-{namespace}"
    router.run(
        f'printf \'#!/bin/sh\\n[ "$1" = bound ] && echo "$ip/$mask" > {script}.address\\n\''
        f" > {script} && chmod +x {script}"
    )
    router.run(
        f"ip netns exec {namespace} udhcpc -i eth0 -n -R -t 5 -s {script} -p {script}.pid"
        " > /dev/null 2>&1"
    )
    address = router.run(f"cat {script}.address").strip()
    router.run(f"ip -n {namespace} addr add {address} dev eth0")
    return address.split("/")[0]


@pytest.fixture
def clients(router):
    pending = router.run("uci changes firewall").strip()
    assert not pending, f"the firewall has uncommitted changes:\n{pending}"
    for namespace, port, mac in (CLIENT, PEER):
        router.run(
            f"ip netns add {namespace} && "
            f"ip link add {port} type veth peer name eth0 netns {namespace} && "
            f"ip -n {namespace} link set lo up && "
            f"ip -n {namespace} link set eth0 address {mac} up && "
            f"ip link set {port} master {BRIDGE} up"
        )
    yield {namespace: lease(router, namespace) for namespace, _, _ in (CLIENT, PEER)}
    router.ssh(
        f"kill $(cat {LEASE}-{CLIENT[0]}.pid {LEASE}-{PEER[0]}.pid); sleep 2; "
        f"ip netns del {CLIENT[0]}; ip netns del {PEER[0]}; rm -f {LEASE}-*; "
        f"uci -q del_list firewall.isolated.entry={CLIENT[2]}; uci commit firewall; fw4 -q reload"
    )


def test_an_isolated_client_only_answers(router, clients):
    gateway = router.run(f"ip -4 -o addr show dev {BRIDGE}").split()[3].split("/")[0]
    client, peer = clients[CLIENT[0]], clients[PEER[0]]
    loaded = router.run("nft list table bridge isolated")
    assert "set clients" in loaded, "the isolation rules are not loaded"
    assert reaches(router, CLIENT[0], f"{PING} {gateway}"), "the client is not on the bridge"

    router.run(
        f"uci add_list firewall.isolated.entry={CLIENT[2]} && uci commit firewall && fw4 -q reload"
    )

    assert reaches(router, PEER[0], f"{PING} {client}"), "the isolated client stopped answering"
    assert not reaches(router, CLIENT[0], f"{PING} {peer}"), "the isolated client reached a peer"
    router.ssh(f"ip neigh del {client} dev {BRIDGE}; ip -n {CLIENT[0]} neigh flush dev eth0")
    assert not reaches(router, CLIENT[0], f"{PING} {gateway}"), (
        "the isolated client reached the router"
    )
    learned = router.run(f"ip neigh show {client} dev {BRIDGE}")
    assert CLIENT[2] in learned, "the isolated client's frames that carry no IP stopped passing"
    resolved = reaches(router, CLIENT[0], f"nslookup openwrt.org {gateway}")
    assert not resolved, "the isolated client resolved a name"
