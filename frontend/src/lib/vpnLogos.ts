import amnezia from "../assets/vpn/amnezia.png";
import hysteriaBlack from "../assets/vpn/hysteria2-black.svg";
import hysteriaWhite from "../assets/vpn/hysteria2-white.svg";
import openvpn from "../assets/vpn/openvpn.png";
import outline from "../assets/vpn/outline.svg";
import type { VpnType } from "./types";

type Theme = "light" | "dark";

// Официальные логотипы вендоров ПО (маркой идентифицируем софт, который разворачивает vpn-hub).
// Одноцветные логотипы — независимы от темы.
const STATIC: Partial<Record<VpnType, string>> = {
  amnezia,
  openvpn,
  outline,
};

// Логотипы с вариантом под тему: у Hysteria знак одноцветный, поэтому на светлой теме
// показываем тёмный вариант, на тёмной — белый (иначе сливается с фоном).
const THEMED: Partial<Record<VpnType, Record<Theme, string>>> = {
  hysteria2: { light: hysteriaBlack, dark: hysteriaWhite },
};

// URL логотипа вендора под текущую тему, либо undefined → рисуем акцентную иконку (VPN_ICON).
export function vpnLogo(type: VpnType, theme: Theme): string | undefined {
  return THEMED[type]?.[theme] ?? STATIC[type];
}
