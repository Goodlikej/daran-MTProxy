# Техническое задание: daran-proxy-stack

Дата: 2026-03-24
Статус: draft v1

## 1. Контекст

Нужно разработать собственный набор утилит/менеджеров для VPS, вдохновлённый паттерном из разобранных видео, но реализованный аккуратнее, понятнее и с нормальной архитектурой.

Целевой результат — не один огромный магический bash-скрипт, а модульная система, которая покрывает три основных сценария:

1. **MTProxy Manager** — для Telegram
2. **WARP Manager** — для Xray / 3x-ui / Amnezia как outbound через Cloudflare WARP
3. **Relay / Cascade Manager** — для TCP/UDP forwarding между VPS

Поверх этого должен быть единый слой управления:
- CLI
- при необходимости menu/TUI
- позже возможно web UI или Telegram-бот

---

## 2. Цели проекта

### Основные цели
- Упростить развертывание типовых сетевых сценариев на VPS.
- Спрятать рутину установки и конфигурации за понятным интерфейсом.
- Сохранить прозрачность: пользователь должен понимать, что именно поднято и куда идёт трафик.
- Сделать основу, которую можно сопровождать, расширять и тестировать.

### Не-цели на первом этапе
- Не делать полноценную панель уровня aaPanel/3x-ui.
- Не делать мультиарендность и сложную RBAC-модель.
- Не тащить сразу web-dashboard.
- Не пытаться покрыть все возможные протоколы мира.

---

## 3. Сценарии использования

### 3.1 MTProxy для Telegram
Пользователь хочет:
- установить Telegram MTProxy на VPS;
- выбрать порт;
- выбрать fake TLS host / маскировку;
- получить готовую ссылку `tg://proxy`;
- получить QR-код;
- смотреть статус;
- удалить или обновить прокси.

### 3.2 WARP outbound для Xray / 3x-ui / Amnezia
Пользователь хочет:
- установить Cloudflare WARP на VPS;
- поднять локальный SOCKS5 endpoint;
- подключить этот SOCKS5 как outbound в Xray;
- направлять через него весь трафик или только выбранные сервисы/домены;
- получить готовый JSON-фрагмент для вставки в Xray/3x-ui;
- управлять жизненным циклом WARP.

### 3.3 Relay / Cascade
Пользователь хочет:
- поднять входной VPS-узел;
- перенаправлять TCP или UDP на другой VPS;
- строить каскад:
  - клиент -> входной узел -> основной сервер;
- видеть список правил;
- удалять и изменять правила;
- сохранять всё после ребута.

---

## 4. Функциональные требования

# 4.1 Общие требования

Система должна:
- работать на Linux VPS (первый приоритет: Ubuntu 24.04);
- проверять root-права там, где это нужно;
- уметь проверять и ставить зависимости;
- хранить конфиг и state в понятных файлах;
- логировать основные действия;
- иметь понятные команды статуса;
- безопасно обрабатывать повторный запуск;
- поддерживать uninstall без лишнего мусора.

### Общие сущности
- global config
- module config
- state files
- logs
- generated artifacts

Рекомендуемые базовые директории:
- `/etc/daran-proxy-stack/`
- `/var/lib/daran-proxy-stack/`
- `/var/log/daran-proxy-stack/`

---

## 5. Модуль 1: MTProxy Manager

### 5.1 Возможности
- install MTProxy
- update/recreate MTProxy
- remove MTProxy
- show status
- show connection data
- generate/re-generate secret
- choose fake TLS host
- choose port
- print/share `tg://proxy` link
- generate QR-code

### 5.2 Технические требования
- приоритетный способ запуска: Docker Compose или Docker run через управляемую оболочку;
- поддержка fake TLS domain;
- хранение параметров в конфиге;
- проверка, что порт свободен;
- перезапуск после reboot;
- удобный вывод:
  - host/IP
  - port
  - secret
  - tg-link
  - status

### 5.3 Ожидаемый артефакт
- config file MTProxy
- docker compose file или equivalent runner
- generated tg link
- QR-code output / file

---

## 6. Модуль 2: WARP Manager

### 6.1 Возможности
- install Cloudflare WARP
- register / re-register WARP
- connect / disconnect WARP
- run local SOCKS5 endpoint
- change local SOCKS5 port
- show status
- show server IP vs WARP IP
- print Xray outbound JSON
- print routing examples
- full uninstall

### 6.2 Технические требования
- использовать штатные средства Cloudflare WARP там, где это возможно;
- не ломать системную сеть сервера, если нужен только outbound через SOCKS5;
- биндинг SOCKS5 по умолчанию на `127.0.0.1`;
- конфигурируемый порт;
- health-check статуса;
- systemd unit для автозапуска при необходимости.

### 6.3 Ожидаемые артефакты
- config file WARP module
- systemd units / service wrappers
- generated Xray outbound JSON
- пример routing rules

---

## 7. Модуль 3: Relay / Cascade Manager

### 7.1 Возможности
- add TCP forward rule
- add UDP forward rule
- list rules
- show rule details
- delete one rule
- reset all rules
- validate port conflicts
- persist rules across reboot

### 7.2 Сценарии
- TCP 443 на удалённый MTProxy
- TCP inbound для VLESS/Xray
- UDP inbound для AmneziaWG/WireGuard

### 7.3 Технические требования
- способ реализации должен быть детерминированным и поддерживаемым;
- конфигурация правил должна быть отделена от логики применения;
- нужен режим безопасного повторного применения правил;
- правила должны переживать reboot;
- должны быть команды диагностики.

### 7.4 Кандидаты на реализацию
Будет уточнено на этапе проектирования. Возможные варианты:
- nftables / iptables
- socat
- haproxy (для TCP)
- systemd services на правило

Итоговый вариант выбрать после проверки надёжности и удобства сопровождения.

---

## 8. Интерфейс управления

### 8.1 CLI обязателен
Нужен основной CLI, например:

```bash
daran-net mtproxy install --port 443 --host wikipedia.org
daran-net mtproxy status
daran-net mtproxy link
daran-net mtproxy qr

daran-net warp install
daran-net warp status
daran-net warp set-port 40000
daran-net warp xray-json

daran-net relay add tcp --listen 443 --target 1.2.3.4:443
daran-net relay add udp --listen 51820 --target 1.2.3.4:51820
daran-net relay list
```

### 8.2 Menu/TUI желателен
Поверх CLI может быть сделано интерактивное меню для новичков:
- numbered menu
- цветной вывод
- подсказки
- безопасные подтверждения для удаления

Важно: **вся логика должна жить в CLI/модулях, а не в TUI**.

---

## 9. Нефункциональные требования

### Поддерживаемость
- модульная структура;
- минимум магии;
- понятные конфиги;
- предсказуемые команды.

### Надёжность
- идемпотентность насколько возможно;
- проверки зависимостей;
- проверка состояния до и после действий;
- понятные ошибки.

### Безопасность
- минимально нужные сетевые открытия;
- по умолчанию локальный bind там, где можно;
- аккуратная работа с firewall;
- отсутствие лишних внешних зависимостей;
- в логах не светить лишние секреты без необходимости.

### UX
- новичку должно быть понятно;
- опытному пользователю не должно быть тесно;
- важные данные должны выводиться явно.

---

## 10. Предварительная структура репозитория

```text
daran-proxy-stack/
  README.md
  docs/
    TZ.md
    architecture.md
    decisions.md
  notes/
    current-understanding.md
    implementation-plan.md
  transcripts/
    2026-03-24-mtproxy-video.md
    2026-03-24-warp-3xui-video.md
  artifacts/
    xray/
    mtproxy/
    relay/
  src/
    cli/
    modules/
      mtproxy/
      warp/
      relay/
    lib/
```

---

## 11. Что уже известно на текущий момент

По разобранным видео и скринам уже понятно:

### MTProxy-ветка
- используется MTProxy в Docker;
- есть выбор fake TLS host;
- есть выбор порта;
- генерируется `tg://proxy` ссылка;
- пользователю показывается QR-код.

### WARP-ветка
- WARP ставится на тот же VPS, где Xray / 3x-ui;
- поднимается локальный SOCKS5 endpoint;
- этот SOCKS5 используется как outbound в Xray;
- маршрутизация может быть полной или выборочной.

### Relay-ветка
- отдельный входной VPS может форвардить трафик на основной VPS;
- нужны TCP и UDP сценарии;
- в первую очередь интересны:
  - MTProxy / VLESS / Xray по TCP
  - AmneziaWG / WireGuard по UDP

---

## 12. Предлагаемый порядок реализации

### Этап 1
Подготовка проектной базы:
- ТЗ
- заметки
- транскрипты
- архитектурное решение

### Этап 2
WARP Manager MVP:
- install
- status
- connect
- disconnect
- local SOCKS5
- xray JSON output

### Этап 3
MTProxy Manager MVP:
- install
- status
- link
- QR
- remove

### Этап 4
Relay / Cascade MVP:
- add/list/delete TCP rule
- add/list/delete UDP rule
- persistence

### Этап 5
Общий menu-wrapper

---

## 13. Открытые вопросы

Нужно уточнить:
- на каком языке писать основу: bash / python / node;
- нужен ли сразу TUI или сначала только CLI;
- какой механизм брать для relay: nftables, socat, haproxy или гибрид;
- нужен ли экспорт готовых конфигов под Amnezia;
- нужен ли режим single-binary installer.

---

## 14. Предварительное решение Daran

Если без лишней романтики, то разумный путь такой:
- **ядро делать не на голом bash**, а на более вменяемой основе;
- bash оставить только как thin launcher, если вообще понадобится;
- сначала сделать CLI и config/state layout;
- только потом лепить меню.

Потому что «огромный интерактивный башник» — это весело ровно до первого нормального рефакторинга, а потом начинается археология и мат.
