"""Провизионеры протоколов (awg / awg_legacy / xray / openvpn / outline)."""

from __future__ import annotations

from vpnhub.infra.provisioning.constants import ProtoSpec, spec_by_id
from vpnhub.infra.provisioning.provisioners.awg import AwgProvisioner
from vpnhub.infra.provisioning.provisioners.base import ClientMaterial, ConfigArtifact, Provisioner, ServerMaterial
from vpnhub.infra.provisioning.provisioners.openvpn import OpenVpnProvisioner
from vpnhub.infra.provisioning.provisioners.outline import OutlineProvisioner
from vpnhub.infra.provisioning.provisioners.xray import XrayProvisioner


def get_provisioner(proto_id: str) -> AwgProvisioner | XrayProvisioner | OpenVpnProvisioner | OutlineProvisioner:
    spec: ProtoSpec = spec_by_id(proto_id)
    if spec.kind == "xray":
        return XrayProvisioner(spec)
    if spec.kind == "openvpn":
        return OpenVpnProvisioner(spec)
    if spec.kind == "outline":
        return OutlineProvisioner(spec)
    return AwgProvisioner(spec)


__all__ = [
    "AwgProvisioner",
    "ClientMaterial",
    "ConfigArtifact",
    "OpenVpnProvisioner",
    "OutlineProvisioner",
    "Provisioner",
    "ServerMaterial",
    "XrayProvisioner",
    "get_provisioner",
]
