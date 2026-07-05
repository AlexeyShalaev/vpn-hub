# Changelog

## [0.5.0](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.4.0...v0.5.0) (2026-07-05)


### Features

* self-update from UI (all deploy modes) + protocol UI redesign + fixes ([f3ea7e8](https://github.com/AlexeyShalaev/vpn-hub/commit/f3ea7e8f7cd903265995173f0c0075f2e48a36d9))
* **updates:** apply updates from the panel across all deploy modes ([4ffdfdb](https://github.com/AlexeyShalaev/vpn-hub/commit/4ffdfdb06ef240b7ff45e2158f326efee694a343))

## [0.4.0](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.3.0...v0.4.0) (2026-07-04)


### Features

* **configs:** let members revoke their own issued configs ([3bf856a](https://github.com/AlexeyShalaev/vpn-hub/commit/3bf856a7f7db2af3f771648354f1bed3ab804ac0))
* **configs:** bundle a server's Amnezia protocols into one vpn:// ([191ec4e](https://github.com/AlexeyShalaev/vpn-hub/commit/191ec4e4e2f1be1dec3182171e0206f2b3d48316))
* **provisioning:** install Amnezia protocols individually with add/remove ([e730306](https://github.com/AlexeyShalaev/vpn-hub/commit/e7303061e8b8ca4c97c546b15ac98552328aa8de))
* **provisioning:** start/stop individual Amnezia protocols (switchers) ([7aa325a](https://github.com/AlexeyShalaev/vpn-hub/commit/7aa325a72ad51ba9925f63458a56c0e9ed56e155))


### Bug Fixes

* **configs:** require explicit device & protocol before issuing a config ([542b8af](https://github.com/AlexeyShalaev/vpn-hub/commit/542b8af3de2e43104d7fd4ee2cd38fa38324684c))

## [0.3.0](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.2.0...v0.3.0) (2026-07-04)


### Features

* **updates:** check official GitHub Releases by default (zero-config) ([cd6a010](https://github.com/AlexeyShalaev/vpn-hub/commit/cd6a010e1984b9688bf91d05aaae35fe21e7ae61))

## [0.2.0](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.1.1...v0.2.0) (2026-07-04)


### Features

* **provisioning:** add Hysteria2 and Xray XHTTP protocols ([46e76a9](https://github.com/AlexeyShalaev/vpn-hub/commit/46e76a993cb9a0a4f598c03445c81f9475f53a7e))
* **provisioning:** auto-fix for failed VPN installs ([848d6b5](https://github.com/AlexeyShalaev/vpn-hub/commit/848d6b58fa04cc7a0d86d1aa244a9aa216ca5e52))
* **servers:** required location with select + auto-named servers ([2555c00](https://github.com/AlexeyShalaev/vpn-hub/commit/2555c0063ada4c03699369001e2430ca5df393d5))

## [0.1.1](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.1.0...v0.1.1) (2026-07-04)


### Bug Fixes

* **db:** external Postgres behind PgBouncer — transaction-mode migrations & DSN credential encoding ([#12](https://github.com/AlexeyShalaev/vpn-hub/issues/12)) ([005f076](https://github.com/AlexeyShalaev/vpn-hub/commit/005f0766517a548d15f5c6a1ddb27d27e7f7f32c))

## 0.1.0 (2026-07-03)


### Features

* initial public release ([e14d41a](https://github.com/AlexeyShalaev/vpn-hub/commit/e14d41ab842641b832882fbdaca3ada0205722cf))


### Bug Fixes

* **k8s:** app crashloop from injected VPNHUB_PORT; harden install-smoke stdin ([bb8e196](https://github.com/AlexeyShalaev/vpn-hub/commit/bb8e196855908e81f5c3437190e4b3b5ca59d1bf))

## Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
