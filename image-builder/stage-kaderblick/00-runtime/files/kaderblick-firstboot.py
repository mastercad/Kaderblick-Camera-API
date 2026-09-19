#!/usr/bin/env python3
"""Wendet die beim Flashen erzeugte Kamerakonfiguration an."""

import json
import ipaddress
import os
import pathlib
import pwd
import re
import subprocess


CONFIG_PATHS = (
    pathlib.Path("/boot/firmware/kaderblick-config.json"),
    pathlib.Path("/boot/kaderblick-config.json"),
)
ACCOUNT_RE = re.compile(r"^[a-z_][a-z0-9_-]{0,31}$")


def run(*args: str, input_text: str | None = None) -> None:
    subprocess.run(args, input=input_text, text=True, check=True)


def load_configuration() -> tuple[pathlib.Path, dict]:
    for path in CONFIG_PATHS:
        if path.exists():
            return path, json.loads(path.read_text(encoding="utf-8"))
    raise RuntimeError("kaderblick-config.json fehlt")


def validate(config: dict) -> None:
    if config.get("schema") != 1 or config.get("camera") not in (1, 2):
        raise ValueError("Ungültiges Konfigurationsformat")
    if not ACCOUNT_RE.fullmatch(config.get("username", "")):
        raise ValueError("Ungültiger Benutzername")
    if not config.get("password") or any(char in config["password"] for char in "\r\n"):
        raise ValueError("Ungültiges Passwort")
    prefix = config.get("prefix")
    if not isinstance(prefix, int) or not 0 <= prefix <= 32:
        raise ValueError("Ungültige Netzmaske")
    interface = ipaddress.IPv4Interface(f"{config.get('ip', '')}/{prefix}")
    if interface.network.num_addresses > 2 and interface.ip in (
        interface.network.network_address,
        interface.network.broadcast_address,
    ):
        raise ValueError("Unbrauchbare Kamera-IP")
    gateway = config.get("gateway", "")
    if gateway:
        gateway_address = ipaddress.IPv4Address(gateway)
        if gateway_address not in interface.network or gateway_address == interface.ip:
            raise ValueError("Ungültiger Gateway")
        if interface.network.num_addresses > 2 and gateway_address in (
            interface.network.network_address,
            interface.network.broadcast_address,
        ):
            raise ValueError("Unbrauchbarer Gateway")


def configure_account(config: dict) -> str:
    old_name = "kaderblick"
    new_name = config["username"]
    try:
        pwd.getpwnam(new_name)
    except KeyError:
        if new_name != old_name:
            run("groupmod", "--new-name", new_name, old_name)
            run("usermod", "--login", new_name, "--home", f"/home/{new_name}", "--move-home", old_name)
    else:
        if new_name != old_name:
            raise ValueError("Der konfigurierte Benutzername ist bereits vergeben")
    run("chpasswd", input_text=f"{new_name}:{config['password']}\n")
    run(
        "usermod",
        "--append",
        "--groups",
        "video,audio,gpio,spi,i2c,dialout,sudo,systemd-journal",
        new_name,
    )
    for directory in ("/opt/kaderblick", "/srv/kaderblick"):
        run("chown", "-R", f"{new_name}:{new_name}", directory)
    return new_name


def configure_services(username: str) -> None:
    for service in ("camera_service", "kaderblick_app"):
        dropin = pathlib.Path(f"/etc/systemd/system/{service}.service.d/user.conf")
        dropin.parent.mkdir(parents=True, exist_ok=True)
        dropin.write_text(f"[Service]\nUser={username}\nGroup={username}\n", encoding="utf-8")
    sudoers = pathlib.Path("/etc/sudoers.d/kaderblick-api-power")
    sudoers.write_text(
        f"{username} ALL=(root) NOPASSWD: /usr/sbin/shutdown, /usr/sbin/reboot\n",
        encoding="utf-8",
    )
    sudoers.chmod(0o440)
    run("visudo", "--check", "--file", str(sudoers))


def configure_ssh_host_keys() -> None:
    run("ssh-keygen", "-A")


def configure_hostname(hostname: str) -> None:
    pathlib.Path("/etc/hostname").write_text(f"{hostname}\n", encoding="utf-8")
    hosts_path = pathlib.Path("/etc/hosts")
    hosts = hosts_path.read_text(encoding="utf-8") if hosts_path.exists() else ""
    lines = [line for line in hosts.splitlines() if not line.startswith("127.0.1.1")]
    lines.append(f"127.0.1.1\t{hostname}")
    hosts_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    timezone = pathlib.Path("/etc/localtime")
    timezone.unlink(missing_ok=True)
    os.symlink("/usr/share/zoneinfo/Europe/Berlin", timezone)
    pathlib.Path("/etc/timezone").write_text("Europe/Berlin\n", encoding="utf-8")


def configure_network(config: dict) -> None:
    gateway = config.get("gateway", "")
    address = f"{config['ip']}/{config['prefix']}"
    gateway_line = f"Gateway={gateway}\n" if gateway else ""
    network = f"""[Match]
Name=eth0

[Network]
Address={address}
{gateway_line}DHCP=no
LinkLocalAddressing=no
IPv6AcceptRA=no
"""
    path = pathlib.Path("/etc/systemd/network/10-kaderblick-eth0.network")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(network, encoding="utf-8")
    path.chmod(0o600)


def configure_samba(username: str, password: str) -> None:
    marker = "# KADERBLICK MANAGED SHARE"
    smb_path = pathlib.Path("/etc/samba/smb.conf")
    current = smb_path.read_text(encoding="utf-8") if smb_path.exists() else "[global]\n"
    current = current.split(marker, 1)[0].rstrip()
    share = f"""

{marker}
[recordings]
   path = /srv/kaderblick/recordings
   browseable = yes
   read only = no
   valid users = {username}
   create mask = 0664
   directory mask = 0775
   force user = {username}
"""
    smb_path.write_text(current + share, encoding="utf-8")
    run("smbpasswd", "-s", "-a", username, input_text=f"{password}\n{password}\n")
    run("smbpasswd", "-e", username)


def main() -> None:
    config_path, config = load_configuration()
    validate(config)
    configure_ssh_host_keys()
    username = configure_account(config)
    configure_hostname(config["hostname"])
    configure_services(username)
    configure_network(config)
    configure_samba(username, config["password"])
    config_path.unlink()
    pathlib.Path("/var/lib/kaderblick-configured").touch(mode=0o600)


if __name__ == "__main__":
    main()
