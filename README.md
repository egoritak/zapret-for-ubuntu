<div align="center">

# Zapret for Ubuntu

Графическое приложение для запуска альтернатив `zapret-discord-youtube` на Ubuntu.

![Ubuntu](https://img.shields.io/badge/Ubuntu-22.04%2B-E95420?logo=ubuntu&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Package](https://img.shields.io/badge/.deb-supported-2ea44f)

</div>

> [!IMPORTANT]
> Этот проект — Linux GUI-обвязка. Основа стратегий и релизы: [Flowseal/zapret-discord-youtube](https://github.com/Flowseal/zapret-discord-youtube).

## Установка

### Вариант 1 (рекомендуется): `.deb`

```bash
sudo dpkg -i ./zapret-for-ubuntu_*.deb
sudo apt-get -f install
```

Пакет подтянет зависимости для локальной сборки Linux backend (`build-essential`, `zlib1g-dev`, `libcap-dev`, `libmnl-dev`, `libnetfilter-queue-dev`, `libnfnetlink-dev`).

Запуск после установки:

```bash
zapret-for-ubuntu
```

### Вариант 2: запуск из репозитория

```bash
./run-ubuntu-gui.sh
```

## Первый запуск

1. Открой приложение.
2. Выбери альтернативу в списке.
3. Нажми `Connect`.
4. Подтверди запрос прав администратора.

На первом подключении приложение при необходимости доустановит системные build-зависимости для `zapret` и соберет `nfqws/tpws/ip2net/mdig`.

Если стратегий нет, приложение само предложит обновление и скачает актуальный набор.

## Как пользоваться

- `Connect / Disconnect` — запуск и остановка сервиса.
- `Autostart` — включение/выключение автозапуска при старте системы.
- `⚙ Настройки`:
  - `Посмотреть логи`
  - `Удалить приложение`
- `Release Page` — страница релиза.
- `⟳` рядом с версией — обновление приложения/исходников, когда доступна новая версия.

## Обновление исходников вручную

Можно в любой момент заменить содержимое папки с исходниками на новую версию `zapret-discord-youtube`.
Приложение подхватит изменения автоматически.

## Где хранятся данные

- Исходники: `~/.local/share/zapret-for-ubuntu/zapret-discord`
- Состояние и логи: `~/.local/state/zapret-for-ubuntu`
- Лог-файл: `~/.local/state/zapret-for-ubuntu/logs/launcher.log`

## Удаление

Через интерфейс:
- `⚙ Настройки` → `Удалить приложение`

Или вручную:

```bash
/opt/zapret-for-ubuntu/uninstall-zapret.sh
```

## Лицензия и благодарность

- Лицензия этого проекта: [LICENSE.txt](./LICENSE.txt)
- Оригинальный проект стратегий: [Flowseal/zapret-discord-youtube](https://github.com/Flowseal/zapret-discord-youtube)
- База экосистемы: [bol-van/zapret](https://github.com/bol-van/zapret)
