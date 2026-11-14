import json
import ssl
import urllib.error
import urllib.request


def test_root_has_a_password(router):
    shadow = router.run("grep '^root:' /etc/shadow").split(":")
    assert shadow[1] not in ("", "*", "!"), "root has no password"


def test_ssh_refuses_password_logins(router):
    config = router.run("uci show dropbear")
    assert "PasswordAuth='off'" in config and "RootPasswordAuth='off'" in config


def test_ssh_is_not_open_on_wan(router):
    zones = json.loads(router.run('ubus call uci get \'{"config":"firewall","type":"zone"}\''))
    wan = [z for z in zones["values"].values() if z.get("name") == "wan"]
    assert wan and wan[0]["input"] in ("REJECT", "DROP")
    dropbear = router.run("uci show dropbear")
    assert "Interface='lan'" in dropbear or "Interface=" not in dropbear


def test_luci_is_served_over_https(router):
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(f"https://{router.host}/", context=context, timeout=15) as reply:
        assert reply.status == 200


class KeepRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def test_luci_over_http_redirects_to_https(router):
    opener = urllib.request.build_opener(KeepRedirect)
    try:
        opener.open(f"http://{router.host}/", timeout=15)
    except urllib.error.HTTPError as reply:
        assert reply.code in (301, 302, 307, 308), f"plain HTTP answered {reply.code}"
        assert reply.headers["Location"].startswith("https://")
        return
    raise AssertionError("plain HTTP served LuCI without redirecting to HTTPS")
