# Changelog

All notable changes to this project are documented here.

Generated from `backend/src/vpnhub/infra/changelog.py` via `make changelog` — do not edit by hand.
Release notes are hand-written and bilingual (RU/EN); the panel shows them in the selected language.

## [0.10.1](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.10.0...v0.10.1) - 2026-07-12

- UI polish: refined layout and styling on the System, Profile and Servers screens

## [0.10.0](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.9.0...v0.10.0) - 2026-07-12

- New providers UltaHost and 62YUN in the catalog; new default providers now reach existing users after an update, while their edits and deletions are kept
- Reworked Finance section: a single display currency for all servers (CBR conversion), spend and traffic trend charts, a who-uses-it breakdown with imputed cost, and a sale-price calculator (per GB and per device/month)
- Xray multi-hop now supports Xray XHTTP too — as entry and as exit, in any combination with plain Xray; the multi-hop card is always shown, with a hint to install Xray
- When issuing a single Amnezia protocol, the config name now includes the protocol (e.g. Server · Xray XHTTP), so a server's configs are no longer easy to mix up
- Reliable Docker install on Ubuntu: docker-ce is used when containerd.io is present (previously the conflicting docker.io failed silently), with a clear error on failure

## [0.9.0](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.8.0...v0.9.0) - 2026-07-12

- Full bilingual support: the entire UI and server responses switch between Russian and English
- Monitoring: traffic dashboards, server resources over SSH (CPU/RAM/disk/uptime) and accurate per-protocol online counts
- Per-client monitoring and tiered metrics storage with retention and a disk-usage cap
- Finance: server cost accounting, a spend overview, and a provider tariff finder with single-currency conversion at CBR rates
- Limits: on devices, on configs per protocol, and on traffic per period — with a real access cutoff when exceeded
- Protocols: added Hysteria2 and Xray XHTTP, multi-hop chains via Xray, per-protocol Amnezia install and single-protocol issuance, and obfuscation/Reality settings in the UI
- In-panel updates across all deploy modes (compose/scripts/k8s), with hints and auto-fix for provisioning errors
- An action audit log, real-time updates (SSE), an onboarding checklist, a super-app home screen, and a device setup guide
- A curated bilingual changelog in the panel and a theme selector: system, dark, or light
- Administration: a System section showing the deployment method and disk usage, plus backups
- Infrastructure: migration testing, an arm64 image, security hardening (sessions, rate limiting, CSRF/CSP, master-key secret encryption), and moving the frontend to TypeScript 6 and Vite 8

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
