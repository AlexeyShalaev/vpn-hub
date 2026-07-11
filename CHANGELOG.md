# Changelog

All notable changes to this project are documented here.

Generated from `backend/src/vpnhub/infra/changelog.py` via `make changelog` — do not edit by hand.
Release notes are hand-written and bilingual (RU/EN); the panel shows them in the selected language.

## [0.8.0](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.7.0...v0.8.0) - 2026-07-05

- A device's issued configs are grouped by server
- Fixed: server names no longer show %5B/%5D in share links

## [0.7.0](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.6.0...v0.7.0) - 2026-07-05

- The Kubernetes update button appears only when patch permission is granted (RBAC pre-check)
- Xray XHTTP configs are tagged "XHTTP" in the server name

## [0.6.0](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.5.0...v0.6.0) - 2026-07-05

- Bundlable Amnezia protocols are issued as a single choice
- Fixed: the bundle no longer leads when Xray XHTTP is chosen
- Fixed: each issued config stays on one line
- Official Android, Linux and Windows platform icons

## [0.5.0](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.4.0...v0.5.0) - 2026-07-05

- Apply updates from the panel across all deploy modes
- A distinct icon per device platform
- Official vendor logos on VPN software cards
- Fixed: the pool badge no longer overlaps the server name on mobile
- Server protocol management redesigned into a clean vertical card
- Fixed: the Hysteria2 accent dot in protocol cards

## [0.4.0](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.3.0...v0.4.0) - 2026-07-04

- Members can revoke their own issued configs
- A server's Amnezia protocols bundle into one vpn://
- Install Amnezia protocols individually, with add/remove
- Start/stop individual Amnezia protocols
- Fixed: require an explicit device and protocol before issuing a config

## [0.3.0](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.2.0...v0.3.0) - 2026-07-04

- Check official GitHub Releases for updates by default (zero-config)

## [0.2.0](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.1.1...v0.2.0) - 2026-07-04

- Added the Hysteria2 and Xray XHTTP protocols
- Auto-fix for failed VPN installs
- Required location with a picker, plus auto-named servers

## [0.1.1](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.1.0...v0.1.1) - 2026-07-04

- Fixed external Postgres behind PgBouncer: transaction-mode migrations and DSN credential encoding

## 0.1.0 - 2026-07-03

- Initial public release
- Fixed the Kubernetes crashloop from an injected VPNHUB_PORT; hardened install-smoke stdin
