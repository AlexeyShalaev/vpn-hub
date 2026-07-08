// Лёгкая, самодельная и типобезопасная локализация — без i18next и прочих зависимостей.
//
// Почему не i18next: панель self-hosted и держит зависимости под контролем; нам нужны
// всего две вещи — словарь с интерполяцией и русская плюрализация. Самодельный вариант
// даёт то, чего нет из коробки у большинства либ: автодополнение и проверку КЛЮЧЕЙ на
// этапе tsc (t("...") подсказывает существующие ключи, опечатка = ошибка сборки), а также
// проверку, что en покрывает ровно те же ключи, что и ru (см. `satisfies` ниже). Ноль рантайма
// сверх пары функций, ноль веса в бандле.
//
// Как добавить строку: допишите ключ в `ru` (источник истины) и тот же ключ в `en` —
// пропуск в en тут же подсветит tsc. Ключ используйте через t("group.title") и т.п.
// Как добавить язык: заведите ещё один объект `xx: Dict = { ... } satisfies Dict` и
// расширьте union `Lang` + массив LANGS.

import { useStore } from "../store";

// ── источник истины: русские строки. Тип словаря выводится из него ──────────────
// Значение может быть строкой (обычный ключ) или объектом плюрализации {one,two,five}
// для ru / {one,other} для en — плюрализацию разруливает helper `plural` ниже.
type PluralForms = { one: string; two: string; five: string };

const ru = {
  // навигация / каркас
  "nav.servers": "Серверы",
  "nav.groups": "Группы",
  "nav.access": "Доступы",
  "nav.available": "Доступно",
  "nav.devices": "Устройства",
  "nav.events": "События",
  "nav.users": "Пользователи",
  "nav.system": "Система",
  "nav.profile": "Профиль",
  "nav.admin": "Администрирование",
  "nav.monitoring": "Мониторинг",
  "nav.finance": "Финансы",

  // общие кнопки / действия
  "common.save": "Сохранить",
  "common.cancel": "Отмена",
  "common.delete": "Удалить",
  "common.back": "Назад",
  "common.copied": "Скопировано",

  // профиль
  "profile.title": "Профиль",
  "profile.logout": "Выйти",
  "profile.security": "Безопасность",
  "profile.changePassword": "Сменить пароль",
  "profile.activeSessions": "Активные сессии",
  "profile.revokeOthers": "Завершить остальные",
  "profile.sessionCurrent": "текущая",
  "profile.admin": "Администрирование",
  "profile.usersHint": "Управление пользователями",
  "profile.systemHint": "Версия, обновления, БД",
  "profile.mode": "Режим работы",
  "profile.modeHint": "Переключитесь, чтобы увидеть приложение глазами участника группы.",
  "profile.roleOwner": "Владелец",
  "profile.roleOwnerSub": "Серверы, группы, доступы",
  "profile.roleMember": "Участник",
  "profile.roleMemberSub": "Доступное мне, устройства",
  "profile.darkTheme": "Тёмная тема",
  "profile.themeNow": "Сейчас: {value}",
  "profile.themeDark": "Тёмная",
  "profile.themeLight": "Светлая",
  "profile.language": "Язык",
  "profile.languageHint": "Интерфейс приложения",
  "profile.tagline": "VPN Hub · self-hosted панель VPN",
  "profile.pwCurrent": "Текущий пароль",
  "profile.pwNew": "Новый пароль (мин. 8 символов)",
  "profile.pwRepeat": "Повторите новый пароль",
  "profile.pwWarn": "После смены пароля все остальные сессии будут завершены.",
  "profile.pwMismatch": "Пароли не совпадают",
  "profile.pwChanged": "Пароль изменён, остальные сессии завершены",
  "profile.pwFailed": "Не удалось сменить пароль",
  "profile.logoutFailed": "Не удалось выйти",
  "profile.sessionRevoked": "Сессия завершена",
  "profile.noOtherSessions": "Других сессий нет",
  "profile.sessionsRevoked": "Завершено сессий: {n}",
  "profile.sessionActivity": "активность {at}",
  "profile.sessionLogin": "вход {at}",

  // события
  "events.title": "События",
  "events.sub": "Журнал действий: входы, доступы, конфиги",
  "events.filterType": "Тип",
  "events.filterFrom": "С",
  "events.filterTo": "По",
  "events.allTypes": "Все события",
  "events.typeLogin": "Вход в систему",
  "events.typeJoin": "Вступление в группу",
  "events.typeConfig": "Выдача конфига",
  "events.typeRevoke": "Отзыв доступа",
  "events.actorAdmin": "администратор",
  "events.actorUser": "пользователь",
  "events.actorSystem": "система",
  "events.resource": "ресурс",
  "events.emptyTitle": "Событий пока нет",
  "events.emptySub": "Действия пользователей появятся здесь.",

  // онбординг владельца (чеклист первого запуска)
  "onboarding.title": "Быстрый старт",
  "onboarding.sub": "Пять шагов, чтобы раздать VPN близким",
  "onboarding.progress": "{done} из {total}",
  "onboarding.stepServer": "Добавьте сервер",
  "onboarding.stepServerSub": "Подключите арендованный VPS по SSH",
  "onboarding.stepInstall": "Установите VPN",
  "onboarding.stepInstallSub": "Разверните протокол на сервере",
  "onboarding.stepGroup": "Создайте группу",
  "onboarding.stepGroupSub": "Группа объединяет людей и доступы",
  "onboarding.stepInvite": "Пригласите участника",
  "onboarding.stepInviteSub": "Добавьте человека или дайте ссылку-приглашение",
  "onboarding.stepAccess": "Выдайте доступ",
  "onboarding.stepAccessSub": "Откройте группе сервер или пул",

  // главная-сводка владельца (Home)
  "home.title": "Главная",
  "home.sub": "Сводка по вашей панели VPN",
  "nav.home": "Главная",
  "home.serversTitle": "Серверы",
  "home.serversOnline": "{n} онлайн",
  "home.serversOffline": "{n} офлайн",
  "home.serversEmpty": "Серверов пока нет",
  "home.groupsTitle": "Группы и участники",
  "home.groupsCount": "групп: {groups}",
  "home.membersCount": "участников: {members}",
  "home.groupsEmpty": "Групп пока нет",
  "home.eventsTitle": "Последние события",
  "home.eventsAll": "Все события",
  "home.eventsEmpty": "Событий пока нет",

  // «Настрой устройство» — справочные инструкции по платформам
  "nav.setup": "Настройка",
  "setup.title": "Настрой устройство",
  "setup.sub": "Как поставить VPN на телефон, компьютер или роутер",
  "setup.pickPlatform": "Выберите платформу",
  "setup.recommendedApp": "Рекомендуемое приложение",
  "setup.openStore": "Открыть в сторе",
  "setup.stepsTitle": "Шаги",
  "setup.hint":
    "Приложение зависит от формата конфига, который вам выдали. Универсальные клиенты ниже открывают vless:// и hy2://; для Amnezia используйте AmneziaVPN, для Outline — Outline.",
  "setup.vendorApps": "Приложения по формату конфига",
  "setup.vendorAmnezia": "Для конфигов Amnezia (vpn://)",
  "setup.vendorOutline": "Для конфигов Outline (ss://)",
  "setup.openInApp": "Открыть в приложении",
  // платформы
  "setup.platformIos": "iPhone / iPad (iOS)",
  "setup.platformAndroid": "Android",
  "setup.platformWindows": "Windows",
  "setup.platformMac": "macOS",
  "setup.platformLinux": "Linux",
  "setup.platformRouter": "Роутер",
  // источники
  "setup.storeAppStore": "App Store",
  "setup.storeGooglePlay": "Google Play",
  "setup.storeSite": "Официальный сайт",
  // шаги
  "setup.stepInstall": "Установите приложение по ссылке выше.",
  "setup.stepGetConfig":
    "На вкладке «Доступно» получите конфиг и скопируйте ссылку или скачайте файл (QR-код тоже подойдёт).",
  "setup.stepImportUri":
    "В приложении нажмите «Добавить из буфера» или отсканируйте QR — конфиг импортируется автоматически.",
  "setup.stepImportFile": "В приложении выберите «Импорт из файла» или вставьте ссылку конфига из буфера обмена.",
  "setup.stepConnect": "Включите переключатель подключения — готово.",
  "setup.stepRouterFw": "Убедитесь, что на роутере есть поддержка WireGuard/AmneziaWG (OpenWrt, Keenetic и т.п.).",
  "setup.stepRouterImport":
    "В веб-интерфейсе роутера создайте WireGuard-интерфейс и вставьте параметры из выданного конфига.",

  // мелочи UX
  "ux.crashTitle": "Что-то пошло не так",
  "ux.crashSub": "Произошла непредвиденная ошибка. Попробуйте перезагрузить страницу.",
  "ux.reload": "Перезагрузить",
  "ux.shareInvite": "Пригласить",
  "ux.inviteCopied": "Ссылка-приглашение скопирована",
} satisfies Record<string, string | PluralForms>;

export type Lang = "ru" | "en";
export const LANGS: Lang[] = ["ru", "en"];
export const LANG_LABEL: Record<Lang, string> = { ru: "Русский", en: "English" };

export type TKey = keyof typeof ru;
type Key = TKey;
type Dict = Record<Key, string | PluralForms>;

// en обязан покрыть РОВНО те же ключи, что и ru — иначе tsc ругнётся на `satisfies Dict`.
const en = {
  "nav.servers": "Servers",
  "nav.groups": "Groups",
  "nav.access": "Access",
  "nav.available": "Available",
  "nav.devices": "Devices",
  "nav.events": "Events",
  "nav.users": "Users",
  "nav.system": "System",
  "nav.profile": "Profile",
  "nav.admin": "Administration",
  "nav.monitoring": "Monitoring",
  "nav.finance": "Finance",

  "common.save": "Save",
  "common.cancel": "Cancel",
  "common.delete": "Delete",
  "common.back": "Back",
  "common.copied": "Copied",

  "profile.title": "Profile",
  "profile.logout": "Log out",
  "profile.security": "Security",
  "profile.changePassword": "Change password",
  "profile.activeSessions": "Active sessions",
  "profile.revokeOthers": "End other sessions",
  "profile.sessionCurrent": "current",
  "profile.admin": "Administration",
  "profile.usersHint": "Manage users",
  "profile.systemHint": "Version, updates, DB",
  "profile.mode": "View mode",
  "profile.modeHint": "Switch to see the app as a group member sees it.",
  "profile.roleOwner": "Owner",
  "profile.roleOwnerSub": "Servers, groups, access",
  "profile.roleMember": "Member",
  "profile.roleMemberSub": "Available to me, devices",
  "profile.darkTheme": "Dark theme",
  "profile.themeNow": "Now: {value}",
  "profile.themeDark": "Dark",
  "profile.themeLight": "Light",
  "profile.language": "Language",
  "profile.languageHint": "App interface",
  "profile.tagline": "VPN Hub · self-hosted VPN panel",
  "profile.pwCurrent": "Current password",
  "profile.pwNew": "New password (min. 8 characters)",
  "profile.pwRepeat": "Repeat new password",
  "profile.pwWarn": "After changing the password all other sessions will be ended.",
  "profile.pwMismatch": "Passwords do not match",
  "profile.pwChanged": "Password changed, other sessions ended",
  "profile.pwFailed": "Could not change password",
  "profile.logoutFailed": "Could not log out",
  "profile.sessionRevoked": "Session ended",
  "profile.noOtherSessions": "No other sessions",
  "profile.sessionsRevoked": "Sessions ended: {n}",
  "profile.sessionActivity": "active {at}",
  "profile.sessionLogin": "signed in {at}",

  "events.title": "Events",
  "events.sub": "Activity log: logins, access, configs",
  "events.filterType": "Type",
  "events.filterFrom": "From",
  "events.filterTo": "To",
  "events.allTypes": "All events",
  "events.typeLogin": "Sign in",
  "events.typeJoin": "Group join",
  "events.typeConfig": "Config issued",
  "events.typeRevoke": "Access revoked",
  "events.actorAdmin": "admin",
  "events.actorUser": "user",
  "events.actorSystem": "system",
  "events.resource": "resource",
  "events.emptyTitle": "No events yet",
  "events.emptySub": "User actions will appear here.",

  "onboarding.title": "Quick start",
  "onboarding.sub": "Five steps to share VPN with the people you care about",
  "onboarding.progress": "{done} of {total}",
  "onboarding.stepServer": "Add a server",
  "onboarding.stepServerSub": "Connect a rented VPS over SSH",
  "onboarding.stepInstall": "Install VPN",
  "onboarding.stepInstallSub": "Deploy a protocol on the server",
  "onboarding.stepGroup": "Create a group",
  "onboarding.stepGroupSub": "A group ties people and access together",
  "onboarding.stepInvite": "Invite a member",
  "onboarding.stepInviteSub": "Add a person or share an invite link",
  "onboarding.stepAccess": "Grant access",
  "onboarding.stepAccessSub": "Open a server or pool to the group",

  "home.title": "Home",
  "home.sub": "Overview of your VPN panel",
  "nav.home": "Home",
  "home.serversTitle": "Servers",
  "home.serversOnline": "{n} online",
  "home.serversOffline": "{n} offline",
  "home.serversEmpty": "No servers yet",
  "home.groupsTitle": "Groups & members",
  "home.groupsCount": "groups: {groups}",
  "home.membersCount": "members: {members}",
  "home.groupsEmpty": "No groups yet",
  "home.eventsTitle": "Recent events",
  "home.eventsAll": "All events",
  "home.eventsEmpty": "No events yet",

  // "Set up your device" — per-platform reference instructions
  "nav.setup": "Setup",
  "setup.title": "Set up your device",
  "setup.sub": "How to install the VPN on a phone, computer, or router",
  "setup.pickPlatform": "Pick a platform",
  "setup.recommendedApp": "Recommended app",
  "setup.openStore": "Open store",
  "setup.stepsTitle": "Steps",
  "setup.hint":
    "The app depends on the config format you were given. The universal clients below open vless:// and hy2://; use AmneziaVPN for Amnezia and Outline for Outline.",
  "setup.vendorApps": "Apps by config format",
  "setup.vendorAmnezia": "For Amnezia configs (vpn://)",
  "setup.vendorOutline": "For Outline configs (ss://)",
  "setup.openInApp": "Open in app",
  // platforms
  "setup.platformIos": "iPhone / iPad (iOS)",
  "setup.platformAndroid": "Android",
  "setup.platformWindows": "Windows",
  "setup.platformMac": "macOS",
  "setup.platformLinux": "Linux",
  "setup.platformRouter": "Router",
  // sources
  "setup.storeAppStore": "App Store",
  "setup.storeGooglePlay": "Google Play",
  "setup.storeSite": "Official site",
  // steps
  "setup.stepInstall": "Install the app from the link above.",
  "setup.stepGetConfig":
    "On the Available tab, get a config and copy the link or download the file (a QR code works too).",
  "setup.stepImportUri": "In the app tap “Add from clipboard” or scan the QR — the config imports automatically.",
  "setup.stepImportFile": "In the app choose “Import from file” or paste the config link from your clipboard.",
  "setup.stepConnect": "Flip the connect toggle — you're done.",
  "setup.stepRouterFw": "Make sure your router supports WireGuard/AmneziaWG (OpenWrt, Keenetic, etc.).",
  "setup.stepRouterImport":
    "In the router web UI create a WireGuard interface and paste the parameters from the config you got.",

  // UX niceties
  "ux.crashTitle": "Something went wrong",
  "ux.crashSub": "An unexpected error occurred. Try reloading the page.",
  "ux.reload": "Reload",
  "ux.shareInvite": "Invite",
  "ux.inviteCopied": "Invite link copied",
} satisfies Dict;

const DICTS: Record<Lang, Dict> = { ru, en };

// ── определение языка ───────────────────────────────────────────────────────────
export function detectLang(): Lang {
  const saved = localStorage.getItem("vpnhub.lang");
  if (saved === "ru" || saved === "en") return saved;
  return navigator.language?.toLowerCase().startsWith("en") ? "en" : "ru";
}

// ── интерполяция {var} ──────────────────────────────────────────────────────────
function interpolate(s: string, vars?: Record<string, string | number>): string {
  if (!vars) return s;
  return s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? String(vars[k]) : m));
}

// ── плюрализация ────────────────────────────────────────────────────────────────
// ru — по правилам русского склонения (та же логика, что была в экранах);
// en — простое n === 1 ? one : five (форма «other»).
function pickPlural(lang: Lang, n: number, forms: PluralForms): string {
  if (lang === "en") return n === 1 ? forms.one : forms.five;
  const n10 = n % 10;
  const n100 = n % 100;
  if (n10 === 1 && n100 !== 11) return forms.one;
  if (n10 >= 2 && n10 <= 4 && (n100 < 10 || n100 >= 20)) return forms.two;
  return forms.five;
}

export type TFunc = (key: Key, vars?: Record<string, string | number>) => string;

function makeT(lang: Lang): TFunc {
  const dict = DICTS[lang];
  return (key, vars) => {
    const raw = dict[key];
    if (typeof raw === "string") return interpolate(raw, vars);
    // объект плюрализации: ждём числовой vars.n
    const n = typeof vars?.n === "number" ? vars.n : 0;
    return interpolate(pickPlural(lang, n, raw), vars);
  };
}

// Кэш связанных t по языку — чтобы не пересоздавать функцию на каждый рендер.
const T_CACHE: Partial<Record<Lang, TFunc>> = {};
export function tFor(lang: Lang): TFunc {
  let fn = T_CACHE[lang];
  if (!fn) {
    fn = makeT(lang);
    T_CACHE[lang] = fn;
  }
  return fn;
}

// ── реактивный хук: t перестраивается при смене языка (lang живёт в Zustand) ─────
export function useT(): TFunc {
  const lang = useStore((s) => s.lang);
  return tFor(lang);
}
