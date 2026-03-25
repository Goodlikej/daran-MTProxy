# Транскрипт / конспект: WARP + 3x-ui видео
Источник: https://www.youtube.com/watch?v=WD4IW1NDiV4
Дата: 2026-03-24

## Краткий смысл
Видео про установку Cloudflare WARP на VPS так, чтобы Xray / 3x-ui использовал его как outbound через локальный SOCKS5.

## Ключевые тезисы
- На VPS уже есть 3x-ui / Xray.
- Поверх ставится WARP.
- Скрипт поднимает локальный SOCKS5 endpoint.
- В 3x-ui руками создаётся outbound типа SOCKS.
- Routing rules направляют через него весь трафик или только часть сервисов.
- Внешний egress IP становится Cloudflare WARP IP.

## Что делает автор
- Запускает кастомный скрипт на том же VPS.
- Скрипт ставит зависимости и WARP.
- Выпускает/регистрирует подключение.
- Поднимает локальный SOCKS5, в видео фигурирует порт 40000.
- Показывает status, server IP, WARP IP.
- Даёт JSON/подсказку для 3x-ui.
- В 3x-ui создаётся SOCKS outbound.
- Добавляется routing rule на этот outbound.
- Дополнительно включается BBR.

## Архитектура
Client -> Xray / 3x-ui -> local SOCKS5 -> WARP -> Internet

## Что это значит для нашего проекта
Нужны:
- WARP manager
- local SOCKS5 management
- Xray outbound JSON generator
- routing examples
