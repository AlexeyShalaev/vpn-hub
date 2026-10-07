// Каталог провайдеров: двуязычное описание и справочник способов оплаты (порядок — как у бэкенда).

import type { Lang } from "./i18n";
import type { PaymentMethod, Provider } from "./types";

export const PAYMENT_METHODS: readonly PaymentMethod[] = [
  "ru_card",
  "sbp",
  "ru_wallet",
  "crypto",
  "card",
  "paypal",
  "bank",
  "local",
];

// описание карточки на языке интерфейса; английского нет — показываем русское
export function providerBlurb(p: Provider, lang: Lang): string {
  return lang === "en" && p.blurbEn ? p.blurbEn : p.blurb;
}
