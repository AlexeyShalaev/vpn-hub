# Changelog

All notable changes to this project are documented here.

Generated from `backend/src/vpnhub/infra/changelog.py` via `make changelog` — do not edit by hand.
Release notes are hand-written and bilingual (RU/EN); the panel shows them in the selected language.

## [0.12.0](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.11.0...v0.12.0) (2026-10-07)


### Features

* 600 VPS providers, 51 live plan sources, catalog search and richer plan finder ([5e81bb9](https://github.com/AlexeyShalaev/vpn-hub/commit/5e81bb9875d7545564bb3bd8a0ef526b39a20b8b))
* **catalog:** ~600 VPS providers in Russia and worldwide ([f6ec6d6](https://github.com/AlexeyShalaev/vpn-hub/commit/f6ec6d63705aaee2c452a88a6a4ac467e05ee36b))
* **catalog:** provider locations, payment methods and English descriptions ([b17f979](https://github.com/AlexeyShalaev/vpn-hub/commit/b17f979190410aab6779b8d6ecb36c56bae82a1d))
* **catalog:** search, filters and sorting for the provider catalog ([456c223](https://github.com/AlexeyShalaev/vpn-hub/commit/456c22336d56a04d36c75c4f95a82966096c74c6))
* **finder:** richer cross-provider plan search ([b6e408a](https://github.com/AlexeyShalaev/vpn-hub/commit/b6e408ae0bf3e8f5977e3f795e9aa459739f44eb))
* **plans:** generic BILLmanager price-list parser and 25 Russian/CIS hosts ([0c8b227](https://github.com/AlexeyShalaev/vpn-hub/commit/0c8b227912a59a70116021527cf06e4c2042cf19))
* **plans:** generic WHMCS store parser and the first WHMCS providers ([c90eabc](https://github.com/AlexeyShalaev/vpn-hub/commit/c90eabc581ac6c42525a9819efa3d111d8c6aadd))
* **plans:** live plans for 4VPS across 35 countries ([ebda92b](https://github.com/AlexeyShalaev/vpn-hub/commit/ebda92bc1e789210aff48a3aa013bb9d014df6d1))
* **plans:** live plans for BinaryLane and Mammoth Cloud (Australia) ([86609f4](https://github.com/AlexeyShalaev/vpn-hub/commit/86609f44b0a6f252fe0266c4571c632f7af12fa2))
* **plans:** live plans for Cherry Servers from the public API ([cf7d15a](https://github.com/AlexeyShalaev/vpn-hub/commit/cf7d15a97d227c2e074f2c222c82f592b28f5142))
* **plans:** live plans for Hetzner Cloud ([c59affc](https://github.com/AlexeyShalaev/vpn-hub/commit/c59affc74660b28c51ec8d3809843885c6f1fe42))
* **plans:** live plans for Timeweb Cloud and Beget ([779c47c](https://github.com/AlexeyShalaev/vpn-hub/commit/779c47c396d5f37efd05adf4a058f18ec7228bc5))
* **plans:** live plans for Vultr and Akamai (Linode) from their public APIs ([707c8c4](https://github.com/AlexeyShalaev/vpn-hub/commit/707c8c48eb211491add65ab2ab91d8447baf89fb))
* **plans:** more WHMCS hosts and wider spec vocabulary ([7472f49](https://github.com/AlexeyShalaev/vpn-hub/commit/7472f496228de4f53a7406eea82fcd4a8f22b78c))
* **plans:** Retzor and MEGAHOST (Kazakhstan) via BILLmanager ([034dd64](https://github.com/AlexeyShalaev/vpn-hub/commit/034dd64ec370f9878d348896d29228960d3f211f))
* **servers:** searchable provider picker in the server form ([7225fa9](https://github.com/AlexeyShalaev/vpn-hub/commit/7225fa91f803cd579964ceead902ba0dbd299099))
* **ui:** roomier plan finder and tidier catalog cards ([9d8481e](https://github.com/AlexeyShalaev/vpn-hub/commit/9d8481e85bd6b6f33778a3d6c523d8f9d0206a70))


### Bug Fixes

* **catalog:** hide tags that repeat a payment method, translate standard tags ([3adf1ba](https://github.com/AlexeyShalaev/vpn-hub/commit/3adf1ba051a35dbfff0cb16598c90d1379b6563a))
* **catalog:** tell apart same-named providers, merge split brands ([7e9b4c1](https://github.com/AlexeyShalaev/vpn-hub/commit/7e9b4c192be02dbfd2b64d89b80505fe30f43136))
* **plans:** don't present an unpublished traffic quota as unlimited ([25b9b95](https://github.com/AlexeyShalaev/vpn-hub/commit/25b9b959b220a0ec0cd30ce78c5b15f77cebc3ef))
* **security:** patch anyio and cryptography, drop pip from the runtime image ([308debd](https://github.com/AlexeyShalaev/vpn-hub/commit/308debdf6d2c68a472ccf90ac5800f90687a60cd))


### Performance Improvements

* **api:** gzip the provider catalog and plan responses ([be9362f](https://github.com/AlexeyShalaev/vpn-hub/commit/be9362f94277be6f111d1a6465579d12e58afde5))
* **catalog:** cache the parsed provider catalog ([f67b4e3](https://github.com/AlexeyShalaev/vpn-hub/commit/f67b4e30b2da27a76fb6f9a3388895a1ea8d8975))
* **plans:** own I/O pool and streaming BILLmanager parsing ([c430847](https://github.com/AlexeyShalaev/vpn-hub/commit/c430847e33ed073530dd9b700e60824db8353fe0))

## [0.11.0](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.10.1...v0.11.0) - 2026-07-12

- Site favicon in the browser tab — previously missing
- Documentation now includes screenshots of every screen and a product overview video

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
