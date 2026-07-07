import { describe, expect, it } from "vitest";
import { hasUsefulInfo, parseServerInfo } from "./credentialParse";

const FIRSTBYTE_EMAIL = `Активация Виртуального сервера
Здравствуйте, Ivan!

Настоящим письмом уведомляем, что на ваше имя был зарегистрирован Виртуальный Сервер. Предлагаем распечатать данное сообщение для удобства использования в дальнейшем.

Информация о cервере
Тарифный план: KVM-SSD-1-PAR
Дата открытия: 2026-06-13
Доменное имя: vm0000001.firstbyte.club
IP-адрес сервера: 203.0.113.10
Пользователь: root
Пароль: s3cretPwd1`;

describe("parseServerInfo: FirstByte", () => {
  it("парсит полное письмо активации", () => {
    const r = parseServerInfo(FIRSTBYTE_EMAIL);
    expect(r.providerId).toBe("firstbyte");
    expect(r.ip).toBe("203.0.113.10");
    expect(r.hostname).toBe("vm0000001.firstbyte.club");
    expect(r.sshUser).toBe("root");
    expect(r.password).toBe("s3cretPwd1");
    expect(r.tariff).toBe("KVM-SSD-1-PAR");
    expect(r.location).toBe("Париж");
  });

  it("парсит фрагмент письма, скопированный с середины", () => {
    const r = parseServerInfo(`cервере
Тарифный план: KVM-SSD-1-PAR
Дата открытия: 2026-06-13
Доменное имя: vm0000001.firstbyte.club
IP-адрес сервера: 203.0.113.10
Пользователь: root
Пароль: xY7mQ2`);
    expect(r.providerId).toBe("firstbyte"); // по домену firstbyte.club
    expect(r.ip).toBe("203.0.113.10");
    expect(r.sshUser).toBe("root");
    expect(r.password).toBe("xY7mQ2");
    expect(r.location).toBe("Париж");
  });

  it("парсит тарифный план из письма FirstByte без локации в коде", () => {
    const r = parseServerInfo(`Информация о cервере
Тарифный план: MSK-highmem-KVM-SSD-2
Дата открытия: 2026-07-04
Доменное имя: vm4457114.firstbyte.club
IP-адрес сервера: 185.195.26.162
Пользователь: root
Пароль: redacted`);
    expect(r.providerId).toBe("firstbyte");
    expect(r.tariff).toBe("MSK-highmem-KVM-SSD-2");
    expect(r.location).toBe("Москва");
    expect(r.ip).toBe("185.195.26.162");
    expect(r.sshUser).toBe("root");
  });

  it("не берёт локацию из тарифа без кода ДЦ", () => {
    const r = parseServerInfo("Тарифный план: KVM-SSD-1\nIP: 1.2.3.4 firstbyte");
    expect(r.location).toBeUndefined();
  });
});

describe("parseServerInfo: generic", () => {
  it("парсит англоязычное письмо в стиле WHMCS", () => {
    const r = parseServerInfo(`Your server has been activated!

Hostname: srv1.example.com
Main IP: 203.0.113.7
Username: root
Root Password: s3cretPwd
SSH Port: 2222
Location: Amsterdam, NL`);
    expect(r.ip).toBe("203.0.113.7");
    expect(r.hostname).toBe("srv1.example.com");
    expect(r.sshUser).toBe("root");
    expect(r.password).toBe("s3cretPwd");
    expect(r.sshPort).toBe("2222");
    expect(r.location).toBe("Amsterdam, NL");
    expect(r.providerId).toBeUndefined();
  });

  it("понимает значение на следующей строке", () => {
    const r = parseServerInfo(`IP-адрес:
198.51.100.3
Пароль:
qwErty123`);
    expect(r.ip).toBe("198.51.100.3");
    expect(r.password).toBe("qwErty123");
  });

  it("понимает разделитель-тире", () => {
    const r = parseServerInfo("Логин — admin\nПароль — pa55word");
    expect(r.sshUser).toBe("admin");
    expect(r.password).toBe("pa55word");
  });

  it("предпочитает SSH-пароль паролю от панели", () => {
    const r = parseServerInfo(`Доступ в панель управления
Логин: client123
Пароль: panelPass1

Доступ к серверу по SSH
IP: 10.0.0.5
Пользователь: root
Пароль: sshPass99`);
    expect(r.sshUser).toBe("root");
    expect(r.password).toBe("sshPass99");
  });

  it("находит IP без метки", () => {
    const r = parseServerInfo("Ваш сервер 198.51.100.22 готов к работе");
    expect(r.ip).toBe("198.51.100.22");
  });

  it("отбрасывает невалидный IP", () => {
    const r = parseServerInfo("IP: 999.108.4.22");
    expect(r.ip).toBeUndefined();
  });

  it("отбрасывает невалидный порт", () => {
    const r = parseServerInfo("Порт: 99999");
    expect(r.sshPort).toBeUndefined();
  });

  it("возвращает пустой результат для текста без данных", () => {
    const r = parseServerInfo("Здравствуйте! Ваш платёж получен, спасибо.");
    expect(hasUsefulInfo(r)).toBe(false);
  });

  it("не путает URL панели с меткой", () => {
    const r = parseServerInfo("Панель: https://my.panel.com\nIP: 5.6.7.8");
    expect(r.ip).toBe("5.6.7.8");
  });

  it("срезает кавычки и хвостовую пунктуацию у значения", () => {
    const r = parseServerInfo('Пользователь: "root".');
    expect(r.sshUser).toBe("root");
  });
});

describe("parseServerInfo: шаблон BILLmanager (FirstByte/UFO)", () => {
  it("берёт root-креды, а не креды панели VMmanager (второй Пользователь/Пароль)", () => {
    const r = parseServerInfo(`Информация о сервере
Тарифный план: KVM-SSD-1-PAR
Доменное имя: vm0000001.firstbyte.club
IP-адрес сервера: 203.0.113.10
Пользователь: root
Пароль: rootPass99
Обязательно смените пароль сервера после первого входа.

VMmanager 6 - внешняя панель управления сервером
Ссылка: https://panel.example.com
Пользователь: client@mail.ru
Пароль: panelPass11`);
    expect(r.sshUser).toBe("root");
    expect(r.password).toBe("rootPass99");
  });

  it("парсит письмо в стиле UFO Hosting и локацию из кода страны в тарифе", () => {
    const r = parseServerInfo(`Активация Виртуального Сервера
Виртуальный сервер
Для вас активирована услуга виртуального выделенного сервера, ниже приведена информация об услуге.
Информация о сервере
Тарифный план: Naos[RS]
Дата открытия: 2026-03-01
IP-адрес сервера: 203.0.113.205
Пользователь: root
Пароль: s3cretPwd2
Обязательно смените пароль сервера после первого входа.
VMmanager 6 - панель управления сервером
Вход в биллинг: https://bill.ufo.hosting`);
    expect(r.providerId).toBe("ufo");
    expect(r.ip).toBe("203.0.113.205");
    expect(r.sshUser).toBe("root");
    expect(r.password).toBe("s3cretPwd2");
    expect(r.tariff).toBe("Naos[RS]");
    expect(r.location).toBe("Сербия");
  });
});

describe("parseServerInfo: ISHOSTING", () => {
  it("парсит welcome email и отсекает примечание после пароля", () => {
    const r = parseServerInfo(`Dedicated/VPS Server Welcome Email
Hello, Alex!
Server information
=============================
Service: Lite - Linux SSD
IP: 203.0.113.55
Username: root
Password: q1W2e3r4 (change for security reasons is strongly recommended)
Additional IP:
not set
Best regards, is*hosting team`);
    expect(r.providerId).toBe("ishosting");
    expect(r.ip).toBe("203.0.113.55");
    expect(r.sshUser).toBe("root");
    expect(r.password).toBe("q1W2e3r4");
    expect(r.tariff).toBe("Lite - Linux SSD");
    expect(r.location).toBeUndefined();
  });

  it("не ловится на «IP: 1» и «Port: 1 Gbps» из письма Order Confirmation", () => {
    const r = parseServerInfo(`Order Confirmation
Service ID: 428913
IP: 1
Port: 1 Gbps
Disk: 30 GB
OS: Ubuntu 22.04`);
    expect(r.ip).toBeUndefined();
    expect(r.sshPort).toBeUndefined();
  });
});

describe("parseServerInfo: копия из панели (Serverspace/AHost)", () => {
  it("понимает метки без двоеточий со значением на следующей строке", () => {
    const r = parseServerInfo(`IP Адрес
198.51.100.3
Логин
root
Пароль
Xy12@abcd`);
    expect(r.ip).toBe("198.51.100.3");
    expect(r.sshUser).toBe("root");
    expect(r.password).toBe("Xy12@abcd");
  });

  it("не принимает следующую метку за значение", () => {
    const r = parseServerInfo(`Пароль
Логин
root`);
    expect(r.password).toBeUndefined();
    expect(r.sshUser).toBe("root");
  });

  it("срезает скобочное пояснение в метке («Логин (обычно root)»)", () => {
    const r = parseServerInfo("Логин (обычно root): root\nПароль root: aBc123");
    expect(r.sshUser).toBe("root");
    expect(r.password).toBe("aBc123");
  });
});

describe("locationFromTariff через parseServerInfo", () => {
  it.each([
    ["EU-KVM-SSD-2-FIN", "Хельсинки"],
    ["MSK-KVM-SSD-3", "Москва"],
    ["US-KVM-SSD-2", "США"],
    ["PARs-1", "Париж"],
    ["Haedus[NL]", "Нидерланды"],
  ])("тариф %s → %s", (tariff, location) => {
    expect(parseServerInfo(`Тарифный план: ${tariff}`).location).toBe(location);
  });
});

describe("parseServerInfo: определение провайдера", () => {
  it.each([
    ["ufo", "Спасибо за заказ на UFO Hosting!\nIP: 1.2.3.4"],
    ["ishosting", "Welcome to is*hosting\nIP: 1.2.3.4"],
    ["serverspace", "Ваш сервер в Serverspace создан\nIP: 1.2.3.4"],
  ])("определяет %s по сигнатуре", (id, text) => {
    expect(parseServerInfo(text).providerId).toBe(id);
  });

  it("использует профиль выбранного провайдера без сигнатуры в тексте", () => {
    const r = parseServerInfo("Тарифный план: KVM-HDD-2-AMS\nIP: 8.8.8.8", "firstbyte");
    expect(r.location).toBe("Амстердам");
    expect(r.providerId).toBeUndefined(); // в тексте провайдер не упомянут
  });
});
