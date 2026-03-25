# Предварительная архитектура

Дата: 2026-03-24
Статус: preliminary

## Принцип
Не делать один огромный bash-скрипт, в котором меню, логика, установка, парсинг, вывод и удаление слеплены в один ком грязи.

Делать слоями.

## Слои

### 1. Core modules
Отдельные модули с собственной логикой:
- mtproxy
- warp
- relay

### 2. Shared library
Общее для модулей:
- config
- logging
- shell helpers
- dependency checks
- IP detection
- validation
- output formatting

### 3. CLI layer
Единая точка входа:
- `daran-net mtproxy ...`
- `daran-net warp ...`
- `daran-net relay ...`

### 4. TUI layer
Необязательный слой поверх CLI:
- numbered menu
- guided setup
- human-readable summaries

Важно: TUI не должна содержать бизнес-логику.

## Конфиги и state
Предлагаемый layout:
- `/etc/daran-proxy-stack/config.yaml`
- `/etc/daran-proxy-stack/modules/*.yaml`
- `/var/lib/daran-proxy-stack/state/*.json`
- `/var/log/daran-proxy-stack/*.log`

## MTProxy module
Основные объекты:
- host
- port
- secret
- fake tls domain
- docker runtime config
- generated tg-link

## WARP module
Основные объекты:
- local socks bind host
- local socks port
- registration state
- connect state
- detected server IP
- detected WARP IP
- generated xray outbound JSON

## Relay module
Основные объекты:
- rule id
- protocol tcp/udp
- listen host/port
- target host/port
- enabled/disabled
- persistence backend

## Почему так лучше
- можно тестировать по модулям;
- можно позже менять реализацию relay без переписывания UI;
- можно сделать web/Telegram обвязку поверх CLI;
- не разваливается после первого расширения функционала.
