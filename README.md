<div align="center">

# Zapret for Ubuntu GUI

Удобный Linux-лаунчер для стратегий `zapret-discord-youtube`  
с управлением через `systemd`, автозапуском, треем и автообновлением.

![Ubuntu](https://img.shields.io/badge/Ubuntu-22.04%2B-E95420?logo=ubuntu&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Systemd](https://img.shields.io/badge/systemd-managed-268BD2)
![License](https://img.shields.io/badge/license-MIT-2ea44f)

</div>

> [!IMPORTANT]
> Этот репозиторий является Linux/Ubuntu GUI-обвязкой вокруг оригинального проекта Flowseal и экосистемы zapret.  
> Основная идея: максимально простой UI + корректная работа без Wine (через Linux backend).

## Содержание

- [Что это](#что-это)
- [Быстрый старт](#быстрый-старт)
- [Зависимости](#зависимости)
- [Структура проекта](#структура-проекта)
- [Как работает подключение](#как-работает-подключение)
- [Автообновление](#автообновление)
- [Автозапуск systemd](#автозапуск-systemd)
- [Трей и запуск из меню](#трей-и-запуск-из-меню)
- [Логи](#логи)
- [Замена исходников zapret-discord](#замена-исходников-zapret-discord)
- [Лицензия и благодарности](#лицензия-и-благодарности)

## Что это

Приложение `zapret_gui.py`:

- показывает минимальный UI: одна большая кнопка `Connect/Disconnect`, выбор альтернативы, автозапуск, версия, логи;
- на Linux запускает `.bat`-стратегии без Wine через Linux backend (`nfqws`);
- хранит runtime-состояние отдельно в `.linux-backend/`;
- работает с заменяемыми исходниками в `zapret-discord/`;
- управляет сервисом через `systemd`:
  - `Connect` = `systemctl start zapret-discord-autostart.service`
  - `Disconnect` = `systemctl stop zapret-discord-autostart.service`
  - checkbox автозапуска = `enable/disable` сервиса при старте ОС.

## Быстрый старт

1. Установите зависимости (ниже).
2. Положите исходники релиза в `zapret-discord/`.
3. Запустите:

```bash
./run-ubuntu-gui.sh
```

или:

```bash
python3 ./zapret_gui.py
```

> [!NOTE]
> При первом запуске `.bat`-стратегии на Linux может занять время сборка backend.

## Зависимости

Минимум:

- `python3`
- `python3-tk`
- `python3-pil` (для корректной иконки)
- `python3-gi` и `gir1.2-gtk-3.0` (иконка/меню в трее)
- `git`
- `make`
- `gcc`
- `sudo` или `pkexec`

Также нужны пакеты, необходимые для сборки/работы Linux-компонентов zapret (`nfqws`).

## Структура проекта

```text
.
├── zapret_gui.py
├── run-ubuntu-gui.sh
├── icons/
│   └── zapret.ico
├── .linux-backend/          # runtime, state, logs, linux backend
└── zapret-discord/          # заменяемые исходники релиза
```

Важно:

- `zapret-discord/` намеренно не хранится в git (кроме `.gitkeep`);
- его содержимое может обновляться приложением и заменяться вручную.

## Как работает подключение

При выборе `.bat`-альтернативы на Linux:

1. аргументы стратегии читаются из `.bat`;
2. генерируется Linux-конфиг:
   - `.linux-backend/state/config.autostart.generated` (для managed-сервиса);
3. создается/обновляется unit:
   - `/etc/systemd/system/zapret-discord-autostart.service`;
4. кнопка `Connect/Disconnect` управляет состоянием сервиса (`start/stop`).

Состояние UI синхронизируется с `systemctl is-active`.

## Автообновление

Проверка обновлений выполняется на старте (если существует `zapret-discord/utils/check_updates.enabled`).

Если версия устарела:

- рядом с версией появляется кнопка `⟳`;
- кнопка запускает обновление по архиву релиза:
  - `https://github.com/Flowseal/zapret-discord-youtube/releases/download/{VERSION}/zapret-discord-youtube-{VERSION}.zip`

Во время `Updating`:

- сервис останавливается;
- `Connect/Disconnect` недоступен;
- селектор альтернатив и автозапуск отключены;
- большая кнопка становится серой и показывает анимацию обновления;
- содержимое `zapret-discord/` заменяется файлами из архива;
- пользовательские override-файлы сохраняются:
  - `lists/ipset-exclude-user.txt`
  - `lists/list-exclude-user.txt`
  - `lists/list-general-user.txt`
  - `utils/check_updates.enabled`
  - `utils/game_filter.enabled`

Если стратегий нет (`No strategy`), запускается recovery-обновление до последнего релиза.

## Автозапуск systemd

Сервис:

- `zapret-discord-autostart.service`

Логика:

- checkbox автозапуска включает/выключает `systemctl enable/disable`;
- `Connect/Disconnect` не трогает enable-state, только активность сервиса;
- если выбранная альтернатива меняется, unit/config пересобирается под нее.

## Трей и запуск из меню

- окно при закрытии уходит в трей;
- меню трея:
  - `Show Zapret`
  - `Connect/Disconnect`
  - `Exit`
- desktop entry создается автоматически:
  - `~/.local/share/applications/zapret-gui.desktop`
- иконка приложения:
  - `~/.local/share/icons/hicolor/256x256/apps/zapret-gui.png`

## Логи

- файл логов:
  - `.linux-backend/logs/launcher.log`
- просмотр из UI:
  - кнопка `Logs`.

## Замена исходников zapret-discord

Поддерживаемый сценарий обновления вручную:

1. зайти в `zapret-discord/`;
2. удалить старые файлы;
3. распаковать новую версию;
4. запустить GUI снова.

Лаунчер подхватит новые стратегии автоматически.

## Лицензия и благодарности

Проект распространяется по лицензии MIT, файл лицензии: [LICENSE.txt](./LICENSE.txt).

Мы сохраняем уважение к оригинальным авторам и их труду:

- исходный проект и стратегии: [Flowseal/zapret-discord-youtube](https://github.com/Flowseal/zapret-discord-youtube)
- базовый проект zapret: [bol-van/zapret](https://github.com/bol-van/zapret)

Отдельная благодарность авторам за проделанную работу и поддержку экосистемы.

